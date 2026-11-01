"""Phase 9: faction catalogs, player stats, finished games closing, and the tournament runner's games.

The first test uses the module's shared game in the menus; the others start their own instances
(LAN games with two players and an observer), so they don't share state.
"""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from generals_api import ApiError, ConnectionClosed, GeneralsClient, World, launcher
from generals_api.client import watcher_url
from generals_api import tournament as t

from .gamehost import GAME_DIR, GAME_EXE
from .helpers import TIMEOUT

pytestmark = pytest.mark.integration

BOT = Path(__file__).resolve().parents[2] / "bots" / "simple.py"
SHORT_GAME_FRAMES = 30 * 75  # 75 s of game time: long enough to build something, short enough for a test


# -- faction_catalog -------------------------------------------------------------------------------

async def test_faction_catalog_for_every_faction(game):
    async with GeneralsClient(game.url, request_timeout=TIMEOUT) as c:
        assert (await c.hello())["game_state"] == "shell"
        factions = [f["name"] for f in (await c.skirmish_options())["factions"]]
        assert len(factions) == 12
        for faction in factions:
            cat = await c.faction_catalog(faction)
            assert cat["faction"] == faction and cat["side"] == t.side_of(faction)
            structures = {s["name"]: s for s in cat["structures"]}
            units = {u["name"]: u for u in cat["units"]}
            assert any(n.endswith("CommandCenter") for n in structures), faction
            assert any(n.endswith("Dozer") or n.endswith("Worker") for n in units), faction
            assert all(s["cost"] >= 0 and "prerequisites" in s and "built_by" in s for s in cat["structures"])
            assert cat["sciences"] and {s["tier"] for s in cat["sciences"]} <= {1, 2, 3}
            assert cat["upgrades"], faction
        with pytest.raises(ApiError) as error:
            await c.faction_catalog("FactionNod")
        assert error.value.code == "INVALID_ARGUMENT"


# -- a finished game closes by itself --------------------------------------------------------------

async def idle(client, world):
    await asyncio.Event().wait()


async def surrender_soon(client, world):
    await asyncio.sleep(5)
    await client.request("surrender")
    await asyncio.Event().wait()


@pytest.mark.timeout(400)
async def test_finished_lan_game_closes_every_instance(results_root, tmp_path):
    bots = tmp_path / "bots.py"
    bots.write_text("")  # load_bot is replaced below; the launcher only needs a path per bot
    args = launcher.parse_args(["--bot1", str(bots), "--bot2", str(bots), "--observer"])
    plan = launcher.make_plan(args)
    runs = {"bot1": idle, "bot2": surrender_soon}
    observer_events = []

    late_hello = {}

    async def watch_observer(clients):
        clients["observer"].on("game_over", observer_events.append)
        while not observer_events:
            await asyncio.sleep(0.5)
        # A client that connects after game_over (a watcher here) still learns the result.
        async with GeneralsClient(watcher_url(f"ws://127.0.0.1:{plan.instance('bot1').port}")) as late:
            late_hello.update(await late.hello())
        await asyncio.Event().wait()

    (t.REPLAY_DIR / "phase9 finished game.rep").unlink(missing_ok=True)  # from an earlier run
    original = launcher.load_bot
    launcher.load_bot = lambda path, _runs=iter(runs.values()): next(_runs)
    try:
        summary = await asyncio.wait_for(launcher.play(
            plan, extra_args=["-ignoreAsserts", "-scriptApiDebug"], keep_observer=False, replay="phase9 finished game",
            on_in_game=watch_observer), timeout=300)
    finally:
        launcher.load_bot = original

    assert summary["results"] == {"bot1": "victory", "bot2": "defeat"}
    assert summary.get("replay") == "phase9 finished game.rep", summary
    assert observer_events and observer_events[0]["result"] == "ended"
    assert late_hello.get("game_result") == "victory", late_hello
    winners = observer_events[0]["winners"]
    assert len(winners) == 1
    assert {p["index"] for p in observer_events[0]["stats"]} >= set(winners)
    for role, proc in summary["processes"].items():
        assert await asyncio.to_thread(proc.wait, 60) == 0, role


# -- the tournament runner -------------------------------------------------------------------------

def tournament_dir(tmp_path, agents, factions) -> tuple[Path, "t.Config"]:
    root = tmp_path / "tournament"
    config = t.make_config("it", [t.Agent(name, "haiku") for name in agents], seed=3)
    config.game_minutes = SHORT_GAME_FRAMES / 30 / 60
    t.init_tournament(root, config)
    for name, faction in zip(agents, factions):
        (root / "agents" / name / "bot.json").write_text(json.dumps({"faction": faction}))
    return root, config


async def stand_in(port: int, checks: dict, name: str) -> None:
    """Plays an agent's side with the reference bot until the referee ends the game."""
    try:
        async with GeneralsClient(f"ws://127.0.0.1:{port}", request_timeout=TIMEOUT) as c:
            await c.hello()
            stats = await c.player_stats()
            checks[name] = {"stats": stats, "faction": (await c.catalog())["faction"]}
            world = World().attach(c)
            await world.load(c)
            await launcher.load_bot(BOT)(c, world)
    except (ConnectionClosed, ApiError, asyncio.CancelledError):
        pass  # the referee takes over the connection at the end


@pytest.mark.timeout(900)
async def test_runner_plays_a_game_to_the_time_limit(results_root, tmp_path):
    root, config = tournament_dir(tmp_path, ["Alpha", "Bravo"], ["FactionChina", "FactionGLAToxinGeneral"])
    slot = t.next_game(config, {})
    checks: dict = {}
    tasks = []

    async def on_ready(info):
        for name, player in info["players"].items():
            tasks.append(asyncio.ensure_future(stand_in(player["port"], checks, name)))

    record = await t.run_game(root, slot, on_ready=on_ready, extra_args=["-ignoreAsserts"])
    await asyncio.gather(*tasks, return_exceptions=True)

    # Factions as declared, each player saw only its own stats during the game.
    assert checks["Alpha"]["faction"] == "China" and checks["Bravo"]["faction"] == "GLAToxinGeneral"
    for name in ("Alpha", "Bravo"):
        assert checks[name]["stats"]["all"] is False and len(checks[name]["stats"]["players"]) == 1

    game_dir = root / "games" / record["folder"]
    saved = json.loads((game_dir / "game.json").read_text())
    assert saved["reason"] in ("time_limit", "game_over")
    assert {saved["winner"], saved["loser"]} == {"Alpha", "Bravo"}  # a bracket game always has a winner
    assert saved["factions"] == {"Alpha": "FactionChina", "Bravo": "FactionGLAToxinGeneral"}
    assert saved["models"] == {"Alpha": "haiku", "Bravo": "haiku"}
    assert {p["name"] for p in saved["stats"]} == {"Alpha", "Bravo"}
    assert all(p["units_built"] >= 0 and "score" in p for p in saved["stats"])
    assert set(saved["start_positions"]) == {"Alpha", "Bravo"}
    assert saved["frames"] >= SHORT_GAME_FRAMES or saved["reason"] == "game_over"
    for name in ("Alpha", "Bravo"):
        assert (root / "agents" / name / "reports" / f"game-{slot.number}.json").exists()
    results = json.loads((root / "results.json").read_text())
    assert str(slot.number) in results
    assert (root / "bracket.md").exists()

    # The saved replay plays back.
    replay = game_dir / "replay.rep"
    assert replay.exists()
    target = t.REPLAY_DIR / f"phase9 runner test.rep"
    target.write_bytes(replay.read_bytes())
    result = await asyncio.to_thread(subprocess.run, [str(GAME_EXE), "-headless", "-ignoreAsserts", "-replay", target.name],
                                     cwd=GAME_DIR, capture_output=True, text=True, timeout=600)
    (results_root / "tournament_replay_simulation.txt").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout[-2000:]

    for role, pid in saved["pids"].items():
        assert not t.process_running(pid), f"{role} still running"


@pytest.mark.timeout(1800)
async def test_bracket_of_four_runs_end_to_end(results_root, tmp_path):
    root, config = tournament_dir(tmp_path, ["Alpha", "Bravo", "Charlie", "Delta"],
                                  ["FactionAmerica", "FactionChina", "FactionGLA", "FactionAmericaAirForceGeneral"])

    async def on_ready(info):
        for name, player in info["players"].items():
            asyncio.ensure_future(stand_in(player["port"], {}, name))

    played = []
    while (slot := t.next_game(config, t.load_results(root))) is not None:
        played.append((await t.run_game(root, slot, on_ready=on_ready, extra_args=["-ignoreAsserts"]))["folder"])
    assert len(played) == 3
    results = t.load_results(root)
    champion = t.champion(config, results)
    assert champion is not None
    assert f"Champion: **{champion}**" in (root / "bracket.md").read_text()
