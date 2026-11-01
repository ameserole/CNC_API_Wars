"""Bot1 macro bot: supply economy, war factories pumping tanks, defend base, attack in waves."""
import sys, asyncio, json, math, time, logging, random
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, ApiError

HERE = r"C:\Users\user\Documents\CNC_Generals_AI\agent-matches\20261101-041421\bot1"
logging.basicConfig(filename=HERE + r"\bot.log", level=logging.INFO,
                    format="%(asctime)s %(message)s")
log = logging.info
URL = "ws://127.0.0.1:64631"
TIME_LIMIT = float(sys.argv[1]) if len(sys.argv) > 1 else 3600

COMBAT = {"AmericaTankCrusader", "AmericaTankPaladin", "AmericaInfantryRanger", "AmericaInfantryMissileDefender",
          "AmericaVehicleHumvee", "AmericaTankAvenger", "AmericaVehicleTomahawk", "AmericaVehicleComanche",
          "AmericaTankMicrowave", "AmericaJetRaptor"}
BUILDINGS = {"AmericaCommandCenter", "AmericaPowerPlant", "AmericaBarracks", "AmericaWarFactory", "AmericaSupplyCenter",
             "AmericaStrategyCenter", "AmericaAirfield", "AmericaPatriotBattery", "AmericaFireBase"}
UNITS_ARMED = {"AmericaTankCrusader", "AmericaTankPaladin", "AmericaInfantryRanger", "AmericaInfantryMissileDefender",
               "AmericaVehicleHumvee", "AmericaTankAvenger", "AmericaVehicleTomahawk", "AmericaVehicleComanche",
               "AmericaTankMicrowave", "AmericaInfantryPathfinder", "AmericaInfantryColonelBurton", "AmericaVehicleSentryDrone",
               "AmericaJetRaptor", "AmericaJetStealthFighter", "AmericaJetAurora", "AmericaInfantryBiohazardTech", "AmericaVehicleMedic"}
COSTS = {"AmericaSupplyCenter": 2000, "AmericaWarFactory": 2000, "AmericaStrategyCenter": 2500,
         "AmericaPatriotBattery": 1000, "AmericaPowerPlant": 800}
SCIENCES = ["SCIENCE_PaladinTank", "SCIENCE_A10ThunderboltMissileStrike1", "SCIENCE_Pathfinder",
            "SCIENCE_A10ThunderboltMissileStrike2", "SCIENCE_EmergencyRepair1", "SCIENCE_A10ThunderboltMissileStrike3",
            "SCIENCE_SpectreGunship1", "SCIENCE_DaisyCutter", "SCIENCE_SpectreGunship2", "SCIENCE_SpectreGunship3",
            "SCIENCE_EmergencyRepair2", "SCIENCE_EmergencyRepair3", "SCIENCE_StealthFighter", "SCIENCE_SpyDrone",
            "SCIENCE_LeafletDrop", "SCIENCE_Paradrop1", "SCIENCE_Paradrop2", "SCIENCE_Paradrop3"]


def d(a, b):
    return math.dist(a[:2], b[:2])


class Bot:
    def __init__(self, c):
        self.c = c
        self.snap = None
        self.pending = {}          # factory id -> queued count
        self.jobs = []             # build jobs (template, near)
        self.busy = {}             # dozer id -> job
        self.attacking = False
        self.wave = int(sys.argv[2]) if len(sys.argv) > 2 else 12
        self.path = [(1800, 1800), (1850, 1480), (1800, 1100), (1760, 720), (1450, 600)]
        self.path_i = 0
        self.done = False
        self.purchased = set()
        self.upgraded = {"Upgrade_InfantryCaptureBuilding", "Upgrade_AmericaCompositeArmor"}
        self.last_attack_order = 0
        self.battleplan = False
        self.supply_dock = None

    def mine(self, tmpl):
        return [u for u in self.snap["units"] if u["template"] == tmpl]

    def complete(self, tmpl):
        return [u for u in self.mine(tmpl) if "under_construction" not in u.get("status", [])]

    async def setup(self):
        c = self.c
        gi = await c.game_info()
        self.me_idx = gi["local_player"]
        s = await c.state()
        self.snap = s
        cc = self.mine("AmericaCommandCenter")[0]
        self.home = cc["pos"]
        self.enemy_start = max(gi["start_positions"], key=lambda p: d(p, self.home))
        docks = [k for k in s["known_structures"] + s["visible"] if k["template"] == "SupplyDock"]
        self.supply_dock = min(docks, key=lambda k: d(k["pos"], self.home))["pos"] if docks else self.home
        dx, dy = self.enemy_start[0] - self.home[0], self.enemy_start[1] - self.home[1]
        L = math.hypot(dx, dy)
        self.fwd = (dx / L, dy / L)
        self.stage = (self.home[0] + self.fwd[0] * 330, self.home[1] + self.fwd[1] * 330)
        sd = self.supply_dock
        self.sc_spot = (sd[0] + (self.home[0] - sd[0]) * 0.4, sd[1] + (self.home[1] - sd[1]) * 0.4)
        self.front = (self.home[0] + self.fwd[0] * 300, self.home[1] + self.fwd[1] * 300)
        self.front2 = (self.home[0] + self.fwd[0] * 380, self.home[1] + self.fwd[1] * 380)
        self.back = (self.home[0] - self.fwd[0] * 250, self.home[1] - self.fwd[1] * 250)
        docks2 = sorted(docks, key=lambda k: d(k["pos"], self.home))
        sd2 = docks2[1]["pos"] if len(docks2) > 1 else sd
        self.sc2_spot = (sd2[0] + (self.home[0] - sd2[0]) * 0.3, sd2[1] + (self.home[1] - sd2[1]) * 0.3)
        log(f"home {self.home} enemy {self.enemy_start} dock {sd} sc_spot {self.sc_spot}")
        for k in s["known_structures"]:
            log(f"known {k['template']} {k['pos']} owner {k['owner']}")
        H = self.home
        self.jobs = [
            ("AmericaPowerPlant", self.back),
            ("AmericaSupplyCenter", self.sc_spot),
            ("AmericaBarracks", self.front),
            ("AmericaWarFactory", self.front),
            ("AmericaPowerPlant", self.back),
            ("AmericaWarFactory", self.front),
            ("AmericaPowerPlant", self.back),
            ("AmericaPatriotBattery", self.front2),
            ("AmericaStrategyCenter", H),
            ("AmericaPowerPlant", self.back),
            ("AmericaPatriotBattery", self.front2),
            ("AmericaWarFactory", self.front),
            ("AmericaPowerPlant", self.back),
        ]
        self.jobs.insert(5, ("AmericaSupplyCenter", self.sc2_spot))
        have = {}
        for u in s["units"]:
            have[u["template"]] = have.get(u["template"], 0) + 1
        newjobs = []
        for j in self.jobs:
            if have.get(j[0], 0) > 0:
                have[j[0]] -= 1
            else:
                newjobs.append(j)
        self.jobs = newjobs
        self.jobs = [j for j in self.jobs if not (j[0] == "AmericaPowerPlant" and self.mine("AmericaPowerPlant"))
                     and not (j[0] == "AmericaWarFactory" and len(self.mine("AmericaWarFactory")) >= 1)]
        self.west_sc = (560, 1650)
        if False:
            self.jobs.insert(0, ("AmericaSupplyCenter", self.west_sc))
        if not any(d(u["pos"], (420, 1620)) < 250 for u in self.mine("AmericaPatriotBattery")):
            self.jobs.insert(0, ("AmericaPatriotBattery", (420, 1620)))
        if not self.mine("AmericaBarracks"):
            self.jobs.insert(1, ("AmericaBarracks", self.front))
        log(f"jobs {self.jobs}")
        import os
        flag = HERE + r"\sold_wf.flag"
        if not os.path.exists(flag):
            wfs = self.mine("AmericaWarFactory")
            pps = self.mine("AmericaPowerPlant")
            try:
                if len(wfs) >= 3:
                    await self.c.sell(max(wfs, key=lambda u: d(u["pos"], self.home))["id"])
                    log("sold a war factory")
                if len(pps) >= 4:
                    await self.c.sell(pps[-1]["id"])
                    log("sold a power plant")
            except ApiError as e:
                log(f"sell err {e.code} {e}")
            open(flag, "w").write("1")
        flag3 = HERE + r"\sold_wf2.flag"
        if not os.path.exists(flag3):
            wfs = self.mine("AmericaWarFactory")
            if len(wfs) >= 2:
                await self.safe(self.c.sell(wfs[-1]["id"]))
                log("sold second war factory")
            open(flag3, "w").write("1")
        flag2 = HERE + r"\sold_strat.flag"
        if not os.path.exists(flag2):
            for st in self.mine("AmericaStrategyCenter"):
                try:
                    await self.c.sell(st["id"])
                    log("sold strategy center")
                except ApiError as e:
                    log(f"sell err {e.code} {e}")
            open(flag2, "w").write("1")
        self.jobs = [j for j in self.jobs if j[0] != "AmericaStrategyCenter"]
        if not any(d(u["pos"], (1400, 1650)) < 250 for u in self.mine("AmericaPatriotBattery")):
            self.jobs.insert(1, ("AmericaPatriotBattery", (1400, 1650)))
        bj = [j for j in self.jobs if j[0] == "AmericaBarracks"]
        self.jobs = [j for j in self.jobs if j[0] != "AmericaBarracks"] + bj[:1]
        for af in self.mine("AmericaAirfield"):
            try:
                await self.c.sell(af["id"])
                log("sold airfield")
                pp = self.mine("AmericaPowerPlant")
                if len(pp) >= 5:
                    await self.c.sell(pp[-1]["id"])
                    log("sold a power plant")
            except ApiError as e:
                log(f"sell err {e.code}")
        await self.try_science()

    async def try_science(self):
        try:
            cat = await self.c.catalog()
        except ApiError:
            return
        self.cat = cat
        try:
            json.dump(cat, open(HERE + r"\catalog.json", "w"), indent=1)
        except Exception:
            pass
        avail = {s["name"] for s in cat.get("sciences", []) if s.get("purchasable_now")}
        for name in SCIENCES:
            if name in avail and name not in self.purchased:
                try:
                    await self.c.purchase_science(name)
                    self.purchased.add(name)
                    try:
                        prev = set(json.load(open(HERE + r"\purchased.json")))
                    except Exception:
                        prev = set()
                    json.dump(sorted(prev | self.purchased), open(HERE + r"\purchased.json", "w"))
                    log(f"science {name}")
                    return
                except ApiError as e:
                    log(f"science {name} failed {e.code}")

    async def place(self, dozer, tmpl, near):
        for radius in (0, 120, 200, 280, 360, 440, 520, 600):
            n = 1 if radius == 0 else 12
            off = random.random()
            for step in range(n):
                a = (step + off) * 2 * math.pi / n
                pos = (near[0] + radius * math.cos(a), near[1] + radius * math.sin(a))
                try:
                    await self.c.build(dozer, tmpl, pos)
                    return pos
                except ApiError as e:
                    if e.code in ("ILLEGAL_LOCATION",):
                        continue
                    raise
        return None

    async def dozer_worker(self, dozer):
        """Runs build jobs with one dozer."""
        while not self.done:
            if not self.jobs:
                await asyncio.sleep(2)
                continue
            if dozer not in {u["id"] for u in self.snap["units"]}:
                return
            tmpl, near = self.jobs.pop(0)
            if tmpl == "RESUME":
                self.busy[dozer] = ("RESUME", near)
                try:
                    await self.c.resume_construction(dozer, near)
                    log(f"dozer {dozer} resuming {near}")
                    await self.c.wait_for_event("construction_complete", lambda e: e["id"] == near, timeout=180)
                except Exception as e:
                    log(f"resume err {e}")
                self.busy.pop(dozer, None)
                continue
            started = asyncio.ensure_future(self.c.wait_for_event(
                "construction_started", lambda e: e["template"] == tmpl, timeout=90))
            try:
                pos = await self.place(dozer, tmpl, near)
                if pos is None:
                    log(f"no spot for {tmpl}")
                    started.cancel()
                    continue
                ev = await started
                log(f"dozer {dozer} started {tmpl} at {pos}")
                await self.c.wait_for_event("construction_complete", lambda e: e["id"] == ev["id"], timeout=180)
                log(f"complete {tmpl}")
            except ApiError as e:
                started.cancel()
                if e.code == "INSUFFICIENT_FUNDS" or e.code == "NOT_AVAILABLE":
                    self.jobs.insert(0, (tmpl, near))
                    await asyncio.sleep(3)
                else:
                    log(f"build {tmpl} error {e.code} {e}")
                    if e.code in ("NOT_OWNED", "UNKNOWN_OBJECT", "NO_SUCH_OBJECT"):
                        self.jobs.insert(0, (tmpl, near))
                        return
                    await asyncio.sleep(2)
            except (asyncio.TimeoutError, TimeoutError):
                started.cancel()
                log(f"timeout on {tmpl}, requeue")
                self.jobs.insert(0, (tmpl, near))
            except Exception as e:
                started.cancel()
                log(f"dozer err {type(e).__name__} {e}")
                await asyncio.sleep(2)

    async def train(self, factory, tmpl, maxq=2):
        if self.pending.get(factory, 0) >= maxq:
            return False
        if tmpl not in ("AmericaVehicleDozer", "AmericaVehicleChinook") and                 ("Upgrade_InfantryCaptureBuilding" not in self.upgraded and not getattr(self, "under_threat", False)):
            return False
        if tmpl not in ("AmericaVehicleDozer", "AmericaVehicleChinook") and self.reserve():
            return False
        try:
            await self.c.train(factory, tmpl, 1)
            self.pending[factory] = self.pending.get(factory, 0) + 1
            return True
        except ApiError as e:
            if e.code not in ("INSUFFICIENT_FUNDS", "QUEUE_FULL"):
                log(f"train {tmpl} err {e.code} {e}")
            return False

    def reserve(self):
        """True when unit spending should wait so the next priority building can be afforded."""
        if not self.jobs or getattr(self, "under_threat", False):
            return False
        head = self.jobs[0][0]
        if head not in COSTS:
            return False
        if head in ("AmericaSupplyCenter", "AmericaPatriotBattery"):
            return self.snap["self"]["money"] < COSTS[head] + 100
        army = [u for u in self.snap["units"] if u["template"] in COMBAT]
        if len(army) < 6:
            return False
        return self.snap["self"]["money"] < COSTS[head] + 300

    def on_destroyed(self, e):
        log(f"LOST {e.get('template')} {e.get('id')} by {e.get('attacker_template')} {e.get('attacker_id')}")
        self.on_damaged(e)

    def on_damaged(self, e):
        aid = e.get("attacker_id")
        if aid is None:
            return
        if not hasattr(self, "attackers"):
            self.attackers = {}
        self.attackers[aid] = (time.time(), e.get("attacker_template"))

    def on_created(self, e):
        f = e.get("factory_id")
        if f in self.pending:
            self.pending[f] = max(0, self.pending[f] - 1)

    async def production(self):
        money = self.snap["self"]["money"]
        dozers = self.mine("AmericaVehicleDozer")
        for cc in self.complete("AmericaCommandCenter"):
            if len(dozers) + self.pending.get(cc["id"], 0) < 3:
                await self.train(cc["id"], "AmericaVehicleDozer", 1)
        chinooks = self.mine("AmericaVehicleChinook")
        scs = self.complete("AmericaSupplyCenter")
        for sc in scs:
            if len(chinooks) + sum(self.pending.get(x["id"], 0) for x in scs) < min(2 * len(scs) + 1, 6):
                await self.train(sc["id"], "AmericaVehicleChinook", 1)
        army = [u for u in self.snap["units"] if u["template"] in COMBAT]
        inf = [u for u in army if "Infantry" in u["template"]]
        for b in self.complete("AmericaBarracks"):
            has_wf = bool(self.mine("AmericaWarFactory"))
            if (len(inf) < 4 and (has_wf or money > 2600)) or (has_wf and len(inf) < 8 and money > 1200) or (money > 3000 and len(inf) < 14):
                t = "AmericaInfantryMissileDefender" if len(inf) % 2 else "AmericaInfantryRanger"
                await self.train(b["id"], t, 2)
        paladin = True
        vehicles = [u for u in army if "Infantry" not in u["template"]]
        for i, wf in enumerate(self.complete("AmericaWarFactory")):
            n = len(vehicles)
            if paladin and n % 3 != 2:
                t = "AmericaTankPaladin"
            elif n % 6 == 5 and self.complete("AmericaStrategyCenter"):
                t = "AmericaVehicleTomahawk"
            else:
                t = "AmericaTankCrusader"
            if not await self.train(wf["id"], t, 2):
                if self.pending.get(wf["id"], 0) == 0:
                    await self.train(wf["id"], "AmericaTankCrusader", 2)
        for af in self.complete("AmericaAirfield"):
            pass
        # upgrades
        for sc in self.complete("AmericaStrategyCenter"):
            if not self.battleplan:
                try:
                    await self.c.use_ability([sc["id"]], "Command_InitiateBattlePlanBombardment")
                    self.battleplan = True
                    log("battle plan bombardment")
                except ApiError as e:
                    log(f"battleplan err {e.code}")
                    self.battleplan = True
            for up in ("Upgrade_AmericaCompositeArmor", "Upgrade_AmericaSupplyLines", "Upgrade_AmericaAdvancedTraining"):
                if up not in self.upgraded and money > 2500:
                    try:
                        await self.c.upgrade(sc["id"], up)
                        self.upgraded.add(up)
                        log(f"upgrade {up}")
                    except ApiError as e:
                        if e.code not in ("INSUFFICIENT_FUNDS",):
                            log(f"upgrade {up} err {e.code}")
                            if e.code in ("ALREADY_HAVE", "NOT_AVAILABLE", "ALREADY_IN_PRODUCTION"):
                                self.upgraded.add(up)
                    break
        for wf in self.complete("AmericaWarFactory")[:1]:
            up = "Upgrade_AmericaTOWMissile"
        # power
        p = self.snap["self"]["power"]
        if p["produced"] - p["consumed"] < 2 and not any(j[0] == "AmericaPowerPlant" for j in self.jobs[:2]) \
                and len(self.complete("AmericaPowerPlant")) > 0:
            if not any(j[0] == "AmericaPowerPlant" for j in self.busy.values()):
                self.jobs.insert(0, ("AmericaPowerPlant", self.back))
                log("queued extra power")
        if money > 3000 and not self.jobs and len(self.mine("AmericaPatriotBattery")) < 5:
            self.jobs.append(("AmericaPatriotBattery", self.front2))
            log("queued extra patriot")
        # late game: more factories when rich
        if money > 3000 and not self.jobs and len(self.mine("AmericaWarFactory")) < 2:
            self.jobs.append(("AmericaWarFactory", self.front))
            log("queued extra war factory")

    def enemies(self):
        return [o for o in self.snap["visible"] if o.get("owner") != self.me_idx and o.get("owner") not in (0, 1)]

    async def army_control(self):
        allarmy = [u for u in self.snap["units"] if u["template"] in COMBAT and u.get("contained_by") is None]
        army = [u for u in allarmy if "Infantry" not in u["template"]]
        ids = [u["id"] for u in army]
        inf = [u["id"] for u in allarmy if "Infantry" in u["template"]]
        en = self.enemies()
        self.under_threat = False
        recent = {a for a, (t, _) in getattr(self, "attackers", {}).items() if time.time() - t < 12}
        threats = [o for o in en if o["template"] not in ("AmericaVehicleChinook", "AmericaVehicleDozer", "AmericaCrateParachute") and o["template"] in UNITS_ARMED] + []
        threats = [o for o in threats if d(o["pos"], self.home) < 650 or self.near_west(o["pos"]) or (self.near_base(o["pos"]) and d(o["pos"], self.home) < 800)]
        now = time.time()
        if threats:
            self.under_threat = True
            t = min(threats, key=lambda o: d(o["pos"], self.home))
            await self.strike(t["pos"])
            if now - self.last_attack_order > 6:
                # defend with everyone not deep in enemy territory
                defenders = [u["id"] for u in allarmy if d(u["pos"], self.home) < 800 or d(u["pos"], t["pos"]) < 400]
                if defenders:
                    await self.safe(self.c.attack_move(defenders, t["pos"][:2]))
                    log(f"defend vs {t['template']} at {t['pos'][:2]} with {len(defenders)}")
                    self.last_attack_order = now
            return
        if inf and now - getattr(self, "cap_t", 0) > 75:
            self.cap_t = now
            ders = [o for o in self.snap["known_structures"] + self.snap["visible"] if o["template"] == "TechOilDerrick"
                    and o.get("owner") != self.me_idx and d(o["pos"], self.home) < 1000]
            if ders:
                if "Upgrade_InfantryCaptureBuilding" not in self.upgraded:
                    for b in self.complete("AmericaBarracks")[:1]:
                        try:
                            await self.c.upgrade(b["id"], "Upgrade_InfantryCaptureBuilding")
                            self.upgraded.add("Upgrade_InfantryCaptureBuilding")
                            log("capture upgrade queued")
                        except ApiError as e:
                            log(f"capture upgrade err {e.code} {e}")
                            if e.code not in ("INSUFFICIENT_FUNDS",):
                                self.upgraded.add("Upgrade_InfantryCaptureBuilding")
                else:
                    rangers = [u["id"] for u in allarmy if u["template"] == "AmericaInfantryRanger"]
                    if rangers:
                        try:
                            await self.c.use_ability(rangers[:1], "Command_AmericaRangerCaptureBuilding", target=ders[0]["id"])
                            self.capturing = rangers[0]
                            log(f"capture derrick {ders[0]['id']} with {rangers[0]}")
                        except ApiError as e:
                            log(f"capture err {e.code} {e}")
                            if e.code == "NOT_AVAILABLE" and self.complete("AmericaBarracks"):
                                self.cap_fail = getattr(self, "cap_fail", 0) + 1
                                if self.cap_fail >= 2:
                                    self.upgraded.discard("Upgrade_InfantryCaptureBuilding")
                                    self.cap_fail = 0
        if False:
            self.cap_t = now
            ders = [o for o in self.snap["known_structures"] + self.snap["visible"] if o["template"] == "TechOilDerrick"
                    and o.get("owner") != self.me_idx and d(o["pos"], self.home) < 1000]
            mine_d = [u for u in self.snap["units"] if u["template"] == "TechOilDerrick"]
            if ders and not mine_d:
                rangers = [u["id"] for u in allarmy if u["template"] == "AmericaInfantryRanger"]
                if rangers:
                    r = await self.safe(self.c.enter(rangers[:1], ders[0]["id"]))
                    log(f"capture derrick {ders[0]['id']} with {rangers[0]}: {r}")
                    self.capturing = rangers[0]
        if inf and now - getattr(self, "inf_t", 0) > 30:
            self.inf_t = now
            await self.safe(self.c.attack_move([i for i in inf if i != getattr(self, "capturing", None)], self.front))
        if not ids:
            return
        if not self.attacking and len(ids) >= self.wave:
            self.attacking = True
            self.path_i = 0
            log(f"ATTACK wave with {len(ids)}")
        if self.attacking:
            if len(ids) < 4:
                self.attacking = False
                self.wave = min(self.wave + 3, 20)
                log("retreat/regroup, new wave size %d" % self.wave)
                await self.safe(self.c.attack_move(ids, self.stage))
                return
            cx = sum(u["pos"][0] for u in army) / len(army)
            cy = sum(u["pos"][1] for u in army) / len(army)
            while self.path_i < len(self.path) and d((cx, cy), self.path[self.path_i]) < 220:
                self.path_i += 1
                log(f"waypoint reached, next {self.path_i}")
                self.last_attack_order = 0
            near_enemy = [o for o in self.enemies() if d(o["pos"], (cx, cy)) < 450]
            if self.path_i < len(self.path) and not near_enemy:
                if now - self.last_attack_order > 8:
                    await self.safe(self.c.attack_move(ids, self.path[self.path_i]))
                    self.last_attack_order = now
                    log(f"flank move {len(ids)} -> wp{self.path_i} {self.path[self.path_i]}")
                return
            if now - self.last_attack_order > 10:
                target = self.pick_target(army)
                await self.strike(target)
                await self.safe(self.c.attack_move(ids, target))
                self.last_attack_order = now
                log(f"attack_move {len(ids)} -> {target}")

    async def strike(self, pos):
        if time.time() - getattr(self, "strike_t", 0) < 15 or not getattr(self, "cat", None):
            return
        self.strike_t = time.time()
        for st in self.cat.get("structures", []):
            for ab in st.get("abilities", []):
                nm = ab.get("name", "")
                if ab.get("type") == "special_power" and ab.get("target") not in ("none", None) and                         self.power_owned(nm):
                    owners = self.complete(st["name"])
                    if not owners:
                        continue
                    try:
                        await self.c.use_ability([owners[0]["id"]], nm, pos=pos[:2])
                        log(f"STRIKE {nm} at {pos[:2]}")
                    except ApiError as e:
                        if e.code not in ("NOT_READY", "NOT_AVAILABLE", "COOLDOWN"):
                            log(f"strike {nm} err {e.code} {e}")

    def power_owned(self, nm):
        # Only use powers whose science we bought (the API accepted science-locked ones; avoid that).
        owned = set(self.purchased)
        try:
            owned |= set(json.load(open(HERE + r"\purchased.json")))
        except Exception:
            pass
        keys = {"A10": "A10Thunderbolt", "Spectre": "SpectreGunship", "DaisyCutter": "DaisyCutter",
                "Paradrop": "Paradrop", "CarpetBomb": "CarpetBomb"}
        for k, sci in keys.items():
            if k in nm:
                return any(sci in o for o in owned)
        return False

    async def redirect_chinooks(self):
        """Sends idle chinooks to the contested middle supply piles."""
        piles = {o["id"]: o for o in self.snap["visible"] + self.snap["known_structures"] if o["template"] == "SupplyPileSmall"}
        pats = [o for o in self.snap["visible"] + self.snap["known_structures"]
                if o["template"] == "AmericaPatriotBattery" and o.get("owner") not in (self.me_idx, 0, 1)]
        safe = [o for o in piles.values() if all(d(o["pos"], p["pos"]) > 420 for p in pats)]
        west = [o for o in safe if d(o["pos"], (530, 1420)) < 200]
        east = [o for o in safe if d(o["pos"], (1330, 1410)) < 150]
        if not west and not east:
            for ch in self.mine("AmericaVehicleChinook"):
                if not getattr(self, "recalled", False) and d(ch["pos"], self.home) > 500:
                    await self.safe(self.c.move([ch["id"]], self.sc_spot))
            self.recalled = True
            return
        if not hasattr(self, "redirected"):
            self.redirected = {}
        now = time.time()
        chs = sorted(self.mine("AmericaVehicleChinook"), key=lambda u: u["id"])
        for i, ch in enumerate(chs):
            if now - self.redirected.get(ch["id"], 0) < 240:
                continue
            group = west if (i % 2 == 0 or not east) else east
            if not group:
                group = west or east
            if not group:
                return
            pile = group[i % len(group)]
            try:
                await self.c.dock([ch["id"]], pile["id"])
                log(f"chinook {ch['id']} -> pile {pile['id']} {pile['pos'][:2]}")
            except ApiError as e:
                log(f"dock err {e.code} {e}")
            self.redirected[ch["id"]] = now

    def near_west(self, pos):
        return d(pos, self.west_sc) < 350

    def near_base(self, pos):
        return any(d(pos, u["pos"]) < 350 for u in self.snap["units"] if u["template"] in BUILDINGS)

    def pick_target(self, army):
        cx = sum(u["pos"][0] for u in army) / len(army)
        cy = sum(u["pos"][1] for u in army) / len(army)
        cands = [o for o in self.snap["visible"] if o.get("owner") not in (self.me_idx, 0, 1) and d(o["pos"], (cx, cy)) < 600]
        cands += [k for k in self.snap["known_structures"] if k.get("owner") not in (self.me_idx, 0, 1)]
        if cands:
            t = min(cands, key=lambda o: d(o["pos"], (cx, cy)))
            return tuple(t["pos"][:2])
        return tuple(self.enemy_start[:2])

    async def safe(self, coro):
        try:
            return await coro
        except ApiError as e:
            log(f"order err {e.code} {e}")

    async def run(self):
        c = self.c
        c.on("unit_created", self.on_created)
        c.on("unit_destroyed", self.on_destroyed)
        c.on("unit_damaged", self.on_damaged)

        def over(e):
            log(f"GAME OVER {e}")
            self.done = True
        c.on("game_over", over)
        c.on("rank_changed", lambda e: asyncio.ensure_future(self.try_science()))
        await self.setup()
        workers = {}
        start = time.time()
        rally_set = set()
        tick = 0
        while not self.done and time.time() - start < TIME_LIMIT:
            try:
                self.snap = await c.state()
            except Exception as e:
                log(f"state err {e}")
                await asyncio.sleep(2)
                continue
            for dz in (self.mine("AmericaVehicleDozer") if tick >= 7 or not any("under_construction" in u.get("status", []) for u in self.snap["units"]) else []):
                if dz["id"] not in workers or workers[dz["id"]].done():
                    workers[dz["id"]] = asyncio.ensure_future(self.dozer_worker(dz["id"]))
            for tmpl in ("AmericaBarracks", "AmericaWarFactory", "AmericaAirfield"):
                for b in self.complete(tmpl):
                    if b["id"] not in rally_set:
                        await self.safe(c.set_rally_point(b["id"], self.stage))
                        rally_set.add(b["id"])
            try:
                await self.production()
                await self.army_control()
            except ApiError as e:
                log(f"loop api err {e.code} {e}")
            except Exception as e:
                log(f"loop err {type(e).__name__} {e}")
            tick += 1
            if tick % 5 == 0:
                await self.redirect_chinooks()
            if tick % 5 == 0:
                prog = getattr(self, "prog", {})
                newprog = {}
                for u in self.snap["units"]:
                    if "under_construction" in u.get("status", []):
                        pc = u.get("construction_percent", 0)
                        newprog[u["id"]] = pc
                        if u["id"] in prog and prog[u["id"]] == pc and not any(j == ("RESUME", u["id"]) for j in self.jobs)                                 and ("RESUME", u["id"]) not in self.busy.values():
                            self.jobs.insert(0, ("RESUME", u["id"]))
                            log(f"stalled {u['template']} {u['id']} at {pc}, queue resume")
                self.prog = newprog
            if tick % 10 == 0:
                s = self.snap
                counts = {}
                for u in s["units"]:
                    counts[u["template"]] = counts.get(u["template"], 0) + 1
                log(f"frame {s['frame']} money {s['self']['money']} power {s['self']['power']} rank {s['self'].get('rank')} "
                    f"jobs {[j[0] for j in self.jobs]} units {counts} enemies_visible {[(o['template'], [int(x) for x in o['pos'][:2]]) for o in self.enemies()][:10]}")
                await self.try_science()
            await asyncio.sleep(2)
        log("bot loop ended")


async def main():
    c = await GeneralsClient(URL, request_timeout=60).connect()
    await c.hello()
    bot = Bot(c)
    try:
        await bot.run()
    finally:
        await c.close()


asyncio.run(main())
