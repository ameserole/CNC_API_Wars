# Script API for C&C Generals Zero Hour — Implementation Plan

## Goal
A Python script plays one player by itself, under the same limits as a human:
- It gives orders only by sending the same commands a mouse click would.
- It sees only what its player could see through fog of war.
- The game keeps running in real time and never waits for the script.

The end goal is two scripted players playing each other over a LAN.

## Decisions
| Area | Choice |
|---|---|
| Actions in | Inject standard network `GameMessage`s for the local player, the same path as mouse clicks |
| Events out | Hooks in the engine push events. Fog-filtered snapshots fill in the rest |
| Transport | WebSocket server inside the game, carrying JSON, one connection per game instance |
| Client | Python (asyncio) |
| Build | `win32` / `win32-debug` presets (VS 2022 Build Tools) only, behind CMake option `RTS_BUILD_OPTION_SCRIPT_API`. The VC6 build is left unchanged |

## Why this fits the engine
- **Game loop:** `GameEngine::update()` runs the client, then `TheMessageStream->propagateMessages()`, then the network, then the game logic ([GameEngine.cpp:878](ZeroHourFork/GeneralsGameCode/GeneralsMD/Code/GameEngine/Source/Common/GameEngine.cpp#L878)). We drain the command queue just before `propagateMessages()`.
- **Player identity is automatic:** a `GameMessage` takes the local player's index when it is created ([MessageStream.cpp:57](ZeroHourFork/GeneralsGameCode/Core/GameEngine/Source/Common/MessageStream.cpp#L57)). Each game instance is one player and its script, so scripts cannot impersonate anyone else.
- **Lockstep-safe:** network-range messages (1000–1999) go from `TheCommandList` through `Network::GetCommandsFromCommandList` to the other peers. LAN games stay in sync, and replays record what the script did.
- **Ownership is already enforced:** `logicMessageDispatcher` drops any selected units the issuing player doesn't own ([GameLogicDispatch.cpp:357](ZeroHourFork/GeneralsGameCode/Core/GameEngine/Source/GameLogic/System/GameLogicDispatch.cpp#L357)).
- **Fog checks exist:** `Object::getShroudedStatus(playerIndex)` and `PartitionManager::getShroudStatusForPlayer(playerIndex, loc)`.
- **Two instances on one PC:** the opt-in CMake option `RTS_DEBUG_MULTI_INSTANCE` defines `RTS_MULTI_INSTANCE` ([config-debug.cmake:33](ZeroHourFork/GeneralsGameCode/cmake/config-debug.cmake#L33)). It is OFF by default, so `scripts/build.ps1` turns it on for debug builds. Without it, a second instance exits with code 1 ("already running"). Each instance gets its own `127.x.y.z` LAN address ([IPEnumeration.cpp:100](ZeroHourFork/GeneralsGameCode/Core/GameEngine/Source/GameNetwork/IPEnumeration.cpp#L100)), so two bots can play LAN on one machine.

## Architecture

```
 Python bot  <--WebSocket JSON-->  [Server thread]
                                      |  inbound queue (commands)
                                      v
 GameEngine::update(): ScriptApi::pumpCommands() -> TheMessageStream (local player)
                       propagateMessages -> CommandList -> Network (lockstep) -> GameLogic
 GameLogic hooks (read-only) --> ScriptApi::emit() --> outbound queue --> Server thread --> Python
 Every N frames: ScriptApi::snapshot() (fog-filtered) --> outbound queue
```

### Rules
1. **Only the game thread touches game objects.** The server thread only reads and writes the two queues (mutex plus deque).
2. **Hooks are read-only.** They must not change game state, use the game's random-number generator, or allocate memory from game-logic memory pools. The logic CRCs (sync checks) must stay identical with the API on or off, so LAN peers never desync.
3. **Every message carries the logic frame number.** A command reply returns `client_frame`. The matching `command_executed` event later reports the `logic_frame` when the command actually ran. In network play there are a few frames of lag between the two.
4. **If the script disconnects, the player just goes idle.** The game never blocks waiting for the script.

### Code layout
- `GeneralsMD/Code/GameEngine/Include/ScriptApi/` and `.../Source/ScriptApi/`
  - `ScriptApi.h/.cpp`: subsystem lifecycle, queues, pump, and `emit()`
  - `ScriptApiServer.cpp`: WebSocket server thread
  - `ScriptApiCommands.cpp`: turns JSON into validated `GameMessage`s
  - `ScriptApiEvents.cpp`: hook entry points and the visibility diff
  - `ScriptApiSnapshot.cpp`: world snapshots, catalog and map info
- Dependencies come through `FetchContent` in new `cmake/` files, the same way stb and gamespy are fetched: **IXWebSocket** for the server and **nlohmann/json** for JSON.
- Command-line flags (all of these also work in the integration tests):
  - `-scriptApi` turns the API on.
  - `-scriptApiPort N` sets the port. The default is `27100 + instance index`.
  - `-scriptApiInput view|locked|full` sets how much a human can do in the bot's window. The default is `view`. See [Input lock](#input-lock-humans-cant-play-a-bots-player).
  - `-scriptApiDebug` (debug builds only) enables test-only commands that reveal hidden state.
  - The server binds to `127.0.0.1` only.
- Python client: `CNC_Generals_AI/python/generals_api/`.

## Protocol (JSON over WebSocket)
Detailed per-phase plans are in [Plans/](Plans/). Every message from the game has a `type` of `reply` or `event`.
- Script to game: `{"id": 17, "cmd": "move", "units": [101, 102], "pos": [1200, 800]}`
- Game to script, reply: `{"type": "reply", "reply_to": 17, "ok": true, "client_frame": 4410}`, or `{"type": "reply", "reply_to": 17, "ok": false, "error": "NOT_VISIBLE", "message": "..."}`
- Game to script, event: `{"type": "event", "event": "unit_destroyed", "frame": 4502, "id": 101, ...}`
- Game to script, snapshot: `{"type": "event", "event": "snapshot", "frame": 4500, "self": {...}, "units": [...], "visible_enemies": [...], "known_structures": [...]}`

### Session commands
These are accepted in the shell (menus) as well as in a game.

| Command | Purpose |
|---|---|
| `hello` | Agree on the protocol version. The reply is `game_state` (`shell`, `loading` or `in_game`), the API version and the build type |
| `start_skirmish` | `{map, factions, opponents: [{difficulty: "easy", faction, team}], seed, fps_limit, start_money}`. Does what the skirmish menu's start button does: fills `TheSkirmishGameInfo`, calls `startGame(0)` and sends `MSG_NEW_GAME` (see `reallyDoStart` in SkirmishGameOptionsMenu.cpp) |
| `quit_game` | Leaves the current game and returns to the shell |
| `exit` | Shuts the game down cleanly, so tests can end the process without killing it |

`start_skirmish` is only allowed when no network game is running. It is a way to set up a single-player match, not an in-game advantage.

### Commands
Each order command takes a `units` list. The API sends `MSG_CREATE_SELECTED_GROUP` before the order, the way a player selects units and then clicks.

| Phase | Commands |
|---|---|
| 4 | `move`, `attack_move`, `attack_object`, `force_attack_pos`, `stop`, `guard`, `train` (`MSG_QUEUE_UNIT_CREATE`), `cancel_train`, `build` (`MSG_DOZER_CONSTRUCT`), `set_rally_point`, `sell` |
| 5 | `upgrade`, `purchase_science`, `special_power` (target: object, position or none), `enter` / `garrison`, `evacuate`, `repair`, `capture`, `hack`, `scatter`, `waypoint` paths, `formation` |

**Validation runs the same checks the game's UI runs before a click goes through:**
- the unit exists, it is ours, and it has this command available
- we can afford it and meet the prerequisites
- the build site is legal, using `TheBuildAssistant->isLocationLegalToBuild`
- any target object is **currently visible to us**, or is a fogged structure we've already seen

A failed check returns an error code. Nothing outside this list gets through.

### Queries (request and response)
- `game_info`: map name and size, players and factions, our player index, start positions.
- `catalog`: what we can build and research: templates, costs, build times, prerequisites and command sets.
- `map`: a coarse height and passability grid. A human sees the terrain too, so this is fair.
- `state`: an on-demand snapshot.

### Events
**Our own player** (always visible to us):
`unit_created`, `construction_started`, `build_failed`, `construction_complete`, `production_queued`, `production_complete`, `upgrade_complete`, `science_purchased`, `money_changed`, `power_changed`, `unit_damaged`, `unit_destroyed`, `special_power_ready`, `eva` (announcer alerts such as base under attack or low power), `command_executed`, `game_state` (shell, loading, in_game, victory, defeat).

**Other players** (fog-filtered, worked out by comparing visibility each frame or every few frames):
- `enemy_spotted` and `enemy_lost_from_view`
- `enemy_destroyed`, only if we could see it die
- `structure_discovered`, `structure_last_seen_updated`, for fogged buildings the player remembers

**Attacker information:** a damage or death event includes `attacker_id` only when the attacker is visible to us.

### Hook points
| Event | Location |
|---|---|
| object created / destroyed | `GameLogic::registerObject` / `destroyObject` |
| died (with killer) | `Object::onDie` (Object.cpp:4722) |
| unit produced | `Player::onUnitCreated` (Player.cpp:1550) |
| construction | `Player::onStructureCreated` / `onStructureConstructionComplete` |
| announcer alerts | `Eva::setShouldPlay` (Eva.cpp:372) |
| executed commands | tap in `logicMessageDispatcher` (own player only) |
| money / power | compare values once per frame |

## Input lock: humans can't play a bot's player
A bot instance is an ordinary game client with a window. Without a lock, any click or keypress in that window becomes a command for the bot's player, and keys like Esc open the quit menu. With the API on, human input is locked down.

| Mode (`-scriptApiInput`) | What a human can do in the bot's window |
|---|---|
| `view` (**default when `-scriptApi` is on**) | Move the camera only: scroll, zoom and rotate by mouse or keyboard. No selecting, no orders, no menus or hotkeys |
| `locked` | Nothing. All mouse and keyboard input is ignored |
| `full` | Everything, as normal. A debugging opt-out only. The script is still connected, so human and script orders mix |

**How it's done (the message stream):**
- **Raw input guard.** A `ScriptApiInputGuard` translator is attached at a priority below 10, so it runs before `WindowTranslator` and every other input translator. It drops raw mouse button messages (`MSG_RAW_MOUSE_*` clicks and double-clicks) and, in `locked` mode, every raw mouse and key message.
- **View mode keeps camera input.** A second guard sits just after `MetaEventTranslator` (priority 20). It passes only camera meta messages (scroll, zoom, rotate, reset) and drops the rest: selection, hotkeys, the quit menu, cheats.
- **Last check on network commands.** A final guard, just before the command list, drops any network-range message (1000–1999) the API didn't create itself. The API records the messages it adds in `ScriptApi::update()`. This also catches anything raised from on-screen GUI buttons.
- **The game UI stays visible but inert.** The control bar, minimap and score display still draw, but clicks never reach them.
- **Mouse capture.** In a locked instance the game must not confine the cursor to its window (`Mouse::blockCapture`), so a person can move between several bot windows freely.
- **Closing the window still works.** Closing it is how a person stops a bot, and it goes through the normal quit path.

The input mode can also be changed at runtime with a `set_input_mode` command (debug builds only), to help while developing. The lock is purely client-side: it drops local input before anything becomes a command, so it can't affect sync.

## Watching matches
Three ways to watch, all built on what the game already has.

### 1. Replays (after the match)
- **Already recorded.** The game records every skirmish and LAN game automatically (`RecorderClass`: `MSG_NEW_GAME` → `MSG_CLEAR_GAME_DATA`). Bot orders go through the normal command stream, so bot matches replay exactly. The phase 3 replay test proves this.
- **Where they go.** `Documents\Command and Conquer Generals Zero Hour Data\Replays\00000000.rep` ("Last Replay"), overwritten by the next game. The fork's "archive replays" option also keeps a timestamped copy (`RecorderClass::archiveReplay`).
- **Viewing.** Main menu → Replays, or `generalszh.exe -loadreplay <file>`. The viewer reveals the whole map and has the observer bar for switching between players' info.
- **To add:** a `save_replay {name}` command (valid in the shell, after a match) that copies the last replay to `Replays\<name>.rep`. The launcher and tests can then keep each bot match under a meaningful name, such as `<date>_<bot1>_vs_<bot2>`.
- **Caveats:**
  - A replay plays only with the same build that recorded it (debug and release don't mix), and with the same map.
  - The replay's "player camera" is the recording player's camera. Bots never move theirs, so use the free camera.

### 2. Live observer (LAN, during the match)
- **Observer slots.** LAN lobbies support them (`PLAYERTEMPLATE_OBSERVER`). An observer is a full client that sees the whole map and takes no part in the match.
- **Bot vs built-in AI (phase 6).** Also a LAN game: the bot hosts with an AI in another slot, and the observer joins (`launcher.py --vs-ai easy --observer`).
- **Bot vs bot (phase 6).** The host bot opens extra `open` slots in `lan_host`. A human then joins from the normal LAN lobby UI and picks the observer faction, or the launcher starts a third instance that joins as an observer (`launcher.py --observer`).
- **Caveat:** an observer is a lockstep network peer. The match waits for it, so a slow observer machine slows the bots' game.

### 3. A bot's own window (during the match, either mode)
- **What you see.** The bot's fogged point of view, in `view` input mode: the camera can move, nothing else.
- **Use it for:** debugging what a bot "sees". It isn't a fair spectator view of the whole match.

## Python client
```python
bot = GeneralsBot("ws://127.0.0.1:27100")

@bot.on("game_start")
async def opening(ctx):
    dozer = ctx.world.mine(kind="DOZER")[0]
    await ctx.build(dozer, "AmericaPowerPlant", near=ctx.world.base_center)

@bot.on("enemy_spotted")
async def react(ctx, ev):
    army = ctx.world.mine(kind="VEHICLE", idle=True)
    await ctx.attack_move(army, ev.pos)

bot.run()
```
- `World` is a local model of the game. It is rebuilt from snapshots and updated from events in between.
- `submit([...])` sends a batch of commands in one frame.
- `on(...)` registers reaction handlers. Each handler is an asyncio task, so a slow script never blocks the game.

## Phases
0. **Baseline (done).** `scripts/build.ps1` builds `win32-debug` and runs it from `GameFiles` with `-win -nologo -noshellmap`.
1. **Skeleton (done).** Add the CMake option and the dependencies. Create the ScriptApi subsystem in GameEngine and start the server thread. Implement `hello` / `ping`, `exit`, and the `game_state` lifecycle events. A minimal Python client connects.
2. **Integration test harness and skirmish start (done).** Add `start_skirmish` and `quit_game`. Build the pytest harness described under [Integration testing](#integration-testing), which launches the game, connects the client and starts a match against an easy AI. At this point the suite covers launching, connecting, starting the skirmish, frames advancing and a clean exit. **Every later phase adds its scenario steps to this suite, and a phase isn't done until its steps pass.**
3. **Read-only view of the world (done).** Implement `game_info`, `catalog`, `map`, own-player hook events, `eva`, and fog-filtered snapshots. Build the Python `World` model.
4. **Core actions and input lock (done).**
   - Implement the core commands with validation, replies and `command_executed`.
   - Add the [input lock](#input-lock-humans-cant-play-a-bots-player) (`-scriptApiInput view|locked|full`, default `view`). It belongs here because this is the first phase where a stray click would mix human orders into a bot's.
   - Integration tests: synthetic clicks and keys (posted Windows messages) in a `view` / `locked` instance change nothing in the game, while camera input still moves the view in `view` mode.
5. **Full action set and enemy-visibility events (done).** Add the remaining commands and the visibility events. Run a performance check of the visibility comparison at 30 frames per second with hundreds of units.
6. **LAN automation and live observers (done; see [Phase 6](Plans/Phase-6-LAN-Observers.md)).**
   - `lan_open`, `lan_host`, `lan_join`, `lan_slot`, `lan_accept`, `lan_start`, `lan_leave`, `surrender` drive the real LAN menu screens and `LANAPI`, as clicks would. Screen changes are deferred, so results come as `lan_lobby` / `lan_game` events.
   - Observer slots are `open` slots in `lan_host`; the joiner picks `lan_slot {observer: true}`.
   - A launcher starts two bot instances and, with `--observer`, a third instance that joins as an observer.
   - Launcher mode **bot vs built-in AI** (`--vs-ai easy|medium|hard`). Without an observer it's a plain skirmish. With `--observer` it's a LAN game where the bot hosts with an AI slot and the observer joins, because skirmish has no observer slots.
   - Add a two-instance LAN integration test, plus one with an observer: the observer client must see the whole map, and the match must finish in sync.
7. **Hardening and replays (done; see [Phase 7](Plans/Phase-7-Hardening-Replays.md)).**
   - Fixes from the first agent-played match: supply docks are reported, and `purchase_science` and the catalog check general's points and pending purchases.
   - Reconnects: a new connection gets a clean session (no `command_executed` for the old client's orders, default snapshot interval) in the same match.
   - `save_replay {name, overwrite?}` from the menus; the launcher keeps every match as a named replay (`--replay`, `--no-replay`).
   - Optional APM cap (`-scriptApiApm N`, launcher `--apm N`): orders over the cap get `RATE_LIMITED`.
   - A saved bot-vs-bot LAN replay plays back headless with no CRC mismatch. Protocol versioning and the API-on/off sync check already existed (phases 1 and 3).
8. **Fixes from the first agent-vs-agent match (see [Phase 8](Plans/Phase-8-Agent-Match-Fixes.md)).**
   - General's powers need their science (`use_ability`; the catalog lists `required_science`). `force_attack_object` uses the UI's forced check, so own and allied targets work.
   - `known_structures` lists every structure seen so far, with `visible`. Visible supply sources report `supply`. Own units get the `idle` and `harvesting` flags.
   - Destruction events skip shots and debris. Money for orders still on their way counts as spent, and `build_failed` reports builds the engine dropped. `resume_construction` says why it was refused.
   - Bot-author gotchas in `python/BOT-NOTES.md`.
9. **Agent bot tournament (done; see [Phase 9](Plans/Phase-9-Bot-Tournament.md); tournament t1 won by Charlie (fable), [report](tournament/t1/report.md)).** Four agents, each with its own model, research, pick a faction (declared in a `bot.json` manifest and applied at game setup) and play a live practice game against the Easy AI. Then they play live in a best-of-one, single-elimination bracket (no 3rd-place game) on Tournament Desert, after a 15-minute preparation: 45 minutes of game time per game (score decides at the limit), no APM cap, and 5 minutes after each game to update the scripts and notes they keep for the whole tournament.
10. **Agents that stay live (done; see [Phase 10](Plans/Phase-10-Live-Agents.md)).** Watcher connections next to the bot's controller, a blocking `watch` command that returns on what matters in the match, `order` and live-tunable bots so agents react without restarting, and liveness measured in every game's audit.

## Integration testing

### Layout
```
CNC_Generals_AI/
  scripts/run-integration.ps1        # optional build + deploy, then pytest; collects artifacts
  python/
    generals_api/                    # client library
    tests/integration/
      conftest.py                    # game_process, client, skirmish fixtures
      test_lifecycle.py              # phase 2
      test_world_view.py             # phase 3
      test_actions.py                # phase 4
      test_visibility.py             # phase 5
  test-results/<timestamp>/          # logs, crash dumps, replay, event transcript
```
Dependencies, kept in a venv at `python/.venv`: `websockets`, `pytest`, `pytest-asyncio`, `pytest-timeout`.

### Fixtures
1. **`game_process`** (one per session)
   - Launches `GameFiles\generalszh.exe -win -nologo -noshellmap -noaudio -xres 1024 -yres 768 -scriptApi -scriptApiPort <free port>`.
   - Polls the port until it accepts a connection, with a 60 s timeout. Fails early if the process exits.
   - Teardown: send `exit`, wait 15 s, then kill the process. Copy `DebugLogFileD.txt` and any new crash dumps into `test-results/`.
2. **`client`** connects and sends `hello`. It asserts that the protocol version matches and that `game_state == "shell"`. Every received message is written to `events.jsonl` in the results folder.
3. **`skirmish`** (one per module)
   - Sends `start_skirmish` with: a fixed 2-player map, ourselves as USA in slot 0, an **Easy AI** as China in slot 1, a fixed seed, `fps_limit` 30 and the standard starting money.
   - Waits for `game_state: in_game`, allowing 120 s for loading.
   - Teardown: `quit_game`, then wait for `game_state: shell`.

### Scenario: one match against an easy AI
The steps run in order inside one match, and each one waits for its expected events with a timeout. The **Phase** column says when each step goes live; before that it is skipped.

| # | Step | Expected result | Phase |
|---|---|---|---|
| 1 | Launch, connect, `hello` | `game_state: shell` | 2 |
| 2 | `start_skirmish` vs Easy AI | `loading`, then `in_game`. The `frame` value rises at about 30 per second for 5 s | 2 |
| 3 | `game_info`, `catalog` | 2 players, our index is 0 and our faction is USA. The catalog has the USA dozer, power plant, barracks and Ranger | 3 |
| 4 | First `snapshot` | We own a Command Center and a dozer. **No enemy objects are visible** at start | 3 |
| 5 | Wait for `eva` / money events | `money_changed` events arrive with the right values for our player | 3 |
| 6 | `build` a power plant with the dozer near the Command Center | Reply `ok`, then `command_executed` with a logic frame, `construction_started`, money goes down, and `construction_complete` within 60 s | 4 |
| 7 | `build` a barracks, then `train` 3 Rangers | `production_queued` ×3, then `production_complete` and `unit_created` ×3 | 4 |
| 8 | `move` the Rangers to a point | Snapshots show them within 50 units of the target within 30 s | 4 |
| 9 | Negative cases | An unknown or enemy unit ID returns `NOT_OWNED`. A building we can't afford returns `INSUFFICIENT_FUNDS`. An illegal build site returns `ILLEGAL_LOCATION`. Targeting a hidden object returns `NOT_VISIBLE`. **None of them change the game** (money and units are unchanged) | 4 |
| 10 | `attack_move` the Rangers toward the enemy start position | `enemy_spotted` arrives before any other enemy event. Enemy fields show only data visible to us | 5 |
| 11 | Fight | `unit_damaged` / `unit_destroyed`. `attacker_id` appears only when the attacker is visible | 5 |
| 12 | Disconnect the client for 10 s, then reconnect | The frame kept advancing. A fresh snapshot arrives on reconnect | 7 |
| 13 | `quit_game`, then `exit` | `game_state: shell`, then the process exits with code 0 and no crash dump | 2 |

### Checks run after every test
- No `ASSERTION FAILURE` or `EXCEPTION DUMP` lines in the debug log, and no new crash dumps.
- Event frame numbers never go backwards. Every command reply matches a request ID.
- The fog rule: no event or snapshot ever contains an enemy object outside the visible set at that frame. The game sends a debug-only `visible_ids` set that the test checks against.

### Running
```powershell
.\scripts\run-integration.ps1            # uses the already-deployed exe
.\scripts\run-integration.ps1 -Build     # build.ps1 -Deploy first
.\scripts\run-integration.ps1 -k actions # pass-through pytest filter
```
The full scenario runs in real time and takes about 3–5 minutes. Only one game instance runs at a time, except in the phase-6 LAN test, which starts two using multi-instance support (on in debug builds made with `build.ps1`). Each instance writes its own log (`DebugLogFileD_InstanceNN.txt`); the harness finds an instance's log by its `ScriptApi: listening on ...:<port>` line.

### Other testing
- C++ unit tests (`Tests/`, googletest) for turning JSON into `GameMessage`s and for validation.
- Sync safety: run the same LAN game with and without hooks attached and check for no CRC mismatch. Replays of bot games must play back cleanly.

## Risks and open items
- **Message argument layouts.** Each command's argument layout has to be copied exactly from the client code that creates it (`CommandXlat`, `GUICommandTranslator`, `PlaceEventTranslator`) and the dispatcher cases (`MSG_QUEUE_UNIT_CREATE` at GameLogicDispatch.cpp:675, `MSG_DOZER_CONSTRUCT` at :685, `MSG_CREATE_SELECTED_GROUP` at :727).
- **Selection state.** Injected selections change the logic-side selection. They should not break the on-screen selection of the instance, but this needs checking.
- **Matching game versions.** Both LAN peers must run the same build, debug with debug or release with release.
- **Two instances in a release build.** `build.ps1` only turns on `RTS_DEBUG_MULTI_INSTANCE` for debug builds. A release build would need it turned on too, to put two instances on one PC.
- **LAN lobby automation** (phase 6): done by driving the menu screens themselves. It depends on their window names (`LanLobbyMenu.wnd:ListboxPlayers`, `TextEntryPlayerName`, `ComboBoxPlayerTemplateN`).
- **Input lock completeness.** Some input may not go through the message stream. Windows messages handled directly in the window procedure (`WM_ACTIVATE`, `Alt+Tab`, `WM_CLOSE`) and any GUI path that reads `TheMouse` state directly are candidates. The phase 4 tests must post real Windows input to the window, not message-stream messages, so these paths get exercised.
- **Observers slow the match.** An observer is a lockstep peer, so a slow observer client stalls both bots. Use observers for watching, and replays for anything that needs bots running at full speed.
- **Replay compatibility.** A replay only plays on the build that recorded it. Keep the exe (or its version string) alongside archived bot replays.
- **`start_skirmish` without the menu.** `reallyDoStart` reads the game speed from a menu slider, and the skirmish menu sets up `TheSkirmishGameInfo` when it opens. `start_skirmish` has to repeat that setup itself without the menu window existing.
- **Map name for tests.** The test map must be referred to by its map-cache name. That name needs confirming against `MapsZH.big`.
