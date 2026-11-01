import asyncio, json, sys, math
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
HOME=(1004.8,583.6)
async def main():
    c = await GeneralsClient("ws://127.0.0.1:55157", request_timeout=30).connect()
    await c.hello()
    s = await c.state()
    rows=[]
    for k in s["known_structures"]+s["visible"]:
        p=k["pos"]; rows.append((round(math.dist(p[:2],HOME)), k["template"], k.get("owner"), [round(x) for x in p[:2]], k.get("visible")))
    rows.sort()
    for r in rows[:40]: print(r)
    print("total", len(rows))
    await c.close()
asyncio.run(main())
