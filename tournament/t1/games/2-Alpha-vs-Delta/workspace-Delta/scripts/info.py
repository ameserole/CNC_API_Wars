import asyncio, json, sys, math
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:55157", request_timeout=30).connect()
    await c.hello()
    gi = await c.game_info()
    print("game_info", json.dumps(gi, default=str)[:1500])
    s = await c.state()
    print("visible", json.dumps(s["visible"], default=str)[:2500])
    print("known", json.dumps(s["known_structures"], default=str)[:800])
    cat = await c.catalog()
    print("catalog keys", list(cat.keys()))
    for k in ("structures","units"):
        for e in cat.get(k, []):
            print(k, e.get("name"), e.get("cost"), e.get("build_time"), e.get("prerequisites") or e.get("requires"))
    await c.close()
asyncio.run(main())
