# CNC_Generals_AI

This project adds a **script API** to a C&C Generals Zero Hour engine fork. It lets a Python script play a player by itself, under exactly the same limits as a human. The end goal is two scripted players playing each other over LAN, with humans watching through replays or LAN observer slots.

- Overview, setup, single games and tournaments for humans: [README.md](README.md)
- Master plan: [PLAN-script-api.md](PLAN-script-api.md)
- Per-phase plans, with results and findings: [Plans/](Plans/)

Read both before starting a phase.

## Layout
| Path | What |
|---|---|
| `ZeroHourFork/GeneralsGameCode/` | The engine fork (TheSuperHackers GeneralsGameCode, a git repo). All C++ work happens here |
| `GameFiles/` | A copy of the Steam Zero Hour install. The built `generalszh.exe` is deployed here and run from here |
| `python/` | The `generals_api` package: `client.py`, `world.py`, `launcher.py`, `tournament.py` (runner, referee, audit, liveness) with `tournament_prompts/`, `watch.py`, `order.py`, `botkit.py`. Also the reference bot `bots/simple.py` (any faction), `BOT-NOTES.md` (gotchas for bot authors; keep it current), and the `tests/` tree (`unit/`, `integration/`). Venv in `python/.venv` |
| `tournament/<id>/` | Agent tournaments (`python -m generals_api.tournament`): config, bracket, agents' workspaces, games, transcripts. Procedure: [Plans/tournament-procedure.md](Plans/tournament-procedure.md) |
| `agent-matches/<timestamp>/` | Matches played by AI agents: each agent's workspace, conversation transcripts, replay |
| `scripts/` | `build.ps1`, `run-integration.ps1` |
| `Plans/` | One structured doc per phase |
| `test-results/<timestamp>/` | Integration-test artifacts: game logs, crash dumps, message transcripts |

Script API code in the fork:
- **`Core/Libraries/Source/ScriptApi/`** (`core_scriptapi`): server, protocol, router, skirmish request parsing, world-view helpers. No game headers, so it is unit-testable without the game.
- **`GeneralsMD/Code/GameEngine/{Include,Source}/ScriptApi/`**: the in-game subsystem.
  - `ScriptApi.cpp`: lifecycle and the per-frame update
  - `ScriptApiSkirmish.cpp`: start, quit and options commands
  - `ScriptApiWorldView.cpp`: queries, snapshots and hooks
  - `ScriptApiLanLobby.cpp`: LAN lobby, host/join/start, surrender (drives the LAN menu screens)
  - `ScriptApiActions.cpp`, `ScriptApiAbilities.cpp`: order commands (`addOrder`), button checks, committed money, `build_failed`
  - `ScriptApiInput.cpp`: the input lock
- **`Tests/Google/ScriptApi/`**: the `scriptapi_googletest` C++ unit tests.
- **Engine hooks:** small guarded calls in `GameEngine.cpp`, `GameLogic.cpp`, `Player.cpp`, `Object.cpp`, `Eva.cpp`, `CommandLine.cpp` and `GlobalData.{h,cpp}`.

## Commands
```powershell
.\scripts\build.ps1                        # configure + build win32-debug z_generals (script API on, multi-instance on)
.\scripts\build.ps1 -Tests -Deploy         # also build/run C++ unit tests; copy exe+pdb into GameFiles
.\scripts\build.ps1 -Target core_scriptapi -Tests   # fast loop for game-independent code
.\scripts\run-integration.ps1 [-Build] [pytest args]  # Python unit + integration tests against GameFiles exe
python\.venv\Scripts\python.exe -m pytest tests/unit -q   # Python unit tests only (run from python/)
python -m generals_api.launcher --bot1 bots/simple.py --vs-ai easy --observer   # play a match (from python/)
python -m generals_api.watch ws://127.0.0.1:PORT --max-wait 60   # wait for something to matter in a running game
python -m generals_api.tournament init|practice|run-game|prompt|snapshot|save-session|bracket|cleanup ...   # see Plans/tournament-procedure.md
```
- PowerShell may need `powershell -ExecutionPolicy Bypass -File scripts\build.ps1 ...`.
- A full rebuild takes about 3–4 minutes. The full Python suite takes about 35 minutes, because it plays real matches; run single modules while developing.
- If a running game has the exe locked, `-Deploy` fails. Close it first.

## Workflow (how the user wants phases done)
1. **Plan:** write `Plans/Phase-N-<Name>.md`, following the format of the existing ones: goal, scope, engine references, design, tests, acceptance checklist, risks.
2. **Tests:** write the C++ and Python unit tests and the integration tests.
3. **Implement**, until everything passes. Then run the **full** suite once (one sweep; the user asked not to repeat it).
4. **Record:** fill in the phase doc's acceptance checklist and a **Findings** section. Update the master plan if the design changed.

Prove an engine assumption with a quick probe (a Python script in the session scratchpad using `tests/integration/gamehost.py`) before building on it.

## Non-negotiable design rules
- **Fair play:** scripts act only by injecting the same network `GameMessage`s a click would. They go in during `ScriptApi::update()`, before `TheMessageStream->propagateMessages()`. Never call game logic directly to cause effects.
- **Fog of war:** report another player's object only if the local human could see it (`scriptapi::isVisibleToPlayer`), or it's a fog "ghost" (the engine says `OBJECTSHROUD_FOGGED` and it's immobile). Never read pathfinding obstacles, enemy economy or production.
- **Hooks are read-only:** they don't write game objects or use the logic random number generator. The replay CRC test (`test_replay_consistency.py`) must keep passing.
- **Threads:** only the game thread touches engine objects. The server threads only use the inbound/outbound queues. Game-side code must never include IXWebSocket headers; `ScriptApiServer.h` hides them behind a pimpl so they don't clash with winsock.
- **APM cap:** `-scriptApiApm N` caps accepted orders per minute of game time. Register new order commands with `addOrder`, not `m_router.add`, so the cap applies.
- **Debug-only hidden state:** commands that reveal it or bypass rules (`debug_world`, `debug_add_cash`, `debug_inject_input`, `set_input_mode`) exist only in debug builds and only with `-scriptApiDebug`.
- **Input lock:** `-scriptApiInput view|locked|full`, default `view` (camera only). Humans must never be able to give orders from a bot's window. Orders are checked like UI clicks: the button exists and is available, `canMakeUnit`, a legal build location, and a visible target.

## Code conventions (fork)
- **Line endings:** the fork's C++ and most CMake files are **CRLF**. `sed -i` in Git Bash turns them into LF, so edit with Python (`newline=''`) or the Edit tool, and check with `file <path>`.
- **New files** get the GPL header used in the repo ("Copyright 2026 TheSuperHackers").
- **Guards:** wrap all engine changes in `#if RTS_SCRIPT_API`. Comment fixes to existing code with `// TheSuperHackers @bugfix ...`.
- **Build-option scope:** `RTS_SCRIPT_API` is defined on `core_config`, so every target sees the same `GlobalData` layout. Code shared through Core must also check `RTS_ZEROHOUR`.
- **`ErrorCode` name clash:** the engine has a global `ErrorCode` type, so game-side files must write `scriptapi::ErrorCode` in full, with no `using`.
- **Passing JSON:** builders take `Json` by value. Move large payloads, such as snapshots, instead of copying them. In debug builds every JSON allocation goes through the game's checked allocator and is slow.

## Engine facts that cost time to learn
- **Starting a game takes two passes.** `GameLogic::startNewGame` first only sets `m_startNewGame`, and the next frame does the blocking load. One normal engine frame runs while the state is already `loading`.
- **"Multiplayer session" is misleading.** `GameEngine::isMultiplayerSession()` stays true after any skirmish. Use `TheNetwork != nullptr` to detect a network game.
- **Quitting.** `GameLogic::quit(FALSE)` opens the quit menu in an interactive game. `quit_game` instead runs what happens after the menu is confirmed.
- **Two instances need an option.** Multi-instance comes from `RTS_DEBUG_MULTI_INSTANCE`, which is off by default; `build.ps1` turns it on for debug. Instance N writes `GameFiles/DebugLogFileD_InstanceNN.txt`.
- **Install path.** Debug builds need `HKCU\Software\Electronic Arts\EA Games\Generals\InstallPath` set to `GameFiles\ZH_Generals\` (already set). On assertion dialogs, "Retry" crashes the game when no debugger is attached.
- **Protected UI methods.** `ControlBar::getCommandAvailability` and `Mouse::blockCapture` are protected. Use the guarded wrapper `getCommandAvailabilityForScriptApi`, and `setCursorCaptureMode`.
- **Client-side network messages.** Some are sent by the client on its own, not by input, for example `MSG_ENABLE_RETALIATION_MODE`, which syncs an option once a second. The input lock's command guard must allow-list such system messages. Look for "dropped network message N" in the log.
- **Minimized windows freeze.** In a skirmish, `Win32GameEngine::update` stops the game loop while the window is minimized; LAN and online games keep running. A script-controlled client now keeps running too.
- **Button availability.** `COMMAND_ACTIVE` means a pressed-in toggle, such as the weapon mode in use, and still counts as clickable. Some buttons (`MUST_BE_STOPPED`) are disabled while the unit moves.
- **Science names.** `ScienceStore::getScienceFromInternalName` only hashes the name, so check `isValidScience` as well.
- **Containers.** Garrisoned or transported units are not selectable, so orders to them get `NOT_OWNED`. They show `contained_by` in snapshots.
- **Orders apply to the logic selection.** The API always sends `MSG_CREATE_SELECTED_GROUP` before an order. Non-mass-selectable objects, such as buildings, can only be selected alone.
- **LAN menus.** `TheShell->push` is deferred until the old screen's shutdown animation ends, so LAN commands reply at once and finish in `updateLan()`. The LAN menu code expects its windows to exist; drive it only while its screen is on top. LAN game names are always the host's IP and seed. Accepts reset on every slot change.
- **Multi-instance LAN.** Instance N binds `127.0.0.(N+1)`; loopback broadcast reaches the other instances.
- **One controller, up to three watchers per instance.** `ws://…:PORT` is the controller; a new controller replaces the old one (close 4001) and starts a clean session. `ws://…:PORT/watch` is a watcher (role from the URL path at socket open, since the old controller is replaced before any message): every event and query, orders allowed, session commands `WRONG_ROLE`; a fourth is refused (close 4003). `command_executed`/`build_failed` go to the sender; snapshot intervals are per connection. `hello` reports `role` and, after `game_over`, `game_result`.
- **Replays.** They go to `Documents\Command and Conquer Generals Zero Hour Data\Replays\00000000.rep` (`00000000_InstanceNN.rep` for instance N > 1), overwritten each game; `save_replay` copies it under a name from the menus. `-headless -replay x.rep` re-simulates one, exiting with 1 on a CRC mismatch. Playback stops at the last recorded message, so a LAN replay ends a second or two short of its header length.
- **Supply docks are `IGNORED_IN_GUI`** in Zero Hour's data, but drawn; the snapshot filter lets `SUPPLY_SOURCE` through.
- **Hidden buttons.** The control bar hides a button with `NEED_SPECIAL_POWER_SCIENCE` until the player owns the power's `RequiredScience`, and `getCommandAvailability` doesn't check that; `requireButtonAvailable` does. Forced attacks use `ATTACK_NEW_TARGET_FORCED` (own targets allowed).
- **Money is taken on execution.** Builds, units and upgrades withdraw money when their message executes, and the engine silently drops one it can't afford then. The API counts orders still on their way as spent (`PendingSpend`) and reports dropped builds as `build_failed`.
- **`isReportable` is also the event filter.** Snapshots, `debug_world` (unless `all: true`) and the destruction events skip projectiles, debris and scenery.
- **After `game_over`** every instance (observer too) goes to the score screen by itself about 12 s later and reports `shell`; `save_replay`/`exit` work there, `quit_game` doesn't apply. Observers get `game_over` with `result: "ended"` (from `VictoryConditions::amIObserver`/`getEndFrame`).
- **Factions.** The 12 selectable factions each have their own side; generals use prefixed templates (`AirF_`, `Lazr_`, `SupW_`, `Tank_`, `Infa_`, `Nuke_`, `Chem_`, `Demo_`, `Slth_`). `catalog()["faction"]` is the side, i.e. the faction name without `Faction`.
- **Sciences.** `getPurchasableSciences` ignores general's points; check `getSciencePurchasePoints` too. `MSG_META_DEMO_GIVE_SCIENCEPURCHASEPOINTS` is client-side and desyncs replays.

## Test harness notes
- **Launch flags.** Integration tests launch `generalszh.exe -win -nologo -noshellmap -noaudio -ignoreAsserts -scriptApiDebug -scriptApiPort <free>`. After each game, `gamehost.check_log` fails the test on assertions or crash dumps.
- **Known allowances**, each documented in the plan docs. Don't widen them without evidence:
  - `KNOWN_BASELINE_LEAKS = 3`
  - `KNOWN_LEAKS_AFTER_MATCH`, checked by leak kind in `AFTER_MATCH_LEAK_KINDS` and used through `@pytest.mark.leak_baseline`
  - `KNOWN_ASSERTIONS` holds the skirmish-AI "Tech Center" data assertion, the AmericaPowerPlant SOLD "ambiguous model match", and two observer-slot assertions (Player.cpp, LoadScreen.cpp)
- **Fixtures:** `test_lan.py` starts its own instances (`start_instances` / `stop_instances`); the launcher tests adopt the launcher's processes (`GameProcess.adopt`). The `game` fixture is per module, `fresh_game` is per test (for tests that end the process), and `skirmish` runs a match against an Easy AI on Tournament Desert.
- **Helpers:** `tests/integration/helpers.py` has `base_setup`, `build_and_wait`, `train_and_wait` and `ensure_structure`, which also builds catalog prerequisites. Tests in a module share one match, so replace units lost in earlier tests rather than assuming they're alive.
- **Reserved request fields:** `id` and `cmd` can't be used as request argument names; the client rejects them.
- **State races:** use `client.wait_for_state()`, not a bare `wait_for_event("game_state")`. It avoids missing a state change that arrived before you started waiting.

## Running agent tournaments
Follow [Plans/tournament-procedure.md](Plans/tournament-procedure.md). Things learned running t1 and t2:
- **Agents are subagents** (Agent tool, `model` per agent, `run_in_background`). Their transcripts are in this session's `subagents/agent-<id>.jsonl`; the task `.output` link can be empty. Keep the ids in `tournament/<id>/state/sessions.json`.
- **Prompts are rendered** with `tournament prompt <id> prep|game <agent>` from `python/generals_api/tournament_prompts/`. Pass the rendered text unchanged, so every agent gets the same prompt; record any deviation in `state/sessions.json`.
- **Game numbers are in playing order**; with best-of series they differ from matchup numbers. `snapshot`, `save-session --game` and `prompt --game` find the game by its recorded `game.json`.
- **Agents often stop preparation early**; each may be told once that it has time left. Run at most two preparations at a time (each has a practice game).
- **In games, agents should stay in the `watch` loop until `game_over`**; if one hands back mid-game, resume it once. Stop each agent at its 5-minute cap, then `snapshot` and `save-session`.
- **Review audit flags before acting on them.** Reading or editing their own old ports, or ports inside files they wrote, aren't violations.
- **Tournament games start with `-ignoreAsserts`** (`GAME_ARGS`); without it the debug build's known assertion dialogs block games.
- **Replays** are saved under `<id> game <n>` in the game's Replays folder and copied to `games/<n>-…/replay.rep`.

## Upstream
The user does not plan to upstream the script API. Bug fixes to existing engine code found along the way may go upstream as separate small PRs, kept free of script API code. Candidates so far: `-ignoreAsserts` lost at shutdown (`CommandLine.cpp`), the debug memory-totals race (`GameMemory.cpp`), and `TheLAN` leaked on exit (`GameEngine.cpp`). The fork's own `AI_POLICY.md` and `CONTRIBUTING.md` apply to anything sent upstream.
