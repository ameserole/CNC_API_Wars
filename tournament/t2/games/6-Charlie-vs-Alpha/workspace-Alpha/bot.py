"""Alpha macro bot (China). Usage: python bot.py ws://127.0.0.1:PORT
Stateless tick loop: every tick re-reads the snapshot and decides. Safe to restart anytime.
Tunable live via settings.json (reloaded each tick). Logs to bot.log in this folder.
"""
from __future__ import annotations

import asyncio
import math
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import ApiError, GeneralsClient, World  # noqa: E402
from generals_api.client import ConnectionClosed  # noqa: E402
from generals_api.botkit import LiveSettings, exit_when_superseded  # noqa: E402

DEFAULTS = {
    "tick": 2.0,
    "attack_size": 8,          # tanks needed before an attack wave
    "retreat": False,          # true: pull army home
    "hold": False,             # true: don't attack, guard home
    "max_dozers": 2,
    "trucks_per_center": 3,
    "redguards": 6,            # early infantry cap
    "tank_hunters": 4,
    "gattling_every": 3,       # every Nth tank is a Gattling tank
    "extra_factory_money": 2000,
    "infernos": 0,             # Inferno Cannons to keep (artillery vs bunkers/cannons/infantry)
    "target": None,            # [x,y] override attack target
    "upgrades": ["Upgrade_Nationalism", "Upgrade_ChinaChainGuns", "Upgrade_ChinaUraniumShells"],
}

LOG = HERE / "bot.log"


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


class Bot:
    def __init__(self, client: GeneralsClient, world: World, settings: LiveSettings):
        self.c, self.w, self.s = client, world, settings
        self.pending: dict[str, float] = {}   # key -> time of last order (avoid duplicates)
        self.names: list[str] = []
        self.home = None
        self.enemy_start = None
        self.attacking = False

    def T(self, suffix: str) -> str:
        return next((n for n in self.names if n.endswith(suffix)), suffix)

    def mine(self, suffix: str, done_only=False):
        out = [u for u in self.w.units.values() if u["template"].endswith(suffix)]
        if done_only:
            out = [u for u in out if not "under_construction" in u.get("status", ())]
        return out

    def recent(self, key: str, secs: float) -> bool:
        return time.time() - self.pending.get(key, 0) < secs

    async def setup(self):
        await self.w.load(self.c)
        cat = self.w.catalog
        self.names = [t["name"] for t in cat["structures"] + cat["units"]]
        info = self.w.game_info
        for _ in range(20):
            hq = self.mine("CommandCenter")
            if hq:
                break
            await asyncio.sleep(0.5)
            self.w.apply_snapshot(await self.c.state())
        self.home = hq[0]["pos"][:2]
        self.enemy_start = max(info["start_positions"], key=lambda p: math.dist(p, self.home))
        log(f"setup side={cat.get('faction')} home={self.home} enemy={self.enemy_start}")

    async def place(self, dozer: int, suffix: str, near, radii=(300, 400, 500, 600, 700)) -> bool:
        tpl = self.T(suffix)
        # face spots away from the enemy first is not needed; just ring around `near`
        for r in radii:
            for step in range(12):
                a = step * math.pi / 6
                pos = (near[0] + r * math.cos(a), near[1] + r * math.sin(a))
                try:
                    await self.c.build(dozer, tpl, pos)
                    log(f"build {tpl} at {pos[0]:.0f},{pos[1]:.0f}")
                    self.pending[suffix] = time.time()
                    self.pending[f"dozer{dozer}"] = time.time()
                    return True
                except ApiError as e:
                    if e.code == "ILLEGAL_LOCATION":
                        continue
                    log(f"build {tpl} refused {e.code}: {e}")
                    self.pending[suffix] = time.time() - 15  # retry in ~5s
                    return False
        return False

    def docks(self):
        objs = list(self.w.visible.values()) + list(self.w.known_structures.values())
        out = {o["id"]: o for o in objs if o.get("supply", 0) > 0 or "SupplyDock" in o["template"] or "SupplyPile" in o["template"]}
        return [o for o in out.values() if o.get("supply", 1) > 0]

    def supply_spot(self):
        docks = self.docks()
        docks = [d for d in docks if "SupplyDock" in d["template"]] or docks
        centers = self.mine("SupplyCenter")
        docks = [d for d in docks if all(math.dist(d["pos"][:2], c["pos"][:2]) > 500 for c in centers)]
        if not docks and centers:
            return None  # every known dock already has a center
        if not docks:
            return self.home
        d = min(docks, key=lambda o: math.dist(o["pos"][:2], self.home))
        # put the center between dock and home, nearer the dock
        dx, dy = self.home[0] - d["pos"][0], self.home[1] - d["pos"][1]
        L = math.hypot(dx, dy) or 1
        return (d["pos"][0] + dx / L * 180, d["pos"][1] + dy / L * 180)

    async def economy(self):
        money = self.w.money or 0
        power = self.w.power or {}
        surplus = power.get("produced", 0) - power.get("consumed", 0)
        dozers = self.mine("VehicleDozer")
        hq = self.mine("CommandCenter", True)
        if hq and len(dozers) < self.s["max_dozers"] and not self.recent("trainDozer", 15) and money >= 1000:
            await self.try_train(hq[0]["id"], "VehicleDozer", "trainDozer")

        def have(sfx):
            return len(self.mine(sfx))

        want = []
        if have("PowerPlant") < 1:
            want.append(("PowerPlant", self.home))
        if have("Barracks") < 1:
            want.append(("Barracks", self.home))
        if have("SupplyCenter") < 1:
            want.append(("SupplyCenter", self.supply_spot()))
        if have("WarFactory") < 1 and have("SupplyCenter", ) >= 1:
            want.append(("WarFactory", self.home))
        if have("SupplyCenter") == 1 and have("WarFactory") >= 1 and money > 1600:
            want.append(("SupplyCenter", self.supply_spot()))
        if have("PowerPlant") >= 1 and surplus < 3 and have("PowerPlant") < 6:
            want.append(("PowerPlant", self.home))
        if have("WarFactory") >= 1 and have("PropagandaCenter") < 1 and money > 2200:
            want.append(("PropagandaCenter", self.home))
        if have("WarFactory") == 1 and money > self.s["extra_factory_money"] and (have("PropagandaCenter") or money > 3500):
            want.append(("WarFactory", self.home))
        if have("PropagandaCenter") >= 1 and have("GattlingCannon") < 2 and money > 2500:
            want.append(("GattlingCannon", self.home))

        idle_dozers = [d for d in dozers if not self.recent(f"dozer{d['id']}", 8)
                       and (d.get("status", ()).__contains__("idle") or not self.recent(f"dozer{d['id']}", 40))]
        for sfx, near in want:
            if near is None:
                continue
            if not idle_dozers:
                break
            if self.recent(sfx, 20):
                continue
            d = idle_dozers.pop(0)
            radii = (60, 120, 180, 250, 350) if sfx == "SupplyCenter" else (300, 400, 500, 600, 700)
            await self.place(d["id"], sfx, near, radii)

        # unfinished buildings with no dozer: resume
        for b in self.w.units.values():
            if b.get("status", ()).__contains__("under_construction") and idle_dozers and not self.recent(f"resume{b['id']}", 30):
                d = idle_dozers.pop(0)
                try:
                    await self.c.resume_construction(d["id"], b["id"])
                    self.pending[f"resume{b['id']}"] = time.time()
                    self.pending[f"dozer{d['id']}"] = time.time()
                except ApiError:
                    self.pending[f"resume{b['id']}"] = time.time()

        # supply trucks
        centers = self.mine("SupplyCenter", True)
        trucks = self.mine("SupplyTruck")
        if centers and len(trucks) < self.s["trucks_per_center"] * len(centers) and not self.recent("trainTruck", 20):
            await self.try_train(centers[0]["id"], "VehicleSupplyTruck", "trainTruck")
        # idle trucks: dock at nearest supply
        docks = self.docks()
        for t in trucks:
            if t.get("status", ()).__contains__("idle") and docks and not self.recent(f"dock{t['id']}", 20):
                d = min(docks, key=lambda o: math.dist(o["pos"][:2], t["pos"][:2]))
                try:
                    await self.c.dock([t["id"]], d["id"])
                except ApiError:
                    pass
                self.pending[f"dock{t['id']}"] = time.time()

    async def try_train(self, factory: int, sfx: str, key: str, count=1) -> bool:
        try:
            await self.c.train(factory, self.T(sfx), count=count)
            self.pending[key] = time.time()
            return True
        except ApiError as e:
            self.pending[key] = time.time() - 10
            if e.code not in ("INSUFFICIENT_FUNDS",):
                log(f"train {sfx} refused {e.code}: {e}")
            return False

    async def production(self):
        money = self.w.money or 0
        for b in self.mine("Barracks", True):
            if self.recent(f"fac{b['id']}", 10):
                continue
            if len(self.mine("Redguard")) < self.s["redguards"] and money >= 300:
                await self.try_train(b["id"], "InfantryRedguard", f"fac{b['id']}")
            elif len(self.mine("TankHunter")) < self.s["tank_hunters"] and money >= 600 and self.mine("WarFactory", True):
                await self.try_train(b["id"], "InfantryTankHunter", f"fac{b['id']}")
        tanks = self.mine("TankBattleMaster") + self.mine("TankGattling")
        if len(self.mine("SupplyCenter")) < 2 and len(tanks) >= 2 and money < 1700 and self.supply_spot() is not None:
            return  # save for the 2nd supply center (economy first)
        reserve = 0
        if len(tanks) >= self.s.get("reserve_after", 4) and (len(self.mine("WarFactory")) < 2 or not self.mine("PropagandaCenter")):
            reserve = self.s.get("reserve", 2000)
        for f in self.mine("WarFactory", True):
            if self.recent(f"fac{f['id']}", 6) or money < 800 + reserve:
                continue
            n = len(tanks)
            sfx = "TankGattling" if n % self.s["gattling_every"] == self.s["gattling_every"] - 1 else "TankBattleMaster"
            if self.mine("PropagandaCenter", True) and n >= 6 and n % 5 == 4 and money >= 2000:
                sfx = "TankOverlord"
            nin = len(self.mine("InfernoCannon"))
            if self.mine("PropagandaCenter", True) and nin < self.s.get("infernos", 0) and nin * 2 <= n + 1 and money >= 900:
                sfx = "VehicleInfernoCannon"
            await self.try_train(f["id"], sfx, f"fac{f['id']}")
            money -= 800
        # upgrades (cheap tries; refusals ignored)
        if money > 2500 and not self.recent("upg", 20):
            self.pending["upg"] = time.time()
            for u in self.s["upgrades"]:
                for host in ("PropagandaCenter", "WarFactory", "Barracks"):
                    for b in self.mine(host, True):
                        try:
                            await self.c.upgrade(b["id"], u)
                            log(f"upgrade {u}")
                            return
                        except ApiError:
                            pass

    def army(self):
        keep = ("TankBattleMaster", "TankGattling", "TankOverlord", "Redguard", "TankHunter", "InfernoCannon")
        return [u for u in self.w.units.values() if u["template"].endswith(keep) and u.get("contained_by") is None]

    async def military(self):
        army = self.army()
        if not army:
            return
        ids = [u["id"] for u in army]
        tanks = [u for u in army if "Tank" in u["template"] and "Hunter" not in u["template"]]
        if self.s["retreat"] or self.s["hold"]:
            if not self.recent("guard", 15):
                self.pending["guard"] = time.time()
                await self.safe(self.c.attack_move(ids, self.home))
            self.attacking = False
            return
        # defend: enemies near home
        threats = [e for e in self.w.enemies() if math.dist(e["pos"][:2], self.home) < 900]
        if threats and not self.recent("defend", 6):
            self.pending["defend"] = time.time()
            known = {o["id"] for o in self.w.known_structures.values()}
            units_ = [e for e in threats if e["id"] not in known]
            t = (units_ or threats)[0]
            if t["id"] in known:
                await self.safe(self.c.attack(ids, t["id"]))
            else:
                await self.safe(self.c.attack_move(ids, t["pos"][:2]))
            log(f"defend vs {t['template']} army={len(ids)}")
            return
        if not self.attacking and len(tanks) >= self.s["attack_size"]:
            self.attacking = True
            log(f"ATTACK wave tanks={len(tanks)} army={len(ids)}")
        if self.attacking and len(tanks) < max(2, self.s["attack_size"] // 3):
            self.attacking = False
            log("wave spent; regroup")
            await self.safe(self.c.attack_move(ids, self.home))
            return
        if self.attacking and not self.recent("push", 8):
            self.pending["push"] = time.time()
            center = (sum(u["pos"][0] for u in army) / len(army), sum(u["pos"][1] for u in army) / len(army))
            visible_enemy_units = [e for e in self.w.enemies() if math.dist(e["pos"][:2], center) < 600
                                   and e["id"] not in self.w.known_structures
                                   and not e["template"].endswith(("Worker", "Dozer", "SupplyTruck", "Chinook"))]
            structs = self.w.enemy_structures()
            if visible_enemy_units:
                await self.safe(self.c.attack_move(ids, visible_enemy_units[0]["pos"][:2]))
            elif structs:
                s = min(structs, key=lambda o: math.dist(o["pos"][:2], center))
                cur = self.w.known_structures.get(getattr(self, "focus", None))
                if cur and math.dist(cur["pos"][:2], center) < 900:
                    s = cur  # sticky: keep hitting the same building
                if math.dist(s["pos"][:2], center) < 700:
                    if getattr(self, "focus", None) != s["id"] or not self.recent("refocus", 30):
                        self.focus = s["id"]
                        self.pending["refocus"] = time.time()
                        await self.safe(self.c.attack(ids, s["id"]))
                else:
                    await self.safe(self.c.attack_move(ids, s["pos"][:2]))
            else:
                tgt = self.s["target"] or self.enemy_start
                await self.safe(self.c.attack_move(ids, tgt))
        elif not self.attacking and not self.recent("rally", 20):
            self.pending["rally"] = time.time()
            # gather in front of base toward the enemy
            dx, dy = self.enemy_start[0] - self.home[0], self.enemy_start[1] - self.home[1]
            L = math.hypot(dx, dy) or 1
            spot = (self.home[0] + dx / L * 400, self.home[1] + dy / L * 400)
            idle = [u["id"] for u in army if u.get("status", ()).__contains__("idle")]
            if idle:
                await self.safe(self.c.attack_move(idle, spot))

    async def safe(self, coro):
        try:
            return await coro
        except ApiError as e:
            log(f"order refused {e.code}: {e}")

    async def run(self):
        await self.setup()
        while self.w.result is None:
            self.s.reload()
            try:
                self.w.apply_snapshot(await self.c.state())
                await self.economy()
                await self.production()
                await self.military()
            except ApiError as e:
                log(f"tick error {e.code}: {e}")
            except ConnectionClosed as e:
                log(f"connection closed ({e}); exiting")
                return
            except Exception:  # noqa: BLE001
                log("tick crash " + traceback.format_exc(limit=3))
            await asyncio.sleep(self.s["tick"])
        log(f"game over: {self.w.result}")


async def main(url: str):
    client = await GeneralsClient(url, request_timeout=60).connect()
    await client.hello()
    exit_when_superseded(client)
    world = World().attach(client)
    settings = LiveSettings(HERE / "settings.json", DEFAULTS)
    await Bot(client, world, settings).run()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
