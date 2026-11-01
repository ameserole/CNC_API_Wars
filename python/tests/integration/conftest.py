import asyncio
import os
import re
import time
from pathlib import Path

import pytest

from .gamehost import GAME_EXE, ROOT, GameProcess


def pytest_collection_modifyitems(config, items):
    if GAME_EXE.exists():
        return
    skip = pytest.mark.skip(reason=f"{GAME_EXE} not found; run scripts/build.ps1 -Deploy first")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def results_root() -> Path:
    root = Path(os.environ.get("GENERALS_TEST_RESULTS", ROOT / "test-results" / time.strftime("%Y%m%d-%H%M%S")))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _launch(results_dir: Path, leak_baseline: int | None = None):
    game = GameProcess(results_dir, **({} if leak_baseline is None else {"leak_baseline": leak_baseline})).start()
    yield game
    game.kill()
    problems = game.collect_artifacts()
    assert not problems, f"game reported problems (see {results_dir}): {problems}"


@pytest.fixture(scope="module")
def game(results_root, request):
    """One game instance shared by the tests in a module."""
    yield from _launch(results_root / request.module.__name__.rsplit(".", 1)[-1])


@pytest.fixture
def fresh_game(results_root, request):
    """A game instance owned by a single test (for tests that end the process).

    Tests that exit cleanly after playing a match mark themselves with
    @pytest.mark.leak_baseline(KNOWN_LEAKS_AFTER_MATCH).
    """
    marker = request.node.get_closest_marker("leak_baseline")
    yield from _launch(results_root / re.sub(r"[^\w.-]", "_", request.node.name), marker.args[0] if marker else None)


@pytest.fixture
def transcript(results_root, request) -> Path:
    return results_root / f"{re.sub(r'[^\w.-]', '_', request.node.name)}.events.jsonl"


# -- skirmish ------------------------------------------------------------------------------------

PREFERRED_MAP = "tournament desert"
LOAD_TIMEOUT = 120.0


def choose_map(options: dict) -> str:
    """Tournament Desert if present, else the first official 2-player map, else any 2+ player map."""
    maps = options["maps"]
    for m in maps:
        if PREFERRED_MAP in m["name"].lower():
            return m["name"]
    for candidates in ([m for m in maps if m["official"] and m["players"] == 2], [m for m in maps if m["players"] >= 2]):
        if candidates:
            return candidates[0]["name"]
    raise RuntimeError("no skirmish map with at least 2 players")


def default_players() -> list[dict]:
    return [{"type": "script", "faction": "FactionAmerica"}, {"type": "easy_ai", "faction": "FactionChina"}]


async def start_match(url: str, **overrides) -> dict:
    """Starts a skirmish against an Easy AI and waits for in_game. Returns the reply plus the states seen."""
    from generals_api import GeneralsClient

    async with GeneralsClient(url, request_timeout=LOAD_TIMEOUT) as client:
        await client.hello()
        options = await client.skirmish_options()
        states = []
        client.on("game_state", lambda ev: states.append(ev["state"]))
        args = {"map": choose_map(options), "players": default_players(), "seed": 1234, **overrides}
        reply = await client.start_skirmish(**args)
        await client.wait_for_state("in_game", timeout=LOAD_TIMEOUT)
        return {**reply, "states_seen": states, "options": options}


async def end_match(url: str) -> None:
    from generals_api import ApiError, GeneralsClient

    async with GeneralsClient(url) as client:
        if (await client.hello())["game_state"] != "in_game":
            return
        try:
            await client.quit_game()
        except ApiError:
            return
        await client.wait_for_state("shell", timeout=30)


@pytest.fixture(scope="module")
def skirmish(game):
    """A running skirmish (script player vs Easy AI) in the module's shared game."""
    match = asyncio.run(start_match(game.url))
    yield match
    asyncio.run(end_match(game.url))
