"""Reference bot: builds power and a barracks, then sends waves of infantry at the enemy start.

Run it with the launcher:  python -m generals_api.launcher --bot1 bots/simple.py --vs-ai easy
"""

from __future__ import annotations

import asyncio
import math

from generals_api import ApiError, GeneralsClient, World

# Templates of the three base factions: builder, power, barracks, infantry. Any faction works.
SIDES = {
    "America": ("AmericaVehicleDozer", "AmericaPowerPlant", "AmericaBarracks", "AmericaInfantryRanger"),
    "China": ("ChinaVehicleDozer", "ChinaPowerPlant", "ChinaBarracks", "ChinaInfantryRedguard"),
    "GLA": ("GLAInfantryWorker", None, "GLABarracks", "GLAInfantryRebel"),
}
WAVE = 5


def mine(snapshot: dict, suffix: str) -> list[dict]:
    """Own units whose template ends with `suffix` (so general variants such as AirF_ match too)."""
    return [u for u in snapshot["units"] if u["template"].endswith(suffix)]


async def place(client: GeneralsClient, builder: int, template: str, near) -> int | None:
    """Starts a building on the first legal spot around `near`; returns its id."""
    for radius in (250, 350, 450, 550):
        for step in range(12):
            angle = step * math.pi / 6
            pos = (near[0] + radius * math.cos(angle), near[1] + radius * math.sin(angle))
            started = asyncio.ensure_future(client.wait_for_event(
                "construction_started", lambda e: e["template"].endswith(template), timeout=30))
            try:
                await client.build(builder, template, pos)
                return (await started)["id"]
            except ApiError as error:
                if error.code not in ("ILLEGAL_LOCATION",):
                    return None
            finally:
                started.cancel()
    return None


async def build(client: GeneralsClient, builder: int, template: str, near) -> int | None:
    building = await place(client, builder, template, near)
    if building is not None:
        await client.wait_for_event("construction_complete", lambda e: e["id"] == building, timeout=120)
    return building


async def run(client: GeneralsClient, world: World) -> None:
    info = world.game_info
    me = next(p for p in info["players"] if p["relation"] == "self")
    # Generals' factions ("ChinaTankGeneral") use their base side's templates under a prefix ("Tank_").
    base = next((side for side in SIDES if me["side"].startswith(side)), "America")
    names = [t["name"] for t in world.catalog["structures"] + world.catalog["units"]]

    def actual(name: str | None) -> str | None:
        return next((n for n in names if n.endswith(name)), name) if name else None
    builder_name, power, barracks_name, infantry = (actual(n) for n in SIDES[base])

    # Right after a LAN game starts the starting units can take a moment to appear.
    for _ in range(20):
        snap = await client.state()
        builders = mine(snap, builder_name)
        if builders:
            break
        await asyncio.sleep(0.5)
    hq = next(u for u in snap["units"] if u["template"].endswith("CommandCenter"))
    home = hq["pos"]
    enemy_start = max(info["start_positions"], key=lambda p: math.dist(p, home[:2]))

    if not builders:
        return
    builder = builders[0]["id"]
    if power is not None:
        await build(client, builder, power, home)
    barracks = await build(client, builder, barracks_name, home)
    if barracks is None:
        return
    await client.set_rally_point(barracks, home)

    while True:
        try:
            await client.train(barracks, infantry, count=WAVE)
        except ApiError:
            pass  # out of money or queue full; try again next wave
        await asyncio.sleep(30)
        snap = await client.state()
        soldiers = [u["id"] for u in mine(snap, infantry) if u.get("contained_by") is None]
        if len(soldiers) >= WAVE:
            await client.attack_move(soldiers, enemy_start)
