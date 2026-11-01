"""Delta macro bot (America). Power, supply, barracks, war factory, then waves of Rangers and Crusaders.

Run:  python.exe macro.py ws://127.0.0.1:PORT   (logs to ../reports/macro.log)
"""
import asyncio, math, sys, time, traceback
sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, World, ApiError

LOG = r"C:\Users\user\Documents\CNC_Generals_AI\tournament\t1\agents\Delta\reports\macro.log"
WAVE_INF, WAVE_TANK = 5, 2

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

def mine(snap, suffix):
    return [u for u in snap["units"] if u["template"].endswith(suffix) and u.get("contained_by") is None]

async def place(client, builder, template, near):
    for radius in (250, 350, 450, 550):
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
                if err.code != "ILLEGAL_LOCATION":
                    return None
            except asyncio.TimeoutError:
                log(f"no construction_started for {template} at {pos}")
            finally:
                started.cancel()
    return None

async def build(client, builder, template, near):
    b = await place(client, builder, template, near)
    if b is not None:
        try:
            await client.wait_for_event("construction_complete", lambda e: e["id"] == b, timeout=240)
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
            rows = [(u["template"], u.get("status"), u.get("health")) for u in snap["units"]]
            log(f"status money={world.money} units={rows}")
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
    log(f"start home={home} enemy={enemy_start} dozer={dozer} money={world.money}")
    asyncio.ensure_future(status_loop(client, world))

    # The War Factory needs a Supply Center first (NOT_AVAILABLE otherwise), so build it after the Supply Center.
    def have(suffix):
        return next((u["id"] for u in snap["units"] if u["template"].endswith(suffix)), None)
    if "--resume" in sys.argv:
        # Reuse buildings from an earlier run of this bot instead of rebuilding them.
        power, barracks, supply, factory = (have("AmericaPowerPlant"), have("AmericaBarracks"),
                                            have("AmericaSupplyCenter"), have("AmericaWarFactory"))
    else:
        power = await build(client, dozer, "AmericaPowerPlant", home)
        barracks = await build(client, dozer, "AmericaBarracks", home)
        supply = await build(client, dozer, "AmericaSupplyCenter", home)
        factory = None
    if factory is None and supply is not None:
        factory = await build(client, dozer, "AmericaWarFactory", home)
    if barracks is not None:
        await client.set_rally_point(barracks, home)
    if factory is not None:
        await client.set_rally_point(factory, home)
    log(f"done build: power={power} barracks={barracks} factory={factory} supply={supply}")

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
        await asyncio.sleep(30)
        snap = await client.state()
        world.apply_snapshot(snap)
        army = [u["id"] for u in snap["units"] if u["template"].endswith(("InfantryRanger", "TankCrusader"))
                and u.get("contained_by") is None]
        if army:
            await client.attack_move(army, enemy_start)
            log(f"attack-move {len(army)} units to {enemy_start} money={world.money}")

if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1]))  # add --resume to reuse existing buildings
    except Exception:
        log("CRASH " + traceback.format_exc())
        raise
