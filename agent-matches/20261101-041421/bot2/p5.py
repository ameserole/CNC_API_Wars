import sys, asyncio, json, math
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64632", request_timeout=60).connect()
    await c.hello()
    s = await c.state()
    print(s["frame"], s["self"])
    for o in s["visible"]:
        if o.get("owner") == 2: print("V", o["template"], o["id"], [round(x) for x in o["pos"]], o.get("health"))
    for o in s["known_structures"]:
        if o.get("owner") == 2: print("K", o)
    army = [u for u in s["units"] if any(k in u["template"] for k in ("Tank", "Tomahawk", "Infantry"))]
    xs = sorted([round(u["pos"][0]) for u in army]); ys = sorted([round(u["pos"][1]) for u in army])
    print("army x", xs); print("army y", ys)
    for u in s["units"]:
        if "Chinook" in u["template"]: print(u["template"], [round(x) for x in u["pos"]], u["status"])
    await c.close()
asyncio.run(main())
