"""Phase 8: fixes from the first agent-vs-agent match (skirmish vs Easy AI).

Tests run in file order and share one match. Money only changes through spending until the supply
center in test 6 starts bringing in income, so the committed-money test runs before it.
"""

import asyncio

import pytest

from generals_api import ApiError, GeneralsClient

from .helpers import TIMEOUT, distance, own, place_building, train_and_wait, wait_until

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(game, skirmish, transcript):
    async with GeneralsClient(game.url, request_timeout=TIMEOUT, transcript=transcript) as c:
        await c.hello()
        yield c


async def dozer_and_cc(client) -> tuple[dict, dict]:
    snap = await client.state()
    return own(snap, "AmericaVehicleDozer")[0], own(snap, "AmericaCommandCenter")[0]


# -- general's powers need their science -----------------------------------------------------------

async def test_special_power_needs_its_science(client):
    catalog = await client.catalog()
    cc_entry = next(s for s in catalog["structures"] if s["name"] == "AmericaCommandCenter")
    not_owned = {s["name"] for s in catalog["sciences"]}  # the catalog lists sciences still to buy
    locked = [a for a in cc_entry["abilities"] if a.get("required_science") in not_owned]
    assert locked, cc_entry["abilities"]

    _, cc = await dozer_and_cc(client)
    for ability in locked:
        with pytest.raises(ApiError) as error:
            await client.use_ability([cc["id"]], ability["name"], pos=cc["pos"][:2], target=cc["id"]
                                     if ability["target"] == "object" else None)
        assert error.value.code == "NOT_AVAILABLE", ability
        assert "requires the science " + ability["required_science"] in str(error.value), ability


# -- supply sources --------------------------------------------------------------------------------

async def test_supply_source_reports_its_value_and_stays_known(client):
    supplies = [o for o in (await client.request("debug_world"))["objects"] if "SUPPLY_SOURCE" in o["kinds"]]
    dozer, _ = await dozer_and_cc(client)
    nearest = min(supplies, key=lambda o: distance(o["pos"], dozer["pos"]))
    await client.move([dozer["id"]], nearest["pos"][:2])

    async def visible_supply():
        snap = await client.state()
        return next((o for o in snap["visible"] if "supply" in o), None), snap
    source, snap = await wait_until(lambda: _first(visible_supply()), timeout=90)
    assert source["supply"] > 0, source

    known = {k["id"]: k for k in snap["known_structures"]}
    assert source["id"] in known, "a visible structure is listed in known_structures too"
    assert known[source["id"]]["visible"] is True
    assert known[source["id"]]["last_seen_frame"] == snap["frame"]
    assert all(k["visible"] is (k["id"] in {o["id"] for o in snap["visible"]}) for k in snap["known_structures"])


async def _first(pair):
    value, rest = await pair
    return (value, rest) if value is not None else None


# -- resume_construction, idle ---------------------------------------------------------------------

async def test_resume_construction_says_why_and_dozer_goes_idle(client):
    dozer, cc = await dozer_and_cc(client)
    started = await place_building(client, dozer["id"], "AmericaPowerPlant", cc["pos"])
    with pytest.raises(ApiError) as error:
        await client.resume_construction(dozer["id"], started["id"])
    assert error.value.code == "NOT_AVAILABLE"
    assert "that dozer is already building it" in str(error.value)

    await client.wait_for_event("construction_complete", lambda e: e["id"] == started["id"], timeout=TIMEOUT)
    with pytest.raises(ApiError) as error:
        await client.resume_construction(dozer["id"], started["id"])
    assert "not under construction" in str(error.value)

    async def dozer_idle():
        unit = next((u for u in (await client.state())["units"] if u["id"] == dozer["id"]), None)
        return unit is not None and "idle" in unit["status"]
    await wait_until(dozer_idle, timeout=30)


# -- committed money -------------------------------------------------------------------------------

async def test_orders_on_their_way_commit_money(client):
    _, cc = await dozer_and_cc(client)
    bank = (await client.state())["self"]["money"]
    cost = next(u for u in (await client.catalog())["units"] if u["name"] == "AmericaVehicleDozer")["cost"]
    count = bank // (2 * cost) + 1  # one order fits the bank, two don't
    assert count * cost <= bank < 2 * count * cost and count <= 9, (bank, cost)

    results = await asyncio.gather(client.train(cc["id"], "AmericaVehicleDozer", count=count),
                                   client.train(cc["id"], "AmericaVehicleDozer", count=count),
                                   return_exceptions=True)
    errors = [r.code for r in results if isinstance(r, ApiError)]
    assert errors == ["INSUFFICIENT_FUNDS"], results

    accepted = next(r for r in results if not isinstance(r, ApiError))
    await client.wait_for_execution(accepted, timeout=10)
    for production_id in accepted["production_ids"]:
        await client.cancel_train(cc["id"], production_id)

    async def refunded():
        return (await client.state())["self"]["money"] == bank
    await wait_until(refunded, timeout=15)


# -- destruction events ----------------------------------------------------------------------------

async def test_projectiles_send_no_destruction_events(client):
    dozer, cc = await dozer_and_cc(client)
    barracks = own(await client.state(), "AmericaBarracks")
    if not barracks:
        started = await place_building(client, dozer["id"], "AmericaBarracks", cc["pos"])
        await client.wait_for_event("construction_complete", lambda e: e["id"] == started["id"], timeout=TIMEOUT)
        barracks_id = started["id"]
    else:
        barracks_id = barracks[0]["id"]
    shooters = await train_and_wait(client, barracks_id, "AmericaInfantryMissileDefender", 2)

    events = []
    for name in ("unit_destroyed", "unit_removed", "enemy_destroyed"):
        client.on(name, events.append)
    # Force-fire at our own barracks (Ctrl+click): the forced check allows own targets. Missile
    # Defenders don't fire at bare ground, and the barracks outlasts the few seconds of shooting.
    await client.force_attack_object(shooters, barracks_id)

    me = (await client.state())["self"]["index"]

    async def own_projectile_seen():
        world = (await client.request("debug_world", all=True))["objects"]
        return any("PROJECTILE" in o["kinds"] and o["owner"] == me for o in world)
    await wait_until(own_projectile_seen, timeout=30, interval=0.1)
    await asyncio.sleep(8)
    await client.stop(shooters)
    assert events == [], events


# -- harvesting ------------------------------------------------------------------------------------

async def test_supply_units_report_harvesting(client):
    supplies = [o for o in (await client.request("debug_world"))["objects"] if "SUPPLY_SOURCE" in o["kinds"]]
    dozer, cc = await dozer_and_cc(client)
    nearest = min(supplies, key=lambda o: distance(o["pos"], cc["pos"]))
    # Between the dock and the command center: the docks sit near the map edge.
    near = ((nearest["pos"][0] + cc["pos"][0]) / 2, (nearest["pos"][1] + cc["pos"][1]) / 2)
    started = await place_building(client, dozer["id"], "AmericaSupplyCenter", near)
    await client.wait_for_event("construction_complete", lambda e: e["id"] == started["id"], timeout=TIMEOUT)

    async def harvesting():
        return any("harvesting" in u["status"] for u in (await client.state())["units"])
    await wait_until(harvesting, timeout=90)
