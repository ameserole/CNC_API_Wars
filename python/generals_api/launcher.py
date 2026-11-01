"""Starts game instances and plays bot scripts in them, optionally with a human observer.

    python -m generals_api.launcher --bot1 bots/simple.py --bot2 bots/simple.py [--observer] [--map NAME]
    python -m generals_api.launcher --bot1 bots/simple.py --vs-ai easy|medium|hard [--ai-faction China] [--observer]

Bot vs built-in AI without an observer is a plain skirmish. Every other mode is a LAN game on this PC:
bot 1 hosts, bot 2 and the observer join by IP. A bot script is a module with
`async def run(client: GeneralsClient, world: World)`.

After the match, bot 1's replay is kept in the replay folder as <--replay>.rep (default: date, bots and
opponent).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import socket
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from .client import ApiError, GeneralsClient
from .world import World

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAME_DIR = ROOT / "GameFiles"
GAME_EXE = "generalszh.exe"
WINDOW_ARGS = ["-win", "-nologo", "-noshellmap", "-xres", "800", "-yres", "600"]
AI_SLOTS = {"easy": "easy_ai", "medium": "medium_ai", "hard": "hard_ai"}
DEFAULT_MAP = "tournament desert"
LOAD_TIMEOUT = 180.0

BotRun = Callable[[GeneralsClient, World], Awaitable[Any]]


@dataclass
class Instance:
    role: str                   # "bot1", "bot2" or "observer"
    name: str                   # LAN player name
    port: int
    input_mode: str             # -scriptApiInput
    bot: Path | None = None
    faction: str = "random"
    apm: int = 0                # -scriptApiApm for bots; 0 for no cap

    def args(self, extra: list[str] = ()) -> list[str]:
        args = [*WINDOW_ARGS, "-scriptApiPort", str(self.port), "-scriptApiInput", self.input_mode]
        if self.bot is not None:
            args.append("-noaudio")  # only the observer's window makes sound
            if self.apm > 0:
                args += ["-scriptApiApm", str(self.apm)]
        return [*args, *extra]


@dataclass
class Plan:
    mode: str                   # "skirmish" or "lan"
    instances: list[Instance]
    slots: list[dict] = field(default_factory=list)   # lan_host slots (LAN mode)
    ai: dict | None = None      # the built-in AI player, if any

    def instance(self, role: str) -> Instance | None:
        return next((i for i in self.instances if i.role == role), None)

    @property
    def bots(self) -> list[Instance]:
        return [i for i in self.instances if i.bot is not None]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def faction_name(name: str | None) -> str:
    """"China" or "FactionChina" -> "FactionChina"; None or "random" -> "random"."""
    if not name or name.lower() == "random":
        return "random"
    return name if name.startswith("Faction") else f"Faction{name}"


def make_plan(args: argparse.Namespace, ports: list[int] | None = None) -> Plan:
    """Decides the instances, ports and slots for the command line, without starting anything."""
    if (args.bot2 is None) == (args.vs_ai is None):
        raise ValueError("pass exactly one of --bot2 or --vs-ai")
    ports = list(ports) if ports else []

    def port() -> int:
        return ports.pop(0) if ports else free_port()

    apm = getattr(args, "apm", 0) or 0
    instances = [Instance("bot1", "Bot1", port(), "view", Path(args.bot1), faction_name(args.bot1_faction), apm)]
    if args.bot2 is not None:
        instances.append(Instance("bot2", "Bot2", port(), "view", Path(args.bot2), faction_name(args.bot2_faction), apm))
    if args.observer:
        instances.append(Instance("observer", "Observer", port(), "full"))

    ai = None
    if args.vs_ai is not None:
        ai = {"type": AI_SLOTS[args.vs_ai], "faction": faction_name(args.ai_faction)}

    if ai is not None and not args.observer:
        return Plan("skirmish", instances, ai=ai)

    slots = [{"type": "host"}, ai if ai is not None else {"type": "open"}]
    if args.observer:
        slots.append({"type": "open"})
    return Plan("lan", instances, slots=slots, ai=ai)


def replay_name(args: argparse.Namespace, now: datetime | None = None) -> str | None:
    """The name bot 1's replay is saved under: --replay, None for --no-replay, else date, bots and opponent."""
    if getattr(args, "no_replay", False):
        return None
    if getattr(args, "replay", None):
        return args.replay
    opponent = Path(args.bot2).stem if args.bot2 is not None else f"{args.vs_ai}-ai"
    return f"{(now or datetime.now()):%Y%m%d-%H%M%S}_{Path(args.bot1).stem}_vs_{opponent}"


def load_bot(path: Path) -> BotRun:
    spec = importlib.util.spec_from_file_location(f"generals_bot_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load bot script {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = getattr(module, "run", None)
    if run is None or not asyncio.iscoroutinefunction(run):
        raise ValueError(f"{path} has no `async def run(client, world)`")
    return run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m generals_api.launcher", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bot1", required=True, help="bot script for player 1 (hosts LAN games)")
    parser.add_argument("--bot2", help="bot script for player 2")
    parser.add_argument("--vs-ai", choices=sorted(AI_SLOTS), help="play bot 1 against the built-in AI")
    parser.add_argument("--ai-faction", help="the AI's faction, e.g. China (default random)")
    parser.add_argument("--bot1-faction", default="America")
    parser.add_argument("--bot2-faction", default="America")
    parser.add_argument("--observer", action="store_true", help="also start a client for a human observer")
    parser.add_argument("--map", default=DEFAULT_MAP, help="map name or part of it (default: tournament desert)")
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--game-arg", action="append", default=[], help="extra game command-line argument")
    parser.add_argument("--duration", type=float, help="stop the bots after this many seconds")
    parser.add_argument("--apm", type=int, default=0, help="cap each bot's orders per minute of game time")
    parser.add_argument("--replay", help="name for bot 1's saved replay (default: date, bots and opponent)")
    parser.add_argument("--no-replay", action="store_true", help="don't save a named replay")
    return parser.parse_args(argv)


# -- running ---------------------------------------------------------------------------------------

def launch(instance: Instance, game_dir: Path, extra_args: list[str]) -> subprocess.Popen:
    return subprocess.Popen([str(game_dir / GAME_EXE), *instance.args(extra_args)], cwd=game_dir)


async def wait_for_port(port: int, proc: subprocess.Popen, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"game on port {port} exited with code {proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            await asyncio.sleep(0.5)
    raise TimeoutError(f"script API port {port} did not open")


def pick_map(options: dict, wanted: str) -> str:
    wanted = wanted.lower()
    for m in options["maps"]:
        if wanted == m["name"].lower() or wanted in m["name"].lower() or wanted in m["display_name"].lower():
            return m["name"]
    raise ValueError(f"no map matching {wanted!r}")


def slot_faction(faction: str) -> dict:
    return {} if faction == "random" else {"faction": faction}


async def setup_lan(plan: Plan, clients: dict[str, GeneralsClient], map_name: str) -> None:
    host = clients["bot1"]
    lobby = await host.lan_open(plan.instance("bot1").name)
    joiners = [i for i in plan.instances if i.role != "bot1"]
    for inst in joiners:
        await clients[inst.role].lan_open(inst.name)

    await host.lan_host(map_name, plan.slots)
    await host.lan_slot(**slot_faction(plan.instance("bot1").faction))
    for inst in joiners:
        client = clients[inst.role]
        await client.lan_join(host_ip=lobby["local_ip"])
        if inst.bot is None:
            await client.lan_slot(observer=True)
        elif inst.faction != "random":
            await client.lan_slot(faction=inst.faction)

    # Accepting resets whenever a slot changes, so accept after every joiner has picked its slot.
    deadline = time.monotonic() + 60
    while True:
        for inst in joiners:
            await clients[inst.role].lan_accept()
        await asyncio.sleep(1.0)
        try:
            await host.lan_start()
            return
        except ApiError as error:
            if error.code != "NOT_READY" or time.monotonic() > deadline:
                raise


async def play(plan: Plan, *, map: str = DEFAULT_MAP, game_dir: Path = DEFAULT_GAME_DIR,
               extra_args: list[str] = (), duration: float | None = None, keep_observer: bool = True,
               replay: str | None = None,
               on_started: Callable[[dict[str, subprocess.Popen]], None] | None = None,
               on_in_game: Callable[[dict[str, GeneralsClient]], Awaitable[Any]] | None = None) -> dict:
    """Runs the whole match. Returns {"results": {role: result}, "events": {role: {event: count}}}.

    on_in_game(clients) runs once every instance is in the match, alongside the bots; its result is
    returned as "observed". Each instance accepts one script connection, so use these clients rather
    than connecting again. With `replay`, bot 1 leaves the match at the end and saves its replay
    under that name ("replay": the file, or "replay_error").
    """
    procs: dict[str, subprocess.Popen] = {}
    clients: dict[str, GeneralsClient] = {}
    summary: dict = {"results": {}, "events": {}, "processes": procs}
    try:
        for inst in plan.instances:
            procs[inst.role] = launch(inst, game_dir, list(extra_args))
        if on_started is not None:
            on_started(procs)
        for inst in plan.instances:
            await wait_for_port(inst.port, procs[inst.role])
            clients[inst.role] = await GeneralsClient(f"ws://127.0.0.1:{inst.port}", request_timeout=60).connect()
            await clients[inst.role].hello()

        options = await clients["bot1"].skirmish_options()
        map_name = pick_map(options, map)
        if plan.mode == "skirmish":
            bot1 = plan.instance("bot1")
            await clients["bot1"].start_skirmish(map_name, [{"type": "script", **slot_faction(bot1.faction)}, plan.ai])
        else:
            await setup_lan(plan, clients, map_name)
        for inst in plan.instances:
            await clients[inst.role].wait_for_state("in_game", timeout=LOAD_TIMEOUT)

        tasks = []
        for inst in plan.bots:
            client = clients[inst.role]
            counts: dict[str, int] = {}
            summary["events"][inst.role] = counts
            for name in ("construction_complete", "unit_created", "enemy_destroyed", "unit_destroyed"):
                client.on(name, lambda ev, counts=counts, name=name: counts.__setitem__(name, counts.get(name, 0) + 1))
            client.on("game_over", lambda ev, role=inst.role: summary["results"].__setitem__(role, ev["result"]))
            world = World().attach(client)
            await world.load(client)
            tasks.append(asyncio.ensure_future(load_bot(inst.bot)(client, world)))

        if on_in_game is not None:
            async def observe():
                summary["observed"] = await on_in_game(clients)
            tasks.append(asyncio.ensure_future(observe()))

        # The match runs until every bot has a result or the time is up. A bot that returns early
        # just stops playing; one that raises ends the match with its error.
        loop = asyncio.get_running_loop()
        deadline = None if duration is None else loop.time() + duration
        while len(summary["results"]) < len(plan.bots) and (deadline is None or loop.time() < deadline):
            for task in tasks:
                if task.done() and not task.cancelled() and task.exception() is not None:
                    raise task.exception()
            await asyncio.sleep(1.0)
        for task in tasks:
            task.cancel()
        if replay is not None:
            await save_match_replay(clients["bot1"], replay, summary)
        return summary
    finally:
        for role, client in clients.items():
            if role != "observer" or not keep_observer:
                try:
                    await client.exit()
                except Exception:
                    pass
            await client.close()
        for role, proc in procs.items():
            if role == "observer" and keep_observer:
                continue
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()


async def save_match_replay(client: GeneralsClient, name: str, summary: dict) -> None:
    """The replay is complete once the game has ended. After game_over the game goes to the score
    screen by itself (about 12 s); a game still running (--duration) is left with quit_game."""
    try:
        if client.game_state != "shell":
            if "bot1" not in summary["results"]:
                await client.quit_game()
            await client.wait_for_state("shell", timeout=60)
        summary["replay"] = (await client.save_replay(name))["file"]
    except (ApiError, asyncio.TimeoutError) as error:
        summary["replay_error"] = str(error)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plan = make_plan(args)
    for inst in plan.instances:
        print(f"{inst.role}: port {inst.port}, input {inst.input_mode}, bot {inst.bot}")
    summary = asyncio.run(play(plan, map=args.map, game_dir=args.game_dir, extra_args=args.game_arg,
                               duration=args.duration, replay=replay_name(args)))
    print(json.dumps({key: summary[key] for key in ("results", "events", "replay", "replay_error") if key in summary},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
