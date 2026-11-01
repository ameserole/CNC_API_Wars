"""Unit tests for GeneralsClient against an in-process fake server."""

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from generals_api import ApiError, ConnectionClosed, GeneralsClient


class FakeServer:
    """Scriptable WebSocket server. `handler(msg, ws)` is called for each request."""

    def __init__(self, handler=None):
        self.handler = handler or self.default_handler
        self.requests = []
        self.connection = None
        self._server = None

    @staticmethod
    async def default_handler(msg, ws):
        await ws.send(json.dumps({"type": "reply", "reply_to": msg.get("id"), "ok": True, "cmd": msg["cmd"]}))

    async def _serve(self, ws):
        self.connection = ws
        async for raw in ws:
            msg = json.loads(raw)
            self.requests.append(msg)
            await self.handler(msg, ws)

    async def __aenter__(self):
        self._server = await serve(self._serve, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()

    async def push_event(self, name, **fields):
        await self.connection.send(json.dumps({"type": "event", "event": name, "frame": fields.pop("frame", 0), **fields}))


async def test_request_ids_increase_and_replies_resolve():
    async with FakeServer() as server, GeneralsClient(server.url) as client:
        first = await client.request("ping")
        second = await client.request("hello", protocol_version=1)
        assert first["cmd"] == "ping"
        assert second["cmd"] == "hello"
        ids = [r["id"] for r in server.requests]
        assert ids[1] > ids[0]
        assert server.requests[1]["protocol_version"] == 1


async def test_out_of_order_replies_resolve_correct_futures():
    pending = []

    async def handler(msg, ws):
        pending.append(msg)
        if len(pending) == 2:
            for m in reversed(pending):
                await ws.send(json.dumps({"type": "reply", "reply_to": m["id"], "ok": True, "echo": m["cmd"]}))

    async with FakeServer(handler) as server, GeneralsClient(server.url) as client:
        a, b = await asyncio.gather(client.request("a"), client.request("b"))
        assert a["echo"] == "a"
        assert b["echo"] == "b"


async def test_error_reply_raises_api_error():
    async def handler(msg, ws):
        await ws.send(json.dumps({"type": "reply", "reply_to": msg["id"], "ok": False,
                                  "error": "UNKNOWN_COMMAND", "message": "no such command"}))

    async with FakeServer(handler) as server, GeneralsClient(server.url) as client:
        with pytest.raises(ApiError) as info:
            await client.request("dance")
        assert info.value.code == "UNKNOWN_COMMAND"
        assert "no such command" in str(info.value)


async def test_events_reach_handlers_and_waiters():
    seen = []
    async with FakeServer() as server, GeneralsClient(server.url) as client:
        client.on("game_state", lambda ev: seen.append(ev["state"]))

        async def async_handler(ev):
            seen.append("async:" + ev["state"])
        client.on("game_state", async_handler)

        waiter = asyncio.create_task(client.wait_for_event("game_state", lambda ev: ev["state"] == "in_game", timeout=2))
        await client.request("ping")  # make sure the connection is established server-side
        await server.push_event("game_state", state="shell", frame=1)
        await server.push_event("game_state", state="in_game", frame=2)
        event = await waiter
        assert event["frame"] == 2
        await asyncio.sleep(0.05)
        # Sync handlers run in arrival order; async handlers run as their own tasks.
        assert [s for s in seen if not s.startswith("async:")] == ["shell", "in_game"]
        assert sorted(s for s in seen if s.startswith("async:")) == ["async:in_game", "async:shell"]


async def test_on_works_as_decorator():
    seen = []
    async with FakeServer() as server, GeneralsClient(server.url) as client:
        @client.on("tick")
        def handler(ev):
            seen.append(ev["frame"])

        await client.request("ping")
        await server.push_event("tick", frame=5)
        await client.wait_for_event("tick", timeout=2)
        await asyncio.sleep(0.01)
        assert seen == [5]


async def test_wait_for_event_times_out():
    async with FakeServer() as server, GeneralsClient(server.url) as client:
        with pytest.raises(asyncio.TimeoutError):
            await client.wait_for_event("never", timeout=0.1)


async def test_server_disconnect_fails_pending_requests():
    async def handler(msg, ws):
        await ws.close(code=4001, reason="superseded")

    async with FakeServer(handler) as server, GeneralsClient(server.url) as client:
        with pytest.raises(ConnectionClosed) as info:
            await client.request("ping")
        assert info.value.code == 4001
        await client.wait_closed(timeout=2)
        assert client.close_code == 4001


async def test_request_timeout():
    async def handler(msg, ws):
        pass  # never replies

    async with FakeServer(handler) as server, GeneralsClient(server.url, request_timeout=0.1) as client:
        with pytest.raises(asyncio.TimeoutError):
            await client.request("ping")


async def test_convenience_methods():
    async def handler(msg, ws):
        fields = {"hello": {"protocol_version": 1, "game_state": "shell"}, "ping": {"frame": 9}, "exit": {}}[msg["cmd"]]
        await ws.send(json.dumps({"type": "reply", "reply_to": msg["id"], "ok": True, **fields}))

    async with FakeServer(handler) as server, GeneralsClient(server.url) as client:
        hello = await client.hello()
        assert hello["game_state"] == "shell"
        assert server.requests[0]["protocol_version"] == 1
        assert (await client.ping())["frame"] == 9
        await client.exit()
        assert server.requests[-1]["cmd"] == "exit"


async def test_transcript_records_traffic(tmp_path):
    path = tmp_path / "events.jsonl"
    async with FakeServer() as server, GeneralsClient(server.url, transcript=path) as client:
        await client.request("ping")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [entry["dir"] for entry in lines] == ["out", "in"]
    assert lines[0]["msg"]["cmd"] == "ping"


# -- phase 2: skirmish commands and game-state tracking ------------------------------------------

async def test_skirmish_commands_send_expected_payloads():
    async with FakeServer() as server, GeneralsClient(server.url) as client:
        await client.skirmish_options()
        await client.start_skirmish("maps\a\a.map", [{"type": "script"}, {"type": "easy_ai"}], seed=5, fps_limit=30)
        await client.quit_game()
        assert [r["cmd"] for r in server.requests] == ["skirmish_options", "start_skirmish", "quit_game"]
        start = server.requests[1]
        assert start["map"] == "maps\a\a.map"
        assert start["players"][1]["type"] == "easy_ai"
        assert start["seed"] == 5 and start["fps_limit"] == 30
        assert "starting_cash" not in start  # unset options are not sent


async def test_game_state_tracks_hello_and_events():
    async def handler(msg, ws):
        await ws.send(json.dumps({"type": "reply", "reply_to": msg["id"], "ok": True, "game_state": "shell"}))

    async with FakeServer(handler) as server, GeneralsClient(server.url) as client:
        assert client.game_state is None
        await client.hello()
        assert client.game_state == "shell"
        await server.push_event("game_state", state="loading", previous="shell")
        await client.wait_for_event("game_state", timeout=2)
        assert client.game_state == "loading"


async def test_wait_for_state_returns_immediately_when_already_there():
    async def handler(msg, ws):
        await ws.send(json.dumps({"type": "reply", "reply_to": msg["id"], "ok": True, "game_state": "shell"}))

    async with FakeServer(handler) as server, GeneralsClient(server.url) as client:
        await client.hello()
        assert await client.wait_for_state("shell", timeout=0.1) == "shell"


async def test_wait_for_state_waits_for_transition():
    async def handler(msg, ws):
        await ws.send(json.dumps({"type": "reply", "reply_to": msg["id"], "ok": True, "game_state": "shell"}))

    async with FakeServer(handler) as server, GeneralsClient(server.url) as client:
        await client.hello()
        waiter = asyncio.create_task(client.wait_for_state("in_game", timeout=2))
        await asyncio.sleep(0.05)
        assert not waiter.done()
        await server.push_event("game_state", state="loading", previous="shell")
        await server.push_event("game_state", state="in_game", previous="loading")
        assert await waiter == "in_game"


# -- phase 4: orders -----------------------------------------------------------------------------

async def test_order_methods_send_expected_payloads():
    async with FakeServer() as server, GeneralsClient(server.url) as client:
        await client.move([1, 2], (100, 200))
        await client.attack_move([1], (5, 6))
        await client.attack([1], 77)
        await client.force_attack([1], (7, 8))
        await client.stop([1, 2])
        await client.guard([1], (9, 10))
        await client.train(3, "AmericaInfantryRanger", count=2)
        await client.cancel_train(3, 41)
        await client.build(4, "AmericaPowerPlant", (300, 400), angle=1.5)
        await client.set_rally_point(3, (50, 60))
        await client.sell(5)
        sent = {r["cmd"]: r for r in server.requests}
        assert sent["move"]["units"] == [1, 2] and sent["move"]["pos"] == [100, 200]
        assert sent["attack"]["target"] == 77
        assert sent["train"] == {**sent["train"], "factory": 3, "template": "AmericaInfantryRanger", "count": 2}
        assert sent["cancel_train"]["production_id"] == 41
        assert sent["build"]["dozer"] == 4 and sent["build"]["angle"] == 1.5 and sent["build"]["pos"] == [300, 400]
        assert sent["set_rally_point"]["building"] == 3
        assert sent["sell"]["building"] == 5
        assert set(sent) >= {"attack_move", "force_attack", "stop", "guard"}


async def test_wait_for_execution_matches_reply_id():
    async def handler(msg, ws):
        await ws.send(json.dumps({"type": "reply", "reply_to": msg["id"], "ok": True, "client_frame": 10, "messages": 1}))
        await ws.send(json.dumps({"type": "event", "event": "command_executed", "frame": 12, "reply_to": msg["id"] + 1000, "cmd": "x"}))
        await ws.send(json.dumps({"type": "event", "event": "command_executed", "frame": 13, "reply_to": msg["id"], "cmd": msg["cmd"]}))

    async with FakeServer(handler) as server, GeneralsClient(server.url) as client:
        reply = await client.move([1], (0, 0))
        executed = await client.wait_for_execution(reply, timeout=2)
        assert executed["frame"] == 13 and executed["cmd"] == "move"


# -- phase 5: full action set --------------------------------------------------------------------

async def test_phase5_methods_send_expected_payloads():
    async with FakeServer() as server, GeneralsClient(server.url) as client:
        await client.upgrade(7, "Upgrade_AmericaRangerFlashBangGrenade")
        await client.cancel_upgrade(7, "Upgrade_AmericaRangerFlashBangGrenade")
        await client.purchase_science("SCIENCE_PaladinTank")
        await client.use_ability([1], "Command_FlashBangMode")
        await client.use_ability([1], "Command_Capture", target=42)
        await client.use_ability([1], "Command_Paradrop", pos=(5, 6))
        await client.enter([1, 2], 42)
        await client.exit_container([1])
        await client.evacuate(42)
        await client.repair(3, 42)
        await client.resume_construction(3, 42)
        await client.get_repaired([1], 42)
        await client.dock([1], 42)
        await client.guard_object([1], 42)
        await client.force_attack_object([1], 42)
        await client.force_move([1], (1, 2))
        await client.move([1], (1, 2), waypoints=[(3, 4), (5, 6)])
        await client.scatter([1])
        await client.formation([1, 2])
        await client.cancel_build(9)
        sent = {}
        for r in server.requests:
            sent.setdefault(r["cmd"], []).append(r)
        assert sent["upgrade"][0] == {**sent["upgrade"][0], "object": 7, "upgrade": "Upgrade_AmericaRangerFlashBangGrenade"}
        assert sent["purchase_science"][0]["science"] == "SCIENCE_PaladinTank"
        abilities = sent["use_ability"]
        assert "target" not in abilities[0] and "pos" not in abilities[0]
        assert abilities[1]["target"] == 42 and abilities[2]["pos"] == [5, 6]
        assert sent["enter"][0]["units"] == [1, 2] and sent["enter"][0]["target"] == 42
        assert sent["evacuate"][0]["object"] == 42
        assert sent["repair"][0]["dozer"] == 3
        assert sent["move"][0]["waypoints"] == [[3, 4], [5, 6]]
        assert sent["cancel_build"][0]["building"] == 9
        assert {"exit_container", "dock", "guard_object", "force_attack_object", "force_move", "scatter", "formation",
                "resume_construction", "get_repaired", "cancel_upgrade"} <= set(sent)


async def test_reserved_argument_names_are_rejected():
    async with FakeServer() as server, GeneralsClient(server.url) as client:
        with pytest.raises(ValueError):
            await client.request("debug_hurt", id=5)
        assert server.requests == []


async def test_lan_methods_send_expected_payloads():
    async def handler(msg, ws):
        await ws.send(json.dumps({"type": "reply", "reply_to": msg["id"], "ok": True, "games": []}))
        follow_up = {"lan_open": "lan_lobby", "lan_host": "lan_game", "lan_join": "lan_game"}.get(msg["cmd"])
        if follow_up:
            await ws.send(json.dumps({"type": "event", "event": follow_up, "frame": 1, "local_ip": "127.0.0.1"}))

    async with FakeServer(handler) as server, GeneralsClient(server.url) as client:
        lobby = await client.lan_open("Bot1")
        assert lobby["event"] == "lan_lobby" and lobby["local_ip"] == "127.0.0.1"
        assert await client.lan_games() == []
        game = await client.lan_host(r"maps\a\a.map", [{"type": "host"}, {"type": "easy_ai", "faction": "FactionChina"}])
        assert game["event"] == "lan_game"
        await client.lan_join(host_ip="127.0.0.1")
        await client.lan_slot(faction="FactionChina", team=None)
        await client.lan_accept()
        await client.lan_start()
        await client.lan_leave()
        await client.surrender()

        sent = {r["cmd"]: r for r in server.requests}
        assert sent["lan_open"]["name"] == "Bot1" and "ip" not in sent["lan_open"]
        assert sent["lan_host"]["slots"][1]["type"] == "easy_ai"
        assert "starting_cash" not in sent["lan_host"]
        assert sent["lan_join"]["host_ip"] == "127.0.0.1" and "host" not in sent["lan_join"]
        assert sent["lan_slot"]["faction"] == "FactionChina" and sent["lan_slot"]["team"] is None
        assert {"lan_accept", "lan_start", "lan_leave", "surrender"} <= set(sent)


async def test_save_replay_payload():
    async with FakeServer() as server, GeneralsClient(server.url) as client:
        await client.save_replay("bot match")
        await client.save_replay("bot match", overwrite=True)
        assert [(r["cmd"], r["name"], r["overwrite"]) for r in server.requests] == [
            ("save_replay", "bot match", False), ("save_replay", "bot match", True)]


async def test_lan_argument_checks():
    async with FakeServer() as server, GeneralsClient(server.url) as client:
        with pytest.raises(ValueError):
            await client.lan_join()
        with pytest.raises(ValueError):
            await client.lan_join(host_ip="127.0.0.1", host="Bot1")
        with pytest.raises(ValueError):
            await client.lan_slot(name="x")
        assert server.requests == []


async def test_lan_failed_event_raises():
    async def handler(msg, ws):
        await ws.send(json.dumps({"type": "reply", "reply_to": msg["id"], "ok": True}))
        await ws.send(json.dumps({"type": "event", "event": "lan_failed", "frame": 1, "action": "join",
                                  "reason": "timeout", "screen": "Menus/LanLobbyMenu.wnd"}))

    async with FakeServer(handler) as server, GeneralsClient(server.url) as client:
        with pytest.raises(ApiError) as error:
            await client.lan_join(host_ip="127.0.0.9", timeout=5)
        assert error.value.code == "LAN_FAILED"
