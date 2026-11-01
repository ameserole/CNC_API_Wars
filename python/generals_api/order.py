"""Sends one command over a watcher connection, alongside the running bot, and prints the reply.

    python -m generals_api.order ws://127.0.0.1:PORT attack units=[12,13] target=40
    python -m generals_api.order ws://127.0.0.1:PORT move '{"units": [12, 13], "pos": [800, 900]}'
    python -m generals_api.order ws://127.0.0.1:PORT use_ability units=[3] ability=Command_ArtilleryBarrage pos=[900,1200] --wait

Arguments are one JSON object, or key=value pairs whose values are JSON (bare words are strings).
--wait also waits for command_executed. Exit code 1 when the game refused the command.
`python -m generals_api.order --list` prints every command with its argument names.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys

from .client import ApiError, ConnectionClosed, GeneralsClient, watcher_url


# Client methods whose name differs from the command they send, or that aren't commands.
_NOT_COMMANDS = {"connect", "close", "wait_closed", "request", "on", "off", "wait_for_event", "wait_for_execution",
                 "wait_for_state", "hello", "exit"}


def command_list() -> list[str]:
    """'cmd arg1 arg2=...' for every command the client knows, from its method signatures."""
    lines = []
    for name, method in sorted(inspect.getmembers(GeneralsClient, inspect.iscoroutinefunction)):
        if name.startswith("_") or name in _NOT_COMMANDS:
            continue
        params = [p for p in inspect.signature(method).parameters.values() if p.name != "self"]
        args = [p.name if p.default is inspect.Parameter.empty else f"[{p.name}]" for p in params]
        doc = (inspect.getdoc(method) or "").splitlines()[0] if inspect.getdoc(method) else ""
        lines.append(f"{name} {' '.join(args)}" + (f"  - {doc}" if doc else ""))
    return lines


def parse_args(pairs: list[str]) -> dict:
    if len(pairs) == 1 and pairs[0].lstrip().startswith("{"):
        return json.loads(pairs[0])
    args = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise ValueError(f"expected key=value, got {pair!r}")
        try:
            args[key] = json.loads(value)
        except ValueError:
            args[key] = value
    return args


async def send(url: str, cmd: str, args: dict, wait: bool) -> int:
    try:
        async with GeneralsClient(watcher_url(url), request_timeout=30) as client:
            await client.hello()
            reply = await client.request(cmd, **args)
            print(json.dumps(reply))
            if wait and "messages" in reply:
                print(json.dumps(await client.wait_for_execution(reply, timeout=20)))
            return 0
    except ApiError as error:
        print(json.dumps({"ok": False, "error": error.code, "message": error.message}))
        return 1
    except (OSError, ConnectionClosed, asyncio.TimeoutError) as error:
        print(json.dumps({"ok": False, "error": "NO_CONNECTION", "message": str(error)}))
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m generals_api.order", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    if argv and argv[0] == "--list":
        print(*command_list(), sep="\n")
        return 0
    parser.add_argument("url")
    parser.add_argument("cmd")
    parser.add_argument("args", nargs="*")
    parser.add_argument("--wait", action="store_true", help="also wait until the game executed the order")
    ns = parser.parse_args(argv)
    try:
        args = parse_args(ns.args)
    except ValueError as error:
        print(json.dumps({"ok": False, "error": "BAD_ARGUMENTS", "message": str(error)}))
        return 1
    return asyncio.run(send(ns.url, ns.cmd, args, ns.wait))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
