import sys, asyncio, json
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64632", request_timeout=60).connect()
    print(await c.hello())
    gi = await c.game_info(); print(json.dumps(gi)[:2000])
    s = await c.state()
    print(json.dumps({k:v for k,v in s.items() if k not in ("units","visible","known_structures")})[:1500])
    for u in s["units"]: print(u)
    print("visible", len(s.get("visible",[])))
    for o in s.get("visible",[])[:60]: print(o["template"], o.get("owner"), o["pos"], o.get("kinds"))
    cat = await c.catalog()
    print(json.dumps(cat)[:4000])
    await c.close()
asyncio.run(main())
