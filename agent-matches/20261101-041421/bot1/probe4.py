import sys, asyncio, json
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64631", request_timeout=60).connect()
    await c.hello()
    s = await c.state()
    print(s["self"])
    for u in s["units"]:
        if u["template"] in ("AmericaVehicleChinook","AmericaSupplyCenter","AmericaVehicleDozer") or "Tank" in u["template"]: print(u)
    for v in s["visible"]: print("V", v)
    for k in s["known_structures"]:
        if k["owner"] not in (0,1): print("K", k)
    await c.close()
asyncio.run(main())
