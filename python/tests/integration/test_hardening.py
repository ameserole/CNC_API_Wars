"""Phase 7: fixes from the first agent-played match, reconnects and the APM cap (skirmish vs Easy AI).

Tests run in file order. The first one runs before the module's match starts.
"""

import asyncio

import pytest

from generals_api import ApiError, GeneralsClient

from .conftest import end_match, start_match
from .gamehost import GameProcess
from .helpers import TIMEOUT, distance, wait_until

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(game, skirmish, transcript):
    async with GeneralsClient(game.url, request_timeout=TIMEOUT, transcript=transcript) as c:
        await c.hello()
        yield c


async def test_save_replay_needs_a_played_game(game):
    async with GeneralsClient(game.url) as c:
        assert (await c.hello())["game_state"] == "shell"
        with pytest.raises(ApiError) as error:
            await c.save_replay("never played")
        assert error.value.code == "NOT_AVAILABLE"


# -- supply docks ----------------------------------------------------------------------------------

async def test_supply_sources_are_reported(client):
    supplies = [o for o in (await client.request("debug_world"))["objects"] if "SUPPLY_SOURCE" in o["kinds"]]
    assert supplies, "the map has supply docks"

    # Walk a dozer to the nearest supply source, so at least one is in sight.
    snap = await client.state()
    dozer = next(u for u in snap["units"] if u["template"].endswith("VehicleDozer"))
    nearest = min(supplies, key=lambda o: distance(o["pos"], dozer["pos"]))
    await client.move([dozer["id"]], nearest["pos"][:2])

    async def sees_supply():
        world = (await client.request("debug_world"))["objects"]
        return {o["id"] for o in world if "SUPPLY_SOURCE" in o["kinds"] and o["visible"]}
    visible_supplies = await wait_until(sees_supply, timeout=90)

    reported = {o["id"]: o for o in (await client.state())["visible"]}
    assert visible_supplies <= set(reported), (visible_supplies, sorted(reported))
    assert all("Supply" in reported[i]["template"] for i in visible_supplies)


# -- sciences --------------------------------------------------------------------------------------

async def science_points(client) -> int:
    return (await client.state())["self"]["science_points"]


async def test_purchase_science_checks_points_and_pending_purchases(client):
    # Spend whatever points the match started with.
    while await science_points(client) > 0:
        science = next(s for s in (await client.catalog())["sciences"] if s["purchasable_now"])
        done = asyncio.ensure_future(client.wait_for_event("science_purchased", lambda e, n=science["name"]: e["science"] == n,
                                                           timeout=15))
        await client.purchase_science(science["name"])
        await done

    sciences = (await client.catalog())["sciences"]
    assert not any(s["purchasable_now"] for s in sciences), "nothing is purchasable without points"
    candidate = next(s for s in sciences if s["prerequisites_met"] and s["cost"] == 1)
    with pytest.raises(ApiError) as error:
        await client.purchase_science(candidate["name"])
    assert error.value.code == "INSUFFICIENT_FUNDS"

    # Debug-only: the demo cheat that grants one point.
    await client.request("debug_give_science_points")
    await wait_until(lambda: _positive(science_points(client)), timeout=10)
    assert any(s["name"] == candidate["name"] and s["purchasable_now"] for s in (await client.catalog())["sciences"])

    # Two purchases sent together: the second sees the first on its way.
    bought = asyncio.ensure_future(client.wait_for_event("science_purchased", lambda e: e["science"] == candidate["name"],
                                                         timeout=15))
    results = await asyncio.gather(client.purchase_science(candidate["name"]), client.purchase_science(candidate["name"]),
                                   return_exceptions=True)
    errors = [r.code for r in results if isinstance(r, ApiError)]
    assert errors == ["NOT_AVAILABLE"], results
    await bought

    with pytest.raises(ApiError) as error:
        await client.purchase_science(candidate["name"])
    assert error.value.code == "NOT_AVAILABLE"


async def _positive(value) -> bool:
    return (await value) > 0


# -- reconnects ------------------------------------------------------------------------------------

async def test_reconnect_gets_a_clean_session(game, skirmish):
    old = await GeneralsClient(game.url, request_timeout=TIMEOUT).connect()
    await old.hello()
    await old.set_snapshot_interval(1)
    units_before = sorted(u["id"] for u in (await old.state())["units"])
    dozer = next(u for u in (await old.state())["units"] if u["template"].endswith("VehicleDozer"))
    await old.move([dozer["id"]], (dozer["pos"][0] + 50, dozer["pos"][1]))
    old._ws.transport.abort()  # drop the connection without a close handshake, before the order executes
    await old.close()

    async with GeneralsClient(game.url, request_timeout=TIMEOUT) as new:
        executed, snapshots = [], []
        new.on("command_executed", executed.append)
        new.on("snapshot", snapshots.append)
        hello = await new.hello()
        assert hello["game_state"] == "in_game"
        await asyncio.sleep(3)
        assert executed == [], "orders of the previous connection are not reported to the new one"
        assert len(snapshots) <= 3 * 30 / 15 + 2, "the snapshot interval is back to its default"

        units_after = sorted(u["id"] for u in (await new.state())["units"])
        assert set(units_before) <= set(units_after)
        await new.wait_for_execution(await new.stop([dozer["id"]]), timeout=10)
        assert [e["cmd"] for e in executed] == ["stop"]


# -- APM cap ---------------------------------------------------------------------------------------

@pytest.mark.timeout(400)
async def test_apm_cap(results_root):
    game = GameProcess(results_root / "test_hardening_apm", extra_args=["-scriptApiApm", "5"])
    await asyncio.to_thread(game.start)
    try:
        await start_match(game.url)
        async with GeneralsClient(game.url, request_timeout=TIMEOUT) as c:
            assert (await c.hello())["apm_limit"] == 5
            dozer = next(u for u in (await c.state())["units"] if u["template"].endswith("VehicleDozer"))

            with pytest.raises(ApiError) as error:  # refused orders don't count
                await c.stop([999999])
            assert error.value.code == "NOT_OWNED"
            for _ in range(5):
                await c.stop([dozer["id"]])
            with pytest.raises(ApiError) as error:
                await c.stop([dozer["id"]])
            assert error.value.code == "RATE_LIMITED"
            assert "frames" in error.value.message

            assert (await c.state())["units"], "queries are never limited"
        await end_match(game.url)
    finally:
        game.kill()
        problems = game.collect_artifacts()
        assert not problems, problems
