"""Phase 3: the read-only, fog-of-war-limited view of a running skirmish (script player vs Easy AI)."""

import asyncio

import pytest

from generals_api import ApiError, GeneralsClient, World

FOG_SHROUDS = {"fogged", "shrouded"}
SEEN_SHROUDS = {"clear", "partial"}


async def test_game_info(game, skirmish):
    async with GeneralsClient(game.url) as client:
        info = await client.game_info()
    players = {p["relation"]: p for p in info["players"]}
    assert set(players) == {"self", "enemy"}
    assert players["self"]["index"] == info["local_player"]
    assert players["self"]["side"] == "America" and players["self"]["type"] == "human"
    assert players["enemy"]["side"] == "China" and players["enemy"]["type"] == "computer"

    (min_x, min_y), (max_x, max_y) = info["map"]["extent"]["min"], info["map"]["extent"]["max"]
    assert max_x > min_x and max_y > min_y
    assert len(info["start_positions"]) >= 2
    for x, y in info["start_positions"]:
        assert min_x <= x <= max_x and min_y <= y <= max_y


async def test_catalog(game, skirmish):
    async with GeneralsClient(game.url) as client:
        catalog = await client.catalog()
    things = {t["name"]: t for t in catalog["structures"] + catalog["units"]}
    for name in ("AmericaPowerPlant", "AmericaBarracks", "AmericaInfantryRanger", "AmericaVehicleDozer"):
        assert name in things, name
        assert things[name]["cost"] > 0, name
    assert "AmericaBarracks" in things["AmericaInfantryRanger"]["built_by"]
    assert "AmericaVehicleDozer" in things["AmericaPowerPlant"]["built_by"]
    assert "STRUCTURE" in things["AmericaPowerPlant"]["kinds"]
    assert things["AmericaPowerPlant"]["available_now"] is True
    assert catalog["upgrades"] and catalog["sciences"]
    assert all({"name", "cost", "build_time", "built_by"} <= u.keys() for u in catalog["upgrades"])


async def test_template_info(game, skirmish):
    async with GeneralsClient(game.url) as client:
        info = await client.template_info(["ChinaCommandCenter", "NoSuchThing"])
    assert info["unknown"] == ["NoSuchThing"]
    china_cc = info["templates"]["ChinaCommandCenter"]
    assert china_cc["side"] == "China"
    assert "STRUCTURE" in china_cc["kinds"]


async def test_map_grid(game, skirmish):
    async with GeneralsClient(game.url) as client:
        info = await client.game_info()
        grid = await client.map(cell_size=40)
    width = info["map"]["extent"]["max"][0] - info["map"]["extent"]["min"][0]
    height = info["map"]["extent"]["max"][1] - info["map"]["extent"]["min"][1]
    assert grid["cell_size"] == 40
    assert grid["columns"] == pytest.approx(width / 40, abs=1)
    assert grid["rows"] == pytest.approx(height / 40, abs=1)
    assert len(grid["heights"]) == grid["rows"] == len(grid["terrain"])
    assert all(len(row) == grid["columns"] for row in grid["terrain"])
    assert set("".join(grid["terrain"])) <= set(".wcx")
    flat = [h for row in grid["heights"] for h in row]
    assert max(flat) > min(flat)


async def test_first_snapshot_shows_own_base_and_no_enemy(game, skirmish):
    async with GeneralsClient(game.url) as client:
        snap = await client.state()
        truth = await client.request("debug_world")
    own = {u["template"] for u in snap["units"]}
    assert {"AmericaCommandCenter", "AmericaVehicleDozer"} <= own
    assert snap["self"]["money"] == skirmish["starting_cash"]

    # Civilian buildings drawn as fog ghosts are known from the start, like on a human's screen.
    truth_by_id = {o["id"]: o for o in truth["objects"]}
    assert any(truth_by_id.get(k["id"], {}).get("relation") == "neutral" for k in snap["known_structures"])
    for known in snap["known_structures"]:
        assert "IMMOBILE" in truth_by_id[known["id"]]["kinds"], known

    china_buildings = [o for o in truth["objects"] if o["template"] == "ChinaCommandCenter"]
    assert china_buildings, "debug_world should list the AI's command center"
    if all(o["shroud"] in FOG_SHROUDS for o in china_buildings):
        assert not any(o["template"].startswith("China") for o in snap["visible"])
        assert not any(o["template"].startswith("China") for o in snap["known_structures"])


async def test_fog_rule_holds_over_time(game, skirmish):
    async with GeneralsClient(game.url) as client:
        for _ in range(10):
            snap = await client.state()
            truth = {o["id"]: o for o in (await client.request("debug_world"))["objects"]}
            for obj in snap["visible"]:
                if obj["id"] in truth and "STRUCTURE" in truth[obj["id"]]["kinds"]:
                    assert truth[obj["id"]]["shroud"] in SEEN_SHROUDS, obj
            await asyncio.sleep(1)


async def test_snapshot_interval(game, skirmish):
    async with GeneralsClient(game.url) as client:
        await client.set_snapshot_interval(30)
        frames = []
        for _ in range(4):
            frames.append((await client.wait_for_event("snapshot", timeout=5))["frame"])
        gaps = [b - a for a, b in zip(frames, frames[1:])]
        assert all(28 <= g <= 32 for g in gaps), gaps

        await client.set_snapshot_interval(0)
        with pytest.raises(asyncio.TimeoutError):
            await client.wait_for_event("snapshot", timeout=2)
        assert "units" in await client.state()

        await client.set_snapshot_interval(15)
        with pytest.raises(ApiError) as info:
            await client.set_snapshot_interval(-1)
        assert info.value.code == "BAD_REQUEST"


async def test_money_changed_and_world_model(game, skirmish):
    async with GeneralsClient(game.url) as client:
        world = World()
        world.attach(client)
        await world.load(client)
        await client.wait_for_event("snapshot", timeout=5)
        before = world.money

        await client.request("debug_add_cash")
        event = await client.wait_for_event("money_changed", timeout=5)
        assert event["delta"] == 10000 and event["money"] == before + 10000
        await client.wait_for_event("snapshot", timeout=5)
        assert world.money == before + 10000

        assert world.mine(kind="COMMANDCENTER")
        assert world.mine(template="AmericaVehicleDozer")
        assert not world.unknown_templates() - {o["template"] for o in world.visible.values()}

