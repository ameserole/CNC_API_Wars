"""Unit tests for `watch` (triggers and digest) and `botkit` (live-reloaded settings and strategy)."""

import json
import os
import time

from generals_api import botkit
from generals_api.client import watcher_url
from generals_api.watch import Watch, WatchState

INFO = {
    "local_player": 2,
    "players": [{"index": 2, "name": "Alpha", "relation": "self"}, {"index": 3, "name": "Bravo", "relation": "enemy"}],
    "start_positions": [[500, 500], [2500, 2500]],
}
CATALOG = {"structures": [{"name": "ChinaCommandCenter"}, {"name": "ChinaSupplyCenter"}, {"name": "ChinaWarFactory"}],
           "units": [{"name": "ChinaTankBattleMaster"}, {"name": "ChinaVehicleSupplyTruck"}]}


def snapshot(frame, money=1000, units=None, visible=None, known=None):
    return {
        "frame": frame,
        "self": {"index": 2, "money": money, "power": {"produced": 10, "consumed": 4}},
        "units": units if units is not None else [
            {"id": 1, "template": "ChinaCommandCenter", "pos": [500, 500, 0], "status": []},
            {"id": 2, "template": "ChinaSupplyCenter", "pos": [700, 500, 0], "status": []},
            {"id": 10, "template": "ChinaTankBattleMaster", "pos": [900, 900, 0], "status": []},
            {"id": 11, "template": "ChinaTankBattleMaster", "pos": [900, 920, 0], "status": []},
        ],
        "visible": visible or [],
        "known_structures": known or [],
    }


def event(name, frame, **fields):
    return {"type": "event", "event": name, "frame": frame, **fields}


def make(state=None):
    w = Watch(INFO, CATALOG, state or WatchState())
    w.on_snapshot(snapshot(100))
    return w


def test_quiet_game_fires_nothing():
    w = make()
    assert w.on_snapshot(snapshot(130)) == []
    assert w.on_event(event("money_changed", 131, money=1100, previous=1000, delta=100)) == []


def test_structure_damage_and_loss():
    w = make()
    assert "base_attacked" in w.on_event(event("unit_damaged", 140, id=2, template="ChinaSupplyCenter", damage=50,
                                               health=950, max_health=1000))
    assert w.on_event(event("unit_damaged", 141, id=10, template="ChinaTankBattleMaster", damage=5,
                            health=400, max_health=480)) == []  # units in a fight are normal
    assert "structure_lost" in w.on_event(event("unit_destroyed", 150, id=2, template="ChinaSupplyCenter",
                                                pos=[700, 500, 0]))


def test_enemies_near_the_base():
    w = make()
    near = [{"id": 100 + i, "template": "AmericaTankCrusader", "owner": 3, "pos": [600 + i * 10, 600, 0]} for i in range(3)]
    far = [{"id": 200 + i, "template": "AmericaTankCrusader", "owner": 3, "pos": [2400, 2400, 0]} for i in range(5)]
    assert "enemies_near_base" in w.on_snapshot(snapshot(160, visible=near))
    assert "enemies_near_base" not in make().on_snapshot(snapshot(160, visible=far))


def test_army_losses():
    w = make()
    units = snapshot(100)["units"] + [{"id": 20 + i, "template": "ChinaTankBattleMaster", "pos": [900, 900, 0],
                                       "status": []} for i in range(4)]
    w.on_snapshot(snapshot(110, units=units))  # 6 tanks
    fired = []
    for i in range(3):
        fired += w.on_event(event("unit_destroyed", 120 + i, id=20 + i, template="ChinaTankBattleMaster", pos=[900, 900, 0]))
    assert "army_losses" in fired


def test_new_enemy_types_and_built_structures():
    w = make()
    assert "new_enemy_type" in w.on_event(event("enemy_spotted", 170, id=300, template="AmericaTankPaladin", owner=3,
                                                pos=[1500, 1500, 0]))
    assert w.on_event(event("enemy_spotted", 171, id=301, template="AmericaTankPaladin", owner=3, pos=[1500, 1500, 0])) == []
    assert "built" in w.on_event(event("construction_complete", 180, id=3, template="ChinaWarFactory"))


def test_money_left_unspent():
    w = make()
    assert w.on_snapshot(snapshot(200, money=4000)) == []
    assert "money_idle" in w.on_snapshot(snapshot(200 + 30 * 61, money=4500))


def test_supply_running_low():
    w = make()
    dock = {"id": 50, "template": "SupplyDock", "owner": 0, "pos": [750, 520, 0], "supply": 20000}
    assert w.on_snapshot(snapshot(210, visible=[dock])) == []
    assert "supply_low" in w.on_snapshot(snapshot(220, visible=[{**dock, "supply": 2000}]))


def test_game_over_and_digest():
    w = make()
    assert "game_over" in w.on_event(event("game_over", 300, result="victory", winners=[2], stats=[]))
    assert w.result == "victory"
    text = w.digest(snapshot(300), {"players": [{"index": 2, "score": 1234, "money_earned": 5000}]}, ["game_over"])
    assert "game over: victory" in text and "score 1234" in text
    assert len(text.splitlines()) <= 30


def test_digest_reports_changes_since_last_call(tmp_path):
    state_file = tmp_path / "watch.json"
    w = make(WatchState.load(state_file))
    w.on_event(event("construction_complete", 180, id=3, template="ChinaWarFactory"))
    w.on_event(event("unit_destroyed", 190, id=11, template="ChinaTankBattleMaster", pos=[900, 920, 0]))
    text = w.digest(snapshot(200), {"players": []}, ["built"])
    assert "built: ChinaWarFactory" in text and "lost: ChinaTankBattleMaster" in text
    w.state.save(state_file)

    again = Watch(INFO, CATALOG, WatchState.load(state_file))
    again.on_snapshot(snapshot(230))
    assert "built:" not in again.digest(snapshot(230), {"players": []}, [])  # reported once
    assert "AmericaTankPaladin" not in again.digest(snapshot(230), {"players": []}, [])


def test_enemy_types_persist_between_calls(tmp_path):
    state_file = tmp_path / "watch.json"
    w = make(WatchState.load(state_file))
    w.on_event(event("enemy_spotted", 170, id=300, template="AmericaTankPaladin", owner=3, pos=[1500, 1500, 0]))
    w.state.save(state_file)
    again = make(WatchState.load(state_file))
    assert again.on_event(event("enemy_spotted", 400, id=301, template="AmericaTankPaladin", owner=3,
                                pos=[1500, 1500, 0])) == []


def test_watcher_url():
    assert watcher_url("ws://127.0.0.1:5000") == "ws://127.0.0.1:5000/watch"
    assert watcher_url("ws://127.0.0.1:5000/") == "ws://127.0.0.1:5000/watch"
    assert watcher_url("ws://127.0.0.1:5000/watch") == "ws://127.0.0.1:5000/watch"


# -- botkit ----------------------------------------------------------------------------------------

_bump = iter(range(10, 10_000, 10))


def touch_later(path, text):
    path.write_text(text)
    later = time.time() + next(_bump)
    os.utime(path, (later, later))  # a distinct, later time even on coarse clocks


def test_live_settings_reload(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"attack_size": 12}))
    settings = botkit.LiveSettings(path, defaults={"attack_size": 8, "retreat": 1.4})
    assert settings["attack_size"] == 12 and settings["retreat"] == 1.4
    touch_later(path, json.dumps({"attack_size": 6}))
    assert settings.reload() is True
    assert settings["attack_size"] == 6
    assert settings.reload() is False
    touch_later(path, "{broken")
    assert settings.reload() is False and settings["attack_size"] == 6  # a bad edit keeps the last good values
    assert "settings.json" in settings.error


def test_live_module_reload(tmp_path):
    path = tmp_path / "strategy.py"
    path.write_text("def wave_size():\n    return 8\n")
    strategy = botkit.LiveModule(path)
    assert strategy.module.wave_size() == 8
    touch_later(path, "def wave_size():\n    return 14\n")
    assert strategy.reload() is True
    assert strategy.module.wave_size() == 14
    touch_later(path, "def wave_size(:\n")
    assert strategy.reload() is False and strategy.module.wave_size() == 14
    assert strategy.error


def test_leaving_the_game_counts_as_over():
    w = make()
    assert "game_over" in w.on_event(event("game_state", 500, previous="in_game", state="shell"))
    assert w.result == "ended (shell)"
    assert make().on_event(event("game_state", 1, previous="loading", state="in_game")) == []


def test_order_lists_commands_with_their_arguments():
    from generals_api.order import command_list, parse_args
    lines = command_list()
    assert any(line.startswith("train factory template [count]") for line in lines), lines
    assert any(line.startswith("attack units target") for line in lines)
    assert not any(line.startswith(("connect", "request ", "wait_for_event")) for line in lines)
    assert parse_args(["units=[1,2]", "target=40", "ability=Command_X"]) == {"units": [1, 2], "target": 40, "ability": "Command_X"}
