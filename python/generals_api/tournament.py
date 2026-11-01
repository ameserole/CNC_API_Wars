"""A single-elimination tournament between AI agents that play Zero Hour live through the script API.

The runner sets games up, referees them and keeps the records; the agents themselves are spawned by
the Claude Code session that runs the tournament (see Plans/tournament-procedure.md).

    python -m generals_api.tournament init <id> Alpha:opus Bravo:sonnet Charlie:opus Delta:haiku [--seed N]
    python -m generals_api.tournament practice <id> <agent> [--faction F] [--minutes 15]
    python -m generals_api.tournament run-game <id>                 # the next bracket game
    python -m generals_api.tournament prompt <id> prep|game <agent> [--game N]
    python -m generals_api.tournament snapshot <id> <game> <agent>
    python -m generals_api.tournament save-session <id> <agent> <label> <transcript.jsonl> [--port N ...]
    python -m generals_api.tournament bracket <id>
    python -m generals_api.tournament cleanup <id>

Layout (Plans/Phase-9-Bot-Tournament.md): tournament/<id>/{config.json, results.json, bracket.md,
agents/<name>/, games/<n>-<a>-vs-<b>/, sessions/<name>/, state/}.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import math
import os
import random
import re
import shutil
import string
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from . import launcher
from .client import ApiError, ConnectionClosed, GeneralsClient, watcher_url

ROOT = Path(__file__).resolve().parents[2]
TOURNAMENT_ROOT = ROOT / "tournament"
PROMPT_DIR = Path(__file__).resolve().parent / "tournament_prompts"
_USER_DATA = Path.home() / "OneDrive" / "Documents" / "Command and Conquer Generals Zero Hour Data"
if not _USER_DATA.exists():
    _USER_DATA = Path.home() / "Documents" / "Command and Conquer Generals Zero Hour Data"
REPLAY_DIR = _USER_DATA / "Replays"

MODELS = ("opus", "sonnet", "haiku", "fable")   # what the Agent tool accepts
BRACKET_SIZES = (2, 4, 8)
FRAMES_PER_MINUTE = 30 * 60
# The debug build raises known assertion dialogs in normal play (tests/integration/gamehost.py
# KNOWN_ASSERTIONS); an unanswered dialog blocks the game, so tournament games log them instead.
GAME_ARGS = ("-ignoreAsserts",)
# Round 1 pairings by seed (0-based), in game order: the top seeds meet as late as possible.
FIRST_ROUND = {2: [(0, 1)], 4: [(0, 3), (1, 2)], 8: [(0, 7), (3, 4), (1, 6), (2, 5)]}
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


# -- config ----------------------------------------------------------------------------------------

@dataclass
class Agent:
    name: str
    model: str


@dataclass
class Config:
    id: str
    agents: list[Agent]
    seed: int
    map: str = "tournament desert"
    game_minutes: float = 45
    iteration_minutes: float = 5
    prep_minutes: float = 15
    best_of: int = 1            # games per matchup; the first to win a majority advances

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Config":
        return cls(**{**data, "agents": [Agent(**a) for a in data["agents"]]})

    def agent(self, name: str) -> Agent:
        return next(a for a in self.agents if a.name == name)


def parse_agent_spec(spec: str) -> Agent:
    """"Alpha:opus" -> Agent("Alpha", "opus")."""
    name, _, model = spec.partition(":")
    if not _NAME.match(name):
        raise ValueError(f"agent name {name!r}: use 1-32 letters, digits, _ or -")
    if model not in MODELS:
        raise ValueError(f"model {model!r} for {name}: one of {', '.join(MODELS)}")
    return Agent(name, model)


def make_config(tournament_id: str, agents: list[Agent], seed: int | None = None, best_of: int = 1) -> Config:
    if best_of < 1 or best_of % 2 == 0:
        raise ValueError(f"best_of must be an odd number of games, not {best_of}")
    if len(agents) not in BRACKET_SIZES:
        raise ValueError(f"a bracket needs {', '.join(map(str, BRACKET_SIZES))} agents, not {len(agents)}")
    if len({a.name.lower() for a in agents}) != len(agents):
        raise ValueError("agent names must be unique")
    return Config(tournament_id, list(agents), seed if seed is not None else random.randrange(1, 1_000_000),
                  best_of=best_of)


# -- bracket ---------------------------------------------------------------------------------------

@dataclass
class GameSlot:
    """A matchup of the bracket (from bracket_games), or one game of it (from next_game)."""
    number: int                 # the game's number in playing order (for a matchup: its number)
    round: int
    a: str | None
    b: str | None
    match: int | None = None    # the matchup this game belongs to
    game_in_match: int = 1      # 1..best_of

    def __post_init__(self):
        if self.match is None:
            self.match = self.number

    @property
    def folder(self) -> str:
        return f"{self.number}-{self.a}-vs-{self.b}"


def seeding(config: Config) -> list[str]:
    names = [a.name for a in config.agents]
    random.Random(config.seed).shuffle(names)
    return names


def match_games(results: dict, match: int) -> list[dict]:
    """The recorded games of a matchup, in playing order (best-of-one results have no "match": it is the game number)."""
    games = [(int(number), r) for number, r in results.items() if r.get("match", int(number)) == match]
    return [r for _, r in sorted(games, key=lambda item: item[0])]


def series_score(results: dict, match: int, a: str, b: str) -> tuple[int, int]:
    games = match_games(results, match)
    return sum(1 for r in games if r["winner"] == a), sum(1 for r in games if r["winner"] == b)


def winner_of(results: dict, match: int, best_of: int = 1) -> str | None:
    wins: dict[str, int] = {}
    for r in match_games(results, match):
        wins[r["winner"]] = wins.get(r["winner"], 0) + 1
        if wins[r["winner"]] > best_of // 2:
            return r["winner"]
    return None


def bracket_games(config: Config, results: dict) -> list[GameSlot]:
    """Every matchup of the bracket in order; players are None until the matchups feeding it are decided."""
    seeds = seeding(config)
    matches = [GameSlot(i + 1, 1, seeds[x], seeds[y]) for i, (x, y) in enumerate(FIRST_ROUND[len(seeds)])]
    previous = matches[:]
    round_number = 1
    while len(previous) > 1:
        round_number += 1
        current = []
        for left, right in zip(previous[0::2], previous[1::2]):
            current.append(GameSlot(len(matches) + len(current) + 1, round_number,
                                    winner_of(results, left.number, config.best_of),
                                    winner_of(results, right.number, config.best_of)))
        matches += current
        previous = current
    return matches


def next_game(config: Config, results: dict) -> GameSlot | None:
    """The next game to play: the first undecided matchup with both players known."""
    for match in bracket_games(config, results):
        if match.a is None or match.b is None or winner_of(results, match.number, config.best_of) is not None:
            continue
        return GameSlot(len(results) + 1, match.round, match.a, match.b, match=match.number,
                        game_in_match=len(match_games(results, match.number)) + 1)
    return None


def champion(config: Config, results: dict) -> str | None:
    return winner_of(results, bracket_games(config, results)[-1].number, config.best_of)


def host_for(config: Config, slot: GameSlot) -> str:
    """Who hosts (and so takes the host's start position): random for a matchup's first game, then alternating."""
    first = slot.a if random.Random(f"{config.seed}-{slot.match}").random() < 0.5 else slot.b
    other = slot.b if first == slot.a else slot.a
    return first if slot.game_in_match % 2 == 1 else other


def round_name(round_number: int, rounds: int) -> str:
    return {0: "Final", 1: "Semifinals", 2: "Quarterfinals"}.get(rounds - round_number, f"Round {round_number}")


def _game_text(result: dict, a: str, b: str) -> str:
    text = f"**{result['winner']}**"
    reason = result.get("reason")
    if reason == "game_over":
        return text + " (destroyed the opponent)"
    if reason:
        text += f" ({reason.replace('_', ' ')}"
        scores = result.get("scores")
        if scores:
            text += ", score " + " – ".join(str(scores.get(n)) for n in (a, b))
        if result.get("tiebreak") == "coin":
            text += ", level on score and buildings: coin toss"
        text += ")"
    return text


def render_bracket(config: Config, results: dict) -> str:
    matches = bracket_games(config, results)
    rounds = matches[-1].round
    models = {a.name: a.model for a in config.agents}
    series = "best of one" if config.best_of == 1 else f"best of {config.best_of}"
    lines = [f"# Tournament {config.id}", "",
             f"Map: {config.map} · {config.game_minutes:g} min games · {series} · seeds: "
             + ", ".join(f"{i + 1}. {name}" for i, name in enumerate(seeding(config))), ""]
    for round_number in range(1, rounds + 1):
        lines += [f"## {round_name(round_number, rounds)}", ""]
        for match in (m for m in matches if m.round == round_number):
            games = match_games(results, match.number)

            def label(name):
                if name is None:
                    return "_tbd_"
                factions = sorted({g.get("factions", {}).get(name) for g in games} - {None})
                return f"{name} ({models[name]}{', ' + '/'.join(factions) if factions else ''})"
            if config.best_of == 1:
                line = f"- Game {match.number}: {label(match.a)} vs {label(match.b)}"
                if games:
                    line += " → " + _game_text(games[0], match.a, match.b)
                lines.append(line)
                continue
            line = f"- Match {match.number}: {label(match.a)} vs {label(match.b)}"
            winner = winner_of(results, match.number, config.best_of)
            if games:
                wa, wb = series_score(results, match.number, match.a, match.b)
                line += f" → **{winner}** {max(wa, wb)}–{min(wa, wb)}" if winner else f" (series {wa}–{wb})"
            lines.append(line)
            numbers = sorted(int(n) for n, r in results.items() if r.get("match", int(n)) == match.number)
            for k, number in enumerate(numbers, 1):
                lines.append(f"  - Game {number} ({k} of {config.best_of}): " + _game_text(results[str(number)], match.a, match.b))
        lines.append("")
    winner = champion(config, results)
    lines.append(f"Champion: **{winner}**" if winner else "Champion: _to be decided_")
    return "\n".join(lines) + "\n"


# -- deciding a game at the time limit -------------------------------------------------------------

def decide_by_score(a: str, a_stats: dict, b: str, b_stats: dict) -> str | None:
    """The higher score (the score screen's), then more buildings destroyed; None if still level."""
    for key in ("score", "buildings_destroyed"):
        if a_stats.get(key, 0) != b_stats.get(key, 0):
            return a if a_stats.get(key, 0) > b_stats.get(key, 0) else b
    return None


# -- manifests -------------------------------------------------------------------------------------

class ManifestError(ValueError):
    pass


def load_manifest(path: Path, allowed: Iterable[str]) -> dict:
    """bot.json: {"faction": F, "vs": {opponent: F}}; every F one of `allowed` (no "random")."""
    allowed = list(allowed)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError(f"{path} does not exist") from None
    except (OSError, ValueError) as error:
        raise ManifestError(f"{path} is not valid JSON: {error}") from None
    if not isinstance(data, dict):
        raise ManifestError("bot.json must be a JSON object")
    if data.get("faction") not in allowed:
        raise ManifestError(f"faction {data.get('faction')!r} is not one of {', '.join(allowed)}")
    vs = data.get("vs", {})
    if not isinstance(vs, dict) or any(not isinstance(k, str) or v not in allowed for k, v in vs.items()):
        raise ManifestError("vs must map opponent names to factions from the same list")
    return {"faction": data["faction"], "vs": dict(vs)}


def resolve_faction(manifest: dict, opponent: str) -> str:
    return manifest.get("vs", {}).get(opponent, manifest["faction"])


def side_of(faction: str) -> str:
    """What catalog()["faction"] reports for a faction: "FactionChinaTankGeneral" -> "ChinaTankGeneral"."""
    return faction[len("Faction"):] if faction.startswith("Faction") else faction


def effective_manifest(workspace: Path, saved: Path, allowed: Iterable[str]) -> tuple[dict, str | None]:
    """The workspace's bot.json if valid (kept as the last valid one), else the last valid one with a warning."""
    allowed = list(allowed)
    try:
        manifest = load_manifest(Path(workspace) / "bot.json", allowed)
    except ManifestError as error:
        if not Path(saved).exists():
            raise
        manifest = load_manifest(saved, allowed)
        return manifest, f"bot.json was rejected ({error}); the last valid one ({manifest['faction']}) is used"
    Path(saved).parent.mkdir(parents=True, exist_ok=True)
    Path(saved).write_text(json.dumps(manifest, indent=2))
    return manifest, None


# -- audit -----------------------------------------------------------------------------------------

_PORT = re.compile(r"(?:127\.0\.0\.1|localhost):(\d{2,5})", re.IGNORECASE)
_KILL = re.compile(r"taskkill|stop-process|\bkill\b|terminate", re.IGNORECASE)


def _norm(text: str) -> str:
    return text.replace("\\\\", "/").replace("\\", "/").lower()


def find_violations(texts: Iterable[str], own_workspace: str | Path, other_workspaces: Iterable[str | Path],
                    allowed_ports: Iterable[int]) -> list[str]:
    """Rule breaks in an agent's tool calls: other agents' workspaces, other game ports, killing games."""
    others = [re.compile(re.escape(_norm(str(w))) + r"(?![a-z0-9_-])") for w in other_workspaces]
    allowed_ports = set(allowed_ports)
    violations = []
    for text in texts:
        norm = _norm(text)
        short = text if len(text) < 160 else text[:157] + "..."
        if any(pattern.search(norm) for pattern in others):
            violations.append(f"another agent's workspace: {short}")
        for port in {int(p) for p in _PORT.findall(text)} - allowed_ports:
            violations.append(f"port {port} is not this agent's: {short}")
        if "generalszh" in norm and _KILL.search(text):
            violations.append(f"touches a game process: {short}")
    return violations


def tool_inputs(lines: Iterable[str]) -> list[str]:
    """The inputs of every tool call in a transcript (JSONL), as JSON text."""
    inputs = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if message is None or message.get("role") != "assistant" or not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                inp = item.get("input")
                # What a file write or edit puts in the file isn't an action: only where it writes counts.
                if item.get("name") in ("Write", "Edit", "NotebookEdit") and isinstance(inp, dict):
                    inp = {"file_path": inp.get("file_path") or inp.get("notebook_path")}
                inputs.append(json.dumps(inp))
    return inputs


# -- liveness --------------------------------------------------------------------------------------

def _when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def liveness(lines: Iterable[str], start: datetime, end: datetime) -> dict:
    """How live an agent was during a game, from its transcript (JSONL) between start and end (UTC).

    longest_gap_seconds: the longest stretch without a tool call (from the start to the first call
    and from the last call to the end count too). watch_seconds/watch_coverage: time spent inside a
    foreground `watch`. actions: orders sent with `order` and edits of settings.json or strategy.py.
    median_reaction_seconds: from a `watch` returning to the next action.
    """
    uses: list[tuple[datetime, str, dict]] = []
    results: dict[str, datetime] = {}
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        if not isinstance(message, dict) or "timestamp" not in entry:
            continue
        when = _when(entry["timestamp"])
        for item in message.get("content") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "tool_use":
                uses.append((when, item.get("id", ""), {"name": item.get("name"), **(item.get("input") or {})}))
            elif item.get("type") == "tool_result":
                results[item.get("tool_use_id", "")] = when

    in_game = [(when, uid, inp) for when, uid, inp in uses if start <= when <= end]
    times = [start] + [when for when, _, _ in in_game] + [end]
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]

    def is_watch(inp):
        return "generals_api.watch" in str(inp.get("command", "")) and not inp.get("run_in_background")

    def is_action(inp):
        if "generals_api.order" in str(inp.get("command", "")):
            return True
        path = str(inp.get("file_path", ""))
        return inp.get("name") in ("Edit", "Write") and (path.endswith("settings.json") or path.endswith("strategy.py"))

    watch_seconds = 0.0
    returns = []
    for when, uid, inp in in_game:
        if is_watch(inp):
            done = results.get(uid, end)
            watch_seconds += (min(done, end) - when).total_seconds()
            if done <= end:
                returns.append(done)
    actions = [when for when, _, inp in in_game if is_action(inp)]
    reactions = []
    for done in returns:
        later = [a for a in actions if a >= done]
        if later:
            reactions.append((min(later) - done).total_seconds())
    reactions.sort()
    median = None
    if reactions:
        middle = len(reactions) // 2
        median = reactions[middle] if len(reactions) % 2 else (reactions[middle - 1] + reactions[middle]) / 2
    window = (end - start).total_seconds()
    return {
        "window_seconds": round(window),
        "longest_gap_seconds": round(max(gaps)) if gaps else round(window),
        "watch_seconds": round(watch_seconds),
        "watch_coverage": round(watch_seconds / window, 2) if window else 0,
        "handbacks": sum(1 for _, _, inp in in_game if inp.get("name") == "SubagentHandback"),
        "actions": len(actions),
        "median_reaction_seconds": median,
    }


# -- prompts ---------------------------------------------------------------------------------------

def render_prompt(kind: str, config: Config, root: Path, agent: str, *, port: int | None = None,
                  opponent: str | None = None, game: int | None = None, faction: str | None = None,
                  opponent_faction: str | None = None, notice: str | None = None, series: str = "") -> str:
    template = string.Template((PROMPT_DIR / f"{kind}.md").read_text(encoding="utf-8"))
    workspace = Path(root) / "agents" / agent
    return template.substitute(
        agent=agent, model=config.agent(agent).model, tournament=config.id, root=Path(root),
        workspace=workspace, python=ROOT / "python" / ".venv" / "Scripts" / "python.exe",
        package=ROOT / "python", repo=ROOT, port=port if port is not None else "(see below)",
        opponent=opponent or "", game=game or "", faction=faction or "", opponent_faction=opponent_faction or "",
        game_minutes=f"{config.game_minutes:g}", iteration_minutes=f"{config.iteration_minutes:g}",
        prep_minutes=f"{config.prep_minutes:g}", map=config.map, notice=notice or "", series=series,
        series_rule="each match is one game" if config.best_of == 1 else
        f"each match is best of {config.best_of}: the first to win {config.best_of // 2 + 1} games advances",
        others=", ".join(a.name for a in config.agents if a.name != agent))


# -- files -----------------------------------------------------------------------------------------

def tournament_root(tournament_id: str) -> Path:
    return TOURNAMENT_ROOT / tournament_id


def init_tournament(root: Path, config: Config) -> None:
    root = Path(root)
    for agent in config.agents:
        workspace = root / "agents" / agent.name
        (workspace / "reports").mkdir(parents=True, exist_ok=True)
        (root / "sessions" / agent.name).mkdir(parents=True, exist_ok=True)
        for name, title in (("notes.md", "Notes"), ("journal.md", "Journal")):
            if not (workspace / name).exists():
                (workspace / name).write_text(f"# {agent.name}: {title}\n")
    for folder in ("games", "state"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(json.dumps(config.to_json(), indent=2))
    if not (root / "results.json").exists():
        save_results(root, config, {})


def load_config(root: Path) -> Config:
    return Config.from_json(json.loads((Path(root) / "config.json").read_text()))


def load_results(root: Path) -> dict:
    path = Path(root) / "results.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_results(root: Path, config: Config, results: dict) -> None:
    (Path(root) / "results.json").write_text(json.dumps(results, indent=2))
    (Path(root) / "bracket.md").write_text(render_bracket(config, results), encoding="utf-8")


def snapshot_workspace(root: Path, game_folder: str, agent: str) -> Path:
    target = Path(root) / "games" / game_folder / f"workspace-{agent}"
    shutil.copytree(Path(root) / "agents" / agent, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return target


def process_running(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


# -- running a game --------------------------------------------------------------------------------

Log = Callable[[str], None]


def _log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


async def _connect(port: int, timeout: float = 60) -> GeneralsClient:
    client = await GeneralsClient(f"ws://127.0.0.1:{port}", request_timeout=timeout).connect()
    await client.hello()
    return client


async def _quietly(awaitable) -> Any:
    try:
        return await awaitable
    except (ApiError, ConnectionClosed, asyncio.TimeoutError, OSError):
        return None


async def _close_instances(procs: dict[str, subprocess.Popen], ports: dict[str, int], log: Log) -> None:
    """Exits every instance through the API (a new connection supersedes any agent), then kills stragglers."""
    for role, port in ports.items():
        if procs[role].poll() is None:
            client = await _quietly(_connect(port, 30))
            if client is not None:
                await _quietly(client.exit())
                await client.close()
    for role, proc in procs.items():
        try:
            # A debug build's shutdown (memory checks) can take most of a minute on a busy PC.
            await asyncio.to_thread(proc.wait, 120)
        except subprocess.TimeoutExpired:
            log(f"{role} did not exit; killing it")
            proc.kill()


async def _save_replay(port: int, name: str, target: Path, log: Log) -> bool:
    client = await _quietly(_connect(port, 60))
    if client is None:
        return False
    try:
        await client.wait_for_state("shell", timeout=90)
        saved = await client.save_replay(name, overwrite=True)
        shutil.copyfile(REPLAY_DIR / saved["file"], target)
        return True
    except (ApiError, ConnectionClosed, asyncio.TimeoutError, OSError) as error:
        log(f"replay not saved: {error}")
        return False
    finally:
        await client.close()


async def _start_positions(observer: GeneralsClient, info: dict, names: dict[int, str]) -> dict[str, int]:
    """Which map start each player has: the start nearest its command center (the observer sees all)."""
    starts = info["start_positions"]
    result = {}
    for obj in (await observer.state())["visible"]:
        if obj["template"].endswith("CommandCenter") and obj["owner"] in names and starts:
            nearest = min(range(len(starts)), key=lambda i: math.dist(starts[i], obj["pos"][:2]))
            result.setdefault(names[obj["owner"]], nearest + 1)
    return result


async def run_game(root: Path, slot: GameSlot, *, on_ready: Callable[[dict], Awaitable[None]] | None = None,
                   extra_args: Iterable[str] = GAME_ARGS, game_dir: Path = launcher.DEFAULT_GAME_DIR,
                   log: Log = _log) -> dict:
    """Sets up a bracket game with both agents' factions, referees it to the end and records it.

    on_ready(info) runs once the game is in progress and the players' API ports are free for the
    agents: info = {"folder", "players": {name: {"port", "faction"}}}.
    """
    root = Path(root)
    config = load_config(root)
    game_path = root / "games" / slot.folder
    game_path.mkdir(parents=True, exist_ok=True)
    rng = random.Random(f"{config.seed}-{slot.number}")
    host = host_for(config, slot)
    guest = slot.b if host == slot.a else slot.a
    names = {"bot1": host, "bot2": guest}
    roles = {host: "bot1", guest: "bot2"}
    instances = [launcher.Instance("bot1", host, launcher.free_port(), "view", bot=Path("live agent")),
                 launcher.Instance("bot2", guest, launcher.free_port(), "view", bot=Path("live agent")),
                 launcher.Instance("observer", "Referee", launcher.free_port(), "full")]
    plan = launcher.Plan("lan", instances, slots=[{"type": "host"}, {"type": "open"}, {"type": "open"}])
    ports = {i.role: i.port for i in instances}
    record: dict = {"number": slot.number, "round": slot.round, "match": slot.match, "game_in_match": slot.game_in_match,
                    "best_of": config.best_of, "folder": slot.folder, "players": [slot.a, slot.b],
                    "host": host, "models": {n: config.agent(n).model for n in (slot.a, slot.b)},
                    "ports": {names[r]: p for r, p in ports.items() if r != "observer"},
                    "observer_port": ports["observer"], "started": time.strftime("%Y-%m-%d %H:%M:%S"), "warnings": {}}

    procs: dict[str, subprocess.Popen] = {}
    clients: dict[str, GeneralsClient] = {}
    try:
        for inst in instances:
            procs[inst.role] = launcher.launch(inst, game_dir, list(extra_args))
        record["pids"] = {r: p.pid for r, p in procs.items()}
        for inst in instances:
            await launcher.wait_for_port(inst.port, procs[inst.role])
            clients[inst.role] = await _connect(inst.port)
        options = await clients["bot1"].skirmish_options()
        allowed = [f["name"] for f in options["factions"]]
        factions = {}
        for name in (host, guest):
            opponent = guest if name == host else host
            manifest, warning = effective_manifest(root / "agents" / name, root / "state" / f"{name}-manifest.json", allowed)
            factions[name] = resolve_faction(manifest, opponent)
            if warning:
                record["warnings"][name] = warning
        record["factions"] = {n: factions[n] for n in (slot.a, slot.b)}
        for inst in instances[:2]:
            inst.faction = factions[inst.name]
        log(f"game {slot.number}: {host} ({factions[host]}) hosts {guest} ({factions[guest]})")
        await launcher.setup_lan(plan, clients, launcher.pick_map(options, config.map))
        for client in clients.values():
            await client.wait_for_state("in_game", timeout=launcher.LOAD_TIMEOUT)
        for role in ("bot1", "bot2"):
            side = (await clients[role].catalog())["faction"]
            if side != side_of(factions[names[role]]):
                raise RuntimeError(f"{names[role]} plays {side}, not {factions[names[role]]}")

        observer = clients["observer"]
        info = await observer.game_info()
        index_names = {p["index"]: p["name"] for p in info["players"]}
        record["start_positions"] = await _start_positions(observer, info, index_names)
        for role in ("bot1", "bot2"):
            await clients.pop(role).close()

        game_over: asyncio.Future = asyncio.get_running_loop().create_future()
        observer.on("game_over", lambda e: game_over.done() or game_over.set_result(e))
        (game_path / "game.json").write_text(json.dumps({**record, "status": "running"}, indent=2))
        ready = {"folder": slot.folder, "players": {n: {"port": record["ports"][n], "faction": factions[n]}
                                                    for n in (slot.a, slot.b)}}
        log("READY " + json.dumps(ready))
        if on_ready is not None:
            await on_ready(ready)

        # Referee: until the game is decided, the time runs out, or a game process dies.
        limit = int(config.game_minutes * FRAMES_PER_MINUTE)
        reason, stats, winner_indices, frame = None, None, [], 0
        while reason is None:
            if game_over.done():
                event = game_over.result()
                reason, stats, winner_indices, frame = "game_over", event["stats"], event["winners"], event["frame"]
                break
            if any(procs[r].poll() is not None for r in procs):
                reason = "crash"
            else:
                frame = (await observer.request("ping"))["frame"]
                if frame >= limit:
                    reason = "time_limit"
            if reason is not None:
                stats = (await _quietly(observer.player_stats()) or {}).get("players", [])
                break
            await asyncio.sleep(2)
        log(f"game {slot.number} ended at frame {frame}: {reason}")

        for entry in stats:
            entry["name"] = index_names.get(entry["index"])
        by_name = {e["name"]: e for e in stats if e.get("name")}
        winners = [index_names[i] for i in winner_indices if i in index_names]
        tiebreak = None
        if len(winners) == 1:
            winner = winners[0]
        else:
            winner = decide_by_score(slot.a, by_name.get(slot.a, {}), slot.b, by_name.get(slot.b, {}))
            tiebreak = "score"
            if winner is None:
                winner, tiebreak = rng.choice([slot.a, slot.b]), "coin"
        loser = slot.b if winner == slot.a else slot.a

        # Leave the game: a decided game goes to the score screen by itself; otherwise both players quit.
        if reason != "game_over":
            for role in ("bot1", "bot2"):
                if procs[role].poll() is None:
                    client = await _quietly(_connect(ports[role], 30))
                    if client is not None:
                        await _quietly(client.quit_game())
                        await client.close()
        await _quietly(observer.wait_for_state("shell", timeout=90))
        replay_saved = procs["bot1"].poll() is None and await _save_replay(
            ports["bot1"], f"{config.id} game {slot.number}", game_path / "replay.rep", log)

        record.update(status="done", reason=reason, tiebreak=tiebreak, winner=winner, loser=loser, frames=frame,
                      game_minutes=round(frame / FRAMES_PER_MINUTE, 2), stats=stats, replay=bool(replay_saved),
                      ended=time.strftime("%Y-%m-%d %H:%M:%S"))
    finally:
        for client in clients.values():
            await client.close()
        await _close_instances(procs, ports, log)

    (game_path / "game.json").write_text(json.dumps(record, indent=2))
    results = load_results(root)
    results[str(slot.number)] = {
        "match": slot.match, "game_in_match": slot.game_in_match,
        "winner": record["winner"], "loser": record["loser"], "reason": record["reason"], "tiebreak": record["tiebreak"],
        "factions": record["factions"], "frames": record["frames"], "folder": slot.folder,
        "scores": {n: by_name.get(n, {}).get("score") for n in (slot.a, slot.b)},
    }
    save_results(root, config, results)
    for name in (slot.a, slot.b):
        opponent = slot.b if name == slot.a else slot.a
        wins = series_score(results, slot.match, name, opponent)
        report = {"game": slot.number, "round": round_name(slot.round, bracket_games(config, results)[-1].round),
                  "series": f"game {slot.game_in_match} of best of {config.best_of}; you {wins[0]}, {opponent} {wins[1]}",
                  "opponent": opponent, "your_faction": record["factions"][name],
                  "opponent_faction": record["factions"][opponent], "result": "win" if name == record["winner"] else "loss",
                  "reason": record["reason"], "tiebreak": record["tiebreak"], "game_minutes": record["game_minutes"],
                  "stats": stats, "warning": record["warnings"].get(name)}
        (root / "agents" / name / "reports" / f"game-{slot.number}.json").write_text(json.dumps(report, indent=2))
    return record


# -- practice --------------------------------------------------------------------------------------

async def run_practice(root: Path, agent: str, *, faction: str | None, minutes: float, ai: str = "easy",
                       extra_args: Iterable[str] = GAME_ARGS, game_dir: Path = launcher.DEFAULT_GAME_DIR,
                       log: Log = _log) -> dict:
    """A skirmish for one agent against the built-in AI; ends at game_over or after `minutes` of wall time."""
    root = Path(root)
    config = load_config(root)
    instance = launcher.Instance("bot1", agent, launcher.free_port(), "view", bot=Path("live agent"))
    proc = launcher.launch(instance, game_dir, list(extra_args))
    state_file = root / "state" / f"practice-{agent}.json"
    state_file.write_text(json.dumps({"port": instance.port, "pid": proc.pid}))
    ports_file = root / "state" / f"practice-ports-{agent}.json"   # kept: the audit allows these ports
    known = json.loads(ports_file.read_text()) if ports_file.exists() else []
    ports_file.write_text(json.dumps(known + [instance.port]))
    report: dict = {"agent": agent, "ai": ai, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        await launcher.wait_for_port(instance.port, proc)
        client = await _connect(instance.port)
        options = await client.skirmish_options()
        allowed = [f["name"] for f in options["factions"]]
        if faction is None:
            faction = load_manifest(root / "agents" / agent / "bot.json", allowed)["faction"]
        elif faction not in allowed:
            raise ManifestError(f"faction {faction!r} is not one of {', '.join(allowed)}")
        report["faction"] = faction
        await client.start_skirmish(launcher.pick_map(options, config.map),
                                    [{"type": "script", "faction": faction}, {"type": launcher.AI_SLOTS[ai], "faction": "random"}])
        await client.wait_for_state("in_game", timeout=launcher.LOAD_TIMEOUT)
        await client.close()
        # A watcher stays connected for the whole game, so the end is seen while the agent's bot is
        # the controller.
        watcher = await GeneralsClient(watcher_url(f"ws://127.0.0.1:{instance.port}"), request_timeout=30).connect()
        await watcher.hello()
        game_over: asyncio.Future = asyncio.get_running_loop().create_future()
        watcher.on("game_over", lambda e: game_over.done() or game_over.set_result(e))
        log(f"PRACTICE READY port {instance.port} faction {faction}")
        deadline = time.monotonic() + minutes * 60
        while not game_over.done() and time.monotonic() < deadline and proc.poll() is None:
            await asyncio.sleep(2)
        if game_over.done():
            event = game_over.result()
            report.update(result=event.get("result"), stats=event.get("stats"), frames=event.get("frame"))
        else:
            report["stats"] = (await _quietly(watcher.player_stats()) or {}).get("players")
            report["result"] = "ended by time"
            # The agent's bot is replaced here; it is told the practice ends at the deadline.
            client = await _quietly(_connect(instance.port, 30))
            if client is not None:
                if client.game_state == "in_game":
                    await _quietly(client.quit_game())
                await client.close()
        await watcher.close()
        log(f"PRACTICE OVER {report['result']}")
    finally:
        await _close_instances({"bot1": proc}, {"bot1": instance.port}, log)
        state_file.unlink(missing_ok=True)
    count = len(list((root / "agents" / agent / "reports").glob("practice-*.json")))
    (root / "agents" / agent / "reports" / f"practice-{count + 1}.json").write_text(json.dumps(report, indent=2))
    return report


async def dump_factions(root: Path, *, extra_args: Iterable[str] = GAME_ARGS, game_dir: Path = launcher.DEFAULT_GAME_DIR,
                        log: Log = _log) -> list[str]:
    """Writes factions/<Faction>.json (faction_catalog) for every selectable faction: shared reference data."""
    target = Path(root) / "factions"
    target.mkdir(parents=True, exist_ok=True)
    instance = launcher.Instance("bot1", "Factions", launcher.free_port(), "view", bot=Path("catalog"))
    proc = launcher.launch(instance, game_dir, list(extra_args))
    try:
        await launcher.wait_for_port(instance.port, proc)
        client = await _connect(instance.port)
        names = [f["name"] for f in (await client.skirmish_options())["factions"]]
        for name in names:
            (target / f"{name}.json").write_text(json.dumps(await client.faction_catalog(name), indent=1))
        await client.close()
        log(f"wrote {len(names)} faction catalogs to {target}")
        return names
    finally:
        await _close_instances({"bot1": proc}, {"bot1": instance.port}, log)


def cleanup(root: Path) -> list[int]:
    """Kills practice games left running (e.g. after a preparation session was stopped)."""
    killed = []
    for state in (Path(root) / "state").glob("practice-*.json"):
        if state.name.startswith("practice-ports-"):
            continue
        pid = json.loads(state.read_text()).get("pid")
        if pid and process_running(pid):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            killed.append(pid)
        state.unlink(missing_ok=True)
    return killed


# -- command line ----------------------------------------------------------------------------------

def save_session(root: Path, agent: str, label: str, transcript: Path, ports: Iterable[int],
                 window: tuple[datetime, datetime] | None = None) -> list[str]:
    """Keeps an agent session's conversation and audits it (and, for a game, how live the agent was);
    returns the violations."""
    root = Path(root)
    config = load_config(root)
    target = root / "sessions" / agent / f"{label}.jsonl"
    shutil.copyfile(transcript, target)
    text = target.read_text(encoding="utf-8", errors="replace")
    # The agent's own practice games print their ports; those are allowed too.
    ports = set(ports) | {int(p) for p in re.findall(r"PRACTICE READY port (\d+)", text)}
    ports_file = root / "state" / f"practice-ports-{agent}.json"
    if ports_file.exists():
        ports |= set(json.loads(ports_file.read_text()))
    others = [root / "agents" / a.name for a in config.agents if a.name != agent]
    violations = find_violations(tool_inputs(text.splitlines()), root / "agents" / agent, others, ports)
    audit: dict = {"violations": violations}
    if window is not None:
        audit["liveness"] = liveness(text.splitlines(), *window)
    (root / "sessions" / agent / f"{label}.audit.json").write_text(json.dumps(audit, indent=2))
    return violations


def game_folder(root: Path, number: int) -> Path:
    """The folder of a game that was played (it has a game.json); numbers are in playing order."""
    for folder in (Path(root) / "games").glob(f"{number}-*"):
        if (folder / "game.json").exists():
            return folder
    raise FileNotFoundError(f"no recorded game {number} in {Path(root) / 'games'}")


def game_window(root: Path, number: int) -> tuple[datetime, datetime]:
    """A recorded game's start and end (game.json keeps local times), in UTC."""
    folder = game_folder(root, number)
    game = json.loads((folder / "game.json").read_text())
    local = lambda text: datetime.strptime(text, "%Y-%m-%d %H:%M:%S").astimezone(timezone.utc)
    return local(game["started"]), local(game["ended"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m generals_api.tournament", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("id")
    p.add_argument("agents", nargs="+", help="Name:model, e.g. Alpha:opus")
    p.add_argument("--seed", type=int)
    p.add_argument("--best-of", type=int, default=1, help="games per matchup (odd)")
    p = sub.add_parser("practice")
    p.add_argument("id")
    p.add_argument("agent")
    p.add_argument("--faction")
    p.add_argument("--minutes", type=float)
    p.add_argument("--ai", choices=sorted(launcher.AI_SLOTS), default="easy")
    p = sub.add_parser("run-game")
    p.add_argument("id")
    p = sub.add_parser("prompt")
    p.add_argument("id")
    p.add_argument("kind", choices=["prep", "game"])
    p.add_argument("agent")
    p.add_argument("--port", type=int)
    p.add_argument("--game", type=int)
    p = sub.add_parser("snapshot")
    p.add_argument("id")
    p.add_argument("game", type=int)
    p.add_argument("agent")
    p = sub.add_parser("save-session")
    p.add_argument("id")
    p.add_argument("agent")
    p.add_argument("label")
    p.add_argument("transcript", type=Path)
    p.add_argument("--port", type=int, action="append", default=[])
    p.add_argument("--game", type=int, help="measure liveness during this game")
    for name in ("bracket", "cleanup"):
        sub.add_parser(name).add_argument("id")
    args = parser.parse_args(argv)
    root = tournament_root(args.id)

    if args.command == "init":
        config = make_config(args.id, [parse_agent_spec(s) for s in args.agents], args.seed, args.best_of)
        init_tournament(root, config)
        asyncio.run(dump_factions(root))
        print(render_bracket(config, {}))
        return 0
    config = load_config(root)
    results = load_results(root)
    if args.command == "practice":
        minutes = args.minutes if args.minutes is not None else config.prep_minutes
        print(json.dumps(asyncio.run(run_practice(root, args.agent, faction=args.faction, minutes=minutes, ai=args.ai)), indent=2))
    elif args.command == "run-game":
        slot = next_game(config, results)
        if slot is None:
            print(f"no game left; champion: {champion(config, results)}")
            return 0
        record = asyncio.run(run_game(root, slot))
        print("RESULT " + json.dumps({k: record[k] for k in ("number", "winner", "loser", "reason", "tiebreak", "game_minutes")}))
    elif args.command == "prompt":
        kwargs: dict = {"port": args.port}
        if args.kind == "game":
            # The game being played: the running one is recorded as "running" and not yet in results.
            slot = next_game(config, results)
            if args.game and (slot is None or slot.number != args.game):
                folder = game_folder(root, args.game)
                recorded = json.loads((folder / "game.json").read_text())
                slot = GameSlot(recorded["number"], recorded["round"], *recorded["players"],
                                match=recorded.get("match"), game_in_match=recorded.get("game_in_match", 1))
            game_file = root / "games" / slot.folder / "game.json"
            game = json.loads(game_file.read_text()) if game_file.exists() else {}
            opponent = slot.b if args.agent == slot.a else slot.a
            series = ""
            if config.best_of > 1:
                mine, theirs = series_score(results, slot.match, args.agent, opponent)
                series = (f"This match is **best of {config.best_of}**: this is game {slot.game_in_match}, and the series "
                          f"stands {mine}–{theirs} (you–{opponent}). The first to {config.best_of // 2 + 1} wins advances.")
            kwargs.update(game=slot.number, opponent=opponent, port=args.port or game.get("ports", {}).get(args.agent),
                          faction=game.get("factions", {}).get(args.agent),
                          notice=game.get("warnings", {}).get(args.agent), series=series)
        print(render_prompt(args.kind, config, root, args.agent, **kwargs))
    elif args.command == "snapshot":
        print(snapshot_workspace(root, game_folder(root, args.game).name, args.agent))
    elif args.command == "save-session":
        window = game_window(root, args.game) if args.game else None
        violations = save_session(root, args.agent, args.label, args.transcript, args.port, window)
        print((root / "sessions" / args.agent / f"{args.label}.audit.json").read_text())
        return 1 if violations else 0
    elif args.command == "bracket":
        print(render_bracket(config, results))
    elif args.command == "cleanup":
        print(json.dumps({"killed": cleanup(root)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
