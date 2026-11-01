"""Bot2 macro bot: USA eco -> tanks, patriots for defense, attack-move waves."""
import sys, asyncio, json, math, time, traceback
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, ApiError

URL = "ws://127.0.0.1:64632"
LOG = open("bot.log", "a", encoding="utf-8")
FPS = 30


def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.write(s + "\n")
    LOG.flush()


HOME = (1004.8, 583.6)
ENEMY = (1010.8, 2102.7)
DOCK_A = (632.5, 127.3)
DOCK_B = (1731.1, 295.7)
STAGE = (1005.0, 820.0)
ENEMY_IDX = 2


def d(a, b):
    return math.dist(a[:2], b[:2])


def short(t):
    return t.replace("America", "")


PLAN = [
    ("AmericaPowerPlant", HOME, None),
    ("AmericaSupplyCenter", DOCK_A, HOME),
    ("AmericaSupplyCenter", (1440, 1000), HOME),
    ("AmericaSupplyCenter", (690, 1000), HOME),
    ("AmericaBarracks", HOME, STAGE),
    ("AmericaWarFactory", HOME, STAGE),
    ("AmericaPowerPlant", HOME, None),
    ("AmericaSupplyCenter", DOCK_B, HOME),
    ("AmericaPatriotBattery", (1004, 960), None),
    ("AmericaPowerPlant", HOME, None),
    ("AmericaPatriotBattery", (800, 900), None),
    ("AmericaWarFactory", HOME, STAGE),
    ("AmericaPowerPlant", HOME, None),
    ("AmericaStrategyCenter", HOME, None),
    ("AmericaFireBase", (1004, 880), None),
    ("AmericaFireBase", (850, 860), None),
    ("AmericaSupplyDropZone", HOME, None),
    ("AmericaFireBase", (1500, 700), None),
    ("AmericaFireBase", (1180, 880), None),
    ("AmericaPowerPlant", (1004, 400), None),
    ("AmericaParticleCannonUplink", (1004, 450), None),
    ("AmericaPowerPlant", (1004, 400), None),
]
COMBAT = ("InfantryRanger", "InfantryMissileDefender", "TankCrusader", "TankPaladin", "VehicleTomahawk",
          "TankAvenger", "VehicleHumvee", "TankMicrowave", "VehicleComanche", "InfantryPathfinder")
SCIENCES = ["SCIENCE_PaladinTank", "SCIENCE_A10ThunderboltMissileStrike1", "AirF_SCIENCE_A10ThunderboltMissileStrike1",
            "SCIENCE_EmergencyRepair1", "Early_SCIENCE_EmergencyRepair1", "SCIENCE_A10ThunderboltMissileStrike2",
            "SCIENCE_SpectreGunship1", "SCIENCE_SpectreGunshipSolo", "SCIENCE_A10ThunderboltMissileStrike3",
            "SCIENCE_Paradrop1", "SCIENCE_SpectreGunship2", "SCIENCE_SpectreGunship3", "SCIENCE_DaisyCutter",
            "SCIENCE_StealthFighter", "SCIENCE_SpyDrone"]
UPGRADES = [("AmericaStrategyCenter", "Upgrade_AmericaCompositeArmor"),
            ("AmericaStrategyCenter", "Upgrade_AmericaSupplyLines"),
            ("AmericaStrategyCenter", "Upgrade_AmericaAdvancedTraining"),
            ("AmericaWarFactory", "Upgrade_AmericaTOWMissile")]
UNIT_T = set()
MEM = {-1: {"id": -1, "template": "AmericaCommandCenter", "pos": [1011, 2103, 0]},
       -2: {"id": -2, "template": "AmericaWarFactory", "pos": [1042, 1918, 0]},
       -3: {"id": -3, "template": "AmericaWarFactory", "pos": [1200, 1864, 0]},
       -4: {"id": -4, "template": "AmericaWarFactory", "pos": [883, 1957, 0]},
       -5: {"id": -5, "template": "AmericaStrategyCenter", "pos": [1193, 2186, 0]},
       -6: {"id": -6, "template": "AmericaSupplyCenter", "pos": [1249, 2369, 0]}}
DEAD = set()


class Bot:
    def __init__(self, c):
        self.c = c
        self.cost = {}
        self.prereq = {}
        self.busy = {}  # dozer id -> (template, until_frame)
        self.frame = 0
        self.attacking = False
        self.last_attack_order = 0
        self.done_upgrades = set()
        self.bad_upgrade = set()
        self.over = False
        self.defending = False
        self.last_repair = {}
        self.wave_size = 22
        self.wave_ids = set()
        self.wave_start = 0
        self.last_home_order = 0
        self.queued = {}
        self.rallied = set()
        self.last_power = -99999
        self.sciences_owned = {'SCIENCE_A10ThunderboltMissileStrike1'}

    async def place(self, dozer, template, anchor, prefer):
        cands = []
        for r in (180, 260, 340, 420, 500, 580, 660):
            for k in range(16):
                a = k * math.pi / 8
                p = (anchor[0] + r * math.cos(a), anchor[1] + r * math.sin(a))
                if not (60 < p[0] < 1980 and 60 < p[1] < 2640):
                    continue
                cands.append(p)
        if prefer is not None:
            cands.sort(key=lambda p: d(p, anchor) + 0.4 * d(p, prefer))
        else:
            cands.sort(key=lambda p: d(p, anchor) + 0.3 * d(p, STAGE))
        for p in cands[:70]:
            try:
                await self.c.build(dozer, template, p)
                log("BUILD", short(template), "at", [round(x) for x in p], "by", dozer)
                return True
            except ApiError as e:
                if e.code == "ILLEGAL_LOCATION":
                    continue
                log("build err", template, e.code, e.message)
                return False
        log("no spot for", template)
        return False

    async def tick(self):
        s = await self.c.state()
        self.frame = s["frame"]
        me = s["self"]
        money = me["money"]
        pw = me["power"]
        units = s["units"]
        vis = [o for o in s.get("visible", []) if o.get("owner") == ENEMY_IDX]
        known = [o for o in s.get("known_structures", []) if o.get("owner") == ENEMY_IDX]
        for o in known + [o for o in vis if o["template"] in self.cost and o["template"] not in UNIT_T]:
            MEM[o["id"]] = {"id": o["id"], "template": o["template"], "pos": o["pos"]}
        vstruct = [o for o in vis if o["template"] in self.cost and o["template"] not in UNIT_T]
        for i in list(MEM):
            if i in DEAD:
                del MEM[i]
            elif i < 0 and any(d(u["pos"], MEM[i]["pos"]) < 200 for u in units) and                     not any(d(o["pos"], MEM[i]["pos"]) < 150 for o in vstruct):
                del MEM[i]
            elif i < 0 and any(d(o["pos"], MEM[i]["pos"]) < 150 for o in vstruct):
                del MEM[i]
        known = list(MEM.values())
        by = {}
        for u in units:
            by.setdefault(u["template"], []).append(u)

        def cnt(t):
            return len(by.get(t, []))

        def done(t):
            return [u for u in by.get(t, []) if "under_construction" not in u["status"]]

        structs = [u for u in units if u["template"] in self.cost and u["template"] not in UNIT_T]

        # ---- sciences
        if me.get("science_points", 0) > 0:
            for sc in SCIENCES:
                try:
                    await self.c.purchase_science(sc)
                    log("SCIENCE", sc)
                    self.sciences_owned.add(sc)
                    break
                except ApiError:
                    pass

        # ---- dozers / building
        dozers = by.get("AmericaVehicleDozer", [])
        for dz in dozers:
            b = self.busy.get(dz["id"])
            if b and self.frame > b[1]:
                near = [u for u in structs if "under_construction" in u["status"] and d(u["pos"], dz["pos"]) < 220]
                if near and self.frame < b[1] + 120 * FPS:
                    continue
                del self.busy[dz["id"]]
        for k in list(self.busy):
            if k not in {z["id"] for z in dozers}:
                del self.busy[k]
        pending = [b[0] for b in self.busy.values() if self.frame <= b[1]]
        need = []
        counts = {}
        for tpl, anchor, prefer in PLAN:
            counts[tpl] = counts.get(tpl, 0) + 1
            have = cnt(tpl) + pending.count(tpl)
            if have < counts[tpl]:
                need.append((tpl, anchor, prefer))
                pending.append(tpl)
        building_power = any(b[0] == "AmericaPowerPlant" for b in self.busy.values())
        if pw["produced"] - pw["consumed"] < 2 and cnt("AmericaPowerPlant") >= 1 and not building_power:
            if not need or need[0][0] != "AmericaPowerPlant":
                need.insert(0, ("AmericaPowerPlant", HOME, None))
        if not need and money > 4000 and cnt("AmericaPatriotBattery") < 6:
            if pw["produced"] - pw["consumed"] < 5 and not building_power:
                need.append(("AmericaPowerPlant", HOME, None))
            else:
                need.append(("AmericaPatriotBattery", (1004 + (cnt("AmericaPatriotBattery") % 3 - 1) * 250, 880), None))
        uc = [u for u in structs if "under_construction" in u["status"]]
        idle = [dz for dz in dozers if dz["id"] not in self.busy
                and not any(d(u["pos"], dz["pos"]) < 160 for u in uc)]
        reserve = 0
        donet = {u["template"] for u in structs if "under_construction" not in u["status"]}
        need = [n for n in need if all(any(x in donet for x in grp) for grp in self.prereq.get(n[0], []))]
        for tpl, anchor, prefer in need[:2]:
            if not idle:
                break
            cost = self.cost.get(tpl, 1000)
            if money < cost:
                reserve = cost
                break
            dz = min(idle, key=lambda z: d(z["pos"], anchor))
            if await self.place(dz["id"], tpl, anchor, prefer):
                self.busy[dz["id"]] = (tpl, self.frame + 10 * FPS)
                money -= cost
                idle.remove(dz)
            else:
                break
        for dz in idle:
            dmg = [u for u in structs if "under_construction" not in u["status"] and u["health"] < 0.6 * u["max_health"]]
            if dmg and self.frame - self.last_repair.get(dz["id"], -9999) > 300:
                t = min(dmg, key=lambda u: d(u["pos"], dz["pos"]))
                try:
                    await self.c.repair(dz["id"], t["id"])
                    self.last_repair[dz["id"]] = self.frame
                    log("repair", short(t["template"]))
                except ApiError as e:
                    log("repair err", e)

        spend = money - reserve

        async def train(fac, tpl, n=1):
            nonlocal spend
            c = self.cost.get(tpl, 0)
            if spend < c:
                return False
            try:
                await self.c.train(fac["id"], tpl, count=n)
                spend -= c * n
                log("TRAIN", short(tpl))
                return True
            except ApiError as e:
                if e.code not in ("INSUFFICIENT_FUNDS",):
                    log("train err", tpl, e.code, e.message)
                return False

        def ready(fac):
            return self.frame >= self.queued.get(fac["id"], 0)

        def mark(fac, secs):
            self.queued[fac["id"]] = self.frame + secs * FPS

        cc = done("AmericaCommandCenter")
        if cc and cnt("AmericaVehicleDozer") < 3 and ready(cc[0]) and (money > 1500 or cnt("AmericaVehicleDozer") < 2):
            if await train(cc[0], "AmericaVehicleDozer"):
                mark(cc[0], 30)
        sup = done("AmericaSupplyCenter")
        chin = cnt("AmericaVehicleChinook")
        for sc in sup:
            if chin < min(3 * len(sup), 8) and ready(sc):
                if await train(sc, "AmericaVehicleChinook"):
                    mark(sc, 25)
                    chin += 1
        await self.chinooks(by, s.get("visible", []), vis)
        army = [u for u in units if short(u["template"]) in COMBAT and u.get("contained_by") is None]

        def nn(k):
            return sum(1 for u in army if u["template"].endswith(k))

        for wf in done("AmericaWarFactory"):
            if not ready(wf):
                continue
            tanks = nn("TankPaladin") + nn("TankCrusader")
            if nn("TankAvenger") * 6 < tanks - 3:
                t = "AmericaTankAvenger"
            elif tanks >= 8 and nn("VehicleTomahawk") * 4 < tanks and cnt("AmericaStrategyCenter"):
                t = "AmericaVehicleTomahawk"
            else:
                t = "AmericaTankPaladin"
            if await train(wf, t):
                mark(wf, 12)
            elif t == "AmericaTankPaladin" and spend >= 900:
                if await train(wf, "AmericaTankCrusader"):
                    mark(wf, 10)
        for br in done("AmericaBarracks"):
            if not ready(br):
                continue
            inf = nn("InfantryRanger") + nn("InfantryMissileDefender")
            if inf < 6 or (inf < 12 and spend > 1800):
                t = ("AmericaInfantryMissileDefender" if nn("InfantryMissileDefender") <= nn("InfantryRanger")
                     else "AmericaInfantryRanger")
                if await train(br, t):
                    mark(br, 8)
        for af in done("AmericaAirfield"):
            if ready(af) and nn("VehicleComanche") < 4 and spend > 2500:
                if await train(af, "AmericaVehicleComanche"):
                    mark(af, 25)
        for tpl, up in UPGRADES:
            if up in self.done_upgrades or up in self.bad_upgrade:
                continue
            b = done(tpl)
            if b and spend > 2500:
                try:
                    await self.c.upgrade(b[0]["id"], up)
                    self.done_upgrades.add(up)
                    log("UPGRADE", up)
                    spend -= 1500
                except ApiError as e:
                    log("upgrade err", up, e.code, e.message)
                    if e.code in ("NOT_AVAILABLE", "INVALID_ARGUMENT"):
                        self.bad_upgrade.add(up)

        for u in structs:
            if (u["template"] in ("AmericaBarracks", "AmericaWarFactory", "AmericaAirfield") and u["id"] not in self.rallied
                    and "under_construction" not in u["status"]):
                try:
                    await self.c.set_rally_point(u["id"], STAGE)
                    self.rallied.add(u["id"])
                except ApiError as e:
                    log("rally err", e)

        await self.powers(cc, vis)
        for up in done("AmericaParticleCannonUplink"):
            if self.frame - getattr(self, "last_pc", -99999) > 20 * FPS and known:
                order = ["AmericaWarFactory", "AmericaStrategyCenter", "AmericaCommandCenter", "AmericaBarracks",
                         "AmericaSupplyCenter", "AmericaAirfield", "AmericaPatriotBattery", "AmericaPowerPlant"]
                ks = sorted(known, key=lambda o: order.index(o["template"]) if o["template"] in order else 99)
                try:
                    await self.c.use_ability([up["id"]], "Command_FireParticleUplinkCannon", pos=ks[0]["pos"][:2])
                    log("PARTICLE CANNON at", ks[0]["template"], [round(x) for x in ks[0]["pos"][:2]])
                except ApiError as e:
                    if e.code != "NOT_AVAILABLE" or self.frame % 900 < 60:
                        log("pc err", e.code, e.message)
                self.last_pc = self.frame
        for scn in done("AmericaStrategyCenter"):
            if not getattr(self, "plan_set", False):
                try:
                    await self.c.use_ability([scn["id"]], "Command_InitiateBattlePlanSearchAndDestroy")
                    log("BATTLEPLAN search and destroy")
                    self.plan_set = True
                except ApiError as e:
                    log("battleplan err", e.code, e.message)
                    self.plan_set = True

        # ---- army control
        ids = [u["id"] for u in army]
        threats = [o for o in vis if min((d(o["pos"], st["pos"]) for st in structs), default=9e9) < 420 and o["pos"][1] < 1250]
        if threats:
            tgt = min(threats, key=lambda o: d(o["pos"], HOME))
            home_army = [u["id"] for u in army if d(u["pos"], HOME) < 1100 or not self.attacking or len(threats) >= 4]
            if home_army and (not self.defending or self.frame - self.last_attack_order > 150):
                await self.order(home_army, tgt["pos"])
                self.last_attack_order = self.frame
                log("DEFEND vs", len(threats), [short(o["template"]) for o in threats][:6], "at",
                    [round(x) for x in tgt["pos"][:2]], "with", len(home_army))
            self.defending = True
            return
        self.defending = False
        if self.attacking:
            wave = [u for u in army if u["id"] in self.wave_ids]
            if len(wave) < max(3, self.wave_start // 3):
                self.attacking = False
                log("attack over, retreat with", len(wave))
                if wave:
                    await self.order([u["id"] for u in wave], STAGE, move=True)
                self.wave_size = min(self.wave_size + 2, 22)
            elif self.frame - self.last_attack_order > 10 * FPS:
                cx = sum(u["pos"][0] for u in wave) / len(wave)
                cy = sum(u["pos"][1] for u in wave) / len(wave)
                cen = (cx, cy)
                vunits = [o for o in vis if o["template"] not in self.cost or o["template"] in UNIT_T]
                vunits = [o for o in vunits if "Chinook" not in o["template"] and d(o["pos"], cen) < 600]
                vst = [o for o in vis if o["template"] in self.cost and o["template"] not in UNIT_T and d(o["pos"], cen) < 900]
                if vunits or not vst:
                    tgt = min(vunits, key=lambda o: d(o["pos"], cen))["pos"] if vunits else self.pick_target(known, vis)
                    await self.order([u["id"] for u in wave], tgt)
                    log("ATTACK", len(wave), "->", [round(x) for x in tgt[:2]], "money", me["money"])
                else:
                    pri = ["AmericaPatriotBattery", "AmericaFireBase", "AmericaWarFactory", "AmericaBarracks",
                           "AmericaCommandCenter", "AmericaAirfield", "AmericaStrategyCenter", "AmericaSupplyCenter",
                           "AmericaParticleCannonUplink", "AmericaSupplyDropZone", "AmericaPowerPlant"]
                    vst.sort(key=lambda o: (pri.index(o["template"]) if o["template"] in pri else 50, d(o["pos"], cen)))
                    ids = [u["id"] for u in wave]
                    # split: two thirds on the top target, rest on the second
                    t1 = vst[0]
                    t2 = vst[1] if len(vst) > 1 else vst[0]
                    k = max(1, (2 * len(ids)) // 3)
                    for grp, t in ((ids[:k], t1), (ids[k:], t2)):
                        if not grp:
                            continue
                        try:
                            await self.c.attack(grp, t["id"])
                        except ApiError as e:
                            log("attack err", e.code, e.message)
                    log("SIEGE", len(ids), "->", short(t1["template"]), short(t2["template"]))
                self.last_attack_order = self.frame
        if not self.attacking:
            home = [u for u in army if u["id"] not in self.wave_ids or not self.attacking]
            if len(home) >= self.wave_size:
                self.attacking = True
                self.wave_ids = {u["id"] for u in home}
                self.wave_start = len(home)
                tgt = self.pick_target(known, vis)
                await self.order([u["id"] for u in home], tgt)
                self.last_attack_order = self.frame
                log("WAVE", len(home), "->", [round(x) for x in tgt[:2]])
            elif self.frame - self.last_home_order > 30 * FPS:
                far = [u["id"] for u in home if d(u["pos"], STAGE) > 350]
                if far:
                    await self.order(far, STAGE)
                self.last_home_order = self.frame

    async def chinooks(self, by, allvis, vis):
        if not hasattr(self, "chin_last"):
            self.chin_last, self.chin_idle, self.chin_order = {}, {}, {}
        sources = [o for o in allvis if o["template"] in ("SupplyPileSmall", "WaterfrontWherehouse01")
                   and o["id"] not in getattr(self, "dead_sources", set())]
        scs = [u for u in by.get("AmericaSupplyCenter", []) if "under_construction" not in u["status"]]
        for ch in by.get("AmericaVehicleChinook", []):
            last = self.chin_last.get(ch["id"])
            self.chin_last[ch["id"]] = ch["pos"]
            if last is not None and d(last, ch["pos"]) < 3 and any(d(ch["pos"], sc["pos"]) < 220 for sc in scs):
                self.chin_idle[ch["id"]] = self.chin_idle.get(ch["id"], 0) + 1
            else:
                self.chin_idle[ch["id"]] = 0
            if self.chin_idle[ch["id"]] < 4 or not sources or not scs:
                continue
            if self.frame - self.chin_order.get(ch["id"], -9999) < 40 * FPS:
                continue
            safe = [o for o in sources if all(d(o["pos"], e["pos"]) > 350 for e in vis)]
            if not safe:
                continue
            tgt = min(safe, key=lambda o: min(d(o["pos"], sc["pos"]) for sc in scs) + 0.3 * d(o["pos"], ch["pos"]))
            try:
                await self.c.dock([ch["id"]], tgt["id"])
                log("DOCK chinook", ch["id"], "->", tgt["template"], [round(x) for x in tgt["pos"][:2]])
            except ApiError as e:
                log("dock err", e.code, e.message)
                self.dead_sources = getattr(self, "dead_sources", set()) | {tgt["id"]}
            self.chin_order[ch["id"]] = self.frame

    def pick_target(self, known, vis):
        cand = [o["pos"] for o in known] + [o["pos"] for o in vis]
        if cand:
            return min(cand, key=lambda p: d(p, HOME))
        return ENEMY

    async def order(self, ids, pos, move=False):
        for i in range(0, len(ids), 30):
            try:
                if move:
                    await self.c.move(ids[i:i + 30], pos[:2])
                else:
                    await self.c.attack_move(ids[i:i + 30], pos[:2])
            except ApiError as e:
                log("order err", e.code, e.message)

    async def powers(self, cc, vis):
        if not cc or not vis or not self.sciences_owned:
            return
        if self.frame - self.last_power < 30 * FPS:
            return
        best = max(vis, key=lambda o: sum(1 for p in vis if d(p["pos"], o["pos"]) < 200))
        for ab, key in (("Command_A10ThunderboltMissileStrike", "A10"), ("Command_SpectreGunship", "Spectre"),
                        ("Command_DaisyCutter", "DaisyCutter")):
            if not any(key in x for x in self.sciences_owned):
                continue
            try:
                await self.c.use_ability([cc[0]["id"]], ab, pos=best["pos"][:2])
                log("POWER", ab, "at", [round(x) for x in best["pos"][:2]], best["template"])
                self.last_power = self.frame
                return
            except ApiError:
                pass


async def main():
    c = await GeneralsClient(URL, request_timeout=30).connect()
    await c.hello()
    bot = Bot(c)
    cat = await c.catalog()
    for e in cat["structures"] + cat["units"]:
        bot.cost[e["name"]] = e["cost"]
        bot.prereq[e["name"]] = e.get("prerequisites", [])
    for e in cat["units"]:
        UNIT_T.add(e["name"])

    def on_over(ev):
        log("GAME OVER", ev)
        bot.over = True

    c.on("game_over", on_over)
    c.on("eva", lambda ev: log("eva", ev.get("message") or ev.get("type") or ev))
    c.on("unit_destroyed", lambda ev: log("lost", ev.get("template"), ev.get("id")) if "America" in str(ev.get("template")) else None)
    c.on("enemy_destroyed", lambda ev: DEAD.add(ev.get("id")))
    c.on("enemy_destroyed", lambda ev: log("killed", ev.get("template")) if "America" in str(ev.get("template")) else None)
    deadline = time.time() + float(sys.argv[1] if len(sys.argv) > 1 else 3600)
    n = 0
    while not bot.over and time.time() < deadline:
        try:
            await bot.tick()
        except ApiError as e:
            log("tick ApiError", e)
        except Exception as e:
            log("tick exception", repr(e))
            log(traceback.format_exc())
            if c._closed.is_set():
                break
        n += 1
        if n % 15 == 0:
            try:
                s = await c.state()
                tl = {}
                for u in s["units"]:
                    tl[short(u["template"])] = tl.get(short(u["template"]), 0) + 1
                log("STATUS f", s["frame"], "money", s["self"]["money"], "power", s["self"]["power"],
                    "rank", s["self"]["rank"], tl,
                    "vis", len([o for o in s["visible"] if o.get("owner") == ENEMY_IDX]),
                    "known", sorted((short(o["template"]), round(o["pos"][0]), round(o["pos"][1])) for o in s["known_structures"] if o.get("owner") == ENEMY_IDX))
            except Exception as e:
                log("status err", repr(e))
        await asyncio.sleep(2)
    log("exiting; over=", bot.over)
    await c.close()


asyncio.run(main())
