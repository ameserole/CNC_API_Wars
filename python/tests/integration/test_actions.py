"""Phase 4: giving orders like a human would (skirmish vs Easy AI).

Tests run in file order and build on each other within one match: power plant, barracks, Rangers,
then movement, production queue handling, refused commands, other orders and selling.
"""

import asyncio
import math

import pytest

from generals_api import ApiError, GeneralsClient

TIMEOUT = 90.0
SHARED: dict = {}  # objects created by earlier tests in this module


# -- helpers -------------------------------------------------------------------------------------

def find(snapshot, template):
    return [u for u in snapshot["units"] if u["template"] == template]


def distance(a, b):
    return math.dist(a[:2], b[:2])


async def wait_until(predicate, timeout=TIMEOUT, interval=0.5):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        result = await predicate()
        if result:
            return result
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(interval)


async def money(client):
    return (await client.state())["self"]["money"]


async def place_building(client, template, near):
    """Tries spots around `near` until the game accepts one; returns (reply, position)."""
    for radius in (220, 300, 380, 460):
        for step in range(12):
            angle = step * math.pi / 6
            pos = (near[0] + radius * math.cos(angle), near[1] + radius * math.sin(angle))
            try:
                return await client.build(SHARED["dozer"], template, pos), pos
            except ApiError as error:
                if error.code != "ILLEGAL_LOCATION":
                    raise
    raise AssertionError(f"no legal spot for {template} near {near}")


@pytest.fixture
async def client(game, skirmish, transcript):
    async with GeneralsClient(game.url, request_timeout=TIMEOUT, transcript=transcript) as c:
        if not SHARED:
            snap = await c.state()
            SHARED["dozer"] = find(snap, "AmericaVehicleDozer")[0]["id"]
            SHARED["cc"] = find(snap, "AmericaCommandCenter")[0]
            catalog = await c.catalog()
            SHARED["catalog"] = {t["name"]: t for t in catalog["structures"] + catalog["units"]}
        yield c


# -- orders that change the game -----------------------------------------------------------------

async def test_build_power_plant(client):
    cost = SHARED["catalog"]["AmericaPowerPlant"]["cost"]
    before = await money(client)
    started = asyncio.ensure_future(client.wait_for_event(
        "construction_started", lambda e: e["template"] == "AmericaPowerPlant", timeout=TIMEOUT))

    reply, _ = await place_building(client, "AmericaPowerPlant", SHARED["cc"]["pos"])
    assert reply["messages"] == 1
    executed = await client.wait_for_execution(reply, timeout=10)
    assert executed["frame"] >= reply["client_frame"]

    event = await started
    SHARED["power_plant"] = event["id"]
    assert event["builder_id"] == SHARED["dozer"]
    await wait_until(lambda: _money_is(client, before - cost), timeout=10)
    await client.wait_for_event("construction_complete", lambda e: e["id"] == event["id"], timeout=TIMEOUT)


async def _money_is(client, value):
    return await money(client) == value


async def test_build_barracks_and_train_rangers(client):
    started = asyncio.ensure_future(client.wait_for_event(
        "construction_started", lambda e: e["template"] == "AmericaBarracks", timeout=TIMEOUT))
    await place_building(client, "AmericaBarracks", SHARED["cc"]["pos"])
    barracks = (await started)["id"]
    SHARED["barracks"] = barracks
    await client.wait_for_event("construction_complete", lambda e: e["id"] == barracks, timeout=TIMEOUT)

    created = []
    client.on("unit_created", lambda e: created.append(e) if e["factory_id"] == barracks else None)
    reply = await client.train(barracks, "AmericaInfantryRanger", count=3)
    assert len(reply["production_ids"]) == 3 and reply["messages"] == 3
    await client.wait_for_execution(reply, timeout=10)

    async def three_rangers():
        return len(created) >= 3
    await wait_until(three_rangers)
    assert all(e["template"] == "AmericaInfantryRanger" for e in created)
    SHARED["rangers"] = [e["id"] for e in created[:3]]


async def test_move_rangers(client):
    start = SHARED["cc"]["pos"]
    target = (start[0] + 300, start[1] + 150)
    reply = await client.move(SHARED["rangers"], target)
    await client.wait_for_execution(reply, timeout=10)

    async def arrived():
        units = {u["id"]: u for u in (await client.state())["units"]}
        return all(distance(units[r]["pos"], target) < 80 for r in SHARED["rangers"])
    await wait_until(arrived, timeout=45)


async def test_rally_point(client):
    cc = SHARED["cc"]["pos"]
    rally = (cc[0] - 250, cc[1] + 250)
    await client.wait_for_execution(await client.set_rally_point(SHARED["barracks"], rally), timeout=10)

    new = asyncio.ensure_future(client.wait_for_event(
        "unit_created", lambda e: e["factory_id"] == SHARED["barracks"], timeout=TIMEOUT))
    await client.train(SHARED["barracks"], "AmericaInfantryRanger")
    ranger = (await new)["id"]
    SHARED["rangers"].append(ranger)

    async def at_rally():
        units = {u["id"]: u for u in (await client.state())["units"]}
        return ranger in units and distance(units[ranger]["pos"], rally) < 80
    await wait_until(at_rally, timeout=45)


async def test_queue_full_then_cancel_restores_money(client):
    barracks = SHARED["barracks"]
    before = await money(client)
    ids = []
    with pytest.raises(ApiError) as info:
        for _ in range(30):
            reply = await client.train(barracks, "AmericaInfantryRanger")
            ids += reply["production_ids"]
            await client.wait_for_execution(reply, timeout=10)
    assert info.value.code == "QUEUE_FULL"
    assert ids

    for production_id in ids:
        await client.wait_for_execution(await client.cancel_train(barracks, production_id), timeout=10)
    await wait_until(lambda: _money_is(client, before), timeout=10)


# -- refused commands ----------------------------------------------------------------------------

async def test_refused_commands_change_nothing(client):
    snap_before = await client.state()
    enemy_cc = next(o for o in (await client.request("debug_world"))["objects"]
                    if o["template"] == "ChinaCommandCenter")
    locked = next(t for t in SHARED["catalog"].values() if "STRUCTURE" in t["kinds"] and not t["available_now"])
    cases = [
        ("NOT_OWNED", client.move([999999], (100, 100))),
        ("NOT_OWNED", client.train(enemy_cc["id"], "ChinaVehicleDozer")),
        ("NOT_VISIBLE", client.attack(SHARED["rangers"], enemy_cc["id"])),
        ("NOT_AVAILABLE", client.train(SHARED["cc"]["id"], "AmericaInfantryRanger")),
        ("NOT_AVAILABLE", client.build(SHARED["dozer"], locked["name"], SHARED["cc"]["pos"][:2])),
        ("ILLEGAL_LOCATION", client.build(SHARED["dozer"], "AmericaPowerPlant", SHARED["cc"]["pos"][:2])),
        ("INVALID_ARGUMENT", client.train(SHARED["barracks"], "NoSuchThing")),
        ("INVALID_ARGUMENT", client.move(SHARED["rangers"], (-50000, -50000))),
    ]
    if enemy_cc["visible"]:
        cases = [c for c in cases if c[0] != "NOT_VISIBLE"]
    for expected, call in cases:
        with pytest.raises(ApiError) as info:
            await call
        assert info.value.code == expected, (expected, info.value)

    await asyncio.sleep(1)
    snap_after = await client.state()
    assert snap_after["self"]["money"] == snap_before["self"]["money"]
    assert {u["id"] for u in snap_after["units"]} == {u["id"] for u in snap_before["units"]}


async def test_insufficient_funds(client):
    cc = SHARED["cc"]["id"]
    cost = SHARED["catalog"]["AmericaVehicleDozer"]["cost"]
    ids = []
    try:
        for _ in range(40):
            current = await money(client)
            try:
                reply = await client.train(cc, "AmericaVehicleDozer")
            except ApiError as error:
                if error.code == "QUEUE_FULL":   # spend the rest elsewhere: cancel and stop here
                    pytest.skip("production queue filled before money ran out")
                assert error.code == "INSUFFICIENT_FUNDS"
                assert current < cost
                return
            ids += reply["production_ids"]
            await client.wait_for_execution(reply, timeout=10)
        raise AssertionError("money never ran out")
    finally:
        for production_id in ids:
            await client.cancel_train(cc, production_id)


# -- other orders --------------------------------------------------------------------------------

async def test_other_orders_execute(client):
    rangers = SHARED["rangers"]
    cc = SHARED["cc"]["pos"]
    for name, call in (("attack_move", client.attack_move(rangers, (cc[0] + 200, cc[1]))),
                       ("guard", client.guard(rangers, (cc[0] + 100, cc[1] + 100))),
                       ("force_attack", client.force_attack(rangers, (cc[0] + 150, cc[1] - 150))),
                       ("stop", client.stop(rangers))):
        executed = await client.wait_for_execution(await call, timeout=10)
        assert executed["cmd"] == name


async def test_sell_power_plant(client):
    plant = SHARED["power_plant"]
    before = await money(client)
    await client.wait_for_execution(await client.sell(plant), timeout=10)

    async def gone_and_refunded():
        snap = await client.state()
        return plant not in {u["id"] for u in snap["units"]} and snap["self"]["money"] > before
    await wait_until(gone_and_refunded, timeout=30)
