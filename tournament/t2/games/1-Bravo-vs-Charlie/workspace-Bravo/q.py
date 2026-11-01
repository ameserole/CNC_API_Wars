import sys,asyncio
sys.path.insert(0,r'C:\Users\user\Documents\CNC_Generals_AI\python')
from generals_api import GeneralsClient
from generals_api.client import watcher_url
async def m():
    async with GeneralsClient(watcher_url("ws://127.0.0.1:65320")) as c:
        s=await c.state()
        t=[u["id"] for u in s["units"] if "Truck" in u["template"]]
        print(t)
        for k in ("visible","known_structures"):
            v=s[k]; v=v.values() if isinstance(v,dict) else v
            for o in v:
                if isinstance(o,dict) and o.get("supply"): print(o["id"],[int(x) for x in o["pos"][:2]],o["supply"])
asyncio.run(m())
