"""Delta's macro bot for FactionChina: power, barracks, supply center, war factory, then timed waves.

Built from bots/simple.py. Tunables live in settings.json next to this file (re-read each wave).
Build order: power plant -> barracks -> supply center -> war factory (the factory needs a supply center).
Restarting the bot in the same match is safe: structures already standing are reused, not rebuilt.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

from generals_api import ApiError, GeneralsClient, World

HERE = Path(__file__).resolve().parent
DEFAULTS = {"wave": 5, "wave_interval": 30, "tank": "ChinaTankBattleMaster", "infantry": "ChinaInfantryRedguard"}


def settings() -> dict:
    try:
        return {**DEFAULTS, **json.loads((HERE / "settings.json").read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def mine(snapshot: dict, suffix: str) -> list[dict]:
    return [u for u in snapshot["units"] if u["template"].endswith(suffix)]


async def place(client: GeneralsClient, builder: int, template: str, near) -> int | None:
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
                if error.code != "ILLEGAL_LOCATION":
                    print(f"build {template} refused: {error.code} {error.message}", flush=True)
                    return None
            finally:
                started.cancel()
    return None


async def build(client: GeneralsClient, builder: int, template: str, near) -> int | None:
    building = await place(client, builder, template, near)
    if building is not None:
        await client.wait_for_event("construction_complete", lambda e: e["id"] == building, timeout=120)
    return building


async def existing_or_build(client: GeneralsClient, snap: dict, builder: int, template: str, near) -> int | None:
    """The id of our standing building of this template, or a freshly built one."""
    standing = mine(snap, template)
    if standing:
        return standing[0]["id"]
    return await build(client, builder, template, near)


async def run(client: GeneralsClient, world: World) -> None:
    info = world.game_info
    names = [t["name"] for t in world.catalog["structures"] + world.catalog["units"]]

    def actual(name: str) -> str:
        return next((n for n in names if n.endswith(name)), name)

    builder_name = actual("ChinaVehicleDozer")
    power = actual("ChinaPowerPlant")
    barracks_name = actual("ChinaBarracks")
    supply_name = actual("ChinaSupplyCenter")
    factory_name = actual("ChinaWarFactory")

    for _ in range(20):
        snap = await client.state()
        builders = mine(snap, builder_name)
        if builders:
            break
        await asyncio.sleep(0.5)
    if not builders:
        return
    hq = next(u for u in snap["units"] if u["template"].endswith("CommandCenter"))
    home = hq["pos"]
    enemy_start = max(info["start_positions"], key=lambda p: math.dist(p, home[:2]))
    builder = builders[0]["id"]

    await existing_or_build(client, snap, builder, power, home)
    barracks = await existing_or_build(client, snap, builder, barracks_name, home)
    if barracks is None:
        return
    await client.set_rally_point(barracks, home)
    await existing_or_build(client, snap, builder, supply_name, home)
    # Save up for the factory before anything else spends money (INSUFFICIENT_FUNDS otherwise).
    factory_cost = world.templates.get(factory_name, {}).get("cost", 2000)
    if not mine(snap, factory_name):
        while (world.money or 0) < factory_cost:
            await asyncio.sleep(2)
    factory = await existing_or_build(client, snap, builder, factory_name, home)
    if factory is not None:
        await client.set_rally_point(factory, home)

    while True:
        cfg = settings()
        try:
            await client.train(barracks, actual(cfg["infantry"]), count=cfg["wave"])
        except ApiError:
            pass
        if factory is not None:
            try:
                await client.train(factory, actual(cfg["tank"]), count=1)
            except ApiError:
                pass
        await asyncio.sleep(cfg["wave_interval"])
        snap = await client.state()
        soldiers = [u["id"] for u in snap["units"]
                    if (u["template"].endswith(cfg["infantry"]) or u["template"].endswith(cfg["tank"]))
                    and u.get("contained_by") is None]
        if len(soldiers) >= cfg["wave"]:
            await client.attack_move(soldiers, enemy_start)
