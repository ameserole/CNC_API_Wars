import sys, asyncio, json
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:64631", request_timeout=60).connect()
    await c.hello()
    cat = await c.catalog()
    print(json.dumps(cat["structures"][7])); print(json.dumps(cat["units"][4]))
    m = await c.map()
    print({k:(v if not isinstance(v,(list,dict)) or len(json.dumps(v))<400 else str(v)[:400]) for k,v in m.items()})
    s = await c.state()
    print([k for k in s])
    print(s.get("supply_sources") or [o for o in s.get("visible",[])][:5])
    await c.close()
asyncio.run(main())
