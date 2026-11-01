# Phase 7 — Hardening, Named Replays and an APM Cap

Parent plan: [PLAN-script-api.md](../PLAN-script-api.md) · Previous: [Phase 6](Phase-6-LAN-Observers.md)
Status: **Done**

## Goal
Make the API dependable for unattended bot matches:
- fix the problems found when an agent first played a whole match through the API
- reconnecting mid-match gives the new client a clean session
- every launcher match is kept as a named replay, and a bot-vs-bot LAN replay plays back without a CRC mismatch
- an optional cap on actions per minute for fair matches

## Input: the first agent-played match
An agent wrote and ran its own bot through the API (LAN, vs Easy AI, with an observer) and won in about 18 minutes of game time. It reported:

| Report | Triage |
|---|---|
| Supply docks never appear in snapshots | **Bug.** `isReportable` drops `KINDOF_IGNORED_IN_GUI`, and Zero Hour's `SupplyDock` and `SupplyPile` carry that kind (`SupplyWarehouse` doesn't). They are drawn and a human sees them, so the bot must too |
| `purchase_science` accepts purchases that can't happen | **Bug.** `ScienceStore::getPurchasableSciences` checks ownership and prerequisites but not points. Also, two purchases sent before the first executes both pass, because ownership changes only when the logic runs the message |
| `attack` on a Chinook replied `ok`, nothing happened | **Not an API bug.** The Chinooks were parked on the ground, and `attack` already runs the engine's own `getAbleToAttackSpecificObject` (the check a click uses); a landed Chinook passes it. No change |
| Reconnecting works (4001 `superseded`) | As designed. This phase defines what a new connection inherits |

## Already covered by earlier phases
- **Protocol versioning:** `hello {protocol_version}` is refused with `PROTOCOL_MISMATCH` since phase 1.
- **Sync check with the API on and off:** the API is off unless a `-scriptApi*` flag is given, so the phase 3 replay test, which re-simulates an API match headless without those flags, is that check: any influence of the API on the simulation is a CRC mismatch.
- **Slow clients:** the server drops a client whose outbound queue or socket buffer is over its limit (phase 1).
- **Replays per instance:** the engine already writes `00000000_InstanceNN.rep` for instance N > 1, so instances on one PC don't overwrite each other's replay.

## In scope

### 1. Fixes
- **Supply sources reported.** `isReportable` keeps `KINDOF_SUPPLY_SOURCE` objects even when they are `IGNORED_IN_GUI`. They are neutral, immobile structures, so they also enter `known_structures` once seen. The amount of supply left isn't reported (a human only sees the pile shrink).
- **`purchase_science` checks points and pending purchases.** The catalog's `purchasable_now` follows the same rule (it also ignored points), and a new `prerequisites_met` tells "no points yet" apart from "locked".
  - Not enough points: `INSUFFICIENT_FUNDS`.
  - A purchase of the same science is already on its way (sent, not yet executed): `NOT_AVAILABLE`. The points of pending purchases count as spent.
  - Pending purchases are dropped when their `MSG_PURCHASE_SCIENCE` executes, and at the start of every match.

### 2. Reconnects
A new connection replaces the old one (close 4001, unchanged). On every new connection:
- `command_executed` events for orders the previous connection sent are no longer reported (they would carry request ids the new client never used). `CommandTracker::orphanAll()` keeps the entries, so the FIFO still lines up with the messages the logic executes, but suppresses their completions.
- The snapshot interval goes back to its default.
- Everything about the match itself carries over: the game, the player's memory of fogged structures, and the enemy-visibility state.

A disconnect itself changes nothing in the match: units keep their orders.

### 3. `save_replay {name, overwrite?}`
- Valid in the `shell` state only (`WRONG_STATE` in a game: the replay is still being written). `NOT_AVAILABLE` when this process hasn't finished a game yet.
- Copies this instance's last replay (`RecorderClass::getLastReplayFileName()`, instance-aware) to `Replays\<name>.rep`.
- **Name rules** (`parseReplayName`, unit-tested): 1–64 characters of letters, digits, space, `_ - . ( )`; no leading or trailing space or dot; a trailing `.rep` is stripped. Anything else, including path separators, is `INVALID_ARGUMENT`.
- An existing file is `INVALID_ARGUMENT` unless `overwrite: true`.
- Reply: `{file}` (the file name inside the replay folder).

### 4. APM cap
- `-scriptApiApm N` (default 0, no cap): at most N accepted order commands per 60 s of game time (1800 logic frames, a sliding window). Game time rather than wall time, so a slowed-down game doesn't hand out extra actions.
- Every command registered through `addOrder` (all of `ScriptApiActions.cpp` and `ScriptApiAbilities.cpp` except the debug commands) checks the budget **before** it appends any message, and counts once it is accepted. A refused order doesn't count, the way a click on a greyed-out button isn't an action. Queries and session commands never count.
- Over the cap: `RATE_LIMITED` (new error code), with the frames until the next slot frees up in the message.
- `hello` reports `apm_limit` (0 when off).
- Game-independent: `scriptapi::ActionRateLimiter`.

### 5. Launcher
- `--apm N` passes `-scriptApiApm N` to every bot instance.
- At the end of a match, bot 1's client leaves the game (`quit_game`), waits for the shell and runs `save_replay`, then all instances exit. The name is `--replay NAME`, by default `<YYYYmmdd-HHMMSS>_<bot1>_vs_<bot2 or ai-difficulty>`; `--no-replay` skips it. The summary lists the replay file.

## Out of scope
- A `reconnect()` convenience in the Python client: a new `GeneralsClient` plus `World.load` already does it.
- Replays of observers' instances (any peer's replay is the same match).

## Game-independent pieces (unit-tested)
| Piece | Where |
|---|---|
| `ActionRateLimiter` (limit, window, `allows`, `record`, `framesUntilAvailable`) | `ScriptApiCommands.{h,cpp}` |
| `CommandTracker::orphanAll` | `ScriptApiCommands.{h,cpp}` |
| `parseReplayName` | `ScriptApiCommands.{h,cpp}` |
| `RATE_LIMITED` error name | `ScriptApiProtocol.{h,cpp}` |

## Tests

### C++ unit tests (`ScriptApiHardeningTest.cpp`)
- Rate limiter: no cap allows everything; N per window; the window slides (frame 1800 frees the slot used at frame 0); `framesUntilAvailable`.
- `orphanAll`: orphaned entries still consume executed messages in order but report no completion; entries added afterwards report normally.
- `parseReplayName`: accepted names, `.rep` stripping, every rejected form (empty, too long, separators, `..`, leading/trailing dot or space, non-ASCII).

### Python unit tests
- `client.save_replay` sends `{name, overwrite}`.
- Launcher: `--apm` reaches the bot instances' arguments only; the default replay name; `--no-replay`.

### Integration
| Test | Module | What |
|---|---|---|
| 1 | `test_hardening.py` | Supply sources: every `SUPPLY_SOURCE` object `debug_world` says is visible appears in the snapshot's `visible`, and there is at least one |
| 2 | `test_hardening.py` | `purchase_science` with 0 points → `INSUFFICIENT_FUNDS`; with 1 point, two purchases of the same science sent together → one `ok`, one `NOT_AVAILABLE`; buying it again once owned → `NOT_AVAILABLE` |
| 3 | `test_hardening.py` | Reconnect mid-match: an order is sent and the socket dropped before it executes; a new client gets `in_game` from `hello`, the same own units, no `command_executed` for the old order, the default snapshot interval, and new orders work |
| 4 | `test_hardening.py` | APM cap (`-scriptApiApm 5`, own instance): `hello` reports 5; refused orders don't count; 5 orders pass, the 6th is `RATE_LIMITED`; queries still work |
| 5 | `test_replay_consistency.py` | `save_replay` in game → `WRONG_STATE`; after the match → the named copy matches the last replay; existing name → `INVALID_ARGUMENT`, `overwrite` works; bad names → `INVALID_ARGUMENT`. The saved copy is what gets re-simulated |
| 6 | `test_hardening.py` | `save_replay` before any game → `NOT_AVAILABLE` |
| 7 | `test_lan_launcher.py` | Bot vs bot over LAN through the launcher saves a named replay; it plays back headless to the end with exit code 0 |

## Acceptance criteria
- [x] Agent-match bugs fixed, with tests (1, 2)
- [x] Reconnect semantics implemented and tested (3)
- [x] APM cap implemented and tested (4)
- [x] `save_replay` and launcher replay naming (5, 6, 7)
- [x] A bot-vs-bot LAN replay plays back headless with no CRC mismatch (7; ends 1-2 s short, Finding 5)
- [x] C++ (109) and Python unit tests pass; the full suite passed three runs in a row: 124 passed, 1 skipped, about 19m35s each
- [x] Master plan and CLAUDE.md updated

## Risks
- **Quitting a LAN match to save the replay** sends a self-destruct from bot 1 if the match is still running. That's the end of the match anyway, but the recorded result is a loss for bot 1.
- **Same-frame requests:** test 2 relies on two requests arriving before the first purchase executes. The pending list makes the second fail whether or not they arrive in the same frame, so the test holds either way.

## Findings
1. **Supply docks are `IGNORED_IN_GUI`.** In Zero Hour's `INIZH.big`, `SupplyDock` and `SupplyPile` have `KindOf = STRUCTURE IMMOBILE SELECTABLE SUPPLY_SOURCE_ON_PREVIEW NO_COLLIDE SUPPLY_SOURCE IGNORED_IN_GUI`; `SupplyWarehouse` lacks the last flag. The phase 3 filter dropped every `IGNORED_IN_GUI` object, so on maps using docks (Tournament Desert) a bot never saw a supply source. `KINDOF_SUPPLY_SOURCE` now overrides the filter (test 1).
2. **`getPurchasableSciences` ignores points.** It checks ownership and prerequisites only; the promotion screen checks the points itself. Both `purchase_science` and the catalog's `purchasable_now` relied on it. The agent's "two purchases of Strike 2 both accepted at 0 points" was this, plus ownership changing only when the logic executes the purchase. Pending purchases now count as owned and spent (test 2).
3. **`attack` on a parked Chinook is accepted by the engine.** The enemy Chinooks sat landed in their base, which passes `getAbleToAttackSpecificObject` for ground units, the check a click uses. Nothing to fix in the API.
4. **The demo cheat for general's points is client-side.** `MSG_META_DEMO_GIVE_SCIENCEPURCHASEPOINTS` adds 1 point directly in `CommandXlat` (no network message), so a test using it would desync a replay; test 2 uses it only in the module's skirmish, never in a replay test.
5. **LAN replays play back headless.** Probe: the agent's 18-minute LAN match (bot vs Easy AI plus an observer) re-simulated to 18:23/18:23 with exit code 0 in 53 s. Launcher replays, where bot 1 quits with `quit_game`, stop 1-2 s short of the header's length (01:56/01:57, 01:40/01:42, 01:20/01:21). The header's `frameCount` is the frame the recording stopped at, but playback ends with the last recorded message (`m_nextFrame == -1`), and leaving a LAN game takes a few message-free frames after the self-destruct. Exit code 0 still means every recorded command and CRC was replayed. Test 7 allows 5 s.
6. **Replays per instance already exist.** `RecorderClass::getLastReplayFileName()` adds `_InstanceNN` for instance N > 1, so `save_replay` copies the calling instance's own file. A saved copy is byte-identical to the last replay after exit (test 5).
7. **Already covered:** protocol versioning (phase 1 `hello`), the API-on/off sync check (the phase 3 replay test re-simulates headless without any `-scriptApi*` flag, so the API is off), and slow-client handling (phase 1 server limits).
8. **The APM cap counts game time.** A minute is 1800 logic frames, so a game slowed down by debug builds or observers doesn't hand out more actions per game minute. Refused orders don't count, so a bot probing placements with `build` only pays for the one that succeeds.
