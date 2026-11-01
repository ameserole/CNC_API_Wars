"""Charlie's macro bot: China Tank General. Power -> Supply Center -> War Factory -> Battlemaster/Gattling spam.

Usage:  python macro_bot.py ws://127.0.0.1:PORT
Logs to bot_log.txt next to this file. One connection per game: do not run anything else against the port.
"""
from __future__ import annotations

import asyncio
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import ApiError, GeneralsClient, World  # noqa: E402
from generals_api.client import ConnectionClosed  # noqa: E402

HERE = Path(__file__).parent
LOG = HERE / "bot_log.txt"
P = "Tank_"
DOZER, POWER, SUPPLY, WARF, BARRACKS, GATT_CANNON = (P + "ChinaVehicleDozer", P + "ChinaPowerPlant",
                                                    P + "ChinaSupplyCenter", P + "ChinaWarFactory",
                                                    P + "ChinaBarracks", P + "ChinaGattlingCannon")
PROP = P + "ChinaPropagandaCenter"
TRUCK, BM, GATT, TH = (P + "ChinaVehicleSupplyTruck", P + "ChinaTankBattleMaster", P + "ChinaTankGattling",
                       P + "ChinaInfantryTankHunter")
EMPEROR = P + "ChinaTankEmperor"
SCIENCE_PRIORITY = ["SCIENCE_BattlemasterTraining", "Early_SCIENCE_EmergencyRepair1", "SCIENCE_ArtilleryBarrage1",
                    "SCIENCE_TankParadrop1", "SCIENCE_Frenzy1", "SCIENCE_ClusterMines", "SCIENCE_ArtilleryBarrage2",
                    "SCIENCE_TankParadrop2", "SCIENCE_Frenzy2", "SCIENCE_EMPPulse", "SCIENCE_ChinaCarpetBomb",
                    "SCIENCE_ArtilleryBarrage3", "SCIENCE_TankParadrop3", "SCIENCE_Frenzy3"]
ATTACK_SIZE = 12
MAP_CENTER = (1007.0, 1343.0)
SOUTH_HOME = (1010.8, 2102.7)
SOUTH_DOCK2 = (1435.0, 2376.0)
COMBAT_WEIGHT = {'ChinaTankBattleMaster': 1.0, 'ChinaTankGattling': 0.5, 'ChinaTankEmperor': 2.5, 'ChinaInfantryTankHunter': 0.5,
                 'ChinaInfantryRedGuard': 0.2, 'ChinaVehicleInferno': 0.8, 'ChinaVehicleDragonTank': 0.8}


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def dist(a, b):
    return math.dist(a[:2], b[:2])


class Bot:
    def __init__(self, client: GeneralsClient, world: World):
        self.c, self.w = client, world
        self.home = None
        self.enemy_start = None
        self.army_target = None
        self.pending_build: set[str] = set()   # templates currently being placed/built
        self.sciences_bought: set[str] = set()
        self.last_attack = 0.0
        self.power_next: dict[str, float] = {}   # ability -> earliest retry time

    # ---------- helpers ----------
    def mine(self, template=None, kind=None):
        return [u for u in self.w.units.values()
                if (template is None or u["template"] == template)
                and (kind is None or kind in self.w.kinds(u["template"]))]

    def done(self, template):
        return [u for u in self.mine(template) if "under_construction" not in u.get("status", [])]

    def idle_dozers(self):
        return [u for u in self.mine(DOZER) if "idle" in u.get("status", [])]

    def toward(self, origin, target, d):
        dx, dy = target[0] - origin[0], target[1] - origin[1]
        n = math.hypot(dx, dy) or 1.0
        return (origin[0] + dx / n * d, origin[1] + dy / n * d)

    async def place(self, dozer, template, near, radii=(180, 260, 340, 420, 500), away_from=None):
        started = asyncio.ensure_future(self.c.wait_for_event(
            "construction_started", lambda e: e["template"] == template, timeout=20))
        try:
            steps = list(range(12))
            if away_from is not None:
                # try spots facing away from the enemy first
                def score(step):
                    a = step * math.pi / 6
                    p = (near[0] + math.cos(a), near[1] + math.sin(a))
                    return -dist(p, away_from)
                steps.sort(key=score)
            for r in radii:
                for step in steps:
                    a = step * math.pi / 6
                    pos = (near[0] + r * math.cos(a), near[1] + r * math.sin(a))
                    try:
                        await self.c.build(dozer, template, pos)
                        ev = await started
                        log("started", template, "at", [round(x) for x in pos])
                        return ev["id"]
                    except ApiError as e:
                        if e.code != "ILLEGAL_LOCATION":
                            log("build refused", template, e.code, e)
                            return None
            log("no spot for", template)
            return None
        finally:
            started.cancel()

    async def build(self, template, near, away_from=None, radii=(180, 260, 340, 420, 500)):
        if template in self.pending_build:
            return
        dozers = self.idle_dozers()
        if not dozers:
            return
        self.pending_build.add(template)
        try:
            bid = await self.place(dozers[0]["id"], template, near, radii=radii, away_from=away_from)
            if bid is None:
                return
            try:
                await self.c.wait_for_event("construction_complete", lambda e: e["id"] == bid, timeout=240)
                log("complete", template)
            except asyncio.TimeoutError:
                log("timeout waiting for", template)
        finally:
            self.pending_build.discard(template)

    def supply_docks(self):
        return [o for o in self.w.visible.values() if o.get("supply", 0) > 0]

    def dock2_guess(self):
        """Second dock near home, guessed by 180-degree map symmetry from the practice game."""
        if dist(self.home, SOUTH_HOME) < 300:
            return SOUTH_DOCK2
        return (2 * MAP_CENTER[0] - SOUTH_DOCK2[0], 2 * MAP_CENTER[1] - SOUTH_DOCK2[1])

    def docks_low(self):
        """True when the docks my supply centers use are nearly dry."""
        used = [s["pos"] for s in self.mine(SUPPLY)]
        near = [d for d in self.supply_docks() if any(dist(d["pos"], u) < 350 for u in used)]
        return bool(near) and sum(d.get("supply", 0) for d in near) < 6000

    async def powers(self):
        """General's powers from the Command Center."""
        while self.w.result is None:
            try:
                await self.powers_step()
            except ConnectionClosed as e:
                log("powers: connection closed", e, "-> exiting")
                import os
                os._exit(0)
            except ApiError as e:
                log("powers ApiError", e.code, e)
            except Exception as e:  # noqa: BLE001
                log("powers error", repr(e))
            await asyncio.sleep(10)

    async def use_power(self, cc_id, ability, pos=None, target=None, retry=30):
        now = time.time()
        if self.power_next.get(ability, 0) > now:
            return False
        try:
            await self.c.use_ability([cc_id], ability, pos=pos, target=target)
            log("POWER", ability, "at", [round(x) for x in pos[:2]] if pos else target)
            self.power_next[ability] = now + 120
            return True
        except ApiError as e:
            if e.code != "NOT_AVAILABLE":
                log("power refused", ability, e.code, e)
            self.power_next[ability] = now + retry
            return False

    async def powers_step(self):
        cc = self.done(P + "ChinaCommandCenter")
        if not cc:
            return
        cc_id = cc[0]["id"]
        tanks = [u for u in self.mine(BM) + self.mine(GATT) + self.mine(EMPEROR) if u.get("contained_by") is None]
        structures = self.w.enemy_structures()
        enemies = [o for o in self.w.visible.values() if not self.is_neutral(o) and "supply" not in o]
        # Artillery barrage: on the enemy structure with most enemies around, else nearest to enemy start
        if structures:
            def crowd(s):
                return sum(1 for o in enemies if dist(o["pos"], s["pos"]) < 120)
            tgt = max(structures, key=lambda s: (crowd(s), -dist(s["pos"], self.enemy_start)))
            await self.use_power(cc_id, "Command_ArtilleryBarrage", pos=tgt["pos"])
        elif enemies and tanks:
            center = tanks[0]["pos"]
            near = [o for o in enemies if dist(o["pos"], center) < 400]
            if len(near) >= 3:
                await self.use_power(cc_id, "Command_ArtilleryBarrage", pos=near[0]["pos"])
        # Tank paradrop: next to my army (or home when there is none)
        drop = tanks[0]["pos"] if tanks else self.toward(self.home, self.enemy_start, 200)
        await self.use_power(cc_id, "Tank_Command_TankParadrop", pos=drop)
        # Emergency repair on the most damaged tank cluster
        hurt = [u for u in tanks if u.get("max_health") and u.get("health", 0) < 0.6 * u["max_health"]]
        if len(hurt) >= 2:
            await self.use_power(cc_id, "Early_Command_EmergencyRepair", pos=hurt[0]["pos"])
        # Frenzy when fighting
        if tanks and enemies:
            near = [o for o in enemies if dist(o["pos"], tanks[0]["pos"]) < 300]
            if near and len(tanks) >= 4:
                await self.use_power(cc_id, "Command_Frenzy", pos=tanks[0]["pos"])

    def queued(self, template, within=16.0):
        now = time.time()
        self.recent_q = [(t, tp) for (t, tp) in getattr(self, "recent_q", []) if now - t < within]
        return sum(1 for (t, tp) in self.recent_q if tp == template)

    async def try_train(self, factory, template, count=1):
        try:
            await self.c.train(factory, template, count=count)
            self.recent_q = getattr(self, "recent_q", []) + [(time.time(), template)]
            return True
        except ApiError as e:
            if e.code not in ("INSUFFICIENT_FUNDS",):
                log("train refused", template, e.code, e)
            return False

    # ---------- phases ----------
    async def macro(self):
        """Runs forever: keeps the build order going according to what exists."""
        while self.w.result is None:
            try:
                await self.macro_step()
            except ConnectionClosed as e:
                log("macro: connection closed", e, "-> exiting")
                import os
                os._exit(0)
            except ApiError as e:
                log("macro ApiError", e.code, e)
            except Exception as e:  # noqa: BLE001
                log("macro error", repr(e))
            await asyncio.sleep(2)

    async def macro_step(self):
        money = self.w.money or 0
        cc = self.mine(P + "ChinaCommandCenter")
        cc_id = cc[0]["id"] if cc else None
        n_dozer = len(self.mine(DOZER))
        powers, supplies, warfs = self.done(POWER), self.done(SUPPLY), self.done(WARF)
        all_power, all_supply, all_warf = self.mine(POWER), self.mine(SUPPLY), self.mine(WARF)

        # second dozer early, third later
        want_dozers = 2 if not warfs else 3
        if cc_id and n_dozer < want_dozers and money >= 1000 and not getattr(self, "_dozer_queued", False):
            if await self.try_train(cc_id, DOZER):
                self._dozer_queued = True
                asyncio.get_event_loop().call_later(25, lambda: setattr(self, "_dozer_queued", False))

        tasks = []
        if not all_power and money >= 1000:
            tasks.append(self.build(POWER, self.home, away_from=self.enemy_start))
        elif not all_supply and money >= 1500 and powers:
            docks = self.supply_docks()
            if docks:
                dock = min(docks, key=lambda o: dist(o["pos"], self.home))
                near = self.toward(dock["pos"], self.home, 230)
                tasks.append(self.build_supply(near))
            else:
                tasks.append(self.build(SUPPLY, self.home, away_from=self.enemy_start))
        elif supplies and not all_warf and money >= 2000:
            tasks.append(self.build(WARF, self.home, away_from=self.enemy_start))
        elif warfs:
            # expansions / defense once the core exists
            if len(all_supply) < 2 and money >= 2500 and len(self.mine(BM) + self.mine(GATT)) >= 8:
                docks = sorted(self.supply_docks(), key=lambda o: dist(o["pos"], self.home))
                used = [s["pos"] for s in all_supply]
                cands = [d["pos"] for d in docks if all(dist(d["pos"], u) > 350 for u in used)]
                if not cands:
                    cands = [self.dock2_guess()]
                    log("no second dock visible; guessing", [round(x) for x in cands[0]])
                tasks.append(self.build_supply(self.toward(cands[0], self.home, 230)))
            elif len(all_power) < 2 and money >= 1800 and (self.w.power or {}).get("consumed", 0) >= \
                    (self.w.power or {}).get("produced", 1):
                tasks.append(self.build(POWER, self.home, away_from=self.enemy_start))
            elif len(all_warf) < 2 and money >= 2200 and len(self.mine(BM)) >= 10:
                tasks.append(self.build(WARF, self.home, away_from=self.enemy_start))
            elif len(all_warf) < 3 and money >= 4500 and len(self.mine(BM)) >= 8:
                tasks.append(self.build(WARF, self.home, away_from=self.enemy_start))
            elif len(all_power) < 3 and money >= 2500 and (self.w.power or {}).get("consumed", 0) >=                     (self.w.power or {}).get("produced", 1):
                tasks.append(self.build(POWER, self.home, away_from=self.enemy_start))
            elif len(all_supply) < 3 and money >= 3000 and len(self.supply_docks()) >= 3 and self.docks_low():
                docks = sorted(self.supply_docks(), key=lambda o: dist(o["pos"], self.home))
                used = [s["pos"] for s in all_supply]
                for d in docks:
                    if all(dist(d["pos"], u) > 350 for u in used) and d.get("supply", 0) > 3000:
                        tasks.append(self.build_supply(self.toward(d["pos"], self.home, 230)))
                        break
            elif not self.mine(GATT_CANNON) and money >= 3000 and len(self.mine(BM)) >= 4:
                front = self.toward(self.home, self.enemy_start, 300)
                tasks.append(self.build(GATT_CANNON, front, radii=(0, 80, 160, 240)))
            elif not self.mine(PROP) and money >= 4000 and len(all_warf) >= 2:
                tasks.append(self.build(PROP, self.home, away_from=self.enemy_start))
        for t in tasks:
            asyncio.ensure_future(t)

        # production
        for s in supplies:
            trucks = self.mine(TRUCK)
            if len(trucks) < 3 * len(supplies) + 1 and money >= 600 and not getattr(self, "_truck_q", False):
                if await self.try_train(s["id"], TRUCK):
                    self._truck_q = True
                    asyncio.get_event_loop().call_later(22, lambda: setattr(self, "_truck_q", False))
        # Idle trucks: send back to a dock
        idle_trucks = [t for t in self.mine(TRUCK) if "idle" in t.get("status", [])]
        if idle_trucks and self.supply_docks():
            dock = min(self.supply_docks(), key=lambda o: dist(o["pos"], self.home))
            try:
                await self.c.dock([t["id"] for t in idle_trucks], dock["id"])
            except ApiError as e:
                log("dock refused", e.code)

        if warfs and money >= 700:
            tanks = self.mine(BM) + self.mine(GATT)
            n_bm, n_gatt = len(self.mine(BM)) + self.queued(BM), len(self.mine(GATT)) + self.queued(GATT)
            for wf in warfs:
                reserve = 2500 if (len(tanks) >= 8 and len(all_supply) < 2) else                     (2200 if (len(self.mine(BM)) >= 10 and len(all_warf) < 2) else 0)
                if (self.w.money or 0) - reserve < 700:
                    break
                n_bm, n_gatt = len(self.mine(BM)) + self.queued(BM), len(self.mine(GATT)) + self.queued(GATT)
                template = GATT if n_bm >= 4 and n_gatt * getattr(self, 'gatt_per', 4) < n_bm else BM
                if self.mine(PROP) and (self.w.money or 0) > 3500 and len(tanks) > 10:
                    template = EMPEROR
                await self.try_train(wf["id"], template)
                await asyncio.sleep(0.2)
            # rally
            if not getattr(self, "_rally_set", False):
                rally = self.toward(self.home, self.enemy_start, 350)
                for wf in warfs:
                    try:
                        await self.c.set_rally_point(wf["id"], rally)
                    except ApiError:
                        pass
                self._rally_set = True

        # upgrades at propaganda center
        for pc in self.done(PROP):
            for up in ("Tank_Upgrade_ChinaTankAutoLoader", "Upgrade_Nationalism"):
                if up not in self.sciences_bought and (self.w.money or 0) >= 2600:
                    try:
                        await self.c.upgrade(pc["id"], up)
                        self.sciences_bought.add(up)
                        log("upgrade", up)
                    except ApiError as e:
                        if e.code != "INSUFFICIENT_FUNDS":
                            self.sciences_bought.add(up)
                            log("upgrade refused", up, e.code)

        # sciences
        if (self.w.me.get("science_points") or 0) > 0 and not getattr(self, "_sci_busy", False):
            self._sci_busy = True
            try:
                cat = await self.c.catalog()
                avail = {s["name"] for s in cat["sciences"] if s["purchasable_now"]}
                for name in SCIENCE_PRIORITY:
                    if name in avail:
                        try:
                            await self.c.purchase_science(name)
                            log("science", name)
                        except ApiError as e:
                            log("science refused", name, e.code)
                        break
            finally:
                self._sci_busy = False

    async def build_supply(self, near):
        await self.build(SUPPLY, near)

    # ---------- army ----------
    async def army(self):
        while self.w.result is None:
            try:
                await self.army_step()
            except ConnectionClosed as e:
                log("army: connection closed", e, "-> exiting")
                import os
                os._exit(0)
            except ApiError as e:
                log("army ApiError", e.code, e)
            except Exception as e:  # noqa: BLE001
                log("army error", repr(e))
            await asyncio.sleep(4)

    async def army_step(self):
        tanks = [u for u in self.mine(BM) + self.mine(GATT) + self.mine(EMPEROR) if u.get("contained_by") is None]
        ids = [u["id"] for u in tanks]
        if not ids:
            return
        # defend: enemies near home -> everyone attacks nearest
        near_home = [o for o in self.w.visible.values()
                     if o.get("relation", "enemy") != "neutral" and "supply" not in o
                     and dist(o["pos"], self.home) < 550 and not self.is_neutral(o)]
        if near_home:
            target = min(near_home, key=lambda o: dist(o["pos"], self.home))
            await self.c.attack_move(ids, target["pos"][:2])
            self.last_attack = time.time()
            return
        # retreat when outnumbered away from home
        front = max(tanks, key=lambda u: dist(u["pos"], self.home))
        center = front["pos"]
        my_str = sum(self.weight(u) for u in tanks if dist(u["pos"], center) < 350)
        foes = [o for o in self.w.visible.values() if not self.is_neutral(o) and "supply" not in o
                and self.weight(o) > 0 and dist(o["pos"], center) < 450]
        foe_str = sum(self.weight(o) for o in foes)
        if foe_str > 1.1 * my_str and dist(center, self.home) > 600:
            if time.time() - getattr(self, "_retreat_logged", 0) > 20:
                log(f"RETREAT: my {my_str:.1f} vs foe {foe_str:.1f} at {[round(x) for x in center[:2]]}")
                self._retreat_logged = time.time()
            self.army_target = None
            self.retreat_until = time.time() + 40
            await self.c.move(ids, self.toward(self.home, self.enemy_start, 250))
            return
        if getattr(self, "retreat_until", 0) > time.time():
            return
        if len(ids) >= ATTACK_SIZE or (self.army_target is not None and len(ids) >= 3):
            structures = [s for s in self.w.enemy_structures()]
            idle = [u["id"] for u in tanks if "idle" in u.get("status", [])]
            if structures:
                target = min(structures, key=lambda s: dist(s["pos"], self.enemy_start))
                self.army_target = target["pos"]
                if idle:
                    # pick nearest structure to the idle group
                    center = tanks[0]["pos"]
                    target = min(structures, key=lambda s: dist(s["pos"], center))
                    try:
                        await self.c.attack(idle, target["id"])
                    except ApiError as e:
                        if e.code in ("INVALID_TARGET", "NOT_VISIBLE"):
                            await self.c.attack_move(idle, target["pos"][:2])
                        else:
                            raise
            else:
                self.army_target = self.enemy_start
                if idle:
                    await self.c.attack_move(idle, self.enemy_start)
            # also throw visible enemy units in the way
        elif time.time() - self.last_attack > 60:
            # gather at rally point; pull back anyone far from home (not attacking as a group)
            rally = self.toward(self.home, self.enemy_start, 350)
            back = [u["id"] for u in tanks if ("idle" in u.get("status", []) and dist(u["pos"], rally) > 200)
                    or dist(u["pos"], self.home) > 700]
            if back:
                await self.c.move(back, rally)

    def weight(self, o):
        t = o["template"]
        for k, v in COMBAT_WEIGHT.items():
            if t.endswith(k):
                return v
        return 0.0

    def is_neutral(self, o):
        idx = o.get("player")
        if idx is None:
            return False
        for p in self.w.game_info["players"]:
            if p["index"] == idx:
                return p["relation"] not in ("enemy",)
        return True  # unknown player index -> neutral/civilian

    async def status(self):
        while self.w.result is None:
            await asyncio.sleep(15)
            counts = {}
            for u in self.w.units.values():
                counts[u["template"].replace(P, "")] = counts.get(u["template"].replace(P, ""), 0) + 1
            en = {}
            for o in self.w.visible.values():
                if not self.is_neutral(o):
                    en[o["template"]] = en.get(o["template"], 0) + 1
            log(f"frame={self.w.frame} money={self.w.money} power={self.w.power} units={counts} "
                f"enemy_structs={len(self.w.enemy_structures())} visible={len(self.w.visible)} enemies={en}")

    async def run(self):
        info = self.w.game_info
        cc = self.mine(P + "ChinaCommandCenter")
        self.home = cc[0]["pos"] if cc else list(min(info["start_positions"], key=lambda p: 0))
        self.enemy_start = max(info["start_positions"], key=lambda p: dist(p, self.home))
        enemy_sides = [p.get("side") for p in info["players"] if p.get("relation") == "enemy"]
        # Gattlings are useless against tanks: fewer of them against China; more against GLA/USA infantry and air
        self.gatt_per = 4 if any("China" in (sd or "") for sd in enemy_sides) else 3
        log("home", self.home, "enemy_start", self.enemy_start, "money", self.w.money, "enemy sides", enemy_sides,
            "gattling per", self.gatt_per)
        await self.c.set_snapshot_interval(15)
        self.c.on("game_over", lambda e: log("GAME OVER", e.get("result"), e.get("winners")))
        self.c.on("build_failed", lambda e: log("build_failed", e.get("template")))
        await asyncio.gather(self.macro(), self.army(), self.status(), self.powers())


async def main(url):
    client = await GeneralsClient(url, request_timeout=60).connect()
    await client.hello()
    try:
        await client.wait_for_state("in_game", timeout=300)
    except Exception:  # noqa: BLE001
        pass
    world = World().attach(client)
    await world.load(client)
    log("connected", url, "faction", world.catalog.get("faction"))
    await Bot(client, world).run()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
