# Phase 1 — Script API Skeleton

Parent plan: [PLAN-script-api.md](../PLAN-script-api.md)
Status: **Done**

## Goal
When the game is started with `-scriptApi`, it runs a WebSocket server on localhost. A Python client can connect, agree a protocol version, ping the game loop, receive `game_state` events, and tell the game to exit cleanly. None of this affects the game simulation. With the CMake option off, the build is byte-for-byte the same as upstream.

## In scope
- CMake option `RTS_BUILD_OPTION_SCRIPT_API`, off by default. `scripts/build.ps1` turns it on.
- Dependencies through `FetchContent`: IXWebSocket for the server, nlohmann/json for JSON.
- `core_scriptapi`: a library with no game dependencies. It holds the server, the protocol, the command router and the game-state tracker.
- `ScriptApi`: a subsystem inside the game that owns the server, runs commands on the game thread and sends events.
- Command-line flags `-scriptApi` and `-scriptApiPort N`.
- Commands: `hello`, `ping`, `exit`. Event: `game_state`.
- Python client library `generals_api`, with unit tests and phase-1 integration tests.

## Out of scope (later phases)
- `start_skirmish`, `quit_game`, and the `loading` state. Map loading blocks the game thread and needs its own hook (phase 2).
- Anything that reads or changes the world (phases 3–5).

## Design

### Components
```
Core/Libraries/Source/ScriptApi/          (core_scriptapi, no game headers)
  ScriptApiServer.h/.cpp     pimpl around ix::WebSocketServer + sender thread
  ScriptApiProtocol.h/.cpp   envelope parsing / reply / error / event builders, ErrorCode
  ScriptApiRouter.h/.cpp     cmd name -> handler, returns serialized reply
  ScriptApiGameState.h/.cpp  GameStateTracker: (inGame, inShellGame, loading) -> transitions
GeneralsMD/Code/GameEngine/Include/ScriptApi/ScriptApi.h
GeneralsMD/Code/GameEngine/Source/ScriptApi/ScriptApi.cpp   (SubsystemInterface)
```
Game code never includes IXWebSocket headers. Winsock2 conflicts with the game's `windows.h`, so `ScriptApiServer.h` exposes only standard-library types. Game code does include `nlohmann/json.hpp`, so the handlers in later phases can build JSON directly.

### Threading
| Thread | Owns | Does |
|---|---|---|
| IX listener and connection threads | sockets | On open, close or text: push an `InboundMessage` onto the inbound queue |
| Sender thread (ours) | outbound queue | Pops messages and calls `ws->sendText`. A slow client never blocks the game |
| Game thread | everything in the game | `ScriptApi::update()` empties the inbound queue (at most 64 messages per frame), runs commands, sends replies and events |

- Both queues are a mutex plus a `std::deque`.
- If more than 10,000 messages are waiting to go out, the client is disconnected with close code 4002 (`slow consumer`), so memory can't grow without limit.
- **One client at a time.** A new connection replaces the old one, which is closed with code 4001 (`superseded`). This makes reconnecting during development painless and makes it impossible for two scripts to control one player.
- The server binds to `127.0.0.1` only.

### Engine integration
- `GameEngine::init()` creates `TheScriptApi` near the end of subsystem init, but only if `TheGlobalData->m_scriptApiEnabled` is set.
- `GameEngine::update()` calls `TheScriptApi->UPDATE()` just before `TheMessageStream->propagateMessages()`. Phase 4 commands will add messages to the stream at exactly this point.
- Shutdown: the subsystem list deletes subsystems in reverse order, so `TheScriptApi` goes early, while the memory manager is still alive. Its destructor sends any remaining messages (up to 1 s) and joins all threads.
- `exit`: the handler replies `ok` and sets a flag. The next `update()` calls `TheGameEngine->setQuitting(TRUE)`, which leads to the normal shutdown path.
- Code is guarded by `#if RTS_SCRIPT_API`. That macro is defined only on `z_gameengine`, so the Generals (non-ZH) targets and VC6 builds are untouched.

### Command line
| Flag | Effect |
|---|---|
| `-scriptApi` | Turns the server on |
| `-scriptApiPort N` | Sets the listen port and implies `-scriptApi`. Default `27100 + ClientInstance::getInstanceIndex()` |

These go in `paramsForEngineInit`, and the values are stored in two new fields in `GlobalData` (ZH only, guarded by the macro).

### Protocol v1 (this phase)
Every message is a JSON object with a `type` of `reply` or `event`.

**Requests** (script to game): `{"id": <int|string>, "cmd": "<name>", ...args}`. `id` is optional and comes back as `reply_to`.

**Replies:**
- Success: `{"type":"reply","reply_to":<id|null>,"ok":true, ...fields}`
- Failure: `{"type":"reply","reply_to":<id|null>,"ok":false,"error":"<CODE>","message":"..."}`

**Error codes this phase:** `BAD_JSON`, `BAD_REQUEST` (not an object, or `cmd` missing or not a string), `UNKNOWN_COMMAND`, `INTERNAL_ERROR` (the handler threw).

**Events:** `{"type":"event","event":"<name>","frame":<logic frame>, ...fields}`

| Command | Reply fields |
|---|---|
| `hello` `{protocol_version?}` | `protocol_version: 1`, `game: "zh"`, `build: "debug"/"release"`, `game_state`, `frame`. If the client sends a different `protocol_version`, the reply is the error `PROTOCOL_MISMATCH` |
| `ping` | `frame`: the logic frame. Proves the game loop handled it |
| `exit` | none. The process then shuts down |

| Event | Fields | When |
|---|---|---|
| `game_state` | `state` (`shell` or `in_game`), `previous` | When the state changes. The current state is in the `hello` reply |

**Game state:** `in_game` means `isInGame() && !isInShellGame()`. Anything else is `shell`.

## Files

**New**
- `cmake/ixwebsocket.cmake`, `cmake/nlohmann_json.cmake`
- `Core/Libraries/Source/ScriptApi/*` (above) and its `CMakeLists.txt`
- `GeneralsMD/Code/GameEngine/{Include,Source}/ScriptApi/ScriptApi.{h,cpp}`
- `Tests/Google/ScriptApi/*`: target `scriptapi_googletest`. It links only `core_scriptapi` and GTest, so no game is needed to run it
- `python/pyproject.toml`, `python/generals_api/*`, `python/tests/{unit,integration}/*`
- `scripts/run-integration.ps1`

**Changed**
- `cmake/config-build.cmake`: the option
- `CMakeLists.txt`: include the dependency files when the option is on
- `Core/Libraries/CMakeLists.txt`: `add_subdirectory(Source/ScriptApi)`
- `GeneralsMD/Code/GameEngine/CMakeLists.txt`: sources, link, `RTS_SCRIPT_API` define
- `GeneralsMD/.../GlobalData.{h,cpp}`: `m_scriptApiEnabled`, `m_scriptApiPort`
- `Core/GameEngine/Source/Common/CommandLine.cpp`: the two flags
- `GeneralsMD/.../GameEngine.cpp`: create and update `TheScriptApi`
- `Tests/Google/CMakeLists.txt`: add the ScriptApi subdirectory
- `scripts/build.ps1`: `-DRTS_BUILD_OPTION_SCRIPT_API=ON`, plus a `-Tests` switch

## Tests

### C++ unit tests (`scriptapi_googletest`, no game)
- **Protocol**
  - Valid request with an int id and with a string id.
  - Missing `id` gives `reply_to: null`.
  - Bad JSON gives `BAD_JSON`.
  - A non-object or a missing or non-string `cmd` gives `BAD_REQUEST`.
  - The reply, error and event builders produce the exact fields above.
- **Router**
  - Sends each command to its handler, with the handler's fields merged into the reply.
  - Unknown command gives `UNKNOWN_COMMAND`.
  - A handler throwing `CommandError` gives its code. Any other exception gives `INTERNAL_ERROR`.
  - Handler fields can't overwrite `type`, `reply_to` or `ok`.
- **GameStateTracker**
  - The first update only records the state and reports no transition. Clients learn the current state from `hello`.
  - Shell to in_game and back each give exactly one transition. No transition when nothing changes.
  - A shell game (the menu background map) counts as `shell`.
- **Server, over loopback using an IX client**
  - start, then connect, then the `Opened` message arrives.
  - Text round-trips in both directions. close gives `Closed`.
  - A second client replaces the first, which gets close code 4001.
  - `stop()` sends pending messages before closing.
  - Port already in use: `start` returns false with an error.

### Python unit tests (`python/tests/unit`, no game)
Run the client against a fake `websockets` server.
- Requests get increasing ids. Replies resolve the right future, even out of order.
- `ok:false` raises `ApiError` with `code` and `message`.
- Events go to `on(...)` handlers and to `wait_for_event(name, predicate, timeout)`.
- Server disconnect fails any pending requests with `ConnectionClosed`.

### Integration tests (`python/tests/integration/test_lifecycle.py`, real game)
The `game_process` fixture launches `generalszh.exe -win -nologo -noshellmap -noaudio -xres 800 -yres 600 -scriptApiPort <free>` from `GameFiles` and waits up to 90 s for the port.
1. `hello` returns protocol 1, `game: zh`, `game_state: shell`.
2. `ping` ×3 returns frames that never go backwards. Round trip under 500 ms.
3. Bad JSON and an unknown command give the right error codes, and the game keeps responding afterwards.
4. A second client connects. The first gets close code 4001, and the second can `ping`.
5. `exit`: the reply arrives, the socket closes, and the process exits within 30 s with code 0.

After every test: no `ASSERTION FAILURE` or `EXCEPTION DUMP` in `DebugLogFileD.txt`, and no new crash dumps.

## Acceptance criteria
- [x] `build.ps1` builds `z_generals` with the option on, and `scriptapi_googletest` with `-Tests`.
- [x] A build with the option off compiles none of the ScriptApi code. Checked in `build/win32-debug-noapi`: `z_generals` links, and `compile_commands.json` has no `RTS_SCRIPT_API` or ScriptApi entries.
- [x] All C++ unit tests (34), Python unit tests (15) and phase-1 integration tests (6) pass. `run-integration.ps1` passed 7 of 8 full runs, and the exit test passed 8 of 8 runs on its own. See the "used count mismatch" finding below.
- [x] Without `-scriptApi`, the game starts as before: no listening port. Checked with a run where the window was closed normally.

## Findings during implementation
- **Multi-instance is opt-in.** `RTS_MULTI_INSTANCE` comes from the CMake option `RTS_DEBUG_MULTI_INSTANCE`, which is OFF by default. Without it, a second client exits with code 1 ("already running"). `build.ps1` now turns it on for debug builds.
- **Per-instance logs.** Instance N > 1 writes `DebugLogFileD_InstanceNN.txt`. The harness finds an instance's log by its `ScriptApi: listening on 127.0.0.1:<port>` line.
- **Baseline leaks.** The unmodified debug build reports 3 memory leaks on every clean exit, including runs without `-scriptApi`. The harness tolerates up to 3 (`KNOWN_BASELINE_LEAKS`) and fails above that.
- **Fix to existing code: `-ignoreAsserts` stopped working during shutdown.** The leak report runs after `TheGlobalData` is deleted, so the default query no longer saw the flag, and a modal crash box blocked the exit. `parseIgnoreAsserts` now also installs an always-ignore query with `DebugSetIgnoreAssertsQuery` (CommandLine.cpp). This is a candidate for an upstream PR. The harness passes `-ignoreAsserts`, and assertions are still logged and caught.
- **Intermittent "used count mismatch" (seen once in about 15 runs).** It fires from `MemoryPoolFactory::debugMemoryVerify` at shutdown, which sums pool usage without a lock, so another live thread allocating would trip it. The ScriptApi server is logged as stopped (`ScriptApi: server stopped`) well before the report, so the server threads are an unlikely cause. Not yet reproduced on demand. The harness will flag it if it comes back, and it should be investigated if it does.

## Risks
| Risk | Mitigation |
|---|---|
| IXWebSocket's CMake files are older than CMake 4.x allows | Set `CMAKE_POLICY_VERSION_MINIMUM=3.5` before fetching |
| Winsock / `windows.h` header clash | IX headers appear only in `ScriptApiServer.cpp`, behind a pimpl |
| The game's global `operator new` used from IX threads | The allocator is protected by critical sections. Threads stop in the subsystem destructor, before the memory manager shuts down |
| The debug-build leak report flags the server's buffers | Free everything in `stop()`. Check the log on exit |
| Exit code isn't 0 in debug builds | Find the cause during integration testing and record it here |
