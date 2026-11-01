# Phase 4 — Core Actions and Input Lock

Parent plan: [PLAN-script-api.md](../PLAN-script-api.md) · Previous: [Phase 3](Phase-3-World-View.md)
Status: **Done**, except for checking `view` mode by hand

## Goal
A script can order its units and buildings the way a human does with the mouse:
- move, attack, attack-move, force-fire, stop, guard
- train and cancel units
- place buildings with a dozer
- set rally points, sell

Every order goes through the same network messages a click produces and passes the **same checks the UI makes before sending them**. The script learns when each order actually ran (`command_executed`). With the API on, a human in the bot's window can only move the camera.

## In scope
- **Commands:** `move`, `attack_move`, `attack`, `force_attack`, `stop`, `guard`, `train`, `cancel_train`, `build`, `set_rally_point`, `sell`.
- **`command_executed` event:** carries `reply_to` and the logic frame the order ran on.
- **Input lock:** `-scriptApiInput view|locked|full`, default `view`.
- **Debug only** (debug build plus `-scriptApiDebug`):
  - `set_input_mode`
  - `debug_inject_input`: puts raw mouse or key messages into the stream exactly as the input devices do
  - `debug_input_stats`
  - `debug_camera`: where the view is looking
- **Python:** a client method for each command, `wait_for_execution(reply)`, and `World.units_by_template`.
- **Integration:** scenario steps 6–9 (build, train, move, refused commands), cancelling production, and input-lock tests.

## Out of scope (phase 5)
Upgrades, sciences, special powers, garrison/enter, evacuate, repair, capture, hack, waypoints, formations, line-building (walls), attacking fogged buildings, enemy-visibility events and damage events.

## What the engine does for each order
Orders apply to the player's **logic selection**. So the API first sends `MSG_CREATE_SELECTED_GROUP(createNew=TRUE, ids…)`, which is what the UI sends when you select units, then the order.

| Command | Message and arguments (dispatcher in GameLogicDispatch.cpp) | Checks the UI does first (copied by the API) |
|---|---|---|
| `move {units, pos}` | `MSG_DO_MOVETO (location)` | — |
| `attack_move {units, pos}` | `MSG_DO_ATTACKMOVETO (location)` | — |
| `attack {units, target}` | `MSG_DO_ATTACK_OBJECT (objectID)` | You can only click a target you can see. At least one unit `getAbleToAttackSpecificObject(ATTACK_NEW_TARGET, target, CMD_FROM_PLAYER) != ATTACKRESULT_NOT_POSSIBLE` |
| `force_attack {units, pos}` | `MSG_DO_FORCE_ATTACK_GROUND (location)` | At least one unit `isAbleToAttack()` |
| `stop {units}` | `MSG_DO_STOP ()` | — |
| `guard {units, pos}` | `MSG_DO_GUARD_POSITION (location, GUARDMODE_NORMAL)` | — |
| `train {factory, template, count}` | Per unit: `MSG_QUEUE_UNIT_CREATE (templateID, productionID)`, with the ID from `pu->requestUniqueUnitID()` | `ControlBarCommandProcessing` `GUI_COMMAND_UNIT_BUILD`: the factory's command set has a `UNIT_BUILD` button for the template, `TheControlBar->getCommandAvailability(button, factory, nullptr) == COMMAND_AVAILABLE`, `TheBuildAssistant->canMakeUnit(factory, tmpl) == CANMAKE_OK` |
| `cancel_train {factory, production_id}` | `MSG_CANCEL_UNIT_CREATE (productionID)` | The ID is in the factory's queue |
| `build {dozer, template, pos, angle}` | `MSG_DOZER_CONSTRUCT (templateID, location, angle)` | `PlaceEventTranslator`: `DOZER_CONSTRUCT` button, availability, `canMakeUnit`, `isLocationLegalToBuild(pos, tmpl, angle, USE_QUICK_PATHFIND\|TERRAIN_RESTRICTIONS\|CLEAR_PATH\|NO_OBJECT_OVERLAP\|SHROUD_REVEALED\|IGNORE_STEALTHED\|FAIL_STEALTHED_WITHOUT_FEEDBACK, dozer, player) == LBC_OK` |
| `set_rally_point {building, pos}` | `MSG_SET_RALLY_POINT (objectID, location)`; `CommandXlat::handleSetRallyPointCommand` | An own building with a production interface |
| `sell {building}` | `MSG_SELL ()` | The command set has a `GUI_COMMAND_SELL` button that is `COMMAND_AVAILABLE` |

**Positions:** `pos` is `[x, y]` in world units. `z` comes from `TheTerrainLogic->getGroundHeight`. A position outside the map extent gives `INVALID_ARGUMENT`.

### Argument checks (shared by all orders)
- **`units` / `factory` / `dozer` / `building`:** every ID must be one of **our** live, selectable objects, otherwise `NOT_OWNED`. The answer is the same whether or not the ID exists, so it reveals nothing hidden. `units` holds 1–100 IDs.
- **`target`:** must be visible to us right now (`isVisibleToPlayer`), otherwise `NOT_VISIBLE`. Again the same answer whether or not it exists.
- **`template`:** must be a known template, otherwise `INVALID_ARGUMENT`.

### Error codes added
| Code | When |
|---|---|
| `NOT_OWNED` | An ID isn't one of our live, selectable objects |
| `NOT_VISIBLE` | The target isn't visible to us |
| `NOT_AVAILABLE` | The object has no such button, or it is disabled (missing prerequisites, unpowered…) |
| `INSUFFICIENT_FUNDS` | `CANMAKE_NO_MONEY` |
| `QUEUE_FULL` | `CANMAKE_QUEUE_FULL` |
| `PARKING_FULL` | `CANMAKE_PARKING_PLACES_FULL` |
| `LIMIT_REACHED` | `CANMAKE_MAXED_OUT_FOR_PLAYER` |
| `ILLEGAL_LOCATION` | Building site rejected. `message` holds the reason (`restricted_terrain`, `not_flat`, `objects_in_the_way`, `no_clear_path`, `shroud`, `too_close_to_supplies`) |
| `CANNOT_ATTACK` | None of the units can attack that target |

A failed check sends **no** messages.

### Replies and `command_executed`
- **Reply:** `{client_frame, messages: N}`. `train` also returns `production_ids: [...]`.
- **`command_executed {reply_to, cmd, frame}`:** sent once the logic has run the last of the request's order messages. Selection messages don't count.
- **How replies are matched to execution:**
  - A `CommandTracker` (game-independent) keeps a FIFO of (request ID, command, message types) in sending order.
  - A read-only hook at the top of `logicMessageDispatcher` reports each network message the **local** player sent: its type and the frame.
  - Lockstep keeps the order, so the tracker matches messages in sequence.
  - Messages it doesn't recognise (selection, camera, CRC) are ignored.

## Input lock
**Mode by input type.** Worked out by a pure, unit-tested function `inputAction(mode, kind)`:

| Input kind | `full` | `view` (default) | `locked` |
|---|---|---|---|
| Mouse position | pass | pass (cursor, edge scroll) | drop |
| Left button (down/up/click/drag/double-click) | pass | **drop** | drop |
| Right button | pass | **camera only** (right-drag scroll) | drop |
| Middle button | pass | **camera only** (rotate) | drop |
| Wheel | pass | **camera only** (zoom) | drop |
| Keys | pass | **camera only** (arrow-key scroll) | drop |

"Camera only" means the guard passes the message to `TheLookAtTranslator` itself, then destroys it, so nothing else sees it: no selection, hotkeys, menus, orders or pause.

**Guards** (attached in `ScriptApi::init` unless the mode is `full`, removed in the destructor):
1. **Input guard**, priority 1, ahead of `WindowTranslator` at 10. Applies the table above to `MSG_RAW_MOUSE_*` and `MSG_RAW_KEY_*`.
2. **Command guard**, priority 999999998, just before `GameClientMessageDispatcher`. Drops any network-range message (1000–1999) that this frame's `ScriptApi::update()` didn't add, except system messages: `MSG_LOGIC_CRC`, `MSG_SET_REPLAY_CAMERA`, `MSG_SELF_DESTRUCT` and `MSG_BEGIN_NETWORK_MESSAGES`. This is the safety net for any input path the first guard misses. The API's own messages are found by remembering the stream's last message before the update and walking the new ones after it.

**Cursor capture.** In `view` and `locked` modes the game must not confine the cursor to its window: `TheMouse->setCursorCaptureMode(0)`. The `blockCapture()` reasons are protected, so they aren't used. `full` mode restores the player's setting from `OptionPreferences::getCursorCaptureMode()`.

**Counters.** `debug_input_stats` reports how many messages were passed, dropped and camera-forwarded by kind, plus how many foreign commands were dropped.

## Code layout
- **`core_scriptapi`:**
  - `ScriptApiCommands.{h,cpp}`: `parseUnitIds`, `parsePosition`, `parseInputMode`, `inputAction`, `CommandTracker`
  - new `ErrorCode`s
- **Game side:**
  - `ScriptApiActions.cpp`: the order commands
  - `ScriptApiInput.cpp`: the guards, modes and debug input commands
- **Hook:** `GameLogicDispatch.cpp` calls `TheScriptApi->onCommandExecuted(msg)` for network messages, guarded by `#if RTS_SCRIPT_API && RTS_ZEROHOUR`, since Core files are also built for Generals.

## Tests

### C++ unit tests
- **`parseUnitIds`:** a missing, empty or non-array list, a non-integer entry, more than 100 IDs, and duplicates (removed) → `BAD_REQUEST`.
- **`parsePosition`:** `[x, y]` and `[x, y, z]` (z ignored); wrong length or non-numbers → `BAD_REQUEST`.
- **`parseInputMode`:** the three names; anything else → `BAD_REQUEST`.
- **`inputAction`:** every row of the table above.
- **`CommandTracker`:**
  - A one-message request completes on its message.
  - A multi-message request completes only on its last.
  - Unknown types are ignored.
  - A message of the wrong type for the head of the FIFO is ignored and doesn't consume the entry.
  - Two requests complete in order.
  - `clear()` (for a new game) drops everything.

### Python unit tests
Each order method sends the right payload. `wait_for_execution` matches `command_executed` by `reply_to`.

### Integration — `test_actions.py` (skirmish vs Easy AI)
| # | Test | Expected |
|---|---|---|
| 1 | `build` an AmericaPowerPlant with the dozer near the Command Center (tries several offsets) | Reply OK. `command_executed`, `construction_started` with the same template, money drops by the catalog cost, `construction_complete` within 90 s |
| 2 | `build` an AmericaBarracks, then `train` 3 AmericaInfantryRanger | `production_ids` has 3 entries. `unit_created` × 3 with `factory_id` = the barracks |
| 3 | `move` the Rangers 300 units away | Within 30 s, a snapshot shows each within 60 units of the target |
| 4 | `set_rally_point` on the barracks, then `train` 1 Ranger | The new Ranger ends up near the rally point |
| 5 | Fill the barracks queue with Rangers, then `cancel_train` them all | `QUEUE_FULL` appears before the money runs out. After cancelling, money is back to where it started |
| 6 | Refused commands | Each gives its code, and money, unit count and the current orders are unchanged afterwards: <br>• `move` with ID 999999 → `NOT_OWNED` <br>• `attack` on the enemy Command Center (ID from `debug_world`) while it's unseen → `NOT_VISIBLE` <br>• `train` a Ranger from the Command Center → `NOT_AVAILABLE` <br>• `build` a structure whose catalog `available_now` is false → `NOT_AVAILABLE` <br>• `build` on top of the Command Center → `ILLEGAL_LOCATION` <br>• `train` dozers until money runs short → `INSUFFICIENT_FUNDS` |
| 7 | `stop` / `guard` / `attack_move` / `force_attack` on the Rangers | Reply OK, then `command_executed`, for each |
| 8 | `sell` the power plant | `command_executed`, then later `unit_destroyed` for it and money goes up |

### Integration — `test_input_lock.py`
- **Positive control (`full` mode via `set_input_mode`):** inject the pause key → frames stop advancing. Inject it again → frames resume.
- **`view` (default):**
  - Injected pause key, Esc, left and right clicks, and the select-all key change nothing: frames keep advancing and no foreign commands reach the command list.
  - Injected arrow keys and the wheel **do** move or zoom the camera (`debug_camera` changes).
- **`locked`:** nothing changes the camera either.
- **Real Windows input:** clicks posted to the game window with `PostMessage(WM_LBUTTONDOWN/UP, WM_RBUTTONDOWN/UP)` show up as dropped messages in `debug_input_stats`. That proves the `Win32Mouse` path reaches the guard.

## Acceptance criteria
- [x] All C++ unit tests (81) and Python unit tests (32) pass.
- [x] Phases 1–4 integration tests pass three full runs in a row (75 Python tests per run, about 4.5 min).
- [x] The replay CRC test now places a building, trains a dozer and moves the dozer, and its replay still plays back to the end with no CRC mismatch. So the orders, including `requestUniqueUnitID` on the client side, replay exactly.
- [ ] Watched by hand in `view` mode: clicks do nothing, and the camera can be moved. *Still to do by a person.* The tests cover it with injected input plus `PostMessage` mouse clicks.

## Risks
| Risk | Mitigation |
|---|---|
| `getCommandAvailability` assumes a GUI window (`win`) | Read the body: `win` is only used for the visual overlays. If nullptr breaks it, port just the availability rules into a helper |
| Selection messages interfere with the client's on-screen selection | Only logic selection changes. In `view` / `locked` modes the human can't change the client selection anyway |
| `requestUniqueUnitID()` changes the producer from the client side | It's exactly what the UI does. Confirmed by the replay CRC test with orders |
| Keyboard is DirectInput (needs the foreground window) | Integration tests inject raw key messages into the stream (`debug_inject_input`). Windows-level keyboard input is checked by hand |
| Pause key mapping unknown | Look it up in `CommandMap.ini` / `MetaEvent.cpp` during implementation |
| Other client paths create network messages (beacons, chat) | The command guard drops them in `view` / `locked`; only system messages are allowed |

## Findings during implementation
- **Some useful UI methods are protected.** `ControlBar::getCommandAvailability` is protected, so a small guarded public wrapper, `getCommandAvailabilityForScriptApi(button, obj)`, was added to `ControlBar.h`. `Mouse::blockCapture` is also protected; the public `setCursorCaptureMode(0)` does the job instead (and `OptionPreferences::getCursorCaptureMode()` restores it).
- **The UI greys out buttons for money and queue space too.** `getCommandAvailability` reports `COMMAND_RESTRICTED` when the player can't afford a unit or the queue is full. The API runs `canMakeUnit` first, so scripts get `INSUFFICIENT_FUNDS` / `QUEUE_FULL` rather than a vague `NOT_AVAILABLE`. Both checks still have to pass.
- **The command guard needed a settings message on its allow-list.** Once a second, `Player::update` re-sends `MSG_ENABLE_RETALIATION_MODE` from the client's option if the logic's copy differs. It's a settings sync, not human input. Dropping it made it repeat every second and never sync. It's now on the system allow-list. The guard's debug log line, "dropped network message N", is how to spot any other such message.
- **The logic re-checks production.** `ProductionUpdate::queueCreateUnit` runs `canMakeUnit` again when the message executes, so orders that slip past the API's checks (for example several in one frame) are refused safely. If the queue is somehow over-full it raises a "how did we get here" assertion, but `canMakeUnit` stops that first.
- **Pause is Shift+P for players.** Plain `P` only works for observers. The injected Shift+P in `full` mode is the positive control for the lock tests. The key mapper reads Shift from the key message's own state bits, so injected modifiers work.
- **A new known data assertion.** Selling an AmericaPowerPlant raises "ambiguous model match in findBestInfoSlow": its art defines overlapping SOLD model states. Any debug-build player sees it. It's in `KNOWN_ASSERTIONS`.
- **Post-match leaks are now checked by kind** (`AFTER_MATCH_LEAK_KINDS` in `gamehost.py`) instead of by total. The total varies (24–31) with rendering buffers, so a fixed limit was fragile. The 16-byte blocks are still capped at 18, and any unknown kind of leak fails.
- **`run-integration.ps1` passes pytest flags through now.** A `[Parameter]` attribute made PowerShell add common parameters, and `-p` matched `-PipelineVariable`. It's now a plain script that hands everything after `-Build` to pytest.
- **Selling doesn't produce `unit_destroyed`.** The building is removed rather than killed. Scripts should watch snapshots for it to disappear. A `structure_sold` / `object_removed` event can be added in phase 5.
