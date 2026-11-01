"""Phase 6: LAN games between script clients on one PC, observers, and the launcher.

Tests 0-7 share one pair of instances and one match, in order. The observer test starts its own
instances. The launcher tests are in test_lan_launcher.py.
"""

import asyncio
import math

import pytest
import pytest_asyncio

from generals_api import ApiError, GeneralsClient, launcher

from .gamehost import KNOWN_LEAKS_AFTER_MATCH, GameProcess
from .helpers import own, place_building

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

LOAD_TIMEOUT = 180.0
LAN_MAP = "tournament desert"


def command_centers(objects: list[dict]) -> list[dict]:
    return [o for o in objects if o["template"].endswith("CommandCenter")]


def start_instances(results_dir, count: int, extra_args=None) -> list[GameProcess]:
    games = []
    try:
        for i in range(count):
            games.append(GameProcess(results_dir / f"instance{i}", extra_args=extra_args,
                                     leak_baseline=KNOWN_LEAKS_AFTER_MATCH).start())
    except Exception:
        for game in games:
            game.kill()
        raise
    return games


def stop_instances(games: list[GameProcess]) -> None:
    problems = []
    for game in games:
        game.kill()
        problems += game.collect_artifacts()
    assert not problems, f"game reported problems: {problems}"


async def connect(game: GameProcess) -> GeneralsClient:
    client = await GeneralsClient(game.url, request_timeout=60).connect()
    await client.hello()
    return client


async def lan_map(client: GeneralsClient) -> str:
    return launcher.pick_map(await client.skirmish_options(), LAN_MAP)


async def start_when_accepted(host: GeneralsClient, joiners: list[GeneralsClient]) -> None:
    for _ in range(30):
        for joiner in joiners:
            await joiner.lan_accept()
        await asyncio.sleep(1.0)
        try:
            await host.lan_start()
            return
        except ApiError as error:
            if error.code != "NOT_READY":
                raise
    raise AssertionError("players never all accepted")


# -- tests 0-7: one match between two script clients ---------------------------------------------

@pytest.fixture(scope="module")
def lan_pair(results_root):
    games = start_instances(results_root / "test_lan", 2)
    yield games
    stop_instances(games)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pair(lan_pair):
    a, b = await connect(lan_pair[0]), await connect(lan_pair[1])
    state = {"a": a, "b": b}
    yield state
    await a.close()
    await b.close()


async def test_0_lobby_discovery(pair):
    a, b = pair["a"], pair["b"]
    pair["lobby_a"] = await a.lan_open("BotA")
    # Waiters are registered before the action that triggers their event, so nothing is missed.
    sees_a = asyncio.ensure_future(b.wait_for_event(
        "lan_lobby", lambda e: any(p["name"] == "BotA" for p in e["players"]), timeout=30))
    pair["lobby_b"] = await b.lan_open("BotB")
    assert pair["lobby_a"]["name"] == "BotA"
    assert pair["lobby_a"]["local_ip"] != pair["lobby_b"]["local_ip"], "instances need distinct LAN addresses"

    # Loopback broadcast reaches the other instances (finding of the phase 6 spike).
    seen = await sees_a
    assert any(p["ip"] == pair["lobby_a"]["local_ip"] for p in seen["players"])


async def test_1_host_and_join(pair):
    a, b = pair["a"], pair["b"]
    pair["map"] = await lan_map(a)
    listed = asyncio.ensure_future(b.wait_for_event(
        "lan_lobby", lambda e: any(g["host"] == "BotA" for g in e["games"]), timeout=30))
    hosted = await a.lan_host(pair["map"], [{"type": "host"}, {"type": "open"}])
    assert hosted["is_host"] and hosted["local_slot"] == 0
    assert [s["state"] for s in hosted["slots"][:3]] == ["player", "open", "closed"]

    game = await listed
    assert any(g["host_ip"] == pair["lobby_a"]["local_ip"] for g in game["games"])

    joined_on_host = asyncio.ensure_future(a.wait_for_event(
        "lan_game", lambda e: e["slots"][1]["state"] == "player", timeout=30))
    joined = await b.lan_join(host_ip=pair["lobby_a"]["local_ip"])
    assert not joined["is_host"] and joined["local_slot"] == 1
    assert (await joined_on_host)["slots"][1]["name"] == "BotB"


async def test_2_slot_and_accept(pair):
    a, b = pair["a"], pair["b"]
    await a.lan_slot(faction="FactionAmerica")
    on_host = asyncio.ensure_future(a.wait_for_event(
        "lan_game", lambda e: e["slots"][1]["faction"] == "FactionChina", timeout=30))
    reply = await b.lan_slot(faction="FactionChina")
    assert reply["slots"][1]["faction"] == "FactionChina"
    await on_host

    with pytest.raises(ApiError) as error:
        await b.lan_slot(start_pos=9)
    assert error.value.code == "BAD_REQUEST"


async def test_3_start_refused_before_accept(pair):
    a, b = pair["a"], pair["b"]
    with pytest.raises(ApiError) as error:
        await a.lan_start()
    assert error.value.code == "NOT_READY"
    with pytest.raises(ApiError) as error:
        await b.lan_start()
    assert error.value.code == "NOT_AVAILABLE"  # only the host starts

    accepted = asyncio.ensure_future(a.wait_for_event("lan_game", lambda e: e["slots"][1].get("accepted"), timeout=30))
    await b.lan_accept()
    accepted = await accepted
    assert accepted["slots"][1]["faction"] == "FactionChina"


async def test_4_start(pair):
    a, b = pair["a"], pair["b"]
    await start_when_accepted(a, [b])
    await a.wait_for_state("in_game", timeout=LOAD_TIMEOUT)
    await b.wait_for_state("in_game", timeout=LOAD_TIMEOUT)
    for client, other in ((a, "BotB"), (b, "BotA")):
        players = {p["name"]: p for p in (await client.game_info())["players"]}
        assert players[other]["relation"] == "enemy"
        assert players[other]["type"] == "human"


async def test_5_lockstep_orders(pair):
    a, b = pair["a"], pair["b"]
    for client, prefix in ((a, "America"), (b, "China")):
        snap = await client.state()
        dozer = own(snap, f"{prefix}VehicleDozer")[0]["id"]
        cc = own(snap, f"{prefix}CommandCenter")[0]
        started = await place_building(client, dozer, f"{prefix}PowerPlant", cc["pos"])
        assert started["template"] == f"{prefix}PowerPlant"
    first = (await a.ping())["frame"]
    await asyncio.sleep(60)
    # Both clients advance together; a desync would be logged and fail the fixture's log check.
    assert (await a.ping())["frame"] > first + 600
    assert abs((await a.ping())["frame"] - (await b.ping())["frame"]) < 60


async def test_6_fog_across_players(pair):
    for client, enemy in ((pair["a"], "China"), (pair["b"], "America")):
        snap = await client.state()
        truth = (await client.request("debug_world"))["objects"]
        assert any(o["template"] == f"{enemy}CommandCenter" for o in truth)
        assert not any(o["template"].startswith(enemy) for o in snap["visible"])


async def test_7_surrender(pair):
    a, b = pair["a"], pair["b"]
    victory = asyncio.ensure_future(a.wait_for_event("game_over", timeout=60))
    defeat = asyncio.ensure_future(b.wait_for_event("game_over", timeout=60))
    await asyncio.sleep(0)
    await b.surrender()
    assert (await victory)["result"] == "victory"
    assert (await defeat)["result"] == "defeat"


# -- tests 8 / 9a: an observer, watching a bot against the built-in AI ------------------------------

async def test_9a_bot_vs_builtin_ai_with_observer(results_root):
    games = start_instances(results_root / "test_lan_observer", 2)
    try:
        host, observer = await connect(games[0]), await connect(games[1])
        lobby = await host.lan_open("Bot1")
        await observer.lan_open("Watcher")
        await host.lan_host(await lan_map(host),
                            [{"type": "host"}, {"type": "easy_ai", "faction": "FactionChina"}, {"type": "open"}])
        await host.lan_slot(faction="FactionAmerica")
        await observer.lan_join(host_ip=lobby["local_ip"])
        reply = await observer.lan_slot(observer=True)
        assert reply["slots"][reply["local_slot"]]["observer"]
        with pytest.raises(ApiError) as error:
            await observer.lan_slot(observer=True, team=1)
        assert error.value.code == "BAD_REQUEST"

        await start_when_accepted(host, [observer])
        await host.wait_for_state("in_game", timeout=LOAD_TIMEOUT)
        await observer.wait_for_state("in_game", timeout=LOAD_TIMEOUT)

        players = {p["side"]: p for p in (await host.game_info())["players"]}
        assert players["China"]["relation"] == "enemy" and players["China"]["type"] == "computer"

        # The observer sees the whole map and owns nothing.
        snap = await observer.state()
        assert snap["units"] == []
        assert {o["template"] for o in command_centers(snap["visible"])} >= {"AmericaCommandCenter", "ChinaCommandCenter"}
        host_cc = own(await host.state(), "AmericaCommandCenter")[0]
        with pytest.raises(ApiError) as error:
            await observer.stop([host_cc["id"]])
        assert error.value.code == "NOT_AVAILABLE"
        with pytest.raises(ApiError) as error:
            await observer.surrender()
        assert error.value.code == "NOT_AVAILABLE"

        # The AI plays inside the lockstep simulation: after a minute the observer sees it building.
        china_before = {o["id"] for o in snap["visible"] if o["template"].startswith("China")}
        await asyncio.sleep(60)
        snap = await observer.state()
        china_after = {o["id"] for o in snap["visible"] if o["template"].startswith("China")}
        assert china_after - china_before, "the built-in AI should have built or trained something"
        await host.close()
        await observer.close()
    finally:
        stop_instances(games)
