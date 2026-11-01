import sys, asyncio, json
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64631", request_timeout=60).connect()
    await c.hello()
    m = await c.map(cell_size=40)
    t = m["terrain"]
    json.dump(m, open("map.json","w"))
    for r in range(len(t)-1, -1, -1):
        print(f"{r*40:5d} {t[r]}")
    await c.close()
asyncio.run(main())
