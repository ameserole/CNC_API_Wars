"""Phase 5: upgrades, sciences, abilities, garrisons, paths and the other orders (skirmish vs Easy AI).

Tests run in file order within one match. Which upgrades and abilities exist comes from the
catalog, so the tests pick what is actually available instead of hard-coding game data.
"""

import asyncio

import pytest

from generals_api import ApiError, GeneralsClient, World

from .helpers import TIMEOUT, base_setup, distance, ensure_structure, money, train_and_wait, wait_until

SHARED: dict = {}


@pytest.fixture
async def client(game, skirmish, transcript):
    async with GeneralsClient(game.url, request_timeout=TIMEOUT, transcript=transcript) as c:
        if not SHARED:
            SHARED.update(await base_setup(c))
            SHARED["rangers"] = await train_and_wait(c, SHARED["barracks"], "AmericaInfantryRanger", 3)
        else:
            # Replace Rangers lost in earlier tests so one test's casualties do not fail the next.
            alive = {u["id"] for u in (await c.state())["units"]}
            SHARED["rangers"] = [r for r in SHARED["rangers"] if r in alive]
            missing = 3 - len(SHARED["rangers"])
            if missing > 0 and SHARED["barracks"] in alive:
                SHARED["rangers"] += await train_and_wait(c, SHARED["barracks"], "AmericaInfantryRanger", missing)
        yield c


def barracks_upgrades():
    return [u for u in SHARED["catalog"]["upgrades"] if "AmericaBarracks" in u["built_by"]]


# -- catalog -------------------------------------------------------------------------------------

async def test_catalog_lists_abilities(client):
    ranger = SHARED["things"]["AmericaInfantryRanger"]
    assert ranger["abilities"], "the Ranger has command buttons the API supports"
    for ability in ranger["abilities"]:
        assert {"name", "type", "target"} <= ability.keys()
        assert ability["target"] in ("none", "position", "object")
    assert barracks_upgrades(), "the barracks offers upgrades"


# -- upgrades and sciences -----------------------------------------------------------------------

async def test_upgrade_completes(client):
    barracks = SHARED["barracks"]
    before = await money(client)
    for upgrade in barracks_upgrades():
        try:
            reply = await client.upgrade(barracks, upgrade["name"])
        except ApiError as error:
            assert error.code in ("NOT_AVAILABLE", "INSUFFICIENT_FUNDS", "QUEUE_FULL"), error
            continue
        await client.wait_for_execution(reply, timeout=10)
        done = await client.wait_for_event("upgrade_complete", lambda e: e["upgrade"] == upgrade["name"],
                                           timeout=TIMEOUT + upgrade["build_time"])
        assert done["upgrade"] == upgrade["name"]
        assert await money(client) < before
        SHARED["upgraded"] = upgrade["name"]
        return
    pytest.fail("no barracks upgrade could be queued")


async def test_cancel_upgrade_restores_money(client):
    barracks = SHARED["barracks"]
    for upgrade in barracks_upgrades():
        if upgrade["name"] == SHARED.get("upgraded"):
            continue
        before = await money(client)
        try:
            reply = await client.upgrade(barracks, upgrade["name"])
        except ApiError:
            continue
        await client.wait_for_execution(reply, timeout=10)
        await client.wait_for_execution(await client.cancel_upgrade(barracks, upgrade["name"]), timeout=10)

        async def refunded():
            return await money(client) == before
        await wait_until(refunded, timeout=10)
        return
    pytest.skip("no second barracks upgrade is available to cancel")


async def test_use_ability(client):
    catalog = await client.catalog()  # abilities can depend on upgrades just completed
    ranger = {t["name"]: t for t in catalog["units"]}["AmericaInfantryRanger"]
    # Some buttons (MUST_BE_STOPPED) are disabled while the unit moves, as in the UI.
    await client.wait_for_execution(await client.stop(SHARED["rangers"]), timeout=10)
    await asyncio.sleep(1)
    tried = []
    for ability in ranger["abilities"]:
        if ability["target"] != "none":
            continue
        try:
            reply = await client.use_ability(SHARED["rangers"][:1], ability["name"])
        except ApiError as error:
            tried.append((ability["name"], error.code))
            continue
        executed = await client.wait_for_execution(reply, timeout=10)
        assert executed["cmd"] == "use_ability"
        return
    pytest.skip(f"no no-target Ranger ability is available right now: {tried}")


async def test_purchase_science(client):
    purchasable = [s for s in (await client.catalog())["sciences"] if s["purchasable_now"]]
    if not purchasable:
        # Debug-only: the existing demo cheat that grants a general's point.
        await client.request("debug_give_science_points")

        async def has_points():
            return (await client.state())["self"]["science_points"] > 0
        await wait_until(has_points, timeout=10)
        purchasable = [s for s in (await client.catalog())["sciences"] if s["purchasable_now"]]
    assert purchasable, "a science should be purchasable with a point"
    science = purchasable[0]["name"]
    done = asyncio.ensure_future(client.wait_for_event("science_purchased", lambda e: e["science"] == science, timeout=15))
    await client.wait_for_execution(await client.purchase_science(science), timeout=10)
    await done


# -- movement and simple orders ------------------------------------------------------------------

async def test_move_with_waypoints(client):
    cc = SHARED["cc"]["pos"]
    path = [(cc[0] + 250, cc[1]), (cc[0] + 250, cc[1] + 250)]
    final = (cc[0], cc[1] + 300)
    reply = await client.move(SHARED["rangers"], path[0], waypoints=path[1:] + [final])
    assert reply["messages"] == 3
    await client.wait_for_execution(reply, timeout=10)

    async def arrived():
        units = {u["id"]: u for u in (await client.state())["units"]}
        return all(distance(units[r]["pos"], final) < 90 for r in SHARED["rangers"])
    await wait_until(arrived, timeout=60)


async def test_other_orders_execute(client):
    rangers = SHARED["rangers"]
    cc = SHARED["cc"]
    for name, call in (("scatter", client.scatter(rangers)),
                       ("formation", client.formation(rangers)),
                       ("force_move", client.force_move(rangers, (cc["pos"][0] + 150, cc["pos"][1] + 150))),
                       ("guard_object", client.guard_object(rangers, cc["id"]))):
        executed = await client.wait_for_execution(await call, timeout=10)
        assert executed["cmd"] == name


# -- containers ----------------------------------------------------------------------------------

async def test_enter_and_evacuate_civilian_building(client):
    world = World().attach(client)
    await world.load(client)
    home = SHARED["cc"]["pos"]
    # Only buildings near our base: further out the Rangers would walk into the enemy's defences.
    garrisonable = sorted((k for k in world.known_structures.values()
                           if "GARRISONABLE_UNTIL_DESTROYED" in world.kinds(k["template"])
                           and distance(k["pos"], home) < 1000),
                          key=lambda k: distance(k["pos"], home))
    if not garrisonable:
        pytest.skip("no garrisonable civilian building known on this map")
    rangers = SHARED["rangers"]

    async def units():
        return {u["id"]: u for u in (await client.state())["units"]}

    # Some map buildings stand where infantry cannot path; like a player, try the next one.
    for building in garrisonable:
        await client.move(rangers, (home[0] + 150, home[1] + 150))
        await client.move(rangers, (building["pos"][0] - 60, building["pos"][1] - 60))

        async def in_view():
            return any(o["id"] == building["id"] for o in (await client.state())["visible"])
        try:
            await wait_until(in_view, timeout=45)
        except TimeoutError:
            continue
        await client.wait_for_execution(await client.enter(rangers, building["id"]), timeout=10)

        async def inside():
            current = await units()
            return all(current[r].get("contained_by") == building["id"] for r in rangers)
        try:
            await wait_until(inside, timeout=30)
        except TimeoutError:
            continue

        await client.wait_for_execution(await client.evacuate(building["id"]), timeout=10)

        async def outside():
            current = await units()
            return all(current[r].get("contained_by") is None for r in rangers)
        await wait_until(outside, timeout=30)
        return
    await client.move(rangers, (home[0] + 150, home[1] + 150))
    pytest.skip(f"none of the {len(garrisonable)} civilian buildings near the base could be reached by infantry")


async def test_enter_and_exit_own_transport(client):
    """Map-independent container test: Rangers board one of our Humvees, then get out again."""
    factory = await ensure_structure(client, SHARED, "AmericaWarFactory")
    humvee = (await train_and_wait(client, factory, "AmericaVehicleHumvee", 1))[0]
    rangers = SHARED["rangers"][:2]

    async def units():
        return {u["id"]: u for u in (await client.state())["units"]}

    await client.wait_for_execution(await client.enter(rangers, humvee), timeout=10)

    async def aboard():
        current = await units()
        return all(current[r].get("contained_by") == humvee for r in rangers)
    await wait_until(aboard, timeout=45)

    # Passengers cannot be ordered directly (not selectable), like in the UI.
    with pytest.raises(ApiError) as info:
        await client.stop(rangers)
    assert info.value.code == "NOT_OWNED"

    await client.wait_for_execution(await client.evacuate(humvee), timeout=10)

    async def ashore():
        current = await units()
        return all(current[r].get("contained_by") is None for r in rangers)
    await wait_until(ashore, timeout=30)


# -- events --------------------------------------------------------------------------------------

async def test_damage_is_reported_grouped(client):
    ranger = SHARED["rangers"][0]
    events = []
    client.on("unit_damaged", lambda e: events.append(e) if e["id"] == ranger else None)
    for _ in range(3):
        await client.request("debug_hurt", object=ranger)
    await asyncio.sleep(1.5)
    assert len(events) == 1, events
    assert events[0]["damage"] > 0 and events[0]["health"] < events[0]["max_health"]
    assert events[0]["attacker_id"] is None


async def test_refused_commands(client):
    enemy_cc = next(o for o in (await client.request("debug_world"))["objects"] if o["template"] == "ChinaCommandCenter")
    other_upgrade = next(u for u in SHARED["catalog"]["upgrades"] if "AmericaBarracks" not in u["built_by"])
    before = await client.state()
    cases = [
        ("NOT_AVAILABLE", client.use_ability(SHARED["rangers"][:1], "Command_NoSuchButton")),
        ("NOT_AVAILABLE", client.upgrade(SHARED["barracks"], other_upgrade["name"])),
        ("INVALID_ARGUMENT", client.purchase_science("SCIENCE_NoSuchThing")),
        ("NOT_OWNED", client.evacuate(enemy_cc["id"])),
    ]
    if not enemy_cc["visible"]:
        cases.append(("NOT_VISIBLE", client.enter(SHARED["rangers"], enemy_cc["id"])))
    for expected, call in cases:
        with pytest.raises(ApiError) as info:
            await call
        assert info.value.code == expected, (expected, info.value)
    await asyncio.sleep(1)
    assert (await client.state())["self"]["money"] == before["self"]["money"]


async def test_sell_reports_unit_removed(client):
    barracks = SHARED["barracks"]
    removed = asyncio.ensure_future(client.wait_for_event("unit_removed", lambda e: e["id"] == barracks, timeout=TIMEOUT))
    await client.wait_for_execution(await client.sell(barracks), timeout=10)
    event = await removed
    assert event["reason"] == "sold" and event["template"] == "AmericaBarracks"
