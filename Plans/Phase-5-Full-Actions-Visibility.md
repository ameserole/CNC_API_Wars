# Phase 5 — Full Action Set, Enemy-Visibility and Damage Events

Parent plan: [PLAN-script-api.md](../PLAN-script-api.md) · Previous: [Phase 4](Phase-4-Core-Actions.md)
Status: **Done**

## Goal
A script can do everything a human player regularly does in a match:
- upgrades and general's powers (sciences)
- special powers and unit abilities, including capture and hacking
- garrison/enter, exit and evacuate
- repair, dock, waypoint paths, scatter, formations
- cancelling construction and upgrades

It also gets events for:
- enemies coming into view, leaving view and dying in view
- buildings discovered through fog
- damage to its own units
- its own buildings being sold or otherwise removed

The fog rule still applies to everything.

## In scope

### Commands
| Command | Message (args) | Checks copied from the UI |
|---|---|---|
| `upgrade {object, upgrade}` | `MSG_QUEUE_UPGRADE (objectID, upgradeNameKey)` | The object's command set has a `PLAYER_UPGRADE` / `OBJECT_UPGRADE` button for it. `TheUpgradeCenter->canAffordUpgrade` → `INSUFFICIENT_FUNDS`. `pu->canQueueUpgrade` → `QUEUE_FULL` / `NOT_AVAILABLE`. An object upgrade the object already has or isn't affected by → `NOT_AVAILABLE`. Then the button must be available (`ControlBarCommandProcessing` `GUI_COMMAND_*_UPGRADE`) |
| `cancel_upgrade {object, upgrade}` | `MSG_CANCEL_UPGRADE (upgradeNameKey)` | The upgrade is in that object's production queue |
| `purchase_science {science}` | `MSG_PURCHASE_SCIENCE (scienceType)` | The science is in `getPurchasableSciences(player).now` (prerequisites and points) → otherwise `NOT_AVAILABLE` |
| `use_ability {units, ability, target?, pos?}` | Depends on the button type (below) | The button named `ability` is in the first unit's command set and available. Target rules below |
| `enter {units, target}` | `MSG_ENTER (INVALID_ID, targetID)` | The target is visible. At least one unit can `TheActionManager->canEnterObject(unit, target, CMD_FROM_PLAYER, CHECK_CAPACITY)` (garrison, transport, tunnel) → otherwise `CANNOT_ENTER` |
| `exit_container {units}` (`exit` is the shutdown command) | per unit `MSG_EXIT (objectID)` | Each unit is inside a container (`getContainedBy()`) |
| `evacuate {object}` | `MSG_EVACUATE ()` | The object contains something |
| `repair {dozer, target}` | `MSG_DO_REPAIR (targetID)` | `canRepairObject` |
| `resume_construction {dozer, target}` | `MSG_RESUME_CONSTRUCTION (targetID)` | `canResumeConstructionOf` |
| `get_repaired {units, target}` | `MSG_GET_REPAIRED (targetID)` | `canGetRepairedAt` for at least one unit |
| `dock {units, target}` | `MSG_DOCK (targetID)` | `canDockAt` (supply trucks) for at least one unit |
| `guard_object {units, target}` | `MSG_DO_GUARD_OBJECT (targetID, GUARDMODE_NORMAL)` | The target is visible |
| `force_attack_object {units, target}` | `MSG_DO_FORCE_ATTACK_OBJECT (targetID)` | The target is visible; a unit can attack it |
| `force_move {units, pos}` | `MSG_DO_FORCEMOVETO (location)` | — |
| `move {units, pos, waypoints?}` | `MSG_DO_MOVETO (p0)`, then `MSG_ADD_WAYPOINT (pN)` for each waypoint | All points inside the map |
| `scatter {units}`, `formation {units}` | `MSG_DO_SCATTER ()`, `MSG_CREATE_FORMATION ()` | — |
| `cancel_build {building}` | `MSG_DOZER_CANCEL_CONSTRUCT ()` | The building is under construction |

### `use_ability` by button type
The type comes from the button found by name in the unit's command set.

| `GUICommandType` | Message | Target |
|---|---|---|
| `SPECIAL_POWER`, `SPECIAL_POWER_FROM_SHORTCUT` | `MSG_DO_SPECIAL_POWER (spID, options, INVALID_ID)` | none |
| | `MSG_DO_SPECIAL_POWER_AT_LOCATION (spID, location, INVALID_ANGLE, INVALID_ID, options, INVALID_ID)` | `pos`, if the button has `NEED_TARGET_POS` |
| | `MSG_DO_SPECIAL_POWER_AT_OBJECT (spID, targetID, options, INVALID_ID)` | `target`, if the button needs an object target. It must be visible and pass `button->isValidObjectTarget(unit, target)` |
| `SWITCH_WEAPON` | `MSG_SWITCH_WEAPONS (weaponSlot)` | none |
| `HACK_INTERNET` | `MSG_INTERNET_HACK ()` | none |
| `TOGGLE_OVERCHARGE` | `MSG_TOGGLE_OVERCHARGE ()` | none |
| `EVACUATE` | `MSG_EVACUATE ()` | none |
| Upgrade buttons | Same as `upgrade` | none |
| Anything else | `NOT_AVAILABLE` ("not supported by the script API yet") | — |

**Notes:**
- `MSG_CAPTUREBUILDING` is never sent by the game. Capture and hack abilities are special powers, so they go through `use_ability`.
- Location and object specials also need `TheActionManager->canDoSpecialPowerAtLocation` / `AtObject` (source requirements: ready, in range…) for at least one unit. Otherwise → `NOT_AVAILABLE`.
- **Abilities in the catalog:** structures and units gain `abilities: [{name, type, target: "none"|"position"|"object", special_power?, upgrade?}]`, listing the API-supported buttons of the template's command set.

### Events
| Event | Source | Fields |
|---|---|---|
| `enemy_spotted` | Visibility scan every 3 frames: an enemy object that wasn't visible now is | `id, template` (as it appears), `owner, pos` |
| `enemy_lost_from_view` | An enemy object that was visible isn't, and didn't die in view | `id, template, last_pos` |
| `enemy_destroyed` | `Object::onDie` for an enemy object that was visible to us | `id, template, owner, pos, attacker_id?` (the attacker named only if visible or ours) |
| `structure_discovered` | `KnownStructureMemory` adds an entry, either seen clearly or as a fog ghost | `id, template, owner, pos, fogged` |
| `unit_damaged` | `ActiveBody::attemptDamage` when one of our objects loses health. **Grouped per object, one event per 15 frames** | `id, template, damage` (sum), `health`, `max_health`, `attacker_id?` / `attacker_template?` (the last attacker that was visible) |
| `unit_removed` | `GameLogic::destroyObject` for our object that didn't die (sold, or removed by scripts) | `id, template, reason: "sold"\|"removed"` |

- **Starting state:** the visibility scan starts empty at `in_game`, so anything visible on the first scan is "spotted". At the start that's normally nothing.
- **Sharing work:** the scan also keeps `KnownStructureMemory` up to date. Snapshots no longer have to run for remembered buildings to stay current, and `set_snapshot_interval 0` no longer freezes that memory.

### Debug only (debug build plus `-scriptApiDebug`)
- `debug_hurt {id}` sends `MSG_DEBUG_HURT_OBJECT (id)`, as the debug selection tool does.
- `debug_give_science_points` sends the existing debug demo message, if there is one; otherwise this is recorded as a finding.

## Game-independent pieces (`core_scriptapi`, unit-tested)
- **`VisibilityTracker`:**
  - `update(map<id, VisibleInfo>)` returns `{spotted, lost}`.
  - `forget(id)` is used for deaths, so a dead object isn't reported as lost.
  - `clear()`.
- **`DamageAggregator`:**
  - `add(id, amount, attacker, frame)`.
  - `due(frame, window)` returns grouped entries whose window has passed.
  - An attacker of 0 doesn't overwrite a known attacker.
- **`KnownStructureMemory::observe` / `observeFogged`** return `true` when an entry is new.
- **`parseWaypoints`** parses an optional list of `[x, y]` points (at most 20).

## Engine hooks added
All read-only and guarded, like phase 3:
- `ActiveBody::attemptDamage` → `TheScriptApi->onObjectDamaged(obj, damageInfo)` (after health has dropped)
- `GameLogic::destroyObject` → `TheScriptApi->onObjectRemoved(obj)`

## Tests

### C++ unit tests
- **`VisibilityTracker`:**
  - First appearance → spotted. Still visible → nothing. Gone → lost, with the last position.
  - Forgotten (died) → not reported as lost.
  - Comes back → spotted again.
  - `clear()` starts over.
- **`DamageAggregator`:**
  - Hits within the window add up into one entry.
  - Separate objects get separate entries.
  - The last visible attacker is kept, and a later hit with attacker 0 keeps it.
  - Nothing is due before the window ends.
- **`KnownStructureMemory`:** the new return values.
- **`parseWaypoints`:** absent, valid, too many, malformed.

### Python unit tests
Payloads for each new command. `World` drops a unit on `unit_removed`, and keeps an `enemies_seen` dict from spotted/lost/destroyed events.

### Integration — `test_full_actions.py` (skirmish vs Easy AI)
| # | Test | Expected |
|---|---|---|
| 1 | Catalog abilities | The Ranger has at least one ability. The barracks lists upgrade buttons |
| 2 | `upgrade` the first affordable, available player upgrade at the barracks (found from the catalog) | Reply OK, `command_executed`, money goes down, `upgrade_complete` with the same name within 90 s |
| 3 | `cancel_upgrade` | Queue an upgrade and cancel it: money returns |
| 4 | `use_ability` on a no-target ability that's available (found from the catalog, for example the flash-bang mode after its upgrade) | `command_executed`. If none is available, skip with the reason |
| 5 | `purchase_science` | If `rank_changed` / points allow, buy the first purchasable science → `science_purchased`. Otherwise skip, or use the debug science points |
| 6 | `move` with waypoints | The units visit the last waypoint |
| 7 | `scatter`, `formation`, `force_move`, `guard_object` (own CC) | Each gives `command_executed` |
| 8 | `enter` / `evacuate` | The Rangers enter a visible garrisonable civilian building (found with `World` + `template_info` kinds `GARRISONABLE_UNTIL_DESTROYED` / `STRUCTURE`, after moving there). Snapshots show them gone from the map, then `evacuate` brings them back. Skip if the map has no reachable one |
| 9 | `debug_hurt` one of our Rangers | One `unit_damaged` with damage > 0 and `health < max_health`, not one per hit |
| 10 | `sell` a building | `unit_removed {reason: "sold"}` |
| 11 | Refused commands | Each of these gives its error and changes nothing: <br>• `enter` an invisible target → `NOT_VISIBLE` <br>• `use_ability` with an unknown button name → `NOT_AVAILABLE` <br>• `upgrade` the barracks with a War Factory upgrade → `NOT_AVAILABLE` <br>• `purchase_science` an unknown name → `INVALID_ARGUMENT` |

### Integration — `test_contact.py` (scenario steps 10–11)
`attack_move` all combat units toward the enemy start position (the start position farthest from our Command Center). Over up to 4 minutes:
- **Order:** the first enemy event received is `enemy_spotted`.
- **Fog rule at the moment of sighting:** every `enemy_spotted` object is visible in `debug_world` right after.
- **Attackers stay hidden when unseen:** every `unit_destroyed` / `unit_damaged` with an `attacker_id` names an attacker that was visible at the time (checked against the most recent `enemy_spotted`, without a later `enemy_lost_from_view` for the same ID).
- **Contact happens:** at least one `unit_damaged` and one `enemy_spotted` arrive.

### Performance
Log the visibility scan cost every 300 scans. The scan with 150+ objects must take under 1 ms in the debug build.

## Acceptance criteria
- [x] All C++ unit tests (92) and Python unit tests (36) pass.
- [x] Phases 1–5 integration tests pass three full runs in a row: 92 passed and 1 skipped per run, about 11–12 min. The skip is the civilian-building garrison test (see Findings). Containers are covered on every map by the Humvee transport test.
- [x] The replay CRC test still passes. Its orders now also include a barracks, an upgrade and a waypoint move.
- [x] The visibility scan cost is measured: **57–969 µs** for 157–161 objects in the debug build (logged every 300 scans).

## Risks
| Risk | Mitigation |
|---|---|
| Too many ability types | Support the common button types; reject the rest with an explicit `NOT_AVAILABLE` reason. The catalog lists only supported abilities |
| `isValidObjectTarget` / `canDoSpecialPowerAt*` need a source | Use each candidate unit as the source. Pass `INVALID_ID` as the specific source, as the UI does, so the logic uses the selection |
| Contact test flakiness: the Easy AI may not fight back in time | Generous timeouts. Only assert on events that arrived. Require `enemy_spotted` (guaranteed when units reach the base) and damage (Easy AI base defences shoot) |
| Damage hook frequency (every bullet) | Group per object over 15 frames, with no per-hit allocation beyond one map entry per object |
| `destroyObject` is also called for objects that died | Remember IDs reported by `onObjectDied`; report only the others as `unit_removed` |

## Findings during implementation
- **A minimized skirmish client froze.** `Win32GameEngine::update` spins in a sleep loop while the window is iconic, except in LAN and online games. A bot's game (and its API) therefore stopped whenever its window was minimized, which showed up as request timeouts and logic advancing at a few frames per second. Script-controlled clients now keep running too (guarded change in Win32GameEngine.cpp). `test_minimized_bot_keeps_playing` covers it.
- **`COMMAND_ACTIVE` counts as clickable.** A weapon-mode button that is "pressed in" reports `ACTIVE`, and that is worked out from the *on-screen* selection, which bots don't use. Buttons with `MUST_BE_STOPPED` are disabled while the unit moves, as in the UI.
- **`ScienceStore::getScienceFromInternalName` only hashes the name.** Any string maps to a "science". The API now also checks `isValidScience`.
- **Reserved request fields.** A request argument named `id` overwrote the request ID, and the reply then never matched. The Python client now rejects `id` and `cmd` as argument names, and the debug command takes `object` instead.
- **Garrisoned and transported units aren't selectable,** so orders to them get `NOT_OWNED`, as a UI click would fail. Snapshots report `contained_by` for them.
- **Map-specific reachability.** On Tournament Desert none of the garrisonable civilian buildings within 1000 units of the base can be reached by infantry. The orders are accepted, as a human's click would be, but the units stop short. So that test skips with the reason, and a Humvee transport test covers `enter` / `evacuate` on any map. Earlier attempts walked the Rangers into the enemy base, so the test now only uses buildings near the base and replaces lost Rangers between tests.
- **`MSG_CAPTUREBUILDING` is never sent by the game.** Capture and hack abilities are special powers, so `use_ability` covers them.
- **Snapshot cost rises with visible objects.** Most snapshots take 0.6–2 ms, but with 5–8 visible objects a few took 3–15 ms in the debug build. Snapshots run every 15 frames, so this is acceptable for now. If it grows, cache the per-object JSON like `known_structures`.
