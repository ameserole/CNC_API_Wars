"""Blocks until something matters in the match, then prints a short digest of what changed.

    python -m generals_api.watch ws://127.0.0.1:PORT [--max-wait 60] [--state watch.json] [--stream]

It connects as a watcher (`.../watch`), so it runs alongside the player's bot. Without --stream it
returns at the first trigger or after --max-wait seconds: run it in the foreground in a loop
("watch, act, watch again") to stay in the game without polling. Exit codes: 0 trigger or timeout,
2 the game is over, 3 no game (connection failed or not in a game).

Triggers: base_attacked (an own structure damaged), structure_lost, enemies_near_base (3+ visible
enemies within 1000 of an own structure), army_losses (half the army, at least 3 units, lost within
30 s), built (a structure finished), new_enemy_type, supply_low (a supply source near an own structure
below 15 % of the most seen in it), money_idle (3000+ unspent for 60 s), game_over.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .client import ApiError, ConnectionClosed, GeneralsClient, watcher_url

FPS = 30
NEAR_BASE = 1000
ENEMIES_NEAR_BASE = 3
LOSS_WINDOW = 30 * FPS
IDLE_MONEY = 3000
IDLE_FRAMES = 60 * FPS
SUPPLY_LOW = 0.15
SUPPLY_NEAR = 1200
MAX_LINES = 30


@dataclass
class WatchState:
    """What persists between calls (--state), so a digest says what changed since the last one."""
    enemy_types: list[str] = field(default_factory=list)
    supply_max: dict[str, int] = field(default_factory=dict)
    supply_low_reported: list[str] = field(default_factory=list)
    money_high_since: int | None = None
    last_frame: int = 0
    last_earned: int | None = None
    last_earned_frame: int | None = None

    @classmethod
    def load(cls, path: Path | None) -> "WatchState":
        if path is None or not Path(path).exists():
            return cls()
        try:
            return cls(**json.loads(Path(path).read_text()))
        except (ValueError, TypeError):
            return cls()

    def save(self, path: Path | None) -> None:
        if path is not None:
            Path(path).write_text(json.dumps(asdict(self)))


class Watch:
    """Turns events and snapshots into triggers, and builds the digest. No I/O."""

    def __init__(self, info: dict, catalog: dict, state: WatchState):
        self.state = state
        self.me = info["local_player"]
        self.enemies = {p["index"] for p in info["players"] if p["relation"] == "enemy"}
        self.names = {p["index"]: p.get("name", str(p["index"])) for p in info["players"]}
        self.structure_types = {s["name"] for s in catalog.get("structures", [])}
        self.units: dict[int, dict] = {}
        self.losses: deque[tuple[int, str]] = deque()   # (frame, template) of own non-structure losses
        self.army_at_window_start = 0
        self.built: list[str] = []
        self.lost: list[str] = []
        self.new_enemy_types: list[str] = []
        self.result: str | None = None
        self.near_base: list[dict] = []
        self.snapshot: dict | None = None

    # -- inputs -------------------------------------------------------------------------------

    def is_structure(self, template: str) -> bool:
        return template in self.structure_types

    def army(self) -> list[dict]:
        return [u for u in self.units.values() if not self.is_structure(u["template"])]

    def structures(self) -> list[dict]:
        return [u for u in self.units.values() if self.is_structure(u["template"])]

    def on_event(self, event: dict) -> list[str]:
        name, frame = event.get("event"), event.get("frame", self.state.last_frame)
        fired = []
        if name == "game_over":
            self.result = event.get("result")
            fired.append("game_over")
        elif name == "game_state" and event.get("state") != "in_game":
            # Left the game without a result (e.g. the referee ended it at the time limit).
            self.result = self.result or f"ended ({event.get('state')})"
            fired.append("game_over")
        elif name == "unit_damaged" and self.is_structure(event.get("template", "")):
            fired.append("base_attacked")
        elif name == "unit_destroyed":
            template = event.get("template", "")
            self.units.pop(event.get("id"), None)
            self.lost.append(template)
            if self.is_structure(template):
                fired.append("structure_lost")
            else:
                self.losses.append((frame, template))
                while self.losses and frame - self.losses[0][0] > LOSS_WINDOW:
                    self.losses.popleft()
                army_before = len(self.army()) + len(self.losses)
                if len(self.losses) >= max(3, army_before / 2):
                    fired.append("army_losses")
                    self.losses.clear()
        elif name == "construction_complete":
            self.built.append(event.get("template", ""))
            fired.append("built")
        elif name == "enemy_spotted" and event.get("owner") in self.enemies:
            template = event.get("template", "")
            if template not in self.state.enemy_types:
                self.state.enemy_types.append(template)
                self.new_enemy_types.append(template)
                fired.append("new_enemy_type")
        self.state.last_frame = max(self.state.last_frame, frame)
        return fired

    def on_snapshot(self, snapshot: dict) -> list[str]:
        self.snapshot = snapshot
        frame = snapshot.get("frame", self.state.last_frame)
        self.state.last_frame = max(self.state.last_frame, frame)
        self.units = {u["id"]: u for u in snapshot.get("units", [])}
        fired = []

        bases = [u["pos"] for u in self.structures()]
        enemies = [o for o in snapshot.get("visible", []) if o.get("owner") in self.enemies]
        self.near_base = [o for o in enemies if any(math.dist(o["pos"][:2], b[:2]) <= NEAR_BASE for b in bases)]
        if len(self.near_base) >= ENEMIES_NEAR_BASE:
            fired.append("enemies_near_base")

        for source in snapshot.get("visible", []):
            if "supply" not in source:
                continue
            key = str(source["id"])
            most = max(self.state.supply_max.get(key, 0), source["supply"])
            self.state.supply_max[key] = most
            near = any(math.dist(source["pos"][:2], b[:2]) <= SUPPLY_NEAR for b in bases)
            if near and most > 0 and source["supply"] < SUPPLY_LOW * most and key not in self.state.supply_low_reported:
                self.state.supply_low_reported.append(key)
                fired.append("supply_low")

        money = snapshot.get("self", {}).get("money", 0)
        if money >= IDLE_MONEY:
            if self.state.money_high_since is None:
                self.state.money_high_since = frame
            elif frame - self.state.money_high_since >= IDLE_FRAMES:
                fired.append("money_idle")
                self.state.money_high_since = frame
        else:
            self.state.money_high_since = None
        return fired

    # -- output -------------------------------------------------------------------------------

    def digest(self, snapshot: dict, stats: dict, triggers: list[str]) -> str:
        self.on_snapshot(snapshot)
        frame = snapshot.get("frame", 0)
        me = snapshot.get("self", {})
        own = next((p for p in stats.get("players", []) if p.get("index") == self.me), {})
        lines = [f"WATCH frame {frame} ({frame // FPS // 60}:{frame // FPS % 60:02d})"
                 f" | triggers: {', '.join(triggers) or 'none (max wait)'}"]
        if self.result:
            lines.append(f"game over: {self.result}")
        income = ""
        earned = own.get("money_earned")
        if earned is not None and self.state.last_earned is not None and frame > (self.state.last_earned_frame or 0):
            per_minute = (earned - self.state.last_earned) * 60 * FPS / (frame - self.state.last_earned_frame)
            income = f" (+{per_minute:.0f}/min)"
        if earned is not None:
            self.state.last_earned, self.state.last_earned_frame = earned, frame
        power = me.get("power", {})
        score = f" | score {own['score']}" if "score" in own else ""
        lines.append(f"money {me.get('money', 0)}{income} | power {power.get('produced', 0)}/{power.get('consumed', 0)}{score}")
        lines.append("army: " + _counts(u["template"] for u in self.army()))
        lines.append("structures: " + _counts(u["template"] for u in self.structures()))
        if self.built:
            lines.append("built: " + _counts(self.built))
        if self.lost:
            lines.append("lost: " + _counts(self.lost))
        enemies = [o for o in snapshot.get("visible", []) if o.get("owner") in self.enemies]
        if self.near_base:
            lines.append(f"ENEMIES NEAR BASE ({len(self.near_base)}): " + _counts(o["template"] for o in self.near_base))
        if enemies:
            lines.append(f"enemies in sight ({len(enemies)}): " + _counts(o["template"] for o in enemies))
        known = [k for k in snapshot.get("known_structures", []) if k.get("owner") in self.enemies]
        if known:
            lines.append("enemy structures known: " + _counts(k["template"] for k in known))
        if self.new_enemy_types:
            lines.append("new enemy types: " + ", ".join(self.new_enemy_types))
        sources = [o for o in snapshot.get("visible", []) if "supply" in o]
        bases = [u["pos"] for u in self.structures()]
        near = [o for o in sources if any(math.dist(o["pos"][:2], b[:2]) <= SUPPLY_NEAR for b in bases)]
        if near:
            lines.append("supply near you: " + ", ".join(
                f"{o['template']}@{o['pos'][0]:.0f},{o['pos'][1]:.0f} {o['supply']}" for o in near[:4]))
        self.built, self.lost, self.new_enemy_types = [], [], []
        return "\n".join(lines[:MAX_LINES])


def _counts(templates) -> str:
    counts = Counter(templates)
    return ", ".join(f"{name} x{n}" if n > 1 else name for name, n in counts.most_common()) or "-"


# -- command line ----------------------------------------------------------------------------------

async def watch(url: str, *, max_wait: float, state_path: Path | None, stream: bool, out=sys.stdout) -> int:
    try:
        client = await GeneralsClient(watcher_url(url), request_timeout=30).connect()
        hello = await client.hello()
    except (OSError, ConnectionClosed, ApiError, asyncio.TimeoutError) as error:
        print(f"WATCH no game: {error}", file=out)
        return 3
    try:
        if hello.get("game_result"):
            # The game ended while no watch was connected (e.g. between two calls).
            print(f"WATCH game over: {hello['game_result']} (state {hello.get('game_state')})", file=out)
            return 2
        if hello.get("game_state") != "in_game":
            print(f"WATCH no game in progress (state {hello.get('game_state')})", file=out)
            return 3
        state = WatchState.load(state_path)
        w = Watch(await client.game_info(), await client.catalog(), state)
        w.on_snapshot(await client.state())
        fired: asyncio.Queue = asyncio.Queue()

        def handle(event: dict) -> None:
            triggers = w.on_snapshot(event) if event.get("event") == "snapshot" else w.on_event(event)
            if triggers:
                fired.put_nowait(triggers)
        for name in ("game_over", "game_state", "unit_damaged", "unit_destroyed", "construction_complete", "enemy_spotted", "snapshot"):
            client.on(name, handle)
        await client.set_snapshot_interval(FPS)

        while True:
            try:
                triggers = await asyncio.wait_for(fired.get(), timeout=None if stream else max_wait)
            except asyncio.TimeoutError:
                triggers = []
            await asyncio.sleep(0.3)  # let related events of the same moment arrive
            while not fired.empty():
                triggers += fired.get_nowait()
            triggers = list(dict.fromkeys(triggers))
            if stream:
                print(f"WATCH frame {w.state.last_frame}: {', '.join(triggers)}", file=out, flush=True)
                if "game_over" in triggers:
                    return 2
                continue
            if "game_over" in triggers and (w.result or "").startswith("ended"):
                try:  # left the game: the result, if any, is in hello
                    w.result = (await client.hello()).get("game_result") or w.result
                except (ApiError, ConnectionClosed):
                    pass
            try:
                snapshot = await client.state()
                stats = await client.player_stats()
            except (ApiError, ConnectionClosed):
                snapshot, stats = w.snapshot or {}, {}
            print(w.digest(snapshot, stats, triggers), file=out, flush=True)
            state.save(state_path)
            return 2 if w.result else 0
    except ConnectionClosed:
        print("WATCH the game closed the connection (the game is over or was closed)", file=out)
        return 2
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m generals_api.watch", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="the player's API, e.g. ws://127.0.0.1:5000")
    parser.add_argument("--max-wait", type=float, default=60, help="seconds to wait for a trigger (default 60)")
    parser.add_argument("--state", type=Path, help="file that keeps what was reported, between calls")
    parser.add_argument("--stream", action="store_true", help="print one line per trigger until the game ends")
    args = parser.parse_args(argv)
    return asyncio.run(watch(args.url, max_wait=args.max_wait, state_path=args.state, stream=args.stream))


if __name__ == "__main__":
    raise SystemExit(main())
