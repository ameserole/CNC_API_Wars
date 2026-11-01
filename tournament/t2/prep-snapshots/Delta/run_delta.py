"""Connects Delta's bot to a running game as the controller.

    python run_delta.py ws://127.0.0.1:PORT

Logs to delta_bot.log next to this file. Re-run it to reconnect (it replaces the previous controller).
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "C:/Users/user/Documents/CNC_Generals_AI/python")
sys.path.insert(0, str(HERE))

from generals_api import GeneralsClient, World  # noqa: E402
import delta_bot  # noqa: E402

LOG = HERE / "delta_bot.log"


def log(message: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {message}\n")


async def main(url: str) -> None:
    client = await GeneralsClient(url, request_timeout=60).connect()
    await client.hello()
    log(f"connected {url} state={client.game_state}")
    await client.wait_for_state("in_game", timeout=300)
    world = World().attach(client)
    await world.load(client)
    client.on("game_over", lambda ev: log(f"game over: {ev.get('result')}"))
    try:
        await delta_bot.run(client, world)
        log("bot returned")
    except Exception as error:  # keep the log useful if the bot dies
        log(f"bot error: {error!r}")
        raise


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
