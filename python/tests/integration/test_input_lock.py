"""Phase 4: a human in the bot's window can only move the camera (default "view" input mode).

Keyboard input is injected as raw input messages (the game reads the keyboard through DirectInput,
which only works for the foreground window). Mouse input is also posted as real Windows messages to
check that the Win32 mouse path reaches the guard.
"""

import asyncio
import ctypes
from ctypes import wintypes

import pytest

from generals_api import GeneralsClient

user32 = ctypes.windll.user32
WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0201, 0x0202, 0x0204, 0x0205


def game_window(pid: int) -> int:
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    assert found, "game window not found"
    return found[0]


async def frames_advance(client, seconds=1.0) -> bool:
    first = (await client.ping())["frame"]
    await asyncio.sleep(seconds)
    return (await client.ping())["frame"] > first


async def press(client, key, shift=False):
    await client.request("debug_inject_input", kind="key", key=key, shift=shift)


@pytest.fixture
async def client(game, skirmish):
    async with GeneralsClient(game.url) as c:
        yield c
        await c.request("set_input_mode", mode="view")


async def test_default_mode_is_view(client):
    assert (await client.request("debug_input_stats"))["mode"] == "view"


async def test_pause_key_works_in_full_mode(client):
    """Positive control: the injected key does reach the game when input is not locked."""
    await client.request("set_input_mode", mode="full")
    await press(client, "P", shift=True)
    await asyncio.sleep(0.5)
    assert not await frames_advance(client), "Shift+P should pause the game in full mode"
    await press(client, "P", shift=True)
    await asyncio.sleep(0.5)
    assert await frames_advance(client)


async def test_view_mode_ignores_game_input(client):
    stats_before = await client.request("debug_input_stats")
    await press(client, "P", shift=True)       # pause
    await press(client, "ESC")                 # quit menu
    await press(client, "Q")                   # a selection hotkey
    for button in ("left", "right"):
        await client.request("debug_inject_input", kind="click", button=button, x=400, y=300)
    await asyncio.sleep(0.5)
    assert await frames_advance(client), "view mode must not let the human pause the game"

    stats = await client.request("debug_input_stats")
    assert stats["dropped"]["mouse_left"] > stats_before["dropped"]["mouse_left"]
    assert stats["camera"]["key"] > stats_before["camera"]["key"]


async def test_view_mode_allows_camera(client):
    before = await client.request("debug_camera")
    await client.request("debug_inject_input", kind="key_down", key="UP")
    await asyncio.sleep(0.7)
    await client.request("debug_inject_input", kind="key_up", key="UP")
    await client.request("debug_inject_input", kind="wheel", spin=-2.0, x=400, y=300)
    await asyncio.sleep(0.3)
    after = await client.request("debug_camera")
    assert after["pos"] != before["pos"] or after["zoom"] != before["zoom"]


async def test_locked_mode_blocks_camera(client):
    await client.request("set_input_mode", mode="locked")
    before = await client.request("debug_camera")
    await client.request("debug_inject_input", kind="key_down", key="UP")
    await asyncio.sleep(0.7)
    await client.request("debug_inject_input", kind="key_up", key="UP")
    after = await client.request("debug_camera")
    assert after["pos"] == before["pos"]
    assert await frames_advance(client)


async def test_real_windows_clicks_are_dropped(game, client):
    hwnd = game_window(game.proc.pid)
    before = (await client.request("debug_input_stats"))["dropped"]
    lparam = (300 << 16) | 400
    for down, up in ((WM_LBUTTONDOWN, WM_LBUTTONUP), (WM_RBUTTONDOWN, WM_RBUTTONUP)):
        user32.PostMessageW(hwnd, down, 1, lparam)
        user32.PostMessageW(hwnd, up, 0, lparam)
    await asyncio.sleep(0.5)
    after = (await client.request("debug_input_stats"))["dropped"]
    assert after["mouse_left"] > before["mouse_left"]
    assert await frames_advance(client)


async def test_minimized_bot_keeps_playing(game, client):
    """Several bot windows cannot all have focus: a minimized bot client must keep running."""
    hwnd = game_window(game.proc.pid)
    SW_MINIMIZE, SW_RESTORE = 6, 9
    user32.ShowWindow(hwnd, SW_MINIMIZE)
    try:
        await asyncio.sleep(0.5)
        assert user32.IsIconic(hwnd)
        assert await frames_advance(client, seconds=2.0)
    finally:
        user32.ShowWindow(hwnd, SW_RESTORE)
