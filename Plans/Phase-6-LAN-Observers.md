# Phase 6 — LAN Matches Between Bots, and Live Observers

Parent plan: [PLAN-script-api.md](../PLAN-script-api.md) · Previous: [Phase 5](Phase-5-Full-Actions-Visibility.md)
Status: **Done** (the hand check of a live human observer is left to the user)

## Goal
Two scripted players play each other in a real LAN game, on one PC (multi-instance) or on two:
- one bot hosts and the other joins
- both pick their faction and accept
- the host starts, the match runs in lockstep, and it ends with a winner

A single bot can also play **against the game's built-in AI**, with a human watching. Skirmish has no observer slots, but LAN games accept AI players, so this mode is a LAN game: the bot hosts, an AI takes slot 1, and the observer joins.

A human can watch live from an **observer** slot, either joining from the normal LAN lobby or through a launcher-started observer client. A launcher script runs the whole setup with one command.

## How the engine does it (what we drive)
LAN games are driven through the **LAN menu screens**. The API does what a player's clicks do, in the same order, through the same functions. It does not rebuild the menus' logic.

| Step | Player action | Engine code |
|---|---|---|
| Open LAN lobby | Main menu → Multiplayer → Network | `TheShell->push("Menus/LanLobbyMenu.wnd")`. `LanLobbyMenuInit` creates `TheLAN`, picks the local IP (`TheGlobalData->m_defaultIP`, else the first `IPEnumeration` address) and calls `TheLAN->init()` |
| Set name | Name box | `TheLAN->RequestSetName(name)` |
| Host | Host button | `TheLAN->RequestGameCreate(name, FALSE)`. `OnGameCreate` pushes `LanGameOptionsMenu.wnd`, which sets up the game from preferences |
| Change match options (host) | Combo boxes | Edit `TheLAN->GetMyGame()` (map: `setMap/setMapCRC/setMapSize`; slots: `GameSlot::setState(SLOT_OPEN / SLOT_CLOSED / SLOT_*_AI)`), then `resetAccepted()`, `TheLAN->RequestGameOptions(GenerateGameOptionsString(), true)` and `lanUpdateSlotList()` |
| Change own slot (joiner) | Own combo boxes | `TheLAN->RequestGameOptions("PlayerTemplate=%d" / "Color=%d" / "StartPos=%d" / "Team=%d", true)`, as in `LanGameOptionsMenu.cpp` ~line 505 |
| Find games | Game list | The `TheLAN` game list (`LookupGameByListOffset`, broadcast announcements on UDP 8086) |
| Join | Join button / Direct connect | `TheLAN->RequestGameJoin(game)` or `RequestGameJoinDirectConnect(ip)`. `OnGameJoin` pushes the options menu |
| Accept | Accept button | `TheLAN->RequestAccept()` |
| Start (host) | Start button | `StartPressed()` (global in LanGameOptionsMenu.cpp): it checks the player count, map, teams and accepts, then `RequestGameStart` / `RequestGameStartTimer`. `OnGameStart` → `startGame(0)` → `MSG_NEW_GAME`. Loading then follows the same `loading` → `in_game` path as skirmish |
| Leave a game (LAN) | Quit menu | `GameLogic::quit`: `MSG_SELF_DESTRUCT(TRUE)` in a multiplayer non-skirmish game (surrender), then `exitGame()` |

## In scope

### Commands (all in the `shell` state unless noted)
| Command | Effect | Reply / follow-up |
|---|---|---|
| `lan_open {name, ip?}` | From the main menu: push the LAN lobby (as the Network button does), then type the player name into the lobby's name box once the screen is up. `ip` picks the lobby address, as the options menu does | Replies at once; the first `lan_lobby` event carries `local_ip` |
| `lan_games` | List the games seen in the lobby | `[{name, host_ip, map, players, open_slots, in_progress}]` |
| `lan_host {map, slots: [..], starting_cash?, limit_superweapons?}` | Create a game (the lobby's Host button), then, once the options screen is up, set the map and slots as the map-select menu and the host's combo boxes do. There is no game name: the engine names LAN games after the host's IP and seed. Each slot is `{type: "open"\|"closed"\|"easy_ai"\|"medium_ai"\|"hard_ai"}`; slot 0 is the host itself. AI slots may also set `faction`, `color`, `team` and `start_pos`, which the host controls for AIs, as in the menu | Reply once the request is sent. `lan_game` events follow as it's created and updated |
| `lan_join {host_ip}` or `lan_join {host}` | Join by IP (direct connect) or by the host's player name from the game list | `lan_game` events; `lan_failed {action: join, reason}` after 15 s without a game |
| `lan_slot {faction?, color?, team?, start_pos?, observer?}` | Change our own slot, the way the menu does for a host or a joiner. `observer: true` selects `PLAYERTEMPLATE_OBSERVER`. Taken colors and start positions are refused with `INVALID_ARGUMENT` (the menu ignores such clicks silently) | The new setup as in `lan_game`; the host's update follows as a `lan_game` event |
| `lan_accept` | `RequestAccept()` (joiners). The host has no accept button, so this is a no-op for it | `lan_game` update |
| `lan_game` | Query the current setup | Same fields as the event |
| `lan_start` | **Host only.** Runs the same checks as `StartPressed` first, so each failure gets a specific error (`NOT_READY`: not everyone accepted; `INVALID_ARGUMENT`: map or player count), then calls `StartPressed()` | Then `game_state: loading` → `in_game` on **every** instance |
| `lan_leave` | Leave the game (`RequestGameLeave`) or the lobby (`RequestLobbyLeave`), back to the main menu | `game_state` stays `shell` |
| `surrender` (in game) | `MSG_SELF_DESTRUCT(TRUE)`, the network-safe quit of a multiplayer game | The opponent's script receives `game_over {result: victory}` |

### `quit_game` in LAN games
`quit_game` follows `GameLogic::quit(FALSE)` for multiplayer games: it sends the self-destruct, then `exitGame()`. It is no longer limited to skirmish.

### Events
| Event | When | Fields |
|---|---|---|
| `lan_lobby` | Lobby players or game list change (polled every 15 frames while in the lobby) | `players: [{name, ip}]`, `games: [...]` |
| `lan_game` | Our game's options or slots change (`OnGameOptions`, `OnPlayerJoin`/`Leave`, `OnAccept`) | `name, host, map, local_slot, slots: [{index, state, name, faction, color, team, start_pos, accepted, observer}]` |
| `lan_left` | The host left or we were kicked (`OnHostLeave`) | `reason` |
| `lan_failed` | A screen change the script asked for did not happen within 15 s | `action` (open, host, join), `reason`, `screen` |

`lan_game` and `lan_lobby` are polled every shell frame and sent when their JSON changes (`JsonChangeDetector`); the `lan_game` reply and event come from one function (`lanGameJson()`). The planned `lan_starting` event was dropped: `game_state: loading` already reports the start on every instance.

### Observers
An observer is a LAN client whose slot uses `PLAYERTEMPLATE_OBSERVER`. The engine reveals the whole map to it permanently (GameLogic.cpp ~1820). For the script API on an observer client:
- **`game_info`:** `local_player` is the observer player, and `relation` comes out `neutral` for everyone.
- **Snapshots:** `units` is empty; `visible` contains every object the observer can see, which with the map revealed is all of them. That's correct, because a human observer sees everything too.
- **Orders:** an observer can't give any. Orders from an observer client are refused with `NOT_AVAILABLE` ("observers cannot give orders"), and so is `surrender`.
- **Events:** an observer gets no `game_over`; it can't win or lose.
- **Input mode:** the launcher starts a human observer with `-scriptApiInput full`, so the person can use the observer controls. Nothing they do can affect the match, because observers own no units.

### Launcher (`python/generals_api/launcher.py`)
```
python -m generals_api.launcher --bot1 bots/simple.py --bot2 bots/simple.py [--observer] [--map "..."]
python -m generals_api.launcher --bot1 bots/simple.py --vs-ai easy|medium|hard [--ai-faction China] [--observer] [--map "..."]
```

Modes:
| Mode | Instances | Match type |
|---|---|---|
| Bot vs bot | 2, plus 1 with `--observer` | LAN: bot 1 hosts with 2 open slots (3 with an observer) |
| Bot vs built-in AI, no observer | 1 | Plain skirmish (`start_skirmish`): no network, fastest to start |
| **Bot vs built-in AI with an observer** | 2: bot and observer | LAN: the bot hosts with `slots: [host, {type: <ai difficulty>}, open]`. The bot sets the AI's faction with `lan_host` (`slots[1].faction`), and the observer joins the open slot |

Steps for the LAN modes:
1. Starts 2 (or 3) instances, each with `-scriptApiPort` and `-scriptApiInput view` (`full` for the observer). Instances are placed side by side and use different ports.
2. Instance 1 does `lan_open` → `lan_host` (2 open slots). Instance 2 does `lan_open` → `lan_join {host_ip}` → `lan_slot` → `lan_accept`. The observer does `lan_join` → `lan_slot {observer: true}` → `lan_accept`.
3. Instance 1 does `lan_start`, then hands control to each bot's `run(client)` coroutine.
4. When `game_over` arrives on both bots, it prints the result and closes the bot instances. The observer instance stays open for the human.

Bot scripts are plain Python modules with an `async def run(client: GeneralsClient, world: World)` entry point. A reference `bots/simple.py` builds power and a barracks, then sends waves of infantry at the enemy start; it knows the three base factions.

As built: `--bot1-faction` / `--bot2-faction` (default America), `--duration` (stop after N seconds), `--game-arg` (extra game arguments, repeatable). Bot instances get `-noaudio`. `play()` takes `on_in_game(clients)`, a hook that runs alongside the bots with the launcher's own clients; tests use it, because an instance accepts only one script connection and a second one would replace the launcher's. Windows are not placed side by side yet.

## Out of scope (phase 7)
Named replay saving (`save_replay`), reconnecting after a disconnect, an APM cap, internet / GameSpy play, and LAN on two physical PCs. Two PCs should work through `lan_join {host_ip}` but won't be tested automatically.

## Game-independent pieces (unit-tested)
- **`parseLanHostRequest`:** map, `slots` (1–8 entries, `slots[0]` must be `{type: "host"}`; without `slots` the game has the host and one open slot; only AI slots take faction, color, team and start position), starting cash and superweapon options.
- **`parseLanSlotRequest`:** the same field rules as `start_skirmish` players (1-based team and start position), plus `observer`. `observer` can't be combined with faction, team or start position.
- **`JsonChangeDetector`:** turns successive lobby and game snapshots into `lan_lobby` / `lan_game` events only when something changed. This is the same pattern as `ChangeDetector`, applied to JSON.
- **`parseLanPlayerName`:** 1–12 characters (`g_lanPlayerNameLength`).

## Tests

### C++ unit tests
The parsers and the diff above: valid input, every invalid field, and observer conflicts.

### Python unit tests
- The launcher's process and port planning (no game): ports are distinct, the observer instance gets `full` input, and the bot module loader finds `run`.
- The client's `lan_*` method payloads.

### Integration — `test_lan.py` (two instances on one PC; three for the observer test)
| # | Test | Expected |
|---|---|---|
| 0 | **Spike: discovery across loopback instances** | B's `lan_games` lists A's game. If loopback broadcast doesn't reach the other instances, record it as a finding and use `host_ip` from then on |
| 1 | Host and join | A hosts on Tournament Desert with 2 open slots. B joins with `host_ip`. Both receive `lan_game` with 2 occupied slots |
| 2 | Slot and accept | B sets faction China. A's `lan_game` shows B as China, and accepted after B's `lan_accept` |
| 3 | Start refused | `lan_start` before B accepts → `NOT_READY` |
| 4 | Start | Both instances go `loading` → `in_game`. Each `game_info` lists the other as `enemy`, type `human` |
| 5 | Lockstep orders | Each bot builds a power plant. Each gets `construction_started` for its own building. After 60 s, neither log shows a CRC mismatch (from `-DebugCRCFromFrame` / network "mismatch" logging) |
| 6 | Fog across players | Neither bot's snapshot shows the other's base at the start (`debug_world` ground truth) |
| 7 | Surrender | B sends `surrender`. A gets `game_over {victory}`, B gets `game_over {defeat}` |
| 8 | Observer | A third instance C joins as an observer. After the start, C's snapshot `visible` contains **both** command centers, C's `units` is empty, and orders from C are refused |
| 9a | Bot vs built-in AI with an observer | Instance A hosts with `slots: [host, {type: "easy_ai", faction: "FactionChina"}, open]`. Observer C joins and accepts, then A starts. A's `game_info` lists China as `enemy`, type `computer`. C's snapshot shows both command centers. After 60 s there's no desync, and the AI has built something: C sees new China structures |
| 9b | Launcher, bot vs AI with observer | `launcher.py --bot1 bots/simple.py --vs-ai easy --observer` gets both instances `in_game`, and the bot produces `construction_complete` |
| 9 | Launcher smoke test | `launcher.py` with two copies of `bots/simple.py`, for 2 minutes. Both bots produce `construction_complete`; there's no desync and no crash dump |

**Harness:** add a `lan_pair` fixture (and a `lan_trio` fixture) that start several `GameProcess`es with distinct ports. Each instance's log is found by its port line (already supported). After-match leak checks use `@pytest.mark.leak_baseline(KNOWN_LEAKS_AFTER_MATCH)`.

## Acceptance criteria
- [x] All C++ and Python unit tests pass: 101 C++ (9 new in `ScriptApiLanTest.cpp`), 49 Python (13 new: LAN client payloads, launcher planning, desync marker).
- [x] Phases 1–6 integration tests pass three full runs in a row: 116 passed, 1 skipped in each run (19m39s, 19m40s, 19m44s).
- [x] A bot-vs-bot LAN match on one PC runs for 5 minutes with no desync (launcher smoke run, with an observer). Both bots built bases and fought (unit kills and losses match across the two bots: 33 and 17), and no log reported a desync, assertion or crash.
- [ ] A human observer, started with `launcher.py --observer`, can watch the whole map live, both bot vs bot and bot vs built-in AI. **Left for the user to check by hand.** The automated part passes: the observer client sees both command centers, owns nothing and can't give orders (tests 9a, 9, 9b).

## Risks
| Risk | Mitigation |
|---|---|
| **Loopback broadcast:** LAN discovery broadcasts to `255.255.255.255:8086`, and instances bound to different `127.x` addresses may not receive it on Windows | Test 0 checks this first. `lan_join {host_ip}` (direct connect) needs no broadcast, and the launcher always uses it |
| **The LAN menu code expects its windows to exist** (`lanUpdateSlotList`, chat list boxes) | Push the real screens through the shell, as a player's clicks would, before calling `TheLAN`. Don't call menu functions on a screen that isn't open |
| **All instances on one PC share one preferences file** (player name, preferred map) | `lan_open {name}` sets a unique name per instance. The host sets the map explicitly |
| **Duplicate player names** may be rejected or renamed by the LAN code | The launcher uses `Bot1`, `Bot2`, `Observer` |
| **Lockstep speed:** three debug instances on one PC are CPU-heavy, and the slowest client sets the pace | Use the 30 fps default. Tests measure frame progress rather than wall time. Observer use is documented as possibly slowing matches |
| **The input lock blocks lobby clicks** in bot windows | Intended. The observer instance uses `full` mode |
| **`StartPressed` reports problems as lobby chat, not as return values** | Repeat its checks before calling it, and report specific errors |
| **LAN start / host timers** (`RequestGameStartTimer`) | Use the immediate start the start button uses. Don't wait for timer events |
| **Built-in AI in a LAN game:** AI players run inside the lockstep simulation on every client, as in a normal LAN game against computer players. AI slot options are set by the host only | Test 9a covers an AI with an observer. A desync there would also be one for humans, so the CRC check catches it |
| **Quitting a LAN match** must not desync the remaining player | `surrender` / `quit_game` follow `GameLogic::quit` (self-destruct message, then exit). Test 7 checks the result on both sides |

## Findings
1. **Loopback broadcast works.** Each multi-instance client binds its own `127.0.0.N` address (instance N+1), and lobby announcements to `255.255.255.255:8086` reach the other instances: each lobby lists the others' players and games (test 0). Direct connect by IP works too, and the launcher always uses it, so two PCs need no broadcast.
2. **Screen changes are deferred.** `Shell::push` waits for the old top screen's shutdown animation, so the lobby or options screen appears a few frames after the click. `lan_open`, `lan_host` and `lan_join` therefore reply at once, finish in `ScriptApi::updateLan()` when the screen is up, and report through `lan_lobby` / `lan_game` (or `lan_failed` after 15 s). The Python client wraps this: `lan_open` / `lan_host` / `lan_join` return the first event.
3. **LAN games have no usable name.** `RequestGameCreate` names the game `%8.8X%8.8X` (host IP and seed) plus the given name, truncated to 16 characters, so the given name never survives. `game_name` was dropped from `lan_host`; games are identified by host name or IP.
4. **Engine bug (fixed): `TheLAN` leaked on exit.** Only the lobby's Back button deleted it, so quitting to the desktop from a LAN lobby or match leaked the LAN state and its transport (about 800 KB, plus game and player lists). It is now deleted in `GameEngine::~GameEngine` after the subsystems shut down. A first attempt deleted it earlier and crashed every exit, because the shell's shutdown runs `LanLobbyMenuShutdown`, which calls `TheLAN->RequestLobbyLeave`. Not API code; an upstream bug-fix candidate.
5. **Observer assertions (known).** Every client of a game with an observer slot raises two debug assertions from the unmodified engine: `Player.cpp` finds no skirmish side "Observer", and `LoadScreen.cpp` has no portrait for the observer template. Both were added to `KNOWN_ASSERTIONS`.
6. **Leaks after LAN play (known, by kind).** `LanLobbyMenu.cpp`'s file-static `defaultName` outlives the leak report (its block size follows the name's length), and one shell-created menu layout is left after a LAN match. Both were added to `AFTER_MATCH_LEAK_KINDS` with a maximum of 1. With finding 4 fixed, a LAN exit otherwise reports only the existing after-match kinds.
7. **One script connection per instance.** A second connection replaces the first (close code 4001), so a test that probed the observer on its own connection cut off the launcher's. `launcher.play()` gained an `on_in_game(clients)` hook for this.
8. **Harness:** `GameProcess.adopt(proc)` takes over a launcher-started process and records the crash dumps that already existed; without it, an unrelated older dump was reported as new. `check_log` also fails on Network's "Latest frame for mismatch" line (desync), in addition to the engine's "CRC mismatch!" assertion. No desync was seen in any run.
9. **Accepts reset on every slot change.** The host resets all accepts whenever a slot changes, so a joiner that accepts too early is un-accepted. The launcher and tests accept in a loop until `lan_start` stops returning `NOT_READY`.
10. **Surrender and quitting.** `surrender` gives `victory` and `defeat` on the same frame on both clients (test 7). `quit_game` in a LAN game sends the same self-destruct first, as the quit menu does, unless the game is a sandbox.
11. **Built-in AI in a LAN game.** The AI runs inside the lockstep simulation on every client; the observer saw it build within 60 s, with no desync (test 9a).
12. **Run results.** The suite now takes about 20 minutes per run (phase 6 adds about 8). Three runs in a row passed (116 passed, 1 skipped: the same skip as in phase 5). The 5-minute smoke run (`--bot2 --bot2-faction China --observer`, through the launcher test helper, so its logs were checked) passed: the bots killed each other's units for 5 minutes in lockstep, with no desync.
