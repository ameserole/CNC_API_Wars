"""Launches generalszh.exe with the script API enabled and checks it for crashes afterwards."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GAME_DIR = Path(os.environ.get("GENERALS_GAME_DIR", ROOT / "GameFiles"))
GAME_EXE = GAME_DIR / "generalszh.exe"
CRASH_DUMP_DIR = Path.home() / "OneDrive" / "Documents" / "Command and Conquer Generals Zero Hour Data" / "CrashDumps"
if not CRASH_DUMP_DIR.exists():
    CRASH_DUMP_DIR = Path.home() / "Documents" / "Command and Conquer Generals Zero Hour Data" / "CrashDumps"

# -ignoreAsserts keeps debug assertion boxes from blocking unattended runs; assertions are still
# written to the log, which collect_artifacts() checks. -scriptApiDebug enables the debug-build-only
# commands (debug_world, debug_add_cash) the tests use as ground truth.
DEFAULT_ARGS = ["-win", "-nologo", "-noshellmap", "-noaudio", "-xres", "800", "-yres", "600", "-ignoreAsserts",
                "-scriptApiDebug"]

# Assertions the unmodified debug build raises in normal play. Anything else fails the tests.
KNOWN_ASSERTIONS = (
    # Raised once when any skirmish AI player starts, on every map and for every AI faction; comes from
    # the AI's script data, not from the script API (see Plans/Phase-2-Skirmish-Harness.md).
    "Failed to find thing template Tech Center",
    # Raised when an AmericaPowerPlant is sold: its art defines overlapping SOLD model states
    # (game data; any human selling one in a debug build sees it).
    "ambiguous model match in findBestInfoSlow",
    # Raised on every client of a game with an observer slot: Player.cpp looks for a skirmish side
    # "Observer" (no map has one), and LoadScreen.cpp has no portrait for the observer template.
    # A human observer joining from the LAN menus sees the same (see Plans/Phase-6-LAN-Observers.md).
    "Could not find skirmish player for side Observer",
    "Unexpected player template",
)

# The unmodified debug build already reports these leaks on every clean exit (upstream issue).
# The leak report is checked separately so new leaks still fail the tests.
KNOWN_BASELINE_LEAKS = 3
# Exiting after a live (API-started) skirmish reports extra blocks that do not depend on API use (see
# Plans/Phase-3-World-View.md and Phase-4-Core-Actions.md, Findings). Their total varies with what was
# on screen, so they are checked by kind: (pattern, max count or None for any number).
KNOWN_LEAKS_AFTER_MATCH = "after_match"
AFTER_MATCH_LEAK_KINDS = (
    (re.compile(r"size 16, tagstring global operator new"), 18),     # live-play static containers
    (re.compile(r"size (3076|5124), tagstring global operator new"), None),  # rendering buffers
    (re.compile(r"Vector\.h"), 1),
    (re.compile(r"GameAudio\.cpp, from pool/dma AudioRequest"), 1),
    # After using the LAN menus: LanLobbyMenu.cpp's file-static player name outlives the leak report (its
    # size follows the name's length), and one menu layout (created through the shell, never by the API)
    # is left after a LAN match.
    (re.compile(r"size (16|32|64), tagstring STR_UnicodeString::ensureUniqueBufferOfSize"), 1),
    (re.compile(r"GameWindowManagerScript\.cpp, from pool/dma WindowLayoutPool"), 1),
)
# Logged by Network::setSawCRCMismatch when the lockstep clients disagree (a desync).
DESYNC_MARKER = "Latest frame for mismatch"

LEAK_REPORT = re.compile(r"Begin Simple Leak Report.*?End Simple Leak Report", re.S)
LEAK_COUNT = re.compile(r"There were (\d+) memory leaks")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _crash_dumps() -> set[Path]:
    return set(CRASH_DUMP_DIR.glob("*.dmp")) if CRASH_DUMP_DIR.exists() else set()


def check_after_match_leaks(report: str) -> list[str]:
    counts = [0] * len(AFTER_MATCH_LEAK_KINDS)
    problems = []
    for line in report.splitlines():
        if not line.startswith("Leaked"):
            continue
        for index, (pattern, _) in enumerate(AFTER_MATCH_LEAK_KINDS):
            if pattern.search(line):
                counts[index] += 1
                break
        else:
            problems.append(f"unexpected leak: {line.strip()}")
    for (pattern, limit), count in zip(AFTER_MATCH_LEAK_KINDS, counts):
        if limit is not None and count > limit:
            problems.append(f"{count} leaks matching {pattern.pattern!r} (allowed {limit})")
    return problems


def check_log(text: str, leak_baseline: int | str = KNOWN_BASELINE_LEAKS) -> list[str]:
    """Returns problems found in a debug log, tolerating the known baseline leak report."""
    problems = []
    for report in LEAK_REPORT.findall(text):
        if leak_baseline == KNOWN_LEAKS_AFTER_MATCH:
            problems += check_after_match_leaks(report)
            continue
        match = LEAK_COUNT.search(report)
        leaks = int(match.group(1)) if match else 0
        if leaks > leak_baseline:
            problems.append(f"{leaks} memory leaks (baseline {leak_baseline})")
    remainder = LEAK_REPORT.sub("", text)
    for line in remainder.splitlines():
        if "ASSERTION FAILURE" in line and not any(known in line for known in KNOWN_ASSERTIONS):
            problems.append(line.strip())
        elif "EXCEPTION DUMP" in line:
            problems.append("EXCEPTION DUMP")
        elif DESYNC_MARKER in line:
            problems.append(f"desync: {line.strip()}")
    return problems


class GameProcess:
    def __init__(self, results_dir: Path, extra_args: list[str] | None = None, port: int | None = None,
                 leak_baseline: int | str = KNOWN_BASELINE_LEAKS):
        self.leak_baseline = leak_baseline
        self.port = port or free_port()
        self.url = f"ws://127.0.0.1:{self.port}"
        self.results_dir = results_dir
        self.args = [str(GAME_EXE), *DEFAULT_ARGS, "-scriptApiPort", str(self.port), *(extra_args or [])]
        self.proc: subprocess.Popen | None = None
        self._dumps_before: set[Path] = set()

    def start(self, timeout: float = 90.0) -> "GameProcess":
        self._dumps_before = _crash_dumps()
        self.proc = subprocess.Popen(self.args, cwd=GAME_DIR)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"game exited during startup with code {self.proc.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return self
            except OSError:
                time.sleep(0.5)
        self.kill()
        raise TimeoutError(f"script API port {self.port} did not open within {timeout}s")

    def adopt(self, proc: subprocess.Popen) -> "GameProcess":
        """Takes over a game process started elsewhere (the launcher), on this object's port."""
        self._dumps_before = _crash_dumps()
        self.proc = proc
        return self

    def wait_exit(self, timeout: float) -> int:
        assert self.proc is not None
        return self.proc.wait(timeout=timeout)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def kill(self) -> None:
        if self.running:
            self.proc.kill()
            self.proc.wait(timeout=10)

    def debug_log(self) -> Path | None:
        """This instance's log. Each client instance writes its own DebugLogFileD*.txt."""
        marker = f"ScriptApi: listening on 127.0.0.1:{self.port}"
        for log in sorted(GAME_DIR.glob("DebugLogFileD*.txt")):
            if "Prev" not in log.name and marker in log.read_text(errors="replace"):
                return log
        return None

    def collect_artifacts(self) -> list[str]:
        """Copies the log and new crash dumps to results_dir; returns problems found."""
        self.results_dir.mkdir(parents=True, exist_ok=True)
        problems = []
        log = self.debug_log()
        if log is not None:
            shutil.copy2(log, self.results_dir / log.name)
            problems += check_log(log.read_text(errors="replace"), self.leak_baseline)
        for dump in sorted(_crash_dumps() - self._dumps_before):
            shutil.copy2(dump, self.results_dir / dump.name)
            problems.append(f"crash dump {dump.name}")
        return problems
