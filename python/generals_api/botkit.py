"""Helpers for bots an agent tunes while they play: settings and strategy code reloaded on change.

    settings = LiveSettings("settings.json", defaults={"attack_size": 12})
    strategy = LiveModule("strategy.py")
    while True:
        settings.reload(); strategy.reload()        # cheap: only re-reads files that changed
        await strategy.module.tick(client, world, settings)

The bot keeps its connection while the agent edits settings.json or strategy.py; a broken edit is
ignored (the last good version stays, with the problem in .error) so a typo can't stop the bot.
Use exit_when_superseded(client) so an old bot exits by itself when a new one connects.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


class LiveSettings:
    """A JSON object reloaded when its file changes; missing keys fall back to `defaults`."""

    def __init__(self, path: str | Path, defaults: dict | None = None):
        self.path = Path(path)
        self.defaults = dict(defaults or {})
        self.values: dict = {}
        self.error: str | None = None
        self._mtime: tuple[int, int] | None = None
        self.reload()

    def reload(self) -> bool:
        """Re-reads the file if it changed; True when new values were loaded."""
        try:
            stat = os.stat(self.path)
        except OSError:
            return False
        # Size too: two quick edits can share a modification time on coarse clocks.
        mtime = (stat.st_mtime_ns, stat.st_size)
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(values, dict):
                raise ValueError("the file must hold a JSON object")
        except (OSError, ValueError) as error:
            self.error = f"{self.path.name}: {error}"
            return False
        self.values, self.error = values, None
        return True

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, self.defaults.get(key, default))

    def __getitem__(self, key: str) -> Any:
        if key in self.values:
            return self.values[key]
        return self.defaults[key]


class LiveModule:
    """A Python file imported again when it changes; `.module` is the last version that loaded."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.module: Any = None
        self.error: str | None = None
        self._mtime: tuple[int, int] | None = None
        self.reload()
        if self.module is None:
            raise ImportError(self.error or f"cannot load {self.path}")

    def reload(self) -> bool:
        try:
            stat = os.stat(self.path)
        except OSError:
            return False
        # Size too: two quick edits can share a modification time on coarse clocks.
        mtime = (stat.st_mtime_ns, stat.st_size)
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        name = f"botkit_live_{self.path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(name, self.path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:  # noqa: BLE001 - any error in the edited file keeps the old version
            self.error = traceback.format_exc(limit=1)
            return False
        sys.modules[name] = module
        self.module, self.error = module, None
        return True


def exit_when_superseded(client) -> None:
    """Exits the process when a newer controller replaces this one (close code 4001)."""
    async def check(_event=None):
        await client.wait_closed()
        if client.close_code == 4001:
            os._exit(0)
    import asyncio
    asyncio.get_running_loop().create_task(check())
