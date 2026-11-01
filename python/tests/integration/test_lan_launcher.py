"""Phase 6 tests 9 / 9b: the launcher plays whole matches, with an observer client."""

import asyncio
import re
import subprocess

import pytest

from generals_api import ApiError, GeneralsClient, launcher

from .gamehost import DEFAULT_ARGS, GAME_DIR, GAME_EXE, KNOWN_LEAKS_AFTER_MATCH, GameProcess
from .test_lan import command_centers, stop_instances
from .test_replay_consistency import REPLAY_DIR

pytestmark = pytest.mark.integration

BOT = str(launcher.ROOT / "python" / "bots" / "simple.py")
LAN_REPLAY = "phase7 lan launcher test"


def run_launcher(results_dir, argv: list[str], duration: float, replay: str | None = None) -> dict:
    """Runs the launcher with harness arguments and checks the observer's view once the match runs.

    Returns the launcher's summary. The logs of all instances are checked like the fixtures' logs.
    """
    args = launcher.parse_args(["--bot1", BOT, *argv])
    plan = launcher.make_plan(args)
    harness_args = [a for a in DEFAULT_ARGS if a not in launcher.WINDOW_ARGS and not re.fullmatch(r"\d+", a)]
    games = {inst.role: GameProcess(results_dir / inst.role, port=inst.port, leak_baseline=KNOWN_LEAKS_AFTER_MATCH)
             for inst in plan.instances}

    def started(procs):
        for role, proc in procs.items():
            games[role].adopt(proc)

    try:
        return asyncio.run(launcher.play(plan, map=args.map, extra_args=harness_args, duration=duration,
                                         keep_observer=False, replay=replay, on_started=started,
                                         on_in_game=observe_both_bases))
    finally:
        stop_instances(list(games.values()))


async def observe_both_bases(clients: dict[str, GeneralsClient]) -> dict:
    """What the observer client sees a few seconds into the match."""
    await asyncio.sleep(5)
    snap = await clients["observer"].state()
    with pytest.raises(ApiError) as error:
        await clients["observer"].stop([snap["visible"][0]["id"]])
    return {"units": snap["units"], "ccs": len(command_centers(snap["visible"])), "order_error": error.value.code}


@pytest.mark.timeout(900)
def test_9_launcher_bot_vs_bot_with_observer(results_root):
    """Also phase 7 test 7: the match is kept as a named replay, which plays back without a CRC mismatch."""
    saved = REPLAY_DIR / f"{LAN_REPLAY}.rep"
    saved.unlink(missing_ok=True)
    summary = run_launcher(results_root / "test_lan_launcher", ["--bot2", BOT,
                                                                "--bot2-faction", "China", "--observer"],
                           duration=120, replay=LAN_REPLAY)
    for role in ("bot1", "bot2"):
        assert summary["events"][role].get("construction_complete", 0) >= 1, summary["events"]
    observed = summary["observed"]
    assert observed["units"] == [] and observed["ccs"] >= 2 and observed["order_error"] == "NOT_AVAILABLE", observed

    assert summary.get("replay") == saved.name, summary
    result = subprocess.run([str(GAME_EXE), "-headless", "-ignoreAsserts", "-replay", saved.name],
                            cwd=GAME_DIR, capture_output=True, text=True, timeout=600)
    (results_root / "lan_replay_simulation.txt").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout[-2000:]
    # Exit code 0: every recorded command and CRC was replayed. Playback stops at the last recorded
    # message, but the header's length is the frame the recording stopped at; leaving a LAN game takes
    # a few message-free seconds after bot 1's self-destruct, so the end falls short by that much (seen:
    # 1-2 s; see Plans/Phase-7-Hardening-Replays.md, Findings).
    progress = re.findall(r"Game Time: (\d+):(\d+)/(\d+):(\d+)", result.stdout)
    assert progress, result.stdout[-2000:]
    played_m, played_s, total_m, total_s = map(int, progress[-1])
    assert (total_m * 60 + total_s) - (played_m * 60 + played_s) <= 5, result.stdout[-2000:]


@pytest.mark.timeout(600)
def test_9b_launcher_bot_vs_ai_with_observer(results_root):
    summary = run_launcher(results_root / "test_lan_launcher_ai", ["--vs-ai", "easy", "--ai-faction", "China",
                                                                   "--observer"],
                           duration=90)
    assert summary["events"]["bot1"].get("construction_complete", 0) >= 1, summary["events"]
    assert summary["observed"]["ccs"] >= 2, summary["observed"]
