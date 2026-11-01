import sys, asyncio, json
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, ApiError
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64632", request_timeout=60).connect()
    await c.hello()
    s = await c.state(); print(s["frame"], s["self"])
    for u in s["units"]: print(u)
    await c.close()
asyncio.run(main())
