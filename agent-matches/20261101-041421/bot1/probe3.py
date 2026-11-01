import sys, asyncio, json
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64631", request_timeout=60).connect()
    await c.hello()
    s = await c.state()
    print(s["frame"], s["known_structures"][:10], s["visible"][:10])
    m = await c.map()
    print([k for k in m])
    for k in m:
        if k not in ("heights","terrain"): print(k, str(m[k])[:2000])
    await c.close()
asyncio.run(main())
