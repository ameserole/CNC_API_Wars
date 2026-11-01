import sys, asyncio, json
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64631", request_timeout=60).connect()
    await c.hello()
    gi = await c.game_info(); print(json.dumps(gi)[:1500])
    s = await c.state()
    print(json.dumps(s["self"]))
    for u in s["units"]: print(u)
    print("visible", len(s["visible"]))
    for v in s["visible"][:40]: print(v["template"], v["pos"], v.get("owner"))
    cat = await c.catalog()
    for k in cat: 
        if isinstance(cat[k], list): print(k, [ (x.get("name"), x.get("cost"), x.get("prerequisites_met")) for x in cat[k]][:60])
    await c.close()
asyncio.run(main())
