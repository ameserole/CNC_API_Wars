"""Probe: connect to a running game and dump what the API reports (game info, snapshot summary, catalog names)."""
import asyncio, json, sys
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, World, ApiError

OUT = r"C:\Users\user\Documents\CNC_Generals_AI\tournament\t1\agents\Delta\reports\probe.json"

async def main(url):
    client = await GeneralsClient(url, request_timeout=60).connect()
    await client.hello()
    world = await World().load(client) if False else World()
    info = await client.game_info()
    cat = await client.catalog()
    snap = await client.state()
    world.game_info = info
    world.apply_catalog(cat)
    world.apply_snapshot(snap)
    out = {"game_info": info, "snapshot_keys": list(snap.keys()), "self": snap.get("self"),
           "units": snap.get("units"), "catalog_keys": list(cat.keys()),
           "structures": [s["name"] for s in cat.get("structures", [])],
           "units_catalog": [u["name"] for u in cat.get("units", [])]}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("wrote", OUT)
    await client.close()

asyncio.run(main(sys.argv[1]))
