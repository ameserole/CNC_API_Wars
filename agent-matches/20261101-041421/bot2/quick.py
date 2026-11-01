import sys, asyncio, json
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, ApiError
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64632", request_timeout=60).connect()
    await c.hello()
    try: print(await c.train(145, "AmericaVehicleDozer", count=2))
    except ApiError as e: print("train", e)
    for pos in [(1004,800),(1150,700),(860,700),(1200,580)]:
        try: print(await c.build(146, "AmericaPowerPlant", pos)); break
        except ApiError as e: print("build", pos, e)
    cat = await c.catalog(); json.dump(cat, open("catalog.json","w"), indent=1)
    m = await c.map(); json.dump(m, open("map.json","w"))
    s = await c.state(); json.dump(s, open("state.json","w"), indent=1)
    await c.close()
asyncio.run(main())
