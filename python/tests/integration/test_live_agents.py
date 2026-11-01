"""Phase 10: watcher connections next to the bot, `watch` and `order` (skirmish vs Easy AI).

Tests run in file order and share one match.
"""

import asyncio
import io

import pytest

from generals_api import ApiError, GeneralsClient
from generals_api import order as order_cli
from generals_api import watch as watch_cli
from generals_api.client import watcher_url

from .helpers import TIMEOUT, own, place_building

pytestmark = pytest.mark.integration


async def test_watcher_runs_alongside_the_controller(game, skirmish):
    controller = await GeneralsClient(game.url, request_timeout=TIMEOUT).connect()
    watcher = await GeneralsClient(watcher_url(game.url), request_timeout=TIMEOUT).connect()
    try:
        assert (await controller.hello())["role"] == "controller"
        assert (await watcher.hello())["role"] == "watcher"

        # Both get events.
        await controller.set_snapshot_interval(15)
        await watcher.set_snapshot_interval(15)
        seen = {"controller": 0, "watcher": 0}
        controller.on("snapshot", lambda e: seen.__setitem__("controller", seen["controller"] + 1))
        watcher.on("snapshot", lambda e: seen.__setitem__("watcher", seen["watcher"] + 1))
        await asyncio.sleep(2)
        assert seen["controller"] >= 2 and seen["watcher"] >= 2

        # The watcher's order is reported to the watcher only.
        executed = {"controller": [], "watcher": []}
        controller.on("command_executed", executed["controller"].append)
        watcher.on("command_executed", executed["watcher"].append)
        dozer = own(await watcher.state(), "AmericaVehicleDozer")[0]
        reply = await watcher.move([dozer["id"]], (dozer["pos"][0] + 60, dozer["pos"][1]))
        await watcher.wait_for_execution(reply, timeout=10)
        await asyncio.sleep(1)
        assert [e["cmd"] for e in executed["watcher"]] == ["move"]
        assert executed["controller"] == []

        # Session commands are the controller's.
        for cmd in ("quit_game", "exit", "save_replay"):
            with pytest.raises(ApiError) as error:
                await watcher.request(cmd, name="x") if cmd == "save_replay" else await watcher.request(cmd)
            assert error.value.code == "WRONG_ROLE", cmd

        # Up to three watchers; a fourth is refused.
        extra = [await GeneralsClient(watcher_url(game.url), request_timeout=TIMEOUT).connect() for _ in range(2)]
        for client in extra:
            await client.hello()
        refused = await GeneralsClient(watcher_url(game.url), request_timeout=TIMEOUT).connect()
        await refused.wait_closed(timeout=10)
        assert refused.close_code == 4003
        for client in [*extra, refused]:
            await client.close()

        # A new controller replaces the old one but not the watcher.
        replacement = await GeneralsClient(game.url, request_timeout=TIMEOUT).connect()
        await replacement.hello()
        await controller.wait_closed(timeout=10)
        assert controller.close_code == 4001
        assert (await watcher.request("ping"))["ok"] is True
        await replacement.close()
    finally:
        await controller.close()
        await watcher.close()


async def test_watch_times_out_with_a_digest(game, skirmish):
    out = io.StringIO()
    code = await watch_cli.watch(game.url, max_wait=3, state_path=None, stream=False, out=out)
    text = out.getvalue()
    assert code == 0, text
    assert text.startswith("WATCH frame") and "none (max wait)" in text
    assert "structures: AmericaCommandCenter" in text and "money" in text


async def test_watch_returns_when_a_structure_is_built(game, skirmish, tmp_path):
    state = tmp_path / "watch.json"
    out = io.StringIO()
    async with GeneralsClient(game.url, request_timeout=TIMEOUT) as bot:
        await bot.hello()
        snap = await bot.state()
        dozer, cc = own(snap, "AmericaVehicleDozer")[0], own(snap, "AmericaCommandCenter")[0]
        watching = asyncio.ensure_future(watch_cli.watch(game.url, max_wait=120, state_path=state, stream=False, out=out))
        await asyncio.sleep(2)
        await place_building(bot, dozer["id"], "AmericaPowerPlant", cc["pos"])
        code = await asyncio.wait_for(watching, timeout=150)  # returns when the plant is finished
    text = out.getvalue()
    assert code == 0, text
    assert "built" in text.splitlines()[0] and "built: AmericaPowerPlant" in text
    assert state.exists()


async def test_order_sends_a_command_alongside_the_bot(game, skirmish, capsys):
    async with GeneralsClient(game.url, request_timeout=TIMEOUT) as bot:
        await bot.hello()
        dozer = own(await bot.state(), "AmericaVehicleDozer")[0]
        assert await order_cli.send(game.url, "stop", {"units": [dozer["id"]]}, wait=True) == 0
        assert '"cmd": "stop"' in capsys.readouterr().out
        assert await order_cli.send(game.url, "attack", {"units": [dozer["id"]], "target": 999999}, wait=False) == 1
        assert (await bot.request("ping"))["ok"] is True  # the bot's connection was never replaced
