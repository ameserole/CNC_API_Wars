import asyncio, sys
sys.path.insert(0, r"C:/Users/user/Documents/CNC_Generals_AI/python")
from generals_api import GeneralsClient, World
from generals_api.client import watcher_url
async def main():
    c = await GeneralsClient(watcher_url("ws://127.0.0.1:65319"), request_timeout=30).connect()
    w = World().attach(c); await w.load(c)
    print("frame", w.frame, "money", w.money)
    for u in w.units.values():
        if u.get("contained_by") is None:
            print("ME", u["id"], u["template"].replace("China",""), [int(x) for x in u["pos"][:2]], f'{u["health"]}/{u["max_health"]}', u.get("status"))
    for o in w.enemies():
        print("EN", o["id"], o["template"].replace("China",""), [int(x) for x in o["pos"][:2]], o.get("health"))
    for o in w.enemy_structures():
        print("ES", o["id"], o["template"], [int(x) for x in o["pos"][:2]], o.get("visible"))
    await c.close()
asyncio.run(main())
