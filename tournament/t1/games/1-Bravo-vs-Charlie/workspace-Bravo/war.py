"""Phase 2: assumes base built. train tanks, attack-move; explicit attack on enemy structures."""
import asyncio, sys, time, math
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, ApiError
LOG=open("war.log","a",buffering=1)
def log(*a): print(time.strftime("%H:%M:%S"),*a,file=LOG)
async def main():
    c=await GeneralsClient(sys.argv[1],request_timeout=60).connect(); await c.hello()
    gi=await c.game_info()
    snap=await c.state()
    hq=next(u for u in snap["units"] if u["template"].endswith("CommandCenter"))
    enemy=max(gi["start_positions"],key=lambda p:math.dist(p,hq["pos"][:2]))
    wf=[u["id"] for u in snap["units"] if u["template"].endswith("WarFactory")][0]
    while True:
        for _ in range(3):
            try: await c.train(wf,"Tank_ChinaTankBattleMaster")
            except ApiError as e: break
        snap=await c.state()
        tanks=[u["id"] for u in snap["units"] if u["template"].endswith("TankBattleMaster") and u.get("contained_by") is None]
        sc=[u["id"] for u in snap["units"] if u["template"].endswith("SupplyCenter")]
        trucks=[u for u in snap["units"] if u["template"].endswith("SupplyTruck")]
        log("trucks",len(trucks),"money",snap.get("money"),"types",sorted({u["template"] for u in snap["units"]}))
        if sc and len(trucks)<4:
            try: await c.train(sc[0],"Tank_ChinaVehicleSupplyTruck")
            except ApiError as e: log("truck",e.code)
        ks=snap.get("known_structures",[])
        if ks: log("ks sample",ks[0])
        log("tanks",len(tanks))
        if len(tanks)>=5:
            try: await c.attack_move(tanks,enemy)
            except ApiError as e: log("am",e)
            for k in ks:
                if k.get("owner") in (0,snap.get("player_id"),snap.get("me")) or not k.get("visible"): continue
                try: await c.attack(tanks,k["id"]); log("atk",k["id"]); break
                except ApiError as e: pass
        await asyncio.sleep(20)
asyncio.run(main())
