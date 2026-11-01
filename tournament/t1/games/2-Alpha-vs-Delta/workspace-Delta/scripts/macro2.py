"""Delta macro v2 (America). Power, barracks, supply center at the dock (income), war factory, 2nd power, then waves.

Run:  python.exe macro2.py ws://127.0.0.1:55157   (log: ../reports/macro2.log)
"""
import asyncio, math, sys, time, traceback
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, World, ApiError

LOG = r"C:\Users\user\Documents\CNC_Generals_AI\tournament\t1\agents\Delta\reports\macro2.log"
DOCK = (633.0, 127.0)
WAVE_INF, WAVE_TANK = 5, 2
ATTACK_MIN = 8

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

def mine(snap, suffix):
    return [u for u in snap["units"] if u["template"].endswith(suffix) and u.get("contained_by") is None]

async def place(client, builder, template, near, radii=(250, 350, 450, 550)):
    for radius in radii:
        for step in range(12):
            a = step * math.pi / 6
            pos = (near[0] + radius * math.cos(a), near[1] + radius * math.sin(a))
            started = asyncio.ensure_future(client.wait_for_event(
                "construction_started", lambda e, t=template: e["template"].endswith(t), timeout=30))
            try:
                reply = await client.build(builder, template, pos)
                log(f"build {template} at {pos} accepted: {reply}")
                ev = await started
                log(f"construction_started {template} id={ev['id']}")
                return ev["id"]
            except ApiError as err:
                log(f"build {template} refused {err.code}: {err}")
                if err.code not in ("ILLEGAL_LOCATION",):
                    return None
            except asyncio.TimeoutError:
                log(f"no construction_started for {template} at {pos}")
            finally:
                started.cancel()
    return None

async def build(client, builder, template, near, radii=(250, 350, 450, 550)):
    b = await place(client, builder, template, near, radii)
    if b is not None:
        try:
            await client.wait_for_event("construction_complete", lambda e: e["id"] == b, timeout=300)
            log(f"built {template} id={b}")
        except asyncio.TimeoutError:
            log(f"construction_complete timeout for {template} id={b}")
    return b

async def status_loop(client, world):
    while True:
        await asyncio.sleep(10)
        try:
            snap = await client.state()
            world.apply_snapshot(snap)
            rows = [(u["template"][7:], (u.get("status") or [""])[0], int(u.get("health") or 0)) for u in snap["units"] if u.get("contained_by") is None]
            log(f"status money={world.money} power={snap.get('self',{}).get('power')} units={rows}")
        except Exception as err:
            log(f"status error {err!r}")

async def main(url):
    client = await GeneralsClient(url, request_timeout=60).connect()
    await client.hello()
    world = await World().load(client)
    world.attach(client)
    info = world.game_info
    snap = await client.state()
    hq = next(u for u in snap["units"] if u["template"].endswith("CommandCenter"))
    home = hq["pos"][:2]
    enemy_start = max(info["start_positions"], key=lambda p: math.dist(p, home))
    dozer = mine(snap, "VehicleDozer")[0]["id"]
    # Supply center point: 150 units from the dock toward home.
    d = math.dist(DOCK, home); sc_near = (DOCK[0] + 150 * (home[0]-DOCK[0]) / d, DOCK[1] + 150 * (home[1]-DOCK[1]) / d)
    log(f"start home={home} enemy={enemy_start} dozer={dozer} money={world.money} sc_near={sc_near}")
    asyncio.ensure_future(status_loop(client, world))

    def have(suffix):
        return next((u["id"] for u in snap["units"] if u["template"].endswith(suffix)), None)
    # Resume: reuse buildings already placed (run 2 placed power + barracks before the supply spot failed).
    power = have("AmericaPowerPlant") or await build(client, dozer, "AmericaPowerPlant", home)
    barracks = have("AmericaBarracks") or await build(client, dozer, "AmericaBarracks", home)
    supply = have("AmericaSupplyCenter")
    if supply is None:
        # The dock area is in shroud (unexplored), so build the supply center next to home instead.
        supply = await build(client, dozer, "AmericaSupplyCenter", home)
    factory = have("AmericaWarFactory")
    if supply is not None and factory is None:
        # The War Factory needs a finished Supply Center: wait for it, then retry on NOT_AVAILABLE.
        sc = next((u for u in snap["units"] if u["id"] == supply), None)
        if sc is not None and sc.get("status") and "under_construction" in sc["status"]:
            try:
                await client.wait_for_event("construction_complete", lambda e: e["id"] == supply, timeout=300)
                log(f"supply center {supply} complete")
            except asyncio.TimeoutError:
                log(f"supply center {supply} not complete after 300s")
        else:
            log(f"supply center {supply} already complete")
        for _ in range(20):
            factory = await build(client, dozer, "AmericaWarFactory", home)
            if factory is not None:
                break
            await asyncio.sleep(5)
    power2 = await build(client, dozer, "AmericaPowerPlant", home) if factory and not have("AmericaPowerPlant") is None and False else None
    if barracks is not None:
        await client.set_rally_point(barracks, home)
    if factory is not None:
        await client.set_rally_point(factory, home)
    log(f"done build: power={power} barracks={barracks} factory={factory} supply={supply} power2={power2}")

    while True:
        try:
            if barracks is not None:
                await client.train(barracks, "AmericaInfantryRanger", count=WAVE_INF)
        except ApiError as err:
            log(f"train ranger refused {err.code}: {err}")
        try:
            if factory is not None:
                await client.train(factory, "AmericaTankCrusader", count=WAVE_TANK)
        except ApiError as err:
            log(f"train crusader refused {err.code}: {err}")
        await asyncio.sleep(25)
        snap = await client.state()
        world.apply_snapshot(snap)
        army = [u["id"] for u in snap["units"] if u["template"].endswith(("InfantryRanger", "TankCrusader"))
                and u.get("contained_by") is None]
        if len(army) >= ATTACK_MIN:
            await client.attack_move(army, enemy_start)
            log(f"attack-move {len(army)} units to {enemy_start} money={world.money}")

if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1]))
    except Exception:
        log("CRASH " + traceback.format_exc())
        raise
