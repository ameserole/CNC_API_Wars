"""Shared steps for integration tests that play a match: placing buildings, training, waiting."""

from __future__ import annotations

import asyncio
import math

from generals_api import ApiError, GeneralsClient

TIMEOUT = 90.0


def distance(a, b) -> float:
    return math.dist(a[:2], b[:2])


def own(snapshot: dict, template: str) -> list[dict]:
    return [u for u in snapshot["units"] if u["template"] == template]


async def wait_until(predicate, timeout: float = TIMEOUT, interval: float = 0.5):
    """Polls an async predicate until it returns something truthy."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        result = await predicate()
        if result:
            return result
        if loop.time() > deadline:
            raise TimeoutError("condition not met")
        await asyncio.sleep(interval)


async def money(client: GeneralsClient) -> int:
    return (await client.state())["self"]["money"]


async def place_building(client: GeneralsClient, dozer: int, template: str, near) -> dict:
    """Tries spots around `near` until the game accepts one; returns construction_started."""
    started = asyncio.ensure_future(client.wait_for_event(
        "construction_started", lambda e: e["template"] == template, timeout=TIMEOUT))
    try:
        for radius in (220, 300, 380, 460, 540):
            for step in range(12):
                angle = step * math.pi / 6
                pos = (near[0] + radius * math.cos(angle), near[1] + radius * math.sin(angle))
                try:
                    await client.build(dozer, template, pos)
                    return await started
                except ApiError as error:
                    if error.code != "ILLEGAL_LOCATION":
                        raise
        raise AssertionError(f"no legal spot for {template} near {near}")
    finally:
        started.cancel()


async def build_and_wait(client: GeneralsClient, dozer: int, template: str, near) -> int:
    started = await place_building(client, dozer, template, near)
    await client.wait_for_event("construction_complete", lambda e: e["id"] == started["id"], timeout=TIMEOUT)
    return started["id"]


async def train_and_wait(client: GeneralsClient, factory: int, template: str, count: int) -> list[int]:
    created: list[int] = []

    def on_created(event):
        if event["factory_id"] == factory and event["template"] == template:
            created.append(event["id"])

    client.on("unit_created", on_created)
    await client.train(factory, template, count=count)

    async def done():
        return len(created) >= count
    await wait_until(done, timeout=TIMEOUT + 10 * count)
    return created[:count]


async def base_setup(client: GeneralsClient) -> dict:
    """Our dozer, command center, catalog and a finished barracks."""
    snap = await client.state()
    setup = {
        "dozer": own(snap, "AmericaVehicleDozer")[0]["id"],
        "cc": own(snap, "AmericaCommandCenter")[0],
    }
    catalog = await client.catalog()
    setup["catalog"] = catalog
    setup["things"] = {t["name"]: t for t in catalog["structures"] + catalog["units"]}
    setup["barracks"] = await build_and_wait(client, setup["dozer"], "AmericaBarracks", setup["cc"]["pos"])
    return setup


async def ensure_structure(client: GeneralsClient, setup: dict, template: str) -> int:
    """Builds `template` (and, first, any missing prerequisite structures from the catalog)."""
    owned = {u["template"]: u["id"] for u in (await client.state())["units"]}
    if template in owned:
        return owned[template]
    entry = setup["things"][template]
    for group in entry.get("prerequisites", []):
        if not any(name in owned for name in group):
            await ensure_structure(client, setup, group[0])
    return await build_and_wait(client, setup["dozer"], template, setup["cc"]["pos"])
