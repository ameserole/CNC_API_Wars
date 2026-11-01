import sys, asyncio, json
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64632", request_timeout=60).connect()
    await c.hello()
    s = await c.state()
    for u in s["units"]:
        if "Chinook" in u["template"] or "Supply" in u["template"]: print(u["template"], u["id"], [round(x) for x in u["pos"]], u["status"], u.get("health"))
    for o in s["known_structures"]:
        if "Supply" in o["template"] or "Wherehouse" in o["template"]: print("K", o)
    ti = await c.template_info(["SupplyDock","AmericaVehicleChinook"])
    print(json.dumps(ti)[:1500])
    await c.close()
asyncio.run(main())
