"""Bravo macro bot (China). Usage: python bot.py ws://127.0.0.1:N   (settings.json reloaded live)."""
import asyncio, math, sys, time
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from pathlib import Path
from generals_api import ApiError, GeneralsClient, World
from generals_api.botkit import LiveSettings, exit_when_superseded

HERE = Path(__file__).parent
S = LiveSettings(HERE / "settings.json", {"attack_size": 14, "trucks": 3, "tank": "TankBattleMaster", "inf": "InfantryRedguard"})
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

async def main(url):
    client = await GeneralsClient(url, request_timeout=60).connect()
    await client.hello(); exit_when_superseded(client)
    w = World().attach(client); await w.load(client)
    info = w.game_info
    names = [t["name"] for t in w.catalog["structures"] + w.catalog["units"]]
    def T(n): return next((x for x in names if x.endswith(n)), n)
    def have(n): return [u for u in w.units.values() if u["template"].endswith(n)]
    for _ in range(40):
        w.apply_snapshot(await client.state())
        if have("CommandCenter") and have("VehicleDozer"): break
        await asyncio.sleep(0.5)
    home = have("CommandCenter")[0]["pos"]
    enemy_start = max(info["start_positions"], key=lambda p: math.dist(p, home[:2]))
    log("home", home, "enemy start", enemy_start)

    async def place(builder, tmpl, near):
        for r in (200, 300, 400, 500):
            for i in range(12):
                a = i * math.pi / 6
                pos = (near[0] + r * math.cos(a), near[1] + r * math.sin(a))
                fut = asyncio.ensure_future(client.wait_for_event("construction_started", lambda e: e["template"].endswith(tmpl), timeout=20))
                try:
                    await client.build(builder, tmpl, pos); return (await fut)["id"]
                except ApiError as e:
                    if e.code == "INSUFFICIENT_FUNDS": return "poor"
                    if e.code != "ILLEGAL_LOCATION": log("build err", tmpl, e.code, e); return None
                except asyncio.TimeoutError: return None
                finally: fut.cancel()
        return None

    async def builder_loop():
        order = ["ChinaPowerPlant", "ChinaSupplyCenter", "ChinaBarracks", "ChinaWarFactory", "ChinaPowerPlant", "ChinaBarracks", "ChinaWarFactory"]
        seen = {}
        for want in order:
            seen[want] = seen.get(want, 0) + 1
            tmpl = T(want)
            while len(have(want)) < seen[want]:
                dz = have("VehicleDozer")
                if not dz: await asyncio.sleep(2); continue
                r = await place(dz[0]["id"], tmpl, home)
                if r == "poor" or r is None: await asyncio.sleep(3); continue
                log("building", tmpl)
                try: await client.wait_for_event("construction_complete", lambda e: e["id"] == r, timeout=150)
                except asyncio.TimeoutError: pass
                w.apply_snapshot(await client.state())

    asyncio.ensure_future(builder_loop())
    last_attack = 0
    while True:
        S.reload()
        try:
            snap = await client.state(); w.apply_snapshot(snap)
            await w.refresh_templates(client)
            rally = home
            for b in have("Barracks") + have("WarFactory"):
                if not b.get("under_construction"):
                    try: await client.set_rally_point(b["id"], (home[0] + 150, home[1] + 150))
                    except ApiError: pass
            # trucks
            sc = [b for b in have("SupplyCenter") if not b.get("under_construction")]
            trucks = have("VehicleSupplyTruck")
            if sc and len(trucks) < S.get("trucks") and time.time() - globals().get("_lt", 0) > 25:
                globals()["_lt"] = time.time()
                try: await client.train(sc[0]["id"], T("VehicleSupplyTruck"))
                except ApiError: pass
            idle = [t["id"] for t in trucks if t.get("idle")]
            if idle:
                docks = [o for o in w.visible.values() if o.get("supply")]
                if docks:
                    d = min(docks, key=lambda o: math.dist(o["pos"][:2], home[:2]))
                    try: await client.dock(idle, d["id"])
                    except ApiError as e: log("dock", e.code)
            # production
            for b in have("WarFactory"):
                if not b.get("under_construction"):
                    try: await client.train(b["id"], T(S.get("tank")))
                    except ApiError: pass
            wf_ok = any(not b.get("under_construction") for b in have("WarFactory"))
            for b in have("Barracks"):
                if not b.get("under_construction") and (not wf_ok or (w.money or 0) > 1200):
                    try: await client.train(b["id"], T(S.get("inf")))
                    except ApiError: pass
            # attack
            army = [u for u in snap["units"] if (u["template"].endswith(S.get("tank")) or u["template"].endswith(S.get("inf"))) and u.get("contained_by") is None]
            if len(army) >= S.get("attack_size") and time.time() - last_attack > 20:
                last_attack = time.time()
                es = w.enemy_structures()
                ids = [u["id"] for u in army]
                tgt = es[0]["pos"] if es else enemy_start
                if es:
                    tgt = min(es, key=lambda o: math.dist(o["pos"][:2], home[:2]))["pos"]
                await client.attack_move(ids, tgt); log("attack", len(ids), tgt)
            es = w.enemy_structures()
            if es and army and time.time() - last_attack > 8:
                cx = sum(u["pos"][0] for u in army) / len(army); cy = sum(u["pos"][1] for u in army) / len(army)
                near = min(es, key=lambda o: math.dist(o["pos"][:2], (cx, cy)))
                if math.dist(near["pos"][:2], (cx, cy)) < 500 and len(army) >= 6:
                    try: await client.attack([u["id"] for u in army], near["id"])
                    except ApiError as e: log("attack err", e.code)
            if w.result: log("over", w.result); return
        except ApiError as e: log("api", e.code, e)
        await asyncio.sleep(2)

asyncio.run(main(sys.argv[1]))
