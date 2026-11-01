"""The script API must never change the simulation, and its orders must replay exactly.

Plays an API-driven match with orders (a building, training, a move) and snapshots every frame (so every read-only hook and query runs
constantly), then re-simulates the recorded replay headless without the API. The replay carries the
logic CRCs from the live match, so any influence of the API on the simulation shows up as a CRC
mismatch. (Debug-only cheats such as debug_add_cash are deliberately not used here: they change the
local player's money outside the command stream and would rightly desync the replay.)
"""

import asyncio
import re
import subprocess

import pytest

from generals_api import ApiError, GeneralsClient, World

from .conftest import LOAD_TIMEOUT, start_match
from .gamehost import CRASH_DUMP_DIR, GAME_DIR, GAME_EXE, KNOWN_LEAKS_AFTER_MATCH

REPLAY_DIR = CRASH_DUMP_DIR.parent / "Replays"
MATCH_SECONDS = 60
SAVED_NAME = "phase7 replay test"


async def give_orders(client: GeneralsClient, world: World) -> None:
    """Orders travel through the command list like clicks, so the replay must reproduce them."""
    dozer = world.mine(template="AmericaVehicleDozer")[0]
    cc = world.mine(template="AmericaCommandCenter")[0]
    for offset in ((250, 0), (0, 250), (-250, 0), (0, -250), (300, 300)):
        try:
            pos = (cc["pos"][0] + offset[0], cc["pos"][1] + offset[1])
            await client.build(dozer["id"], "AmericaPowerPlant", pos)
            break
        except ApiError as error:
            if error.code != "ILLEGAL_LOCATION":
                raise
    await client.train(cc["id"], "AmericaVehicleDozer")


async def give_late_orders(client: GeneralsClient, world: World) -> None:
    """Orders that need the power plant: a barracks, an upgrade there, a waypoint move."""
    dozer = world.mine(template="AmericaVehicleDozer")[0]
    cc = world.mine(template="AmericaCommandCenter")[0]
    for offset in ((-300, 0), (0, -300), (300, 300), (-300, -300), (400, 0)):
        try:
            await client.build(dozer["id"], "AmericaBarracks", (cc["pos"][0] + offset[0], cc["pos"][1] + offset[1]))
            break
        except ApiError as error:
            if error.code not in ("ILLEGAL_LOCATION", "NOT_AVAILABLE"):
                raise


async def queue_any_upgrade(client: GeneralsClient, world: World) -> bool:
    barracks = world.mine(template="AmericaBarracks")
    if not barracks or "under_construction" in barracks[0]["status"]:
        return False
    for upgrade in (await client.catalog())["upgrades"]:
        if "AmericaBarracks" in upgrade["built_by"]:
            try:
                await client.upgrade(barracks[0]["id"], upgrade["name"])
                return True
            except ApiError:
                continue
    return False


async def play_and_quit(url: str) -> None:
    await start_match(url, fps_limit=60)
    async with GeneralsClient(url, request_timeout=LOAD_TIMEOUT) as client:
        world = World().attach(client)
        await world.load(client)
        await client.set_snapshot_interval(1)
        await give_orders(client, world)
        upgraded = False
        for second in range(MATCH_SECONDS):
            if second == 15:
                await give_late_orders(client, world)
                dozer = world.mine(template="AmericaVehicleDozer")[0]
                await client.move([dozer["id"]], world.mine(template="AmericaCommandCenter")[0]["pos"][:2],
                                  waypoints=[(dozer["pos"][0] + 100, dozer["pos"][1])])
            if second >= 35 and not upgraded:
                upgraded = await queue_any_upgrade(client, world)
            await client.request("map", cell_size=100)
            await client.catalog()
            await client.request("debug_world")
            await asyncio.sleep(1)
        with pytest.raises(ApiError) as error:  # still being recorded
            await client.save_replay(SAVED_NAME)
        assert error.value.code == "WRONG_STATE"
        await client.quit_game()
        await client.wait_for_state("shell", timeout=30)
        await save_replay_checks(client)
        await client.exit()


async def save_replay_checks(client: GeneralsClient) -> None:
    for bad in ("", "../escape", "a\\b", "c:x", ".hidden", "x" * 65, "00000000"):
        with pytest.raises(ApiError) as error:
            await client.save_replay(bad)
        assert error.value.code == "INVALID_ARGUMENT", bad
    assert (await client.save_replay(SAVED_NAME + ".rep", overwrite=True))["file"] == SAVED_NAME + ".rep"
    with pytest.raises(ApiError) as error:
        await client.save_replay(SAVED_NAME)
    assert error.value.code == "INVALID_ARGUMENT"
    await client.save_replay(SAVED_NAME, overwrite=True)


@pytest.mark.leak_baseline(KNOWN_LEAKS_AFTER_MATCH)
async def test_replay_of_api_match_has_no_crc_mismatch(fresh_game, results_root):
    before = {p: p.stat().st_mtime for p in REPLAY_DIR.glob("*.rep")} if REPLAY_DIR.exists() else {}
    await play_and_quit(fresh_game.url)
    assert await asyncio.to_thread(fresh_game.wait_exit, 60) == 0

    # The named copy is the replay this instance recorded (instance 1: 00000000.rep).
    replay = REPLAY_DIR / f"{SAVED_NAME}.rep"
    assert replay.exists() and before.get(replay) != replay.stat().st_mtime, f"no saved replay in {REPLAY_DIR}"
    assert replay.read_bytes() == (REPLAY_DIR / "00000000.rep").read_bytes()

    result = await asyncio.to_thread(
        subprocess.run, [str(GAME_EXE), "-headless", "-ignoreAsserts", "-replay", replay.name],
        cwd=GAME_DIR, capture_output=True, text=True, timeout=600)
    (results_root / "replay_simulation.txt").write_text(result.stdout + result.stderr)

    # A single replay stops early on the first CRC mismatch and exits with 1.
    assert result.returncode == 0, result.stdout[-2000:]
    progress = re.findall(r"Game Time: (\d+:\d+)/(\d+:\d+)", result.stdout)
    assert progress and progress[-1][0] == progress[-1][1], result.stdout[-2000:]
