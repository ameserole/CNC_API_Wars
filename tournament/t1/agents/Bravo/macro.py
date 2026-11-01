"""Bravo macro bot (China Tank General). Usage: macro.py ws://127.0.0.1:PORT [logfile]
Power -> Supply Center (+trucks) -> Barracks -> War Factory -> mass BattleMasters, attack waves."""
import asyncio, math, sys, time
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, World, ApiError

LOG = open(sys.argv[2] if len(sys.argv) > 2 else "macro.log", "a", buffering=1)
def log(*a): print(time.strftime("%H:%M:%S"), *a, file=LOG)

def mine(snap, suf): return [u for u in snap["units"] if u["template"].endswith(suf)]

async def place(c, builder, tpl, near):
    for r in (250, 350, 450, 550, 650):
        for s in range(12):
            a = s * math.pi / 6
            pos = (near[0] + r * math.cos(a), near[1] + r * math.sin(a))
            st = asyncio.ensure_future(c.wait_for_event("construction_started", lambda e: e["template"] == tpl, timeout=30))
            try:
                await c.build(builder, tpl, pos)
                return (await st)["id"]
            except ApiError as e:
                if e.code != "ILLEGAL_LOCATION":
                    log("build err", tpl, e.code, e); 
                    if e.code == "INSUFFICIENT_FUNDS": await asyncio.sleep(5); continue
                    return None
            except asyncio.TimeoutError:
                log("start timeout", tpl); return None
            finally: st.cancel()
    return None

async def build(c, builder, tpl, near):
    b = await place(c, builder, tpl, near)
    log("placed", tpl, b)
    if b is not None:
        try: await c.wait_for_event("construction_complete", lambda e: e["id"] == b, timeout=150)
        except Exception as e: log("complete wait fail", tpl, e)
    return b

async def main():
    c = await GeneralsClient(sys.argv[1], request_timeout=60).connect(); await c.hello()
    gi = await c.game_info() if hasattr(c, "game_info") else None
    snap = await c.state()
    hq = next(u for u in snap["units"] if u["template"].endswith("CommandCenter"))
    home = hq["pos"]
    starts = gi["start_positions"] if gi else []
    enemy = max(starts, key=lambda p: math.dist(p, home[:2])) if starts else None
    dozer = mine(snap, "VehicleDozer")[0]["id"]
    log("home", home, "enemy", enemy)
    await build(c, dozer, "Tank_ChinaPowerPlant", home)
    sc = await build(c, dozer, "Tank_ChinaSupplyCenter", home)
    for _ in range(2 if sc else 0):
        try: await c.train(sc, "Tank_ChinaVehicleSupplyTruck")
        except ApiError as e: log("truck", e)
    bar = await build(c, dozer, "Tank_ChinaBarracks", home)
    wf = await build(c, dozer, "Tank_ChinaWarFactory", home)
    if wf is None: return
    await c.set_rally_point(wf, home)
    while True:
        for _ in range(3):
            try: await c.train(wf, "Tank_ChinaTankBattleMaster")
            except ApiError as e: log("train", e.code); break
        await asyncio.sleep(25)
        snap = await c.state()
        tanks = [u["id"] for u in mine(snap, "TankBattleMaster") if u.get("contained_by") is None]
        log("tanks", len(tanks), "money", snap.get("money"))
        if len(tanks) >= 8 and enemy:
            try:
                ks=[k for k in snap.get("known_structures",[]) if k.get("relation","enemy")!="self" and not k.get("neutral")]
                near=[k for k in ks if k.get("visible")]
                if near: await c.attack(tanks, near[0]["id"])
                else: await c.attack_move(tanks, enemy)
            except ApiError as e: log("atk", e)

asyncio.run(main())
