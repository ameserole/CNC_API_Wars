# Phase 3 — Read-Only View of the World

Parent plan: [PLAN-script-api.md](../PLAN-script-api.md) · Previous: [Phase 2](Phase-2-Skirmish-Harness.md)
Status: **Done**

## Goal
During a match, a script can learn everything a human player could know, **and nothing more**:
- static facts about the match, the map and its own faction's tech tree
- a regular snapshot of its own forces and of whatever it can currently see
- events for things that happen to its own player, the announcer (EVA) alerts, and the end of the game

A Python `World` model keeps that state up to date for scripts.

## The rule that drives every design choice here
Anything about another player's objects is reported only if the local human could see it **right now**, or saw it earlier and remembers it (a fogged building).

| Situation | Reported |
|---|---|
| Own object | Always, in full detail |
| Another player's object, shroud status `CLEAR` or `PARTIAL_CLEAR` for us, and not hidden by stealth | Yes, in less detail (below) |
| Enemy object that is `STEALTHED` and not `DETECTED` | No |
| Enemy object that is `DISGUISED` | Yes, but shown as the template it is disguised as |
| Another player's immobile object (building, civilian structure) that the client draws as a fog "ghost" | As a `known_structures` entry from **our own memory**. That means the last clear sighting, or for a ghost never seen clearly, its state when first fogged. Ghosts are frozen, so a fogged entry is never updated from the live engine state. The engine reports `FOGGED` only when a ghost is drawn: immobile neutral objects, and immobile buildings the player has seen (`PartitionManager.cpp` ~1636). Every other fogged object counts as `SHROUDED` |
| Terrain heights, water, cliffs, start positions | Yes. This is public map information, shown in the map preview |
| Pathfinding obstacles (buildings), other players' money, power, sciences or production | No |

## In scope
**Queries:**
- `game_info`: match facts.
- `catalog`: our faction's buildable structures, units, upgrades and sciences.
- `template_info`: public game data for any object type.
- `map`: a coarse grid of terrain height and passability.
- `state`: a snapshot on demand.

**Settings:** `set_snapshot_interval`.

**Events:**

| Event | When |
|---|---|
| `snapshot` | Every N frames. Default 15, which is 0.5 s |
| `unit_created` | One of our factories produced a unit |
| `construction_started` / `construction_complete` | One of our buildings was placed or finished |
| `unit_destroyed` | One of our objects died |
| `upgrade_complete` | A player upgrade finished |
| `science_purchased` | We gained a general's power (science) |
| `money_changed`, `power_changed`, `rank_changed` | One of these values changed. Checked every frame |
| `eva` | The announcer raised an alert for us |
| `game_over` | Victory or defeat |

**Debug only** (debug build plus `-scriptApiDebug`): `debug_world` gives the true state of every object for checking the fog rule, and `debug_add_cash` sends the existing debug "add cash" demo message.

**Python:** `World` model, plus `game_info()`, `catalog()`, `template_info()`, `map()`, `state()` and `set_snapshot_interval()`.

## Out of scope
- **Actions** (phase 4). So the production and construction events are built and unit-tested here, but only checked against the real game in phase 4, once a script can build things.
- **Enemy visibility events** (`enemy_spotted`, `enemy_lost_from_view`) and **damage events** (phase 5).
- **Object-level upgrades** (only player upgrades get an event) and **production queue contents** (phase 4/5).

## How the engine provides it
| Need | Engine source |
|---|---|
| All objects | `TheGameLogic->getFirstObject()` / `Object::getNextObject()` |
| Visibility | `Object::getShroudedStatus(localIndex)`, `OBJECT_STATUS_STEALTHED` / `_DETECTED` / `_DISGUISED`, `StealthUpdate::getDisguisedTemplate()` |
| Cell visibility (for remembered buildings) | `ThePartitionManager->getShroudStatusForPlayer(idx, &pos)` |
| Own player | `ThePlayerList->getLocalPlayer()`: `getMoney()->countMoney()`, `getEnergy()->getProduction()/getConsumption()`, `getRankLevel()`, `getSciencePurchasePoints()` |
| Players | `ThePlayerList->getPlayerCount()/getNthPlayer()`, `getRelationship(team)`, `getSide()`, `getPlayerType()`, `isPlayerActive()` |
| Tech tree | Start from the faction's starting building and units (`PlayerTemplate::getStartingBuilding/Unit`), then follow command sets (`TheControlBar->findCommandSet(template->friend_getCommandSetString())`) through `DOZER_CONSTRUCT`, `UNIT_BUILD`, `PLAYER_UPGRADE` and `OBJECT_UPGRADE` buttons |
| Cost and time | `ThingTemplate::calcCostToBuild(player)` / `calcTimeToBuild(player)`, and the same on `UpgradeTemplate` |
| Prerequisites | `ThingTemplate::getNthPrereq()`. **Small engine change:** add read-only accessors to `ProductionPrerequisite` for its unit and science prerequisites, which are currently private |
| Sciences | `TheScienceStore->getPurchasableSciences(player, now, later)`, `getSciencePurchaseCost`, `getInternalNameForScience` |
| Terrain | `TheTerrainLogic->getExtent()`, `getGroundHeight()`, and pathfinder cell type (water, cliff, impassable) via `TheAI->pathfinder()->getCell(LAYER_GROUND, x, y)` |
| Start positions | `MapMetaData::m_waypoints` entries `Player_N_Start` |
| Kinds | `ThingTemplate::isKindOf(i)` with `KindOfMaskType::getNameFromSingleBit(i)` |
| Hooks | `Player::onUnitCreated`, `onStructureCreated`, `onStructureConstructionComplete`, `onUpgradeCompleted`, `addScience`; `Object::onDie(DamageInfo*)` (`m_sourceID`); `Eva::playMessage` |
| Game over | `TheVictoryConditions->isLocalAlliedVictory()` / `isLocalDefeat()` |

## Design

### Hooks
Each hook is a guarded call: `#if RTS_SCRIPT_API` and `if (TheScriptApi) TheScriptApi->onXxx(...)`. The hook:
- returns at once unless the object or player belongs to the local player and the game state is `in_game`
- only **reads** engine state
- builds a JSON event and queues it

They add no logic randomness, no game-object writes, and no memory-pool use beyond `std::string` and JSON. **CRC and replay behavior does not change.**

### Polled values (checked once per `ScriptApi::update()` in `in_game`)
- money, power, rank and science points → `*_changed` events, each with old and new values
- victory / defeat → one `game_over`
- the snapshot timer

### Snapshot
```json
{"type":"event","event":"snapshot","frame":450,
 "self":{"index":2,"money":10000,"power":{"produced":0,"consumed":0},"rank":1,"science_points":0},
 "units":[{"id":12,"template":"AmericaCommandCenter","pos":[x,y,z],"angle":0.0,"health":5000,"max_health":5000,
           "status":["under_construction"],"construction_percent":40.0,"veterancy":0}],
 "visible":[{"id":40,"template":"ChinaInfantryRedguard","owner":3,"pos":[x,y,z],"health_pct":0.8,"status":[]}],
 "known_structures":[{"id":41,"template":"ChinaBarracks","owner":3,"pos":[x,y,z],"last_seen_frame":300}]}
```
- **`units`:** our objects.
- **`visible`:** everyone else's (enemy, ally, neutral) under the visibility rule.
- **Skipped:** projectiles, trees and bushes, inert objects, objects hidden from the GUI, and dead objects.
- **`status` values:** `under_construction`, `sold`, `stealthed`, `detected`, `disguised`.
- **Template details** (kinds, cost and so on) are not repeated in snapshots. Clients ask `template_info` once per template.

### Remembered buildings (`KnownStructureMemory`, game-independent)
- Each snapshot, every visible building not owned by us is recorded with its last-seen data.
- An entry is dropped when its last-seen position is visible to us again and the building is not visible there: it was destroyed, or it's gone.
- An entry is also dropped when the building dies while we can see it.
- A remembered building that is visible again is listed in `visible`, not in `known_structures`.

### Static queries
- **`game_info`:**
  - `map` (name, display name, extent `{min:[x,y], max:[x,y]}`), `local_player` index, `start_positions` `[[x,y], ...]`
  - `players`: `[{index, name, side, type ("human"/"computer"), relation ("self"/"ally"/"enemy"/"neutral"), active}]`
  - Only real players are listed: no neutral or civilian players, and no observers.
- **`catalog`:**
  - `{faction, structures:[..], units:[..], upgrades:[..], sciences:[..]}`
  - Things: `{name, kinds, cost, build_time, energy, built_by:[template], prerequisites:[[names that satisfy it]], available_now}`
  - Upgrades: `{name, type, cost, build_time, built_by}`
  - Sciences: `{name, cost, purchasable_now}`
- **`template_info {names:[...]}`:** `{name, side, kinds, cost, build_time, energy, radius, buildable}` for each name. Unknown names come back in `unknown`.
- **`map {cell_size=20}`:**
  - `{cell_size, origin:[x,y], columns, rows, heights:[[int]], terrain:["..wwc.."]}`
  - Terrain characters: `.` passable, `w` water, `c` cliff, `x` impassable.
  - `cell_size` is between 10 and 200.

### Game-independent pieces (`core_scriptapi`, unit-tested)
- `ChangeDetector<T>`: reports a value change with old and new values. Used for money, power and rank.
- `isVisibleToPlayer(relation, shroud, stealthed, detected)`: the visibility rule as a pure function.
- `KnownStructureMemory`: `observeVisible(structures, frame)`, `forgetWhere(cellVisible, visibleIds)`, `onDestroyedWhileVisible(id)`, `entries()`.
- `encodeTerrainGrid(columns, rows, sampler)`: builds the `heights` and `terrain` arrays.
- `SnapshotTimer`: interval handling; 0 turns snapshots off.

## Tests

### C++ unit tests
- **`ChangeDetector`:** the first value doesn't count as a change; a change is reported once with old and new values.
- **Visibility rule:**
  - `self` is always visible.
  - Others need clear or partial shroud.
  - Fogged and shrouded objects are hidden.
  - A stealthed enemy is hidden unless detected.
  - A stealthed ally is visible.
- **`KnownStructureMemory`:**
  - A building is remembered after it's seen.
  - It's kept while its cell is fogged.
  - It's dropped when the cell is visible and the building isn't.
  - It's dropped when destroyed while visible.
  - It updates `last_seen_frame` and position on a re-sighting.
- **`encodeTerrainGrid`:** row and column counts, the character for each cell type, and height rounding.
- **`SnapshotTimer`:** fires every N frames, can be switched off, and restarts the count when the interval changes.

### Python unit tests (`World`)
- A snapshot replaces `units`, `visible` and `known`.
- `mine(template=..., kind=...)` filters, using kinds from the template cache.
- `unit_destroyed` removes the unit before the next snapshot.
- `money` and `power` follow both snapshots and `*_changed` events.
- `game_over` sets `world.result`.

### Integration (`tests/integration/test_world_view.py`, using the `skirmish` fixture vs Easy AI)
| # | Test | Expected |
|---|---|---|
| 1 | `game_info` | 2 players: us (`relation: self`, America) and China (`relation: enemy`, computer). At least 2 start positions inside the map extent |
| 2 | `catalog` | Has `AmericaPowerPlant`, `AmericaBarracks`, `AmericaInfantryRanger` and `AmericaVehicleDozer`. Costs are above 0. Ranger `built_by` includes `AmericaBarracks`. Power plant `built_by` includes `AmericaVehicleDozer`. At least one upgrade and one science |
| 3 | `template_info` | `ChinaCommandCenter` → side China, kinds include `STRUCTURE`. An unknown name comes back in `unknown` |
| 4 | `map` | `rows × columns` matches the extent and `cell_size`. Only valid terrain characters. Heights vary |
| 5 | First snapshot | `units` has `AmericaCommandCenter` and `AmericaVehicleDozer`. `self.money` is the starting cash. **No China objects in `visible`**, while `debug_world` shows a China command center that is shrouded or fogged for us |
| 6 | Fog rule over 10 s | Every non-own building in any snapshot is `clear` / `partial` in `debug_world` |
| 7 | Snapshot interval | `set_snapshot_interval 30` → frame gaps of about 30. `0` stops snapshots. `state` still answers |
| 8 | `money_changed` | `debug_add_cash` → `money_changed` with `delta` 10000, and the next snapshot agrees |
| 9 | `eva` and `game_over` | Not forced here. Checked by unit tests and again in phase 4/5 |

## Acceptance criteria
- [x] All C++ unit tests (67) and Python unit tests (29) pass.
- [x] Phases 1–3 integration suites (28 tests, plus the replay check) pass three full runs in a row. That is 57 Python tests per run.
- [x] Snapshot cost is logged every 60th snapshot. In the debug build it takes **0.7–1.0 ms** while scanning 147 objects (2 own, 16 known), even with snapshots forced every frame.
- [x] The CRC is unchanged with the API on. `test_replay_consistency.py` plays a 45 s match with snapshots every frame plus constant queries, then re-simulates the replay headless without the API. It plays to the end with no CRC mismatch.

## Risks
| Risk | Mitigation |
|---|---|
| Leaking hidden information | Visibility is a single pure function, unit-tested and checked in integration against `debug_world`. Obstacles and enemy economy are never read |
| Hooks changing the simulation | Hooks are read-only and the CRC is checked by replay |
| The command-set walk misses buttons added by upgrades (`CommandSetUpgrade`) | Accept for now, and note it in the catalog docs. Phase 4 commands check availability live anyway |
| Snapshot cost with many objects | Filter cheaply, and measure (acceptance criterion) |
| `Eva::playMessage` not called with `-noaudio` | The hook sits where the alert is queued, before any audio. Check in phase 4 when base-under-attack alerts can be caused |

## Findings during implementation
- **The engine already defines "what the human sees in fog".** `PartitionManager` (~line 1636) reports an object as `FOGGED` only when the client draws it as a ghost: immobile neutral objects, and immobile buildings the player has seen before (mines never). Every other fogged object counts as `SHROUDED`. In multiplayer and skirmish the whole map starts fogged rather than black, so a human sees the map's civilian buildings in grey from the start. `known_structures` now includes these ghosts (16 on Tournament Desert at the start). Like ghosts, they stay frozen while fogged (`observeFogged`). Before this fix, the bot knew *less* than a human.
- **Snapshot cost in the debug build is mostly JSON allocations.** Every allocation goes through the game's checked debug allocator. Fixes:
  - compute fog status once per object
  - move, don't copy, the arrays into the snapshot and event (`makeEvent` / `makeReply` / `sendEvent` take JSON by value)
  - cache the `known_structures` array, rebuilt only when `KnownStructureMemory::version()` or the set of visible objects changes

  Cost went from about 2–2.8 ms down to 0.7–1.0 ms.
- **Fixed an existing bug: the debug memory totals had a race.** `MemoryPoolFactory::adjustTotals` was called under `TheMemoryPoolCriticalSection` from pool allocations, but under only `TheDmaCriticalSection` from raw DMA allocations. Allocations on two threads could therefore lose updates, which tripped "used/phys count mismatch" at shutdown. This was the intermittent phase-1 assertion; it showed up reliably under heavy API traffic. `adjustTotals` now takes the pool lock as well, which is the same lock order the DMA path already uses. It's in GameMemory.cpp and is a candidate for an upstream PR.
- **Leaks after a live match.** Exiting after an API-started match reports 24–30 leaks, against 3 with no match.
  - The 3076/5124-byte blocks also appear when a replay of the same match is watched in a window with no API, so they come from rendering.
  - The 18 × 16-byte blocks appear only after live matches. The count is identical with minimal and heavy API use, with snapshots on or off, and for different match lengths, so it doesn't grow with API work. Calling only `skirmish_options` adds nothing. It is most likely debug-STL container bookkeeping in static containers on the live-play path, which are freed after the leak report. That isn't proven, because a live match can't currently be started without the API.
  - The harness allowance for clean exits after a match is `KNOWN_LEAKS_AFTER_MATCH = 30` (`@pytest.mark.leak_baseline`). It's still strict, and other exits keep the allowance of 3.
  - **To confirm:** exit the debug build after a skirmish started from the menu, and compare the leak report.
- **Single-replay simulation output.** `-headless -replay x.rep` with one file doesn't print an error count. It stops early on the first mismatch and exits with 1. The test checks the exit code and that the reported game time reached the end.
- **Starting units don't produce `unit_created`.** Hooks only report while the state is `in_game`, and the map is set up during `loading`. So the first snapshot, not events, is how a script learns its starting units.
