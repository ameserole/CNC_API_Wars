import sys, asyncio, json
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64632", request_timeout=60).connect()
    await c.hello()
    s = await c.state()
    print(s["frame"])
    for o in s["visible"]: print("V", o["template"], o.get("owner"), [round(x) for x in o["pos"]], o.get("status"))
    for o in s["known_structures"]: print("K", o["template"], o.get("owner"), [round(x) for x in o["pos"]], o["last_seen_frame"])
    await c.close()
asyncio.run(main())
