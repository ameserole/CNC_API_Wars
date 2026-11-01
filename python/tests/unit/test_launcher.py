"""Unit tests for the launcher's planning (no game is started)."""

from pathlib import Path

import pytest

from generals_api import launcher

ROOT = Path(__file__).resolve().parents[2]


def plan(*argv, ports=(5001, 5002, 5003)):
    return launcher.make_plan(launcher.parse_args(["--bot1", "bots/simple.py", *argv]), list(ports))


def test_bot_vs_bot_is_a_lan_game():
    p = plan("--bot2", "bots/simple.py", "--bot2-faction", "China")
    assert p.mode == "lan"
    assert [i.role for i in p.instances] == ["bot1", "bot2"]
    assert p.slots == [{"type": "host"}, {"type": "open"}]
    assert p.instance("bot2").faction == "FactionChina"
    assert all(i.input_mode == "view" for i in p.instances)


def test_observer_gets_full_input_and_an_open_slot():
    p = plan("--bot2", "bots/simple.py", "--observer")
    observer = p.instance("observer")
    assert observer.input_mode == "full" and observer.bot is None
    assert p.slots == [{"type": "host"}, {"type": "open"}, {"type": "open"}]
    assert "-noaudio" not in observer.args()
    assert "-noaudio" in p.instance("bot1").args()


def test_ports_are_distinct():
    p = launcher.make_plan(launcher.parse_args(["--bot1", "a.py", "--bot2", "b.py", "--observer"]))
    ports = [i.port for i in p.instances]
    assert len(set(ports)) == 3
    args = p.instance("bot2").args(["-ignoreAsserts"])
    assert args[args.index("-scriptApiPort") + 1] == str(p.instance("bot2").port)
    assert args[-1] == "-ignoreAsserts"


def test_vs_ai_without_observer_is_a_skirmish():
    p = plan("--vs-ai", "hard", "--ai-faction", "GLA")
    assert p.mode == "skirmish"
    assert p.ai == {"type": "hard_ai", "faction": "FactionGLA"}
    assert [i.role for i in p.instances] == ["bot1"]


def test_vs_ai_with_observer_is_a_lan_game_with_an_ai_slot():
    p = plan("--vs-ai", "easy", "--observer")
    assert p.mode == "lan"
    assert p.slots == [{"type": "host"}, {"type": "easy_ai", "faction": "random"}, {"type": "open"}]
    assert [i.role for i in p.instances] == ["bot1", "observer"]


def test_needs_exactly_one_opponent():
    with pytest.raises(ValueError):
        plan()
    with pytest.raises(ValueError):
        plan("--bot2", "x.py", "--vs-ai", "easy")


def test_faction_names():
    assert launcher.faction_name("China") == "FactionChina"
    assert launcher.faction_name("FactionGLA") == "FactionGLA"
    assert launcher.faction_name(None) == "random"
    assert launcher.faction_name("Random") == "random"


def test_load_bot_finds_run(tmp_path):
    run = launcher.load_bot(ROOT / "bots" / "simple.py")
    assert run.__name__ == "run"
    bad = tmp_path / "bad.py"
    bad.write_text("def run(client, world):\n    pass\n")
    with pytest.raises(ValueError):
        launcher.load_bot(bad)


def test_pick_map():
    options = {"maps": [{"name": r"maps\a\alpha.map", "display_name": "Alpha"},
                        {"name": r"maps\tournament desert\tournament desert.map", "display_name": "Tournament Desert"}]}
    assert launcher.pick_map(options, "tournament desert").endswith("tournament desert.map")
    assert launcher.pick_map(options, "Alpha") == r"maps\a\alpha.map"
    with pytest.raises(ValueError):
        launcher.pick_map(options, "nowhere")


def test_apm_cap_reaches_bot_instances_only():
    p = plan("--bot2", "bots/simple.py", "--observer", "--apm", "120")
    for role in ("bot1", "bot2"):
        args = p.instance(role).args()
        assert args[args.index("-scriptApiApm") + 1] == "120"
    assert "-scriptApiApm" not in p.instance("observer").args()
    assert "-scriptApiApm" not in plan("--vs-ai", "easy").instance("bot1").args()


def test_replay_names():
    from datetime import datetime
    now = datetime(2026, 10, 31, 12, 30, 5)
    args = launcher.parse_args(["--bot1", "bots/simple.py", "--bot2", "bots/rush.py"])
    assert launcher.replay_name(args, now) == "20261031-123005_simple_vs_rush"
    args = launcher.parse_args(["--bot1", "bots/simple.py", "--vs-ai", "hard"])
    assert launcher.replay_name(args, now) == "20261031-123005_simple_vs_hard-ai"
    args = launcher.parse_args(["--bot1", "a.py", "--vs-ai", "easy", "--replay", "my match"])
    assert launcher.replay_name(args, now) == "my match"
    args = launcher.parse_args(["--bot1", "a.py", "--vs-ai", "easy", "--no-replay"])
    assert launcher.replay_name(args, now) is None
