"""Charlie's macro bot (China). Run from anywhere:

  python bot.py ws://127.0.0.1:PORT

Loop: reload settings.json / strategy.py (botkit), call strategy.tick(). Logs to bot.log next to this file.
"""
from __future__ import annotations

import asyncio
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"C:/Users/user/Documents/CNC_Generals_AI/python")

from generals_api import ApiError, GeneralsClient, World  # noqa: E402
from generals_api.botkit import LiveModule, LiveSettings, exit_when_superseded  # noqa: E402

LOG = open(HERE / "bot.log", "a", buffering=1, encoding="utf-8")


def log(*parts):
    LOG.write(time.strftime("%H:%M:%S ") + " ".join(str(p) for p in parts) + "\n")


async def main(url: str) -> None:
    client = await GeneralsClient(url, request_timeout=60).connect()
    hello = await client.hello()
    log("connected", hello.get("game_state"), "apm", hello.get("apm_limit"))
    exit_when_superseded(client)
    if hello.get("game_state") != "in_game":
        await client.wait_for_state("in_game", timeout=600)
    world = World().attach(client)
    await world.load(client)
    settings = LiveSettings(HERE / "settings.json", defaults={})
    strategy = LiveModule(HERE / "strategy.py")
    memory: dict = {}
    while world.result is None:
        settings.reload()
        if strategy.reload():
            log("strategy reloaded", strategy.error or "ok")
        try:
            await strategy.module.tick(client, world, settings, memory, log)
        except ApiError as e:
            log("ApiError", e.code, e)
        except Exception:
            log("tick crashed\n" + traceback.format_exc())
        await asyncio.sleep(float(settings.get("tick_seconds", 2.0)))
    log("game over:", world.result)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:5000"))
