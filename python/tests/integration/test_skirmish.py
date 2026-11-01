"""Phase 2: start a skirmish against an Easy AI, watch it run, quit and start again.

Tests run in file order and share one game: shell-state tests first, then the running match,
then quitting and a second match.
"""

import asyncio
import time

import pytest

from generals_api import ApiError, GeneralsClient

from .conftest import LOAD_TIMEOUT, choose_map, default_players


# -- in the shell --------------------------------------------------------------------------------

async def test_skirmish_options(game):
    async with GeneralsClient(game.url) as client:
        options = await client.skirmish_options()
    assert any(m["players"] >= 2 for m in options["maps"])
    assert all({"name", "display_name", "players", "official"} <= m.keys() for m in options["maps"])
    factions = {f["name"] for f in options["factions"]}
    assert {"FactionAmerica", "FactionChina", "FactionGLA"} <= factions
    assert options["colors"] and options["colors"][0]["index"] == 0
    assert options["starting_cash"]["default"] in options["starting_cash"]["options"]
    assert options["ai_types"] == ["easy_ai", "medium_ai", "hard_ai"]


async def test_quit_game_in_shell_is_wrong_state(game):
    async with GeneralsClient(game.url) as client:
        with pytest.raises(ApiError) as info:
            await client.quit_game()
        assert info.value.code == "WRONG_STATE"


async def test_world_queries_need_a_game(game):
    async with GeneralsClient(game.url) as client:
        for cmd in ("game_info", "catalog", "state", "map"):
            with pytest.raises(ApiError) as info:
                await client.request(cmd)
            assert info.value.code == "WRONG_STATE", cmd


@pytest.mark.parametrize("override", [
    {"map": "maps\\no such map\\no such map.map"},
    {"players": [{"type": "script", "faction": "FactionMartian"}, {"type": "easy_ai"}]},
    {"players": [{"type": "script"}, {"type": "easy_ai"}, {"type": "easy_ai"}, {"type": "easy_ai"},
                 {"type": "easy_ai"}, {"type": "easy_ai"}, {"type": "easy_ai"}, {"type": "easy_ai"}]},
    {"starting_cash": 12345},
])
async def test_invalid_arguments_are_rejected(game, override):
    async with GeneralsClient(game.url) as client:
        options = await client.skirmish_options()
        args = {"map": choose_map(options), "players": default_players(), **override}
        with pytest.raises(ApiError) as info:
            await client.start_skirmish(**args)
        assert info.value.code == "INVALID_ARGUMENT"
        assert (await client.hello())["game_state"] == "shell"


async def test_malformed_start_is_bad_request(game):
    async with GeneralsClient(game.url) as client:
        with pytest.raises(ApiError) as info:
            await client.request("start_skirmish", map="x", players=[{"type": "easy_ai"}])
        assert info.value.code == "BAD_REQUEST"


# -- in a match ----------------------------------------------------------------------------------

async def test_start_goes_through_loading_to_in_game(skirmish):
    assert skirmish["states_seen"][:2] == ["loading", "in_game"]
    assert skirmish["players"][0]["type"] == "script"
    assert skirmish["players"][1]["type"] == "easy_ai"
    assert skirmish["seed"] == 1234


async def test_frames_advance_in_real_time(game, skirmish):
    async with GeneralsClient(game.url) as client:
        first = (await client.ping())["frame"]
        start = time.monotonic()
        await asyncio.sleep(5)
        last = (await client.ping())["frame"]
        elapsed = time.monotonic() - start
    rate = (last - first) / elapsed
    assert 20 <= rate <= 40, f"logic ran at {rate:.1f} frames/s"


async def test_start_while_in_game_is_wrong_state(game, skirmish):
    async with GeneralsClient(game.url) as client:
        with pytest.raises(ApiError) as info:
            await client.start_skirmish(skirmish["map"], default_players())
        assert info.value.code == "WRONG_STATE"


async def test_quit_returns_to_shell(game, skirmish, transcript):
    async with GeneralsClient(game.url, transcript=transcript) as client:
        assert (await client.hello())["game_state"] == "in_game"
        await client.quit_game()
        await client.wait_for_state("shell", timeout=30)


# -- after quitting ------------------------------------------------------------------------------

async def test_second_match_and_requests_during_loading(game, transcript):
    async with GeneralsClient(game.url, request_timeout=LOAD_TIMEOUT, transcript=transcript) as client:
        assert (await client.hello())["game_state"] == "shell"
        options = await client.skirmish_options()
        await client.start_skirmish(choose_map(options), default_players(), seed=99)
        await client.wait_for_state("loading", timeout=30)

        # A request sent while loading is answered either in the one engine frame between the two
        # startNewGame passes or once the blocking load has finished. Either way it gets a reply, and
        # starting another match is refused.
        assert (await client.ping())["frame"] >= 0
        with pytest.raises(ApiError) as info:
            await client.start_skirmish(choose_map(options), default_players())
        assert info.value.code == "WRONG_STATE"

        await client.wait_for_state("in_game", timeout=LOAD_TIMEOUT)
        await client.quit_game()
        await client.wait_for_state("shell", timeout=30)
