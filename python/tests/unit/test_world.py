"""Unit tests for the World model, fed with synthetic snapshots and events."""

from generals_api import World


def snapshot(frame=30, money=10000, units=None, visible=None, known=None):
    return {
        "type": "event", "event": "snapshot", "frame": frame,
        "self": {"index": 2, "money": money, "power": {"produced": 5, "consumed": 2}, "rank": 1, "science_points": 0},
        "units": units if units is not None else [
            {"id": 1, "template": "AmericaCommandCenter", "pos": [10, 20, 0], "health": 5000, "max_health": 5000, "status": []},
            {"id": 2, "template": "AmericaVehicleDozer", "pos": [15, 25, 0], "health": 250, "max_health": 250, "status": []},
        ],
        "visible": visible if visible is not None else [
            {"id": 9, "template": "ChinaInfantryRedguard", "owner": 3, "pos": [50, 50, 0], "health_pct": 1.0, "status": []},
            {"id": 10, "template": "CivilianCar", "owner": 0, "pos": [60, 60, 0], "health_pct": 1.0, "status": []},
        ],
        "known_structures": known if known is not None else [
            {"id": 11, "template": "ChinaBarracks", "owner": 3, "pos": [90, 90, 0], "last_seen_frame": 12, "visible": False},
        ],
    }


def make_world():
    world = World()
    world.game_info = {"local_player": 2, "players": [
        {"index": 2, "relation": "self"}, {"index": 3, "relation": "enemy"}]}
    world.templates.update({
        "AmericaCommandCenter": {"kinds": ["STRUCTURE", "COMMANDCENTER"]},
        "AmericaVehicleDozer": {"kinds": ["VEHICLE", "DOZER"]},
        "ChinaInfantryRedguard": {"kinds": ["INFANTRY"]},
    })
    return world


def test_snapshot_replaces_state():
    world = make_world()
    world.apply_snapshot(snapshot())
    assert world.frame == 30
    assert set(world.units) == {1, 2}
    assert set(world.visible) == {9, 10}
    assert set(world.known_structures) == {11}
    assert world.money == 10000
    assert world.power == {"produced": 5, "consumed": 2}

    world.apply_snapshot(snapshot(frame=45, units=[], visible=[], known=[]))
    assert world.frame == 45
    assert not world.units and not world.visible and not world.known_structures


def test_mine_filters_by_template_and_kind():
    world = make_world()
    world.apply_snapshot(snapshot())
    assert [u["id"] for u in world.mine(template="AmericaVehicleDozer")] == [2]
    assert [u["id"] for u in world.mine(kind="STRUCTURE")] == [1]
    assert len(world.mine()) == 2
    assert world.mine(kind="AIRCRAFT") == []


def test_enemies_uses_player_relations():
    world = make_world()
    world.apply_snapshot(snapshot())
    assert [o["id"] for o in world.enemies()] == [9]
    assert [o["id"] for o in world.enemies(kind="INFANTRY")] == [9]


def test_unknown_templates_are_listed_for_lookup():
    world = make_world()
    world.apply_snapshot(snapshot())
    assert world.unknown_templates() == {"CivilianCar", "ChinaBarracks"}


def test_unit_destroyed_removes_unit_before_next_snapshot():
    world = make_world()
    world.apply_snapshot(snapshot())
    world.apply_event({"type": "event", "event": "unit_destroyed", "frame": 40, "id": 2, "template": "AmericaVehicleDozer"})
    assert set(world.units) == {1}


def test_money_and_power_follow_events():
    world = make_world()
    world.apply_snapshot(snapshot())
    world.apply_event({"type": "event", "event": "money_changed", "frame": 50, "money": 20000, "previous": 10000, "delta": 10000})
    assert world.money == 20000
    world.apply_event({"type": "event", "event": "power_changed", "frame": 51, "produced": 10, "consumed": 4})
    assert world.power == {"produced": 10, "consumed": 4}
    world.apply_event({"type": "event", "event": "rank_changed", "frame": 52, "rank": 2, "science_points": 1})
    assert world.me["rank"] == 2 and world.me["science_points"] == 1


def test_game_over_sets_result():
    world = make_world()
    assert world.result is None
    world.apply_event({"type": "event", "event": "game_over", "frame": 900, "result": "victory"})
    assert world.result == "victory"


def test_catalog_entries_populate_templates():
    world = World()
    world.apply_catalog({"faction": "America",
                         "structures": [{"name": "AmericaPowerPlant", "kinds": ["STRUCTURE"], "cost": 800}],
                         "units": [{"name": "AmericaInfantryRanger", "kinds": ["INFANTRY"], "cost": 225}],
                         "upgrades": [], "sciences": []})
    assert world.templates["AmericaPowerPlant"]["cost"] == 800
    assert "INFANTRY" in world.kinds("AmericaInfantryRanger")
    assert world.kinds("Nope") == set()


def test_unit_removed_drops_unit():
    world = make_world()
    world.apply_snapshot(snapshot())
    world.apply_event({"type": "event", "event": "unit_removed", "frame": 40, "id": 1, "template": "AmericaCommandCenter",
                       "reason": "sold"})
    assert set(world.units) == {2}


def test_enemies_seen_tracks_spotted_lost_destroyed():
    world = make_world()
    world.apply_event({"type": "event", "event": "enemy_spotted", "frame": 50, "id": 9, "template": "ChinaInfantryRedguard",
                       "owner": 3, "pos": [1, 2, 0]})
    assert world.enemies_seen[9]["visible"] is True
    world.apply_event({"type": "event", "event": "enemy_lost_from_view", "frame": 60, "id": 9,
                       "template": "ChinaInfantryRedguard", "last_pos": [4, 5, 0]})
    assert world.enemies_seen[9]["visible"] is False and world.enemies_seen[9]["pos"] == [4, 5, 0]
    world.apply_event({"type": "event", "event": "enemy_destroyed", "frame": 70, "id": 9,
                       "template": "ChinaInfantryRedguard", "owner": 3, "pos": [4, 5, 0]})
    assert 9 not in world.enemies_seen


def test_enemy_structures_include_visible_and_remembered():
    world = make_world()
    world.apply_snapshot(snapshot(known=[
        {"id": 11, "template": "ChinaBarracks", "owner": 3, "pos": [90, 90, 0], "last_seen_frame": 12, "visible": False},
        {"id": 12, "template": "ChinaWarFactory", "owner": 3, "pos": [95, 90, 0], "last_seen_frame": 30, "visible": True},
        {"id": 13, "template": "SupplyDock", "owner": 0, "pos": [40, 40, 0], "last_seen_frame": 30, "visible": True},
    ]))
    assert sorted(o["id"] for o in world.enemy_structures()) == [11, 12]
    assert [o["id"] for o in world.enemy_structures(template="ChinaWarFactory")] == [12]
