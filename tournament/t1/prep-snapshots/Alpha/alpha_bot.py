"""Alpha macro bot: China Tank General (works for any China faction). Battlemaster/Gattling tank waves.

Usage (from anywhere):
  C:\\Users\\user\\Documents\\CNC_Generals_AI\\python\\.venv\\Scripts\\python.exe alpha_bot.py PORT [logfile]
Polling design: every ~2 s fetch state(), then decide. Restart-safe (no memory needed beyond the game state).
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
import time

sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import ApiError, GeneralsClient  # noqa: E402

PORT = int(sys.argv[1])
LOGFILE = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\user\Documents\CNC_Generals_AI\tournament\t1\agents\Alpha\bot.log"
FIRST_WAVE = 6
WAVE = 5
SCIENCES = ["SCIENCE_BattlemasterTraining", "Early_SCIENCE_EmergencyRepair1", "SCIENCE_RedGuardTraining",
            "SCIENCE_TankParadrop1", "SCIENCE_TankParadrop2", "SCIENCE_TankParadrop3",
            "SCIENCE_ArtilleryBarrage1", "SCIENCE_ArtilleryBarrage2", "SCIENCE_ArtilleryBarrage3",
            "Early_SCIENCE_EmergencyRepair2", "SCIENCE_EMPPulse", "SCIENCE_ChinaCarpetBomb"]


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOGFILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def flag(u, name):
    if u.get(name):
        return True
    st = u.get("status") or u.get("flags") or []
    return name in st if isinstance(st, (list, tuple, set)) else False


class Bot:
    def __init__(self, client):
        self.c = client
        self.busy_until: dict[int, float] = {}   # dozer id -> time we can order it again
        self.next_train: dict[int, float] = {}   # factory id -> time
        self.attacking: set[int] = set()
        self.wave_size = FIRST_WAVE
        self.science_tried = 0.0
        self.last_report = 0.0
        self.tn = 0

    def t(self, suffix):
        return next((n for n in self.names if n.endswith(suffix)), suffix)

    async def setup(self):
        await self.c.hello()
        self.info = await self.c.game_info()
        self.cat = await self.c.catalog()
        self.names = [x["name"] for x in self.cat["structures"] + self.cat["units"]]
        self.cost = {x["name"]: x.get("cost", 0) for x in self.cat["structures"] + self.cat["units"]}
        self.btime = {x["name"]: x.get("build_time", 20) for x in self.cat["structures"] + self.cat["units"]}
        snap = await self.c.state()
        hq = next(u for u in snap["units"] if u["template"].endswith("CommandCenter"))
        self.home = hq["pos"][:2]
        self.enemy_start = max(self.info["start_positions"], key=lambda p: math.dist(p, self.home))[:2]
        log("setup home", self.home, "enemy", self.enemy_start, "side", self.cat.get("faction"))
        log("sample unit", json.dumps(snap["units"][0])[:400])
        log("self", json.dumps(snap.get("self"))[:400])

    def mine(self, snap, suffix, done=True):
        out = [u for u in snap["units"] if u["template"].endswith(suffix)]
        if done:
            out = [u for u in out if not flag(u, "under_construction")]
        return out

    async def place(self, dozer, template, near, radii=(220, 320, 420, 520, 650)):
        for r in radii:
            for k in range(12):
                a = k * math.pi / 6 + r * 0.01
                pos = (near[0] + r * math.cos(a), near[1] + r * math.sin(a))
                try:
                    await self.c.build(dozer, template, pos)
                    self.busy_until[dozer] = time.monotonic() + 6
                    log("build", template, "at", [round(p) for p in pos])
                    return True
                except ApiError as e:
                    if e.code == "ILLEGAL_LOCATION":
                        continue
                    log("build fail", template, e.code, e.message if hasattr(e, "message") else e)
                    return False
        return False

    def supply_spot(self, snap, second=False):
        docks = [o for o in snap.get("visible", []) if "Supply" in o["template"] and o.get("supply", 1) > 0
                 and "Center" not in o["template"] and o.get("owner") not in self.enemy_idx()]
        centers = self.mine(snap, "SupplyCenter", done=False)
        if second:  # a dock not already served by one of our centers
            docks = [o for o in docks if all(math.dist(o["pos"][:2], c["pos"][:2]) > 500 for c in centers)]
            docks = [o for o in docks if math.dist(o["pos"][:2], self.home) < 1400]
        if not docks:
            return self.home
        d = min(docks, key=lambda o: math.dist(o["pos"][:2], self.home))
        p = d["pos"][:2]
        # 45% of the way from dock to home, so the center sits next to the dock
        return (p[0] + (self.home[0] - p[0]) * 0.35, p[1] + (self.home[1] - p[1]) * 0.35)

    async def step(self):
        c = self.c
        snap = await c.state()
        now = time.monotonic()
        money = snap.get("self", {}).get("money", 0)
        power = snap.get("self", {}).get("power") or {}
        spare = power.get("produced", 0) - power.get("consumed", 0)

        dozers = self.mine(snap, "VehicleDozer")
        free = [d for d in dozers if flag(d, "idle") and self.busy_until.get(d["id"], 0) < now]
        allst = lambda s: self.mine(snap, s, done=False)
        n = {s: len(allst(s)) for s in ("PowerPlant", "SupplyCenter", "Barracks", "WarFactory",
                                         "PropagandaCenter", "GattlingCannon")}
        cc = self.mine(snap, "CommandCenter")

        # --- dozers: build order ---
        done = {u["template"] for u in snap["units"] if not flag(u, "under_construction")}
        wants = []
        if n["PowerPlant"] == 0:
            wants.append(("PowerPlant", self.home))
        if n["SupplyCenter"] == 0:
            wants.append(("SupplyCenter", self.supply_spot(snap)))
        if n["Barracks"] == 0:
            wants.append(("Barracks", self.home))
        if n["WarFactory"] == 0:
            wants.append(("WarFactory", self.home))
        if spare < 3 and n["PowerPlant"] < 6 and n["PowerPlant"] == len(self.mine(snap, "PowerPlant")):
            wants.append(("PowerPlant", self.home))
        if n["SupplyCenter"] < 2 and n["WarFactory"] >= 1 and self.supply_spot(snap, second=True) != self.home:
            wants.append(("SupplyCenter", self.supply_spot(snap, second=True)))
        if n["WarFactory"] < 2 and n["SupplyCenter"] >= 2 or n["WarFactory"] < 2 and money > 2200:
            wants.append(("WarFactory", self.home))
        if n["PropagandaCenter"] == 0 and money > 2500 and n["WarFactory"] >= 2:
            wants.append(("PropagandaCenter", self.home))
        if n["GattlingCannon"] < 2 and money > 3000 and n["WarFactory"] >= 2:
            wants.append(("GattlingCannon", (self.home[0] + (self.enemy_start[0] - self.home[0]) * 0.08,
                                             self.home[1] + (self.enemy_start[1] - self.home[1]) * 0.08)))
        if n["WarFactory"] < 3 and money > 4500:
            wants.append(("WarFactory", self.home))
        taken = set()
        reserve = 0
        for want in wants:
            if not free:
                break
            tmpl = self.t("China" + want[0])
            if want[0] in taken:
                continue
            prereqs = next((s.get("prerequisites") or [] for s in self.cat["structures"] if s["name"] == tmpl), [])
            if not all(any(p in done for p in alt) for alt in prereqs):
                continue
            if money < self.cost.get(tmpl, 0):
                if want[0] in ("SupplyCenter", "WarFactory", "PowerPlant"):
                    reserve = self.cost.get(tmpl, 0)
                    break
                continue
            if True:
                d = free.pop(0)
                if await self.place(d["id"], tmpl, want[1]):
                    money -= self.cost.get(tmpl, 0)
                    taken.add(want[0])
        # unfinished buildings without a dozer: resume
        for b in [u for u in snap["units"] if flag(u, "under_construction")]:
            if free and b.get("health", 1) > 0:
                try:
                    await c.resume_construction(free[0]["id"], b["id"])
                    self.busy_until[free[0]["id"]] = now + 6
                    free.pop(0)
                except ApiError:
                    pass
        # repair damaged buildings
        for b in snap["units"]:
            if free and "max_health" in b and b.get("health", 0) < 0.6 * b["max_health"] and \
                    not flag(b, "under_construction") and b["template"] in self.cost and \
                    any(b["template"] == s["name"] for s in self.cat["structures"]):
                try:
                    await c.repair(free[0]["id"], b["id"])
                    self.busy_until[free[0]["id"]] = now + 10
                    free.pop(0)
                except ApiError:
                    pass

        # --- production ---
        async def train(fac, tmpl):
            if self.next_train.get(fac["id"], 0) > now:
                return
            if money - reserve < self.cost.get(tmpl, 0) and not tmpl.endswith(("Dozer", "SupplyTruck")):
                return
            try:
                await c.train(fac["id"], tmpl, 1)
                self.next_train[fac["id"]] = now + self.btime.get(tmpl, 20) * 0.95
            except ApiError as e:
                self.next_train[fac["id"]] = now + 3
                if e.code not in ("INSUFFICIENT_FUNDS",):
                    log("train", tmpl, e.code)

        for h in cc:
            if len(dozers) < (2 if n["WarFactory"] == 0 else 2 + (1 if money > 6000 else 0)):
                await train(h, self.t("ChinaVehicleDozer"))
        trucks = self.mine(snap, "SupplyTruck")
        for s in self.mine(snap, "SupplyCenter"):
            if len(trucks) < 3 * n["SupplyCenter"]:
                await train(s, self.t("ChinaVehicleSupplyTruck"))
        tanks_all = [u for u in snap["units"] if any(u["template"].endswith(x) for x in
                     ("TankBattleMaster", "TankGattling", "TankEmperor", "TankDragon", "InfantryTankHunter",
                      "InfantryRedguard"))]
        has_prop = len(self.mine(snap, "PropagandaCenter")) > 0
        for i, wf in enumerate(self.mine(snap, "WarFactory")):
            self.tn += 0
            gat = sum(u["template"].endswith("TankGattling") for u in tanks_all)
            bm = sum(u["template"].endswith("TankBattleMaster") for u in tanks_all)
            if gat * 3 < bm:
                tmpl = "ChinaTankGattling"
            elif has_prop and money > 3000 and i == 0:
                tmpl = "ChinaTankEmperor"
            else:
                tmpl = "ChinaTankBattleMaster"
            await train(wf, self.t(tmpl))
        bar = self.mine(snap, "Barracks")
        if bar and len(self.mine(snap, "InfantryTankHunter")) < 3 and n["WarFactory"] == 0:
            await train(bar[0], self.t("ChinaInfantryTankHunter"))
        if bar and money > 5000 and len([u for u in tanks_all if "Infantry" in u["template"]]) < 8:
            await train(bar[0], self.t("ChinaInfantryTankHunter"))

        # --- upgrades ---
        for p in self.mine(snap, "PropagandaCenter"):
            for up in ("Upgrade_Nationalism", "Upgrade_ChinaUraniumShells", "Tank_Upgrade_ChinaTankAutoLoader",
                       "Upgrade_ChinaNuclearTanks"):
                if money > 4000:
                    try:
                        await c.upgrade(p["id"], up)
                        money -= 2500
                        log("upgrade", up)
                        break
                    except ApiError:
                        pass

        # --- sciences ---
        if now - self.science_tried > 15 and snap.get("self", {}).get("science_points", 1):
            self.science_tried = now
            for s in SCIENCES:
                try:
                    await c.purchase_science(s)
                    log("science", s)
                except ApiError:
                    pass

        # --- army ---
        army = [u for u in tanks_all if u.get("contained_by") is None and not flag(u, "under_construction")]
        ids = {u["id"] for u in army}
        self.attacking &= ids
        home_army = [u for u in army if u["id"] not in self.attacking]
        enemies_near = [o for o in snap.get("visible", []) if self.is_enemy(o)
                        and math.dist(o["pos"][:2], self.home) < 900]
        if len(enemies_near) >= 4 and len(home_army) < len(enemies_near):
            # base under real attack: recall the field army
            log("RECALL vs", len(enemies_near), "enemies near base")
            self.attacking.clear()
            home_army = army
        if enemies_near and home_army:
            tgt = min(enemies_near, key=lambda o: math.dist(o["pos"][:2], self.home))
            await self.order(c.attack_move, [u["id"] for u in home_army], tgt["pos"][:2])
        elif len(home_army) >= self.wave_size:
            self.attacking |= {u["id"] for u in home_army}
            self.wave_size = WAVE
            log("WAVE of", len(home_army))
        if self.attacking:
            att = [u for u in army if u["id"] in self.attacking]
            idle = [u["id"] for u in att if flag(u, "idle")]
            if idle:
                structs = [o for o in snap.get("known_structures", []) if self.is_enemy(o)]
                if structs:
                    cen = self.centroid(att)
                    tgt = min(structs, key=lambda o: math.dist(o["pos"][:2], cen))
                    if tgt.get("visible") and math.dist(tgt["pos"][:2], cen) < 600:
                        await self.order(c.attack, idle, tgt["id"])
                    else:
                        await self.order(c.attack_move, idle, tgt["pos"][:2])
                else:
                    vis = [o for o in snap.get("visible", []) if self.is_enemy(o)]
                    if vis:
                        await self.order(c.attack_move, idle, vis[0]["pos"][:2])
                    else:
                        await self.order(c.attack_move, idle, self.scout_target())

        trucks = self.mine(snap, "SupplyTruck")
        for tr in trucks:
            if flag(tr, "idle"):
                docks = [o for o in snap.get("visible", []) if "Supply" in o["template"] and o.get("supply", 0) > 0
                         and "Center" not in o["template"] and o.get("owner") not in self.enemy_idx()]
                if docks:
                    d = min(docks, key=lambda o: math.dist(o["pos"][:2], tr["pos"][:2]))
                    try:
                        await c.dock([tr["id"]], d["id"])
                        log("redock truck", tr["id"])
                    except ApiError as e:
                        log("dock", e.code)
        if now - self.last_report > 20:
            self.last_report = now
            log(f"frame {snap.get('frame')} money {money} power {spare} dozers {len(dozers)} "
                f"trucks {len(trucks)} harvesting {sum(flag(u, 'harvesting') for u in trucks)} bld {n} army {len(army)} attacking {len(self.attacking)} "
                f"enemy_structs {len([o for o in snap.get('known_structures', []) if self.is_enemy(o)])}")

    def scout_target(self):
        others = [p[:2] for p in self.info["start_positions"] if math.dist(p[:2], self.home) > 500]
        self.tn += 1
        return others[self.tn % len(others)] if others else self.enemy_start

    def enemy_idx(self):
        return {p["index"] for p in self.info["players"] if p["relation"] == "enemy"}

    def is_enemy(self, o):
        return o.get("owner") in self.enemy_idx()

    @staticmethod
    def centroid(units):
        return (sum(u["pos"][0] for u in units) / len(units), sum(u["pos"][1] for u in units) / len(units))

    async def order(self, fn, units, arg):
        try:
            await fn(units, arg)
        except ApiError as e:
            log("order", fn.__name__, e.code)


async def main():
    client = await GeneralsClient(f"ws://127.0.0.1:{PORT}", request_timeout=60).connect()
    bot = Bot(client)
    over = asyncio.Event()
    client.on("game_over", lambda e: (log("GAME OVER", e.get("result")), over.set()))
    await bot.setup()
    while not over.is_set():
        try:
            await bot.step()
        except ApiError as e:
            log("step error", e.code, e)
        except Exception as e:  # keep running
            log("step exception", repr(e))
            if "ConnectionClosed" in type(e).__name__:
                break
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
