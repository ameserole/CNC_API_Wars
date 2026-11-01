"""Phase 5, scenario steps 10-11: march into the enemy base and check the enemy-visibility events.

What a script learns about the enemy must match what the player could see: enemy events start
with enemy_spotted, every spotted object really is visible at that moment, and attackers are only
named once they have been seen.
"""

import asyncio

import pytest

from generals_api import GeneralsClient

from .helpers import TIMEOUT, base_setup, distance, train_and_wait

CONTACT_TIMEOUT = 240.0
ENEMY_EVENTS = ("enemy_spotted", "enemy_lost_from_view", "enemy_destroyed")


@pytest.fixture
async def client(game, skirmish, transcript):
    async with GeneralsClient(game.url, request_timeout=TIMEOUT, transcript=transcript) as c:
        yield c


async def test_contact_with_enemy_base(client):
    setup = await base_setup(client)
    rangers = await train_and_wait(client, setup["barracks"], "AmericaInfantryRanger", 5)

    info = await client.game_info()
    cc = setup["cc"]["pos"]
    enemy_start = max(info["start_positions"], key=lambda p: distance(p, cc))

    enemy_events: list[dict] = []
    spotted_ever: set[int] = set()
    damage_events: list[dict] = []
    fog_violations: list[str] = []
    checks: list[asyncio.Task] = []

    async def check_visible(event):
        """Right after a sighting, the object must be visible unless it already left view or died."""
        truth = {o["id"]: o for o in (await client.request("debug_world"))["objects"]}
        obj = truth.get(event["id"])
        later = [e for e in enemy_events if e["id"] == event["id"] and e["event"] != "enemy_spotted"
                 and e["frame"] >= event["frame"]]
        if obj is not None and not obj["visible"] and not later:
            fog_violations.append(f"spotted {event['id']} ({event['template']}) is not visible: {obj['shroud']}")

    def on_enemy(event):
        enemy_events.append(event)
        if event["event"] == "enemy_spotted":
            spotted_ever.add(event["id"])
            if len(checks) < 10:
                checks.append(asyncio.ensure_future(check_visible(event)))

    for name in ENEMY_EVENTS:
        client.on(name, on_enemy)
    client.on("unit_damaged", damage_events.append)
    client.on("unit_destroyed", damage_events.append)

    await client.wait_for_execution(await client.attack_move(rangers, enemy_start), timeout=10)

    async def contact_made():
        return bool(spotted_ever) and any(e["event"] == "unit_damaged" for e in damage_events)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + CONTACT_TIMEOUT
    while not await contact_made():
        assert loop.time() < deadline, f"no contact: {len(enemy_events)} enemy events, {len(damage_events)} damage events"
        await asyncio.sleep(1)
    await asyncio.sleep(5)  # let the fight run a little
    await asyncio.gather(*checks)

    assert enemy_events[0]["event"] == "enemy_spotted", enemy_events[:3]
    assert not fog_violations, fog_violations
    for event in damage_events:
        attacker = event.get("attacker_id")
        if attacker is not None and attacker not in rangers:
            assert attacker in spotted_ever, f"{event['event']} names attacker {attacker} that was never seen"
    for event in enemy_events:
        assert event.get("owner", 3) != info["local_player"]
