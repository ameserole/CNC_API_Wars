"""Asyncio client for the Zero Hour script API (protocol v1)."""

from __future__ import annotations

import asyncio
import inspect
import itertools
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable

import websockets
from websockets.asyncio.client import ClientConnection, connect

PROTOCOL_VERSION = 1

Event = dict[str, Any]
EventHandler = Callable[[Event], Any]


class ApiError(Exception):
    """The game answered a request with ok=false."""

    def __init__(self, code: str, message: str, reply: dict):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.reply = reply


class ConnectionClosed(Exception):
    """The connection closed before a reply arrived."""

    def __init__(self, code: int | None, reason: str = ""):
        super().__init__(f"connection closed (code={code}, reason={reason!r})")
        self.code = code
        self.reason = reason


def watcher_url(url: str) -> str:
    """The watcher address of a player's API: ws://host:port/watch.

    A watcher runs alongside the controller (the bot): it gets every event and query and may give
    orders, but can't start, quit or exit games, and never replaces the controller.
    """
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/watch", "", ""))


class GeneralsClient:
    def __init__(self, url: str, *, request_timeout: float = 10.0, transcript: str | Path | None = None):
        self.url = url
        self.request_timeout = request_timeout
        self.close_code: int | None = None
        self.game_state: str | None = None  # from hello, then every game_state event
        self.close_reason = ""
        self._ws: ClientConnection | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._waiters: list[tuple[str, Callable[[Event], bool] | None, asyncio.Future]] = []
        self._reader: asyncio.Task | None = None
        self._handler_tasks: set[asyncio.Task] = set()
        # Recent command_executed events by reply_to, so a waiter that starts late still sees them.
        self._executed: dict[Any, Event] = {}
        self._closed = asyncio.Event()
        self._transcript = open(transcript, "a", encoding="utf-8") if transcript else None

    # -- connection ---------------------------------------------------------------------------

    async def connect(self) -> "GeneralsClient":
        self._ws = await connect(self.url, max_size=None)
        self._reader = asyncio.create_task(self._read_loop())
        return self

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._reader is not None:
            await asyncio.gather(self._reader, return_exceptions=True)
        if self._transcript:
            self._transcript.close()
            self._transcript = None

    async def wait_closed(self, timeout: float | None = None) -> None:
        await asyncio.wait_for(self._closed.wait(), timeout)

    async def __aenter__(self) -> "GeneralsClient":
        return await self.connect()

    async def __aexit__(self, *exc) -> None:
        await self.close()

    # -- requests -----------------------------------------------------------------------------

    async def request(self, cmd: str, **args: Any) -> dict:
        if "id" in args or "cmd" in args:
            raise ValueError("'id' and 'cmd' are reserved request fields; name the argument differently")
        if self._closed.is_set():
            raise ConnectionClosed(self.close_code, self.close_reason)
        request_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = {"id": request_id, "cmd": cmd, **args}
        self._record("out", message)
        try:
            await self._ws.send(json.dumps(message))
        except websockets.ConnectionClosed:
            self._pending.pop(request_id, None)
            raise ConnectionClosed(self.close_code, self.close_reason) from None
        try:
            reply = await asyncio.wait_for(future, self.request_timeout)
        finally:
            self._pending.pop(request_id, None)
        if not reply.get("ok"):
            raise ApiError(reply.get("error", "UNKNOWN"), reply.get("message", ""), reply)
        return reply

    async def hello(self) -> dict:
        reply = await self.request("hello", protocol_version=PROTOCOL_VERSION)
        self.game_state = reply.get("game_state", self.game_state)
        return reply

    async def ping(self) -> dict:
        return await self.request("ping")

    async def exit(self) -> dict:
        """Shuts the game down cleanly."""
        return await self.request("exit")

    async def skirmish_options(self) -> dict:
        return await self.request("skirmish_options")

    async def start_skirmish(self, map: str, players: list[dict], *, seed: int | None = None,
                             fps_limit: int | None = None, starting_cash: int | None = None,
                             limit_superweapons: bool | None = None) -> dict:
        """Starts a skirmish. players[0] must be {"type": "script", ...}; the others are AIs.

        The reply arrives before loading starts; use wait_for_state("in_game") to wait for the match.
        """
        options = {"seed": seed, "fps_limit": fps_limit, "starting_cash": starting_cash,
                   "limit_superweapons": limit_superweapons}
        return await self.request("start_skirmish", map=map, players=players,
                                  **{k: v for k, v in options.items() if v is not None})

    async def quit_game(self) -> dict:
        """Leaves the match. In a LAN game this surrenders first, as the quit menu does."""
        return await self.request("quit_game")

    async def save_replay(self, name: str, *, overwrite: bool = False) -> dict:
        """Copies the last game's replay to <name>.rep in the replay folder. Only from the menus, after a game."""
        return await self.request("save_replay", name=name, overwrite=overwrite)

    # -- LAN games ----------------------------------------------------------------------------

    LAN_SLOT_FIELDS = frozenset({"faction", "color", "team", "start_pos", "observer"})

    async def lan_open(self, name: str, *, ip: str | None = None, timeout: float = 30.0) -> Event:
        """Opens the LAN lobby from the main menu as `name` (1-12 characters).

        Returns the first lan_lobby event, which carries this client's `local_ip`.
        """
        return await self._request_then_event("lan_open", "lan_lobby", timeout, name=name, ip=ip)

    async def lan_games(self) -> list[dict]:
        """Games the lobby has heard of: [{host, host_ip, map, players, open_slots, in_progress}]."""
        return (await self.request("lan_games"))["games"]

    async def lan_host(self, map: str, slots: list[dict] | None = None, *, starting_cash: int | None = None,
                       limit_superweapons: bool | None = None, timeout: float = 30.0) -> Event:
        """Hosts a game from the lobby and returns its first lan_game event.

        slots[0] is {"type": "host"}; the others are open, closed or *_ai slots (default: one open slot).
        """
        return await self._request_then_event("lan_host", "lan_game", timeout, map=map, slots=slots,
                                              starting_cash=starting_cash, limit_superweapons=limit_superweapons)

    async def lan_join(self, *, host_ip: str | None = None, host: str | None = None,
                       timeout: float = 30.0) -> Event:
        """Joins a game by the host's IP (direct connect) or the host's name; returns the first lan_game event."""
        if (host_ip is None) == (host is None):
            raise ValueError("pass exactly one of host_ip or host")
        return await self._request_then_event("lan_join", "lan_game", timeout, host_ip=host_ip, host=host)

    async def lan_slot(self, **fields: Any) -> dict:
        """Changes this client's own slot: faction, color, team, start_pos (null for random) or observer."""
        unknown = set(fields) - self.LAN_SLOT_FIELDS
        if unknown:
            raise ValueError(f"unknown lan_slot fields: {sorted(unknown)}")
        return await self.request("lan_slot", **fields)

    async def lan_accept(self) -> dict:
        return await self.request("lan_accept")

    async def lan_game(self) -> dict:
        """The current game setup, in the same form as the lan_game event."""
        return await self.request("lan_game")

    async def lan_start(self) -> dict:
        """Host only. Fails with NOT_READY until every human player has accepted."""
        return await self.request("lan_start")

    async def lan_leave(self) -> dict:
        """Leaves the game setup (back to the lobby), or the lobby (back to the main menu)."""
        return await self.request("lan_leave")

    async def surrender(self) -> dict:
        """Surrenders a network game; the match goes on for the others."""
        return await self.request("surrender")

    async def _request_then_event(self, cmd: str, event: str, timeout: float, **args: Any) -> Event:
        """Sends `cmd` and returns the next `event`. A lan_failed event raises ApiError("LAN_FAILED")."""
        wanted = asyncio.ensure_future(self.wait_for_event(event, timeout=timeout))
        failed = asyncio.ensure_future(self.wait_for_event("lan_failed", timeout=timeout))
        try:
            await asyncio.sleep(0)  # both waiters are registered before the request goes out
            await self.request(cmd, **{k: v for k, v in args.items() if v is not None})
            done, _ = await asyncio.wait({wanted, failed}, return_when=asyncio.FIRST_COMPLETED)
            if failed in done and failed.exception() is None:
                ev = failed.result()
                raise ApiError("LAN_FAILED", f"{ev.get('action')} {ev.get('reason')} (screen {ev.get('screen')})", ev)
            return wanted.result() if wanted in done else await wanted
        finally:
            for task in (wanted, failed):
                task.cancel()

    # -- world view (in game) -----------------------------------------------------------------

    async def game_info(self) -> dict:
        return await self.request("game_info")

    async def catalog(self) -> dict:
        return await self.request("catalog")

    async def faction_catalog(self, faction: str) -> dict:
        """What any faction (see skirmish_options) builds, with base costs; also from the menus."""
        return await self.request("faction_catalog", faction=faction)

    async def player_stats(self) -> dict:
        """Score-screen numbers: your own during the game; everyone's for an observer or once it is over."""
        return await self.request("player_stats")

    async def template_info(self, names: list[str]) -> dict:
        return await self.request("template_info", names=list(names))

    async def map(self, cell_size: int | None = None) -> dict:
        return await self.request("map", **({} if cell_size is None else {"cell_size": cell_size}))

    async def state(self) -> dict:
        """The current snapshot (same shape as a "snapshot" event)."""
        return await self.request("state")

    async def set_snapshot_interval(self, frames: int) -> dict:
        """Snapshot every `frames` logic frames (30 per second); 0 turns periodic snapshots off."""
        return await self.request("set_snapshot_interval", frames=frames)

    # -- orders (in game) ---------------------------------------------------------------------
    # Each returns the reply ({client_frame, messages, ...}); pass it to wait_for_execution() to
    # wait until the game logic actually carried the order out.

    async def move(self, units: list[int], pos, waypoints=None) -> dict:
        """Moves to pos, then along the optional waypoints (each [x, y]) in order."""
        args = {"units": list(units), "pos": list(pos)}
        if waypoints:
            args["waypoints"] = [list(p) for p in waypoints]
        return await self.request("move", **args)

    async def attack_move(self, units: list[int], pos) -> dict:
        return await self.request("attack_move", units=list(units), pos=list(pos))

    async def attack(self, units: list[int], target: int) -> dict:
        return await self.request("attack", units=list(units), target=target)

    async def force_attack(self, units: list[int], pos) -> dict:
        return await self.request("force_attack", units=list(units), pos=list(pos))

    async def stop(self, units: list[int]) -> dict:
        return await self.request("stop", units=list(units))

    async def guard(self, units: list[int], pos) -> dict:
        return await self.request("guard", units=list(units), pos=list(pos))

    async def train(self, factory: int, template: str, count: int = 1) -> dict:
        """Queues units; the reply's production_ids can be passed to cancel_train()."""
        return await self.request("train", factory=factory, template=template, count=count)

    async def cancel_train(self, factory: int, production_id: int) -> dict:
        return await self.request("cancel_train", factory=factory, production_id=production_id)

    async def build(self, dozer: int, template: str, pos, angle: float = 0.0) -> dict:
        return await self.request("build", dozer=dozer, template=template, pos=list(pos), angle=angle)

    async def set_rally_point(self, building: int, pos) -> dict:
        return await self.request("set_rally_point", building=building, pos=list(pos))

    async def sell(self, building: int) -> dict:
        return await self.request("sell", building=building)

    async def upgrade(self, obj: int, upgrade: str) -> dict:
        """Queues a player or object upgrade at a building (or on a unit, for object upgrades)."""
        return await self.request("upgrade", object=obj, upgrade=upgrade)

    async def cancel_upgrade(self, obj: int, upgrade: str) -> dict:
        return await self.request("cancel_upgrade", object=obj, upgrade=upgrade)

    async def purchase_science(self, science: str) -> dict:
        return await self.request("purchase_science", science=science)

    async def use_ability(self, units: list[int], ability: str, *, target: int | None = None, pos=None) -> dict:
        """Uses a command button by name (see the catalog's "abilities"): special powers, weapon modes..."""
        args = {"units": list(units), "ability": ability}
        if target is not None:
            args["target"] = target
        if pos is not None:
            args["pos"] = list(pos)
        return await self.request("use_ability", **args)

    async def enter(self, units: list[int], target: int) -> dict:
        """Garrison a building, board a transport or enter a tunnel."""
        return await self.request("enter", units=list(units), target=target)

    async def exit_container(self, units: list[int]) -> dict:
        """The units leave the building, transport or tunnel they are in."""
        return await self.request("exit_container", units=list(units))

    async def evacuate(self, obj: int) -> dict:
        return await self.request("evacuate", object=obj)

    async def repair(self, dozer: int, target: int) -> dict:
        return await self.request("repair", dozer=dozer, target=target)

    async def resume_construction(self, dozer: int, target: int) -> dict:
        return await self.request("resume_construction", dozer=dozer, target=target)

    async def get_repaired(self, units: list[int], target: int) -> dict:
        return await self.request("get_repaired", units=list(units), target=target)

    async def dock(self, units: list[int], target: int) -> dict:
        return await self.request("dock", units=list(units), target=target)

    async def guard_object(self, units: list[int], target: int) -> dict:
        return await self.request("guard_object", units=list(units), target=target)

    async def force_attack_object(self, units: list[int], target: int) -> dict:
        return await self.request("force_attack_object", units=list(units), target=target)

    async def force_move(self, units: list[int], pos) -> dict:
        return await self.request("force_move", units=list(units), pos=list(pos))

    async def scatter(self, units: list[int]) -> dict:
        return await self.request("scatter", units=list(units))

    async def formation(self, units: list[int]) -> dict:
        return await self.request("formation", units=list(units))

    async def cancel_build(self, building: int) -> dict:
        return await self.request("cancel_build", building=building)

    async def wait_for_execution(self, reply: dict, timeout: float | None = 10.0) -> Event:
        """Waits for the command_executed event of the request that produced `reply`."""
        request_id = reply["reply_to"]
        if request_id in self._executed:
            return self._executed[request_id]
        return await self.wait_for_event("command_executed", lambda ev: ev.get("reply_to") == request_id, timeout)

    # -- events -------------------------------------------------------------------------------

    def on(self, event: str, handler: EventHandler | None = None):
        """Registers a sync or async handler. Usable as `client.on(name, fn)` or `@client.on(name)`."""
        if handler is None:
            def decorator(fn: EventHandler) -> EventHandler:
                self._handlers[event].append(fn)
                return fn
            return decorator
        self._handlers[event].append(handler)
        return handler

    async def wait_for_event(self, event: str, predicate: Callable[[Event], bool] | None = None,
                             timeout: float | None = 10.0) -> Event:
        """Waits for the next matching event received after this call."""
        future = asyncio.get_running_loop().create_future()
        entry = (event, predicate, future)
        self._waiters.append(entry)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            if entry in self._waiters:
                self._waiters.remove(entry)

    async def wait_for_state(self, state: str, timeout: float | None = 10.0) -> str:
        """Returns once game_state equals state (immediately if it already does)."""
        if self.game_state == state:
            return state
        await self.wait_for_event("game_state", lambda ev: ev.get("state") == state, timeout)
        return state

    # -- internals ----------------------------------------------------------------------------

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                message = json.loads(raw)
                self._record("in", message)
                kind = message.get("type")
                if kind == "reply":
                    future = self._pending.get(message.get("reply_to"))
                    if future and not future.done():
                        future.set_result(message)
                elif kind == "event":
                    await self._dispatch_event(message)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.close_code = self._ws.close_code
            self.close_reason = self._ws.close_reason or ""
            self._closed.set()
            error = ConnectionClosed(self.close_code, self.close_reason)
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            for _, _, future in self._waiters:
                if not future.done():
                    future.set_exception(error)

    async def _dispatch_event(self, event: Event) -> None:
        name = event.get("event")
        if name == "game_state":
            self.game_state = event.get("state")
        elif name == "command_executed":
            self._executed[event.get("reply_to")] = event
            if len(self._executed) > 1000:
                self._executed.pop(next(iter(self._executed)))
        for waiter in list(self._waiters):
            wanted, predicate, future = waiter
            if wanted == name and not future.done() and (predicate is None or predicate(event)):
                future.set_result(event)
        for handler in list(self._handlers.get(name, ())):
            result = handler(event)
            if inspect.isawaitable(result):
                # Async handlers run as independent tasks so a slow reaction never stalls the reader.
                task = asyncio.ensure_future(result)
                self._handler_tasks.add(task)
                task.add_done_callback(self._handler_tasks.discard)

    def _record(self, direction: str, message: dict) -> None:
        if self._transcript:
            self._transcript.write(json.dumps({"dir": direction, "msg": message}) + "\n")
            self._transcript.flush()
