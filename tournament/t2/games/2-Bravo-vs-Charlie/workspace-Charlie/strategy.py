"""Charlie strategy (China). Reloaded live by bot.py; keep tick() cheap and idempotent.

Template names are matched by suffix so general variants (Tank_China...) work too.
"""
from __future__ import annotations

import math

from generals_api import ApiError

P = ""  # prefix detection is done by suffix matching


def ends(u, suffix):
    return u["template"].endswith(suffix)


def mine(world, suffix, built=True):
    out = []
    for u in world.units.values():
        if ends(u, suffix) and u.get("contained_by") is None:
            if built and "under_construction" in u.get("status", []):
                continue
            out.append(u)
    return out


def dist(a, b):
    return math.dist(a[:2], b[:2])


def name_for(world, suffix):
    for t in world.catalog["structures"] + world.catalog["units"]:
        if t["name"].endswith(suffix):
            return t["name"]
    return suffix


def catalog_entry(world, suffix):
    for t in world.catalog["structures"] + world.catalog["units"]:
        if t["name"].endswith(suffix):
            return t
    return None


COMBAT_SUFFIXES = ("TankBattleMaster", "TankGattling", "TankDragon", "TankOverlord", "VehicleInfernoCannon",
                   "InfantryRedguard", "InfantryTankHunter", "VehicleTroopCrawler", "TankECM")


def army(world):
    return [u for u in world.units.values() if any(ends(u, s) for s in COMBAT_SUFFIXES)
            and u.get("contained_by") is None]


async def try_build(client, world, dozer, suffix, near, memory, log, radii=(220, 320, 420, 520, 650)):
    """Try a ring of spots around `near`. Returns True when the order was accepted."""
    template = name_for(world, suffix)
    for radius in radii:
        for step in range(12):
            ang = step * math.pi / 6 + (radius / 100.0)
            pos = (near[0] + radius * math.cos(ang), near[1] + radius * math.sin(ang))
            ext = world.game_info["map"]["extent"]
            if not (ext["min"][0] + 60 < pos[0] < ext["max"][0] - 60 and ext["min"][1] + 60 < pos[1] < ext["max"][1] - 60):
                continue
            try:
                await client.build(dozer["id"], template, pos)
                log("build", template, "at", [int(pos[0]), int(pos[1])], "dozer", dozer["id"])
                memory.setdefault("pending", {})[template] = world.frame
                return True
            except ApiError as e:
                if e.code == "ILLEGAL_LOCATION":
                    continue
                log("build refused", template, e.code, e)
                return False
    log("no spot for", template)
    return False


def supply_sources(world):
    return [o for o in world.visible.values() if "SUPPLY_SOURCE" in world.kinds(o["template"]) and o.get("supply", 1) > 0]


async def tick(client, world, settings, memory, log):
    gi = world.game_info
    units = world.units
    if not units:
        return
    hq = next((u for u in units.values() if ends(u, "CommandCenter")), None)
    home = hq["pos"] if hq else next(iter(units.values()))["pos"]
    if "home" not in memory:
        memory["home"] = home
        memory["enemy_start"] = max(gi["start_positions"], key=lambda p: dist(p, home))
    home = memory["home"]
    enemy_start = memory["enemy_start"]
    money = world.money or 0
    frame = world.frame
    if frame - memory.get("beat", -9999) > 30 * 30:
        memory["beat"] = frame
        log(f"beat frame {frame} money {money} army {len(army(world))} enemies {len(world.enemies())}")

    # Forget pending builds after 15 s so a failed build gets retried.
    pending = memory.setdefault("pending", {})
    for k in list(pending):
        if frame - pending[k] > 30 * 15:
            del pending[k]

    def have(suffix, built=True):
        return len(mine(world, suffix, built))

    def have_name(name):
        return any(u["template"] == name and "under_construction" not in u.get("status", [])
                   for u in units.values())

    def planned(suffix):
        return have(suffix, built=False) + (1 if name_for(world, suffix) in pending else 0)

    dozers = mine(world, "VehicleDozer")
    idle_dozers = [d for d in dozers if "idle" in d.get("status", [])]

    # 1. Dozers: keep settings["dozers"] of them.
    want_dozers = int(settings.get("dozers", 2))
    if hq and planned("VehicleDozer") < want_dozers and money >= 1000 and frame - memory.get("dozer_ordered", -9999) > 30 * 25:
        try:
            await client.train(hq["id"], name_for(world, "VehicleDozer"))
            memory["dozer_ordered"] = frame
            log("train dozer")
        except ApiError as e:
            log("dozer refused", e.code)

    # 2. Build order: list of [suffix, count]. Build the first missing one with an idle dozer.
    order = settings.get("build_order", [["PowerPlant", 1], ["SupplyCenter", 1], ["WarFactory", 1],
                                         ["Barracks", 1], ["PowerPlant", 2], ["WarFactory", 2]])
    # Remember supply sources: they leave `visible` when out of sight, but their ids stay valid.
    remembered = memory.setdefault("sources", {})
    for src in supply_sources(world):
        remembered[src["id"]] = src
    for o in world.visible.values():
        if o["id"] in remembered and o.get("supply", 1) <= 0:
            remembered.pop(o["id"], None)
    sources = list(remembered.values())
    memory["saving"] = 0
    if idle_dozers:
        for suffix, count in order:
            if planned(suffix) >= count:
                continue
            entry = catalog_entry(world, suffix)
            if entry is None:
                break
            if suffix == "SupplyCenter" and planned(suffix) >= 1:
                # A second center only once the source(s) next to the existing centers are nearly dry.
                rich = [s for s in sources if s.get("supply", 0) > 6000
                        and any(dist(s["pos"], c["pos"]) < 600 for c in mine(world, "SupplyCenter", built=False))]
                if rich:
                    continue
            # catalog["available_now"] is stale (loaded once), so check prerequisites ourselves.
            prereqs = entry.get("prerequisites") or []
            if not all(any(have_name(n) for n in group) for group in prereqs):
                break  # prerequisites not met yet; wait
            if money < entry["cost"]:
                memory["saving"] = entry["cost"]  # production waits so the build order is not starved
                break
            near = home
            if suffix in ("GattlingCannon", "Bunker"):
                fwd = 1 if enemy_start[1] > home[1] else -1
                near = (home[0] - 120, home[1] + fwd * 230)
                radii = (0, 60, 120, 180, 240)
            elif suffix == "SupplyCenter" and (sources or settings.get("supply_hints")):
                if sources:
                    near = min(sources, key=lambda s: dist(s["pos"], home))["pos"]
                else:  # docks not in sight yet: use the map hint nearest to home (settings.json)
                    near = min(settings.get("supply_hints"), key=lambda p: dist(p, home))
                radii = (180, 240, 300, 380)
            elif suffix not in ("GattlingCannon", "Bunker"):
                radii = (220, 320, 420, 520, 650)
            dozer = min(idle_dozers, key=lambda d: dist(d["pos"], near))
            await try_build(client, world, dozer, suffix, near, memory, log, radii)
            break

    # 2b. Idle dozers repair damaged structures.
    if len(idle_dozers) > 1 or (idle_dozers and planned("WarFactory") >= 1):
        damaged = [u for u in units.values() if "STRUCTURE" in world.kinds(u["template"])
                   and u["health"] < 0.6 * u["max_health"] and "under_construction" not in u.get("status", [])]
        if damaged:
            d = idle_dozers[-1]
            try:
                await client.repair(d["id"], damaged[0]["id"])
            except ApiError:
                pass

    # 3. Supply trucks: keep N per supply center, dock idle ones.
    centers = mine(world, "SupplyCenter")
    trucks = mine(world, "VehicleSupplyTruck")
    want_trucks = int(settings.get("trucks_per_center", 3)) * len(centers)
    if centers and len(trucks) < want_trucks and money >= 600 and frame - memory.get("truck_ordered", -9999) > 30 * 8:
        try:
            await client.train(centers[0]["id"], name_for(world, "VehicleSupplyTruck"))
            memory["truck_ordered"] = frame
            log("train truck")
        except ApiError as e:
            log("truck refused", e.code)
    for t in trucks:
        if "idle" not in t.get("status", []):
            continue
        if sources:
            # Prefer the richest source near home (the main SupplyDock, ~40000) over small mid-map piles (3750).
            close = [s for s in sources if dist(s["pos"], home) < 900]
            src = max(close, key=lambda s: s.get("supply", 0)) if close else min(sources, key=lambda s: dist(s["pos"], t["pos"]))
            try:
                await client.dock([t["id"]], src["id"])
            except ApiError as e:
                log("dock refused", e.code)
                if e.code in ("NOT_AVAILABLE", "NOT_VISIBLE", "NOT_FOUND"):
                    remembered.pop(src["id"], None)
        else:
            # No dock seen yet: scout a ring around the base with the idle truck.
            i = memory.get("scout_i", 0)
            memory["scout_i"] = i + 1
            ang = i * math.pi / 4
            r = 600 + 250 * (i // 8)
            pos = (home[0] + r * math.cos(ang), home[1] + r * math.sin(ang))
            ext = world.game_info["map"]["extent"]
            pos = (min(max(pos[0], ext["min"][0] + 50), ext["max"][0] - 50), min(max(pos[1], ext["min"][1] + 50), ext["max"][1] - 50))
            try:
                await client.move([t["id"]], pos)
                log("scout truck ->", [int(pos[0]), int(pos[1])])
            except ApiError as e:
                log("scout refused", e.code)

    # 4. Production: war factories pump tanks; barracks a few tank hunters.
    reserve = max(int(settings.get("reserve", 0)), int(memory.get("saving", 0)))
    mix = settings.get("tank_mix", ["TankBattleMaster", "TankBattleMaster", "TankGattling"])
    for wf in mine(world, "WarFactory"):
        if money - reserve < 800:
            break
        key = f"wf_{wf['id']}"
        if frame - memory.get(key, -9999) < 30 * 6:
            continue
        i = memory.get("mix_i", 0)
        suffix = mix[i % len(mix)]
        try:
            await client.train(wf["id"], name_for(world, suffix))
            memory[key] = frame
            memory["mix_i"] = i + 1
            money -= 800
            log("train", suffix)
        except ApiError as e:
            log("train refused", suffix, e.code)
            memory[key] = frame
    for br in mine(world, "Barracks"):
        if have("InfantryTankHunter") + have("InfantryRedguard") < int(settings.get("infantry", 4)) and money - reserve >= 300:
            key = f"br_{br['id']}"
            if frame - memory.get(key, -9999) < 30 * 6:
                continue
            try:
                await client.train(br["id"], name_for(world, "InfantryTankHunter"))
                memory[key] = frame
            except ApiError as e:
                memory[key] = frame
        if "rally" not in memory:
            try:
                await client.set_rally_point(br["id"], (home[0], home[1] + (200 if enemy_start[1] > home[1] else -200)))
                memory["rally"] = True
            except ApiError:
                pass

    # 5. Army control.
    # Auto-scout (game 2 lesson): once the army is big and no enemy has shown up, walk one Gattling tank toward the enemy
    # base along the mid-map piles. It is excluded from the army logic. If it sees an enemy base with no defensive
    # structures, release the hold automatically.
    full = army(world)
    excl = set(settings.get("exclude", []))
    scout_at = int(settings.get("scout_at", 12))
    if settings.get("hold") and len(full) >= scout_at and not memory.get("released"):
        sid = memory.get("scout")
        if sid is not None and sid not in units:
            sid = None
        if sid is None:
            gats = [u for u in full if ends(u, "TankGattling")]
            if gats and frame - memory.get("scout_sent", -99999) > 30 * 60:
                sid = gats[0]["id"]
                memory["scout"] = sid
                memory["scout_wp"] = 0
                memory["scout_sent"] = frame
        if sid is not None:
            excl.add(sid)
            mid = ((home[0] + enemy_start[0]) / 2, (home[1] + enemy_start[1]) / 2)
            wps = [mid, ((mid[0] + enemy_start[0]) / 2, (mid[1] + enemy_start[1]) / 2 + (0 if enemy_start[1] < home[1] else 0)),
                   enemy_start]
            wp = memory.get("scout_wp", 0)
            su = units[sid]
            if wp < len(wps) and frame - memory.get("scout_move", -99999) > 30 * 12:
                if dist(su["pos"], wps[wp]) < 120:
                    memory["scout_wp"] = wp = wp + 1
                if wp < len(wps):
                    try:
                        await client.move([sid], wps[wp])
                        memory["scout_move"] = frame
                    except ApiError:
                        pass
            es = world.enemy_structures()
            defensive = [o for o in es if any(k in o["template"] for k in ("GattlingCannon", "Bunker", "Patriot", "Stinger", "Tunnel", "FireBase"))]
            etanks = [o for o in world.enemies() if "STRUCTURE" not in world.kinds(o["template"]) and "Tank" in o["template"]]
            if es and not defensive and len(etanks) * 2 < len(full) and len(full) >= int(settings.get("attack_size", 14)):
                memory["released"] = True
                settings["hold"] = False
                log("AUTO-RELEASE: enemy base seen without defenses, tanks", len(etanks), "vs mine", len(full))
    if memory.get("released"):
        settings["hold"] = False
    troops = [u for u in full if u["id"] not in excl]
    ids = [u["id"] for u in troops]
    attack_size = int(settings.get("attack_size", 8))
    structures = [u for u in units.values() if "STRUCTURE" in world.kinds(u["template"])]
    # Only real enemy units (owner is an enemy player); `visible` also holds neutral junk such as CarScrap.
    drad = float(settings.get("defend_radius", 550))
    threats = [o for o in world.enemies() if "STRUCTURE" not in world.kinds(o["template"])
               and any(dist(o["pos"], s["pos"]) < drad for s in structures)]
    threats.sort(key=lambda o: dist(o["pos"], home))
    rally = (home[0] - 60, home[1] + (260 if enemy_start[1] > home[1] else -260))
    if settings.get("rally"):
        rally = tuple(settings["rally"])
    # Regroup at home once the base is clear, so the army does not chase retreating raiders across the map.
    if not threats and ids and not memory.get("attacking") and frame - memory.get("defend", -9999) > 30 * 12             and frame - memory.get("clear", -9999) > 30 * 40 and frame - memory.get("regroup", -9999) > 30 * 20:
        away = [u["id"] for u in troops if dist(u["pos"], rally) > 350]
        if away:
            memory["regroup"] = frame
            try:
                await client.move(away, rally)
                log("regroup", len(away), "units")
            except ApiError as e:
                log("regroup refused", e.code)
    # Don't let small harassers interrupt an attack on a forward structure for 15 s after it was ordered.
    if threats and ids and frame - memory.get("defend", -9999) > 30 * 10 and frame - memory.get("clear", -9999) > 30 * 15:
        target = threats[0]
        try:
            # Defend with tanks only when the threat is close to my buildings; pull back out of enemy defenses' range.
            tp = target["pos"]
            if dist(tp, home) > 380:  # stay under the Gattling Cannons; never run after raiders
                k = 380 / dist(tp, home)
                tp = (home[0] + (tp[0] - home[0]) * k, home[1] + (tp[1] - home[1]) * k)
            await client.attack_move(ids, tp)
            memory["defend"] = frame
            log("defend vs", target["template"], "with", len(ids))
        except ApiError as e:
            log("defend refused", e.code)
        return

    # Enemy structures built near my base (forward defenses, e.g. Patriot Battery): attack them explicitly.
    near_structs = [o for o in world.enemy_structures()
                    if any(dist(o["pos"], s["pos"]) < 900 for s in structures)]
    # Only with a full wave (piecemeal attacks on a Patriot lost 3 tanks in practice), unless it sits right on top of my base.
    urgent = [o for o in near_structs if any(dist(o["pos"], s["pos"]) < 350 for s in structures)]
    clear_size = int(settings.get("clear_size", attack_size))
    if near_structs and not settings.get("hold") and (len(ids) >= clear_size or (urgent and len(ids) >= 5)) and frame - memory.get("clear", -9999) > 30 * 10:
        near_structs = urgent or near_structs
        t = min(near_structs, key=lambda o: dist(o["pos"], home))
        guards = [o for o in world.enemies() if "STRUCTURE" not in world.kinds(o["template"])
                  and dist(o["pos"], t["pos"]) < 450]
        try:
            if t.get("visible") and len(guards) < 4:
                await client.attack(ids, t["id"])
            else:  # fogged (attack refused with NOT_VISIBLE) or guarded: attack-move so the tanks shoot the guards first
                await client.attack_move(ids, t["pos"])
            memory["clear"] = frame
            log("clear forward structure", t["template"], "with", len(ids))
        except ApiError as e:
            log("clear refused", e.code)
        return

    attacking = memory.get("attacking", False)
    if settings.get("hold"):
        if attacking:
            memory["attacking"] = False
            log("hold: cancel attack, army home")
            if ids:
                try:
                    await client.attack_move(ids, rally)
                except ApiError:
                    pass
        return
    if not attacking and len(ids) >= attack_size:
        memory["attacking"] = True
        memory["attack_frame"] = frame
        try:
            await client.attack_move(ids, enemy_start)
            log("ATTACK with", len(ids))
        except ApiError as e:
            log("attack refused", e.code)
    elif attacking:
        if len(ids) < max(2, attack_size // 2):
            memory["attacking"] = False
            log("retreat: army too small", len(ids))
            if ids:
                try:
                    await client.move(ids, home)
                except ApiError:
                    pass
            return
        if frame - memory.get("attack_frame", 0) > 30 * 10:
            memory["attack_frame"] = frame
            idle_ids = [u["id"] for u in troops if "idle" in u.get("status", [])]
            known = world.enemy_structures()
            enemy_units = [o for o in world.enemies() if "STRUCTURE" not in world.kinds(o["template"])]
            if idle_ids:
                try:
                    if enemy_units:
                        t = min(enemy_units, key=lambda o: dist(o["pos"], troops[0]["pos"]))
                        await client.attack_move(idle_ids, t["pos"])
                    elif known:
                        t = min(known, key=lambda o: dist(o["pos"], troops[0]["pos"]))
                        if t.get("visible"):
                            await client.attack(idle_ids, t["id"])
                        else:
                            await client.attack_move(idle_ids, t["pos"])
                        log("attack structure", t["template"], "visible" if t.get("visible") else "fogged")
                    else:
                        await client.attack_move(idle_ids, enemy_start)
                except ApiError as e:
                    log("re-attack refused", e.code)
            # Reinforcements at home join in.
            fresh = [u["id"] for u in troops if dist(u["pos"], home) < 600 and "idle" in u.get("status", [])]
            if fresh:
                try:
                    await client.attack_move(fresh, enemy_start)
                except ApiError:
                    pass
