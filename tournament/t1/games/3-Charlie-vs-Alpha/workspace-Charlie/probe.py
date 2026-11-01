"""Quick look at the initial state. Disconnects at once (do not run while the bot runs)."""
import asyncio, json, sys
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient

async def main(url):
    c = await GeneralsClient(url, request_timeout=60).connect()
    print(json.dumps(await c.hello())[:300])
    info = await c.game_info()
    print("INFO", json.dumps(info)[:1500])
    s = await c.state()
    print("SELF", json.dumps(s.get("self")))
    for u in s["units"]:
        print("UNIT", json.dumps(u))
    for o in s["visible"]:
        print("VIS", json.dumps(o)[:300])
    cat = await c.catalog()
    print("SCI", [(x["name"], x.get("purchasable_now")) for x in cat["sciences"]][:6])
    print("SCIKEYS", list(cat["sciences"][0].keys()))
    print("MAP", json.dumps(await c.map())[:400])
    await c.close()

asyncio.run(main(sys.argv[1]))
