# Phase 8 — Fixes from the First Agent-vs-Agent Match

Parent plan: [PLAN-script-api.md](../PLAN-script-api.md) · Previous: [Phase 7](Phase-7-Hardening-Replays.md)
Status: **Done** (third full-suite run cancelled)

## Goal
Fix what two agents found when they played each other through the API. The match was a LAN game on Tournament Desert, America vs America, with an observer. Bot2 won at about 36 minutes; the record is in `agent-matches/20261101-041421/`.

## Input: the two reports
| Report | Who | Triage |
|---|---|---|
| `use_ability` accepts general's powers the player doesn't own (Spectre Gunship, Paradrop, Daisy Cutter, A10 strike) | both | **Bug.** The control bar hides a button with `NEED_SPECIAL_POWER_SCIENCE` whose power's `RequiredScience` the player lacks (`ControlBarCommand.cpp`, "commands that require sciences we don't have are hidden"). `requireButtonAvailable` only asked `getCommandAvailability`, which doesn't check that. The logic drops the message on execution (`AIGroup.cpp`, "Nice try"), so the order did nothing, but the API must refuse it as the UI does |
| `known_structures` dropped every enemy building at frame ~55000 | Bot2 | **Confusing design, not lost data.** Bot2's army was in the enemy base, so those buildings were visible, and the API reports a visible structure only under `visible`, not `known_structures`. Bot1 tripped over the same rule with neutral supply docks. Two agents getting it wrong independently is enough reason to change it: `known_structures` now lists every remembered structure, visible or not, with a `visible` flag |
| `enemy_destroyed` / `unit_destroyed` fire for missiles, laser beams, debris | Bot2 | **Bug.** The death and removal hooks never applied `isReportable`, the filter snapshots use. They now apply its kind part (the object is already dead, so the alive check can't apply). Hulks, parachutes and cargo planes are drawn and reported in snapshots, so they keep their events |
| No supply amount; a dry dock is noticed only when income stops | both | **Gap.** The game's mouse-over tooltip shows a supply source's dollar value (`InGameUI.cpp`, `TOOLTIP:SupplyWarehouse`), and the model shrinks as it empties. Visible supply sources now report `supply` (dollars left) |
| Idle Chinooks look the same as working ones (`status: []`) | Bot2 | **Gap.** A human sees a harvester parked. Own units now get the status flags `idle` (the AI is idle) and `harvesting` (a supply unit's state machine is fetching or docking) |
| `build` accepted, but no `construction_started` and no failure | Bot1 | **Gap.** The engine places the building and takes the money when `MSG_DOZER_CONSTRUCT` executes, and silently drops it if `isPossibleToMakeUnit` fails then (`BuildAssistant::buildObjectNow`). Bot1's money had been spent by orders sent in the meantime. Two fixes: money committed by orders not yet executed counts as spent, and a build that executes without creating a structure sends `build_failed` |
| `resume_construction` → "that dozer cannot resume that" | Bot1 | **Unclear error.** The message now says why: not under construction, or a dozer is already building it |
| Visible enemies have `health: None` | Bot2 | **Not a bug.** Other players' objects carry `health_pct`; own units carry `health` / `max_health`. Documented |
| `dock` on an empty supply pile → `NOT_AVAILABLE` | Bot2 | **Engine behavior** (`ActionManager::canTransferSuppliesAt` refuses an empty warehouse). `supply` now shows it beforehand |
| Capturing the oil derrick: `enter` refused; the capture ability needs `Upgrade_InfantryCaptureBuilding` | Bot1 | **Engine behavior.** Documented |
| `sell` paid nothing | Bot1 | **Engine behavior.** The sale pays when the deconstruction finishes (`BuildAssistant` deposits the sell value at the end); a building destroyed while being sold pays nothing. Documented |
| Attack-move ignores plain buildings | Bot2 | **Engine behavior.** Documented |
| A probe connection supersedes the running bot | both | As designed (phase 7). Documented as a gotcha |

## In scope

### 1. Special powers need their science
`requireButtonAvailable` refuses a button with `NEED_SPECIAL_POWER_SCIENCE` whose special power has a `RequiredScience` the player lacks, with `NOT_AVAILABLE` "requires the science X". It's the shared check, so every order that clicks a button gets it. The catalog's abilities gain `required_science` (the internal name, or null).

### 2. `known_structures` lists every remembered structure
Every entry has `visible: true|false`. Visible ones are also still in `visible`, with their live details. Remembering, forgetting and `structure_discovered` are unchanged. The `World` view keeps the dict as before.

### 3. Destruction events only for reportable objects
`unit_destroyed`, `enemy_destroyed` and `unit_removed` are skipped for projectiles, shrubbery, trees, inert objects and objects ignored by the GUI (supply sources excepted), the same kinds snapshots leave out.

### 4. Snapshot additions
- `supply`: the dollar value left in a visible supply source (`boxes × baseValuePerSupplyBox`), on entries in `visible`.
- Own units: status flags `idle` (`AIUpdateInterface::isIdle`) and `harvesting` (`SupplyTruckAIInterface::isCurrentlyFerryingSupplies`).

### 5. Spending orders and failed builds
- **Committed money:** `build`, `train` and upgrades (`upgrade`, and `use_ability` on an upgrade button) add their cost to a pending list when accepted. An entry is removed when the logic executes the first pending message of its type (`MSG_DOZER_CONSTRUCT`, `MSG_QUEUE_UNIT_CREATE`, `MSG_QUEUE_UPGRADE`). The orders check `money − committed ≥ cost` and refuse with `INSUFFICIENT_FUNDS` otherwise. The pending list is cleared at the start of each match. Game-independent: `scriptapi::PendingSpend`.
- **`build_failed`:** when a `MSG_DOZER_CONSTRUCT` the API sent executes, the build is remembered for that frame. If no `construction_started` for that dozer follows before the next `update()`, the API sends `build_failed {reply_to, dozer, template, pos}`. Builds sent by a previous connection are reported to nobody (as with `command_executed`).

### 6. `resume_construction` errors
`NOT_AVAILABLE` with "that structure is not under construction", "that dozer is already building it", "another dozer is building it", or the old generic message for anything else.

### 7. Bot-author notes
A new `python/BOT-NOTES.md`: the gotchas both agents learned the hard way.

## Out of scope
- Read-only extra connections. A probe still replaces the bot's connection; the notes say to probe from inside the bot.
- A "supply depleted" event: the `supply` field is enough to poll.

## Game-independent pieces (unit-tested)
| Piece | Where |
|---|---|
| `PendingSpend` (add, executed-by-type, committed sum, orphan, clear) | `ScriptApiCommands.{h,cpp}` |

## Tests

### C++ unit tests (`ScriptApiAgentFixesTest.cpp`)
- `PendingSpend`: the committed sum; an executed message removes the oldest entry of its type only; other types are untouched; `clear`.

### Python unit tests
- `World` keeps visible entries in `known_structures`.

### Integration (`test_agent_fixes.py`, one skirmish)
| Test | What |
|---|---|
| 1 | `use_ability` on the Command Center with a general's power the player doesn't own → `NOT_AVAILABLE`; the catalog lists its `required_science` |
| 2 | A supply source in `visible` has `supply` > 0, and it is also in `known_structures` with `visible: true` |
| 3 | A new dozer sits `idle`; supply units report `harvesting` |
| 4 | Two builds of the same structure sent together with money for one → the second `INSUFFICIENT_FUNDS` |
| 5 | Destruction events: a Missile Defender fires at something until destroyed events arrive; none of them names a projectile (`debug_world` kinds) |
| 6 | `resume_construction` on a structure being built by that dozer → "already building it" |

`build_failed` needs a build that passes every check and then fails on execution, which can't be set up reliably in a test without cheats that change money outside the command stream. It is covered by a debug-only probe (Findings), not the suite.

## Acceptance criteria
- [x] Every "Bug" and "Gap" in the triage table fixed, with tests (plus `force_attack_object`, Finding 1)
- [x] `python/BOT-NOTES.md` written
- [ ] C++ (112) and Python (53) unit tests pass; the full suite passed two runs in a row (131 passed, 1 skipped, about 25 min each). The third run was cancelled at the user's request
- [x] Master plan and CLAUDE.md updated

## Risks
- **The pending-spend FIFO** assumes the local player's spending messages execute in the order the API sent them, as the command tracker already does. With `-scriptApiInput full` a human's own orders could pop an entry early; that only makes the check looser, never wrongly refuses.
- **`known_structures` grows visible entries.** Scripts that unioned it with `visible` now see duplicates by id; the World view merges by id already.

## Findings
1. **`force_attack_object` used the normal attack check.** It asked `getAbleToAttackSpecificObject(ATTACK_NEW_TARGET, ...)`, which refuses own and allied targets, while the UI (`CommandXlat` `canObjectForceAttack`) uses `ATTACK_NEW_TARGET_FORCED`. Found while writing test 5: force-firing at our own barracks was `CANNOT_ATTACK`. Fixed; test 5 now depends on it.
2. **Missile Defenders don't fire at bare ground.** `force_attack` with a position is accepted (the UI allows a ground force-attack for almost every mobile unit) but nothing is fired. Engine behavior, noted in `BOT-NOTES.md`.
3. **`debug_world` used the snapshot filter**, so it could never show a projectile. It takes `all: true` now (debug builds only), which test 5 uses to prove missiles were in flight while no events arrived.
4. **Bot2's "dropped" structures were visible ones.** Its log shows `known_structures` going from four entries to none at frame ~55700 while its army sat in the enemy base with 6–8 enemy objects in view. Nothing was lost; the old rule listed visible structures only under `visible`.
5. **Money is withdrawn on execution** for structures (`DozerAIUpdate::construct`), units (`ProductionUpdate::queueCreateUnit`) and upgrades (`ProductionUpdate::queueUpgrade`), so committed money settles at the right moment. A structure is created in the same dispatch as its `MSG_DOZER_CONSTRUCT`, so a build without `construction_started` by the next `update()` really was dropped.
6. **`build_failed` has no test in the suite.** A build that passes the API's checks and then fails on execution needs another order to take the money or the spot within a frame. Committed money now prevents the money case, so only rare cases (a unit standing on the spot) remain.
