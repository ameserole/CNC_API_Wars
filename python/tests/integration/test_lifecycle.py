"""Phase 1: launch the game, talk to the script API and shut down cleanly."""

import asyncio
import time

import pytest
from websockets.asyncio.client import connect

from generals_api import ApiError, ConnectionClosed, GeneralsClient

from .gamehost import GameProcess  # noqa: F401  (fixture type)


async def test_hello(game, transcript):
    async with GeneralsClient(game.url, transcript=transcript) as client:
        hello = await client.hello()
        assert hello["protocol_version"] == 1
        assert hello["game"] == "zh"
        assert hello["build"] in ("debug", "release")
        assert hello["game_state"] == "shell"
        assert isinstance(hello["frame"], int)


async def test_hello_rejects_other_protocol_version(game):
    async with GeneralsClient(game.url) as client:
        with pytest.raises(ApiError) as info:
            await client.request("hello", protocol_version=999)
        assert info.value.code == "PROTOCOL_MISMATCH"


async def test_ping_frames_are_monotonic_and_fast(game, transcript):
    async with GeneralsClient(game.url, transcript=transcript) as client:
        frames = []
        for _ in range(3):
            start = time.perf_counter()
            frames.append((await client.ping())["frame"])
            assert time.perf_counter() - start < 0.5
        assert frames == sorted(frames)


async def test_errors_do_not_break_the_connection(game):
    async with connect(game.url) as ws:
        await ws.send("{not json")
        bad_json = await asyncio.wait_for(ws.recv(), 5)
        assert '"BAD_JSON"' in bad_json

    async with GeneralsClient(game.url) as client:
        with pytest.raises(ApiError) as info:
            await client.request("dance")
        assert info.value.code == "UNKNOWN_COMMAND"
        assert "frame" in await client.ping()


async def test_new_client_supersedes_old(game):
    async with GeneralsClient(game.url) as first:
        await first.ping()
        async with GeneralsClient(game.url) as second:
            await first.wait_closed(timeout=5)
            assert first.close_code == 4001
            with pytest.raises(ConnectionClosed):
                await first.ping()
            assert "frame" in await second.ping()


async def test_exit_shuts_down_cleanly(fresh_game, transcript):
    async with GeneralsClient(fresh_game.url, transcript=transcript) as client:
        await client.hello()
        await client.exit()
        await client.wait_closed(timeout=10)
    exit_code = await asyncio.to_thread(fresh_game.wait_exit, 30)
    assert exit_code == 0
