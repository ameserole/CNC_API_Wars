"""Watcher probe: prints own structures (incl. under construction) and unit counts. Usage: probe.py ws://127.0.0.1:PORT"""

import asyncio
import sys

sys.path.insert(0, "C:/Users/user/Documents/CNC_Generals_AI/python")
from generals_api import GeneralsClient  # noqa: E402
from generals_api.client import watcher_url  # noqa: E402


async def main(url: str) -> None:
    client = await GeneralsClient(watcher_url(url), request_timeout=30).connect()
    await client.hello()
    snap = await client.state()
    for u in snap["units"]:
        if u["template"].startswith("China") and ("Factory" in u["template"] or "Barracks" in u["template"]
                                                  or "Dozer" in u["template"] or "Power" in u["template"]):
            print(u["id"], u["template"], u.get("under_construction"), u.get("idle"), u["pos"])
    print("units", len(snap["units"]), "money", snap["self"].get("money"))
    await client.close()


asyncio.run(main(sys.argv[1]))
