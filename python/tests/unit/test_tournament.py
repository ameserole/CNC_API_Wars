"""Unit tests for the tournament runner's game-independent parts: config, bracket, manifests, tiebreak, audit."""

import json
import re

import pytest

from generals_api import tournament as t

FACTIONS = ["FactionAmerica", "FactionChina", "FactionGLA", "FactionChinaTankGeneral", "FactionGLAToxinGeneral"]


def config(n=4, seed=7):
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"][:n]
    return t.make_config("test", [t.Agent(name, "opus") for name in names], seed=seed)


# -- config ----------------------------------------------------------------------------------------

def test_agent_specs():
    assert t.parse_agent_spec("Alpha:opus") == t.Agent("Alpha", "opus")
    assert t.parse_agent_spec("bravo_2:haiku") == t.Agent("bravo_2", "haiku")
    for bad in ("Alpha", "Alpha:gpt", ":opus", "Al pha:opus", "../x:opus"):
        with pytest.raises(ValueError):
            t.parse_agent_spec(bad)


def test_config_defaults_and_round_trip():
    c = config()
    assert (c.game_minutes, c.iteration_minutes, c.prep_minutes, c.map) == (45, 5, 15, "tournament desert")
    assert t.Config.from_json(json.loads(json.dumps(c.to_json()))) == c


def test_config_needs_a_bracket_size_and_unique_names():
    with pytest.raises(ValueError):
        t.make_config("x", [t.Agent(n, "opus") for n in ("A", "B", "C")])
    with pytest.raises(ValueError):
        t.make_config("x", [t.Agent("A", "opus"), t.Agent("A", "sonnet")])


# -- bracket ---------------------------------------------------------------------------------------

def test_seeding_is_a_deterministic_shuffle():
    assert t.seeding(config(seed=7)) == t.seeding(config(seed=7))
    assert sorted(t.seeding(config())) == ["Alpha", "Bravo", "Charlie", "Delta"]
    assert any(t.seeding(config(seed=s)) != t.seeding(config(seed=7)) for s in range(1, 20))


def test_four_agent_bracket():
    c = config()
    s = t.seeding(c)
    games = t.bracket_games(c, {})
    assert [(g.number, g.round, g.a, g.b) for g in games] == [
        (1, 1, s[0], s[3]), (2, 1, s[1], s[2]), (3, 2, None, None)]
    assert t.next_game(c, {}).number == 1

    results = {"1": {"winner": s[3], "loser": s[0]}}
    assert t.next_game(c, results).number == 2
    results["2"] = {"winner": s[1], "loser": s[2]}
    final = t.next_game(c, results)
    assert (final.number, final.a, final.b) == (3, s[3], s[1])
    assert t.champion(c, results) is None
    results["3"] = {"winner": s[1], "loser": s[3]}
    assert t.next_game(c, results) is None
    assert t.champion(c, results) == s[1]


def test_eight_agent_bracket_has_seven_games():
    c = config(8)
    games = t.bracket_games(c, {})
    assert [g.round for g in games] == [1, 1, 1, 1, 2, 2, 3]
    s = t.seeding(c)
    assert (games[0].a, games[0].b) == (s[0], s[7])


def test_bracket_markdown_names_everyone_and_the_champion():
    c = config()
    s = t.seeding(c)
    results = {"1": {"winner": s[0], "loser": s[3], "reason": "game_over", "factions": {s[0]: "FactionChina", s[3]: "FactionGLA"}},
               "2": {"winner": s[1], "loser": s[2], "reason": "time_limit"},
               "3": {"winner": s[0], "loser": s[1], "reason": "game_over"}}
    text = t.render_bracket(c, results)
    for name in s:
        assert name in text
    assert f"Champion: **{s[0]}**" in text
    assert "FactionChina" in text and "time limit" in text


# -- tiebreak --------------------------------------------------------------------------------------

def test_time_limit_goes_to_the_higher_score_then_buildings_destroyed():
    a = {"score": 900, "buildings_destroyed": 1}
    b = {"score": 800, "buildings_destroyed": 5}
    assert t.decide_by_score("A", a, "B", b) == "A"
    assert t.decide_by_score("A", {**a, "score": 800}, "B", b) == "B"
    assert t.decide_by_score("A", {**a, "score": 800, "buildings_destroyed": 5}, "B", b) is None


# -- manifests -------------------------------------------------------------------------------------

def write(tmp_path, text, name="bot.json"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_manifest_default_and_per_opponent_faction(tmp_path):
    m = t.load_manifest(write(tmp_path, '{"faction": "FactionChina", "vs": {"Bravo": "FactionGLAToxinGeneral"}}'), FACTIONS)
    assert t.resolve_faction(m, "Bravo") == "FactionGLAToxinGeneral"
    assert t.resolve_faction(m, "Charlie") == "FactionChina"


@pytest.mark.parametrize("text", [
    "{not json", "[]", "{}", '{"faction": "random"}', '{"faction": "FactionNod"}', '{"faction": 3}',
    '{"faction": "FactionChina", "vs": {"Bravo": "Random"}}', '{"faction": "FactionChina", "vs": []}',
])
def test_bad_manifests(tmp_path, text):
    with pytest.raises(t.ManifestError):
        t.load_manifest(write(tmp_path, text), FACTIONS)


def test_missing_manifest(tmp_path):
    with pytest.raises(t.ManifestError):
        t.load_manifest(tmp_path / "bot.json", FACTIONS)


def test_effective_manifest_falls_back_to_the_last_valid_one(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    saved = tmp_path / "state" / "Alpha-manifest.json"
    write(workspace, '{"faction": "FactionChina"}')
    manifest, warning = t.effective_manifest(workspace, saved, FACTIONS)
    assert manifest["faction"] == "FactionChina" and warning is None and saved.exists()

    write(workspace, '{"faction": "FactionNod"}')
    manifest, warning = t.effective_manifest(workspace, saved, FACTIONS)
    assert manifest["faction"] == "FactionChina" and "FactionNod" in warning

    saved.unlink()
    with pytest.raises(t.ManifestError):
        t.effective_manifest(workspace, saved, FACTIONS)


def test_faction_side():
    assert t.side_of("FactionChinaTankGeneral") == "ChinaTankGeneral"
    assert t.side_of("FactionAmerica") == "America"


# -- audit -----------------------------------------------------------------------------------------

def test_audit_flags_other_workspaces_ports_and_process_kills():
    own = r"C:\T\agents\Alpha"
    others = [r"C:\T\agents\Bravo"]
    texts = [
        r"cat C:\T\agents\Alpha\notes.md",                      # fine
        r"python C:/T/agents/Alpha/bot.py ws://127.0.0.1:5000",  # fine: own port
        r"type c:\t\AGENTS\bravo\bot.py",                        # another agent's workspace
        "connect ws://127.0.0.1:5001",                           # another port
        "taskkill /F /IM generalszh.exe",                         # touching the game process
        "Stop-Process -Name generalszh",
    ]
    violations = t.find_violations(texts, own, others, allowed_ports={5000})
    assert len(violations) == 4
    assert any("Bravo" in v or "bravo" in v for v in violations)
    assert any("5001" in v for v in violations)


def test_audit_reads_only_tool_inputs_from_a_transcript():
    lines = [
        json.dumps({"message": {"role": "assistant", "content": [
            {"type": "text", "text": "I will not read C:/T/agents/Bravo"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls C:/T/agents/Bravo"}}]}}),
        json.dumps({"message": {"role": "user", "content": [
            {"type": "tool_result", "content": "C:/T/agents/Bravo listed by someone else"}]}}),
        "not json",
    ]
    inputs = t.tool_inputs(lines)
    assert inputs == [json.dumps({"command": "ls C:/T/agents/Bravo"})]


# -- prompts ---------------------------------------------------------------------------------------

def test_prompts_are_filled_in(tmp_path):
    c = config()
    text = t.render_prompt("game", c, tmp_path, "Alpha", port=5000, opponent="Bravo", game=1, faction="FactionChina")
    assert "Alpha" in text and "5000" in text and "Bravo" in text and "FactionChina" in text
    assert not re.search(r"\{[a-z_]+\}", text), "every placeholder is filled"
    prep = t.render_prompt("prep", c, tmp_path, "Alpha")
    assert "15 minutes" in prep and "tournament practice test Alpha" in prep  # it starts its own practice game
    assert "Bravo" in prep and str(tmp_path / "agents" / "Alpha") in prep


# -- liveness --------------------------------------------------------------------------------------

def _entry(ts, role, content):
    return json.dumps({"timestamp": ts, "type": role, "message": {"role": role, "content": content}})


def _use(ts, uid, name, **inp):
    return _entry(ts, "assistant", [{"type": "tool_use", "id": uid, "name": name, "input": inp}])


def _result(ts, uid):
    return _entry(ts, "user", [{"type": "tool_result", "tool_use_id": uid, "content": "ok"}])


def test_liveness_from_a_transcript():
    from datetime import datetime, timezone
    start = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 11, 1, 10, 5, 0, tzinfo=timezone.utc)
    lines = [
        _use("2026-11-01T09:59:00Z", "a", "Bash", command="echo before the game"),  # outside the window
        _use("2026-11-01T10:00:10Z", "b", "Bash", command="python bot.py", run_in_background=True),
        _use("2026-11-01T10:00:20Z", "c", "Bash", command="python -m generals_api.watch ws://x:1 --max-wait 60"),
        _result("2026-11-01T10:01:20Z", "c"),
        _use("2026-11-01T10:01:25Z", "d", "Bash", command="python -m generals_api.order ws://x:1 stop units=[1]"),
        _use("2026-11-01T10:01:30Z", "e", "Bash", command="python -m generals_api.watch ws://x:1"),
        _result("2026-11-01T10:02:30Z", "e"),
        _use("2026-11-01T10:02:40Z", "f", "Edit", file_path="C:/ws/settings.json", old_string="a", new_string="b"),
        _use("2026-11-01T10:03:00Z", "g", "SubagentHandback", report="still playing"),
        _use("2026-11-01T10:04:50Z", "h", "Bash", command="python -m generals_api.watch ws://x:1"),
        _result("2026-11-01T10:05:30Z", "h"),
        "not json",
    ]
    live = t.liveness(lines, start, end)
    assert live["window_seconds"] == 300
    assert live["longest_gap_seconds"] == 110  # 10:03:00 -> 10:04:50
    assert live["watch_seconds"] == 60 + 60 + 10  # the last call is cut at the end of the game
    assert live["watch_coverage"] == round(130 / 300, 2)
    assert live["handbacks"] == 1
    assert live["actions"] == 2  # the order and the settings edit
    assert live["median_reaction_seconds"] == 7.5  # 5 s and 10 s from a watch result to the next action


# -- best-of series --------------------------------------------------------------------------------

def series_config(seed=7):
    return t.make_config("bo3", [t.Agent(n, "opus") for n in ("Alpha", "Bravo", "Charlie", "Delta")], seed=seed, best_of=3)


def test_best_of_must_be_odd():
    for bad in (0, 2, -1):
        with pytest.raises(ValueError):
            t.make_config("x", [t.Agent(n, "opus") for n in ("A", "B")], best_of=bad)
    assert t.Config.from_json(json.loads(json.dumps(series_config().to_json()))).best_of == 3
    assert t.Config.from_json({**config().to_json(), "best_of": 1}).best_of == 1
    old = config().to_json()
    old.pop("best_of")
    assert t.Config.from_json(old).best_of == 1  # t1's config.json has no best_of


def test_series_games_and_matchup_winners():
    c = series_config()
    s = t.seeding(c)
    results = {}

    def play(winner):
        slot = t.next_game(c, results)
        loser = slot.b if winner == slot.a else slot.a
        results[str(slot.number)] = {"match": slot.match, "winner": winner, "loser": loser}
        return slot

    g = play(s[0])
    assert (g.number, g.match, g.game_in_match, g.a, g.b) == (1, 1, 1, s[0], s[3])
    g = play(s[3])
    assert (g.number, g.match, g.game_in_match) == (2, 1, 2)
    g = play(s[0])  # 2-1: the semifinal is decided
    assert (g.number, g.match, g.game_in_match) == (3, 1, 3)
    assert t.series_score(results, 1, s[0], s[3]) == (2, 1)

    g = play(s[1])
    assert (g.number, g.match, g.game_in_match, g.a, g.b) == (4, 2, 1, s[1], s[2])
    g = play(s[1])  # 2-0: no third game
    final = t.next_game(c, results)
    assert (final.number, final.match, final.game_in_match, final.a, final.b) == (6, 3, 1, s[0], s[1])
    assert t.champion(c, results) is None
    play(s[1])
    play(s[1])
    assert t.next_game(c, results) is None
    assert t.champion(c, results) == s[1]

    text = t.render_bracket(c, results)
    assert "best of 3" in text and "2–1" in text and "2–0" in text and f"Champion: **{s[1]}**" in text


def test_best_of_one_results_without_match_fields_still_work():
    c = config()
    s = t.seeding(c)
    results = {"1": {"winner": s[0], "loser": s[3]}, "2": {"winner": s[2], "loser": s[1]}}
    final = t.next_game(c, results)
    assert (final.number, final.match, final.a, final.b) == (3, 3, s[0], s[2])


def test_hosts_alternate_within_a_series():
    c = series_config()
    hosts = [t.host_for(c, t.GameSlot(n, 1, "Alpha", "Bravo", match=1, game_in_match=n)) for n in (1, 2, 3)]
    assert hosts[0] != hosts[1] and hosts[0] == hosts[2]


def test_audit_ignores_what_a_file_write_contains():
    lines = [json.dumps({"message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Write", "input": {"file_path": "C:/T/agents/Alpha/bot.py",
                                                         "content": "URL = 'ws://127.0.0.1:5000'"}},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "C:/T/agents/Bravo/notes.md", "new_string": "x"}}]}})]
    inputs = t.tool_inputs(lines)
    violations = t.find_violations(inputs, "C:/T/agents/Alpha", ["C:/T/agents/Bravo"], allowed_ports={6000})
    assert len(violations) == 1 and "another agent's workspace" in violations[0]  # the edit, not the port


def test_game_folder_finds_the_recorded_game(tmp_path):
    games = tmp_path / "games"
    (games / "2-Alpha-vs-Delta").mkdir(parents=True)          # e.g. a stray folder without a record
    (games / "2-Bravo-vs-Charlie").mkdir()
    (games / "2-Bravo-vs-Charlie" / "game.json").write_text("{}")
    assert t.game_folder(tmp_path, 2).name == "2-Bravo-vs-Charlie"
    with pytest.raises(FileNotFoundError):
        t.game_folder(tmp_path, 3)
