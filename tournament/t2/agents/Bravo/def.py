import asyncio,sys,math
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, World
async def m():
    c=await GeneralsClient("ws://127.0.0.1:60582",request_timeout=30).connect()
    s=await c.state()
    me=s["self"]; print(me if not isinstance(me,dict) else list(me.keys()))
    mine=[u for u in s["units"] if u["template"].endswith(("Redguard","BattleMaster","TankGattling"))]
    ids=[u["id"] for u in mine]
    e=[o for o in s["visible"] if o.get("owner")!=(me.get("player") if isinstance(me,dict) else me) and "pos" in o and not o.get("supply") and o["pos"][1]<1500]
    e=[o for o in e if o["template"].startswith("China") and o["owner"]!=me["index"]]; e.sort(key=lambda o:o["pos"][1]); print(len(ids),len(e),e[:2])
    await c.attack_move(ids,[1004,760,40])
asyncio.run(m())
