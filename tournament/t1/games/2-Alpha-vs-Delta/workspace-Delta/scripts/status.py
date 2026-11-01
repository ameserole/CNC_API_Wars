import asyncio, json, sys, time
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient
async def main():
    c = await GeneralsClient("ws://127.0.0.1:55157", request_timeout=30).connect()
    await c.hello()
    s = await c.state()
    print("keys", list(s.keys()))
    print("self", s.get("self"))
    print("frame", s.get("frame"), "game_state", s.get("game_state"))
    for u in s["units"]:
        if u.get("contained_by") is None:
            print(u["id"], u["template"], u.get("pos"), u.get("status"), u.get("health"), u.get("under_construction"))
    try:
        print("stats", await c.player_stats())
    except Exception as e: print("stats err", e)
    await c.close()
asyncio.run(main())
