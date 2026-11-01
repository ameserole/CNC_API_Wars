# Notes for bot authors

Things that are easy to get wrong with the script API. They were learned the hard way by agents playing whole matches. The commands themselves are in `generals_api/client.py`, and the details are in the phase docs under `Plans/`.

## Connections
- **One controller and up to three watchers per game instance.** `ws://127.0.0.1:PORT` is the controller (your bot); a second controller replaces the first (close code 4001, `superseded`), and the old client's pending requests fail with `ConnectionClosed`. `ws://127.0.0.1:PORT/watch` (`watcher_url(url)` in the client) is a **watcher**: it runs alongside the bot, gets every event and query, and may give orders (same checks and APM cap), but can't start, quit, exit or save replays (`WRONG_ROLE`). A fourth watcher is refused (close code 4003). `command_executed` and `build_failed` go to the connection that sent the order; every other event goes to every connection.
- **`python -m generals_api.watch URL`** blocks until something matters and prints a digest (see its `--help`); **`python -m generals_api.order URL cmd key=value ...`** sends one command. Both use watcher connections, so your bot keeps running.
- **`generals_api.botkit`**: `LiveSettings` and `LiveModule` reload a bot's `settings.json` and `strategy.py` when they change, so a running bot can be retuned without reconnecting; `exit_when_superseded(client)` ends an old bot when a new one connects.
- The match doesn't notice a reconnect: units keep their orders. A new connection gets no `command_executed` for the old one's orders.
- Keep the bot's memory (what was built, sold or planned) in a file if you restart it often; anything only in memory is lost on restart.

## Reading the world
- **Field names:**
  - Own units have `health` and `max_health`.
  - Other players' objects have `health_pct` (0–1).
  - Status flags are lowercase: `under_construction`, `sold`, `stealthed`, `detected`, `disguised`, and for own units `idle` and `harvesting`.
- **`visible`** lists other players' objects in sight now, neutral ones included (supply docks, oil derricks, civilian buildings).
- **`known_structures`** lists every other-player structure seen so far, with `visible: true` for those in sight now (they are also in `visible`) and `false` for ones remembered through fog. `last_seen_frame` is the current frame for visible ones. A remembered structure is forgotten when you can see its spot again and it isn't there, or when you see it destroyed.
  - `World.enemy_structures()` gives the enemy's entries.
- **Supply:** a visible supply source has `supply`, the dollars left in it (what the mouse-over tooltip shows). Docks run dry after 15–20 minutes; plan the next income source (more docks, Supply Drop Zone, oil derricks) before that. `dock` on an empty source is refused with `NOT_AVAILABLE`.
- **Idle harvesters:** a Chinook or supply truck that has stopped harvesting loses `harvesting` and gets `idle`.
- **Events** (`unit_destroyed`, `enemy_destroyed`, `unit_removed`) cover units and buildings only, not missiles or debris. Wrecks (hulks), parachutes and cargo planes are real objects and do appear.

## Factions, stats and the end of a game
- `skirmish_options()["factions"]` lists the 12 selectable factions. `faction_catalog(faction)` returns what any of them builds (base costs, build times, prerequisites, general's sciences by tier), from the menus or in a game. Generals' factions use their base side's templates under a prefix (`AirF_AmericaVehicleDozer`, `Tank_ChinaBarracks`, `Chem_GLAInfantryWorker`); `catalog()["faction"]` is the side (`AmericaAirForceGeneral`).
- `player_stats()` returns the score-screen numbers (score, units and buildings built, lost and destroyed, money earned and spent): only yours while the game runs; everyone's for an observer or once the game is over.
- `game_over` carries `result` (`victory`, `defeat`, or `ended` for an observer), `winners` (player indices) and every player's `stats`. About 12 seconds later the game goes to the score screen by itself (`game_state` `shell`); `quit_game` is not needed then (it answers `WRONG_STATE`), but `save_replay` and `exit` work.

## Giving orders
- **Money is committed when an order is accepted**, not when it executes. `build`, `train` and upgrades refuse with `INSUFFICIENT_FUNDS` if the money left over after orders still on their way doesn't cover them.
- **A build can still fail when it executes**, e.g. if a unit is standing on the spot. You then get `build_failed {reply_to, dozer, template, pos}` instead of `construction_started`; try another spot.
- **Placement:** try a ring of spots around a point until `build` stops returning `ILLEGAL_LOCATION`. Don't sort spots toward the enemy for structures you want to keep.
- **Attack-move doesn't target plain buildings.** It fights units and defenses on the way. To destroy a base, send explicit `attack` orders at the buildings (`World.enemy_structures()`). The match ends when the enemy has no buildings or units that count for victory left.
- **Forced attack** (`force_attack_object`, Ctrl+click) can target your own or allied objects, like the UI. Some weapons can't fire at bare ground (`force_attack` with a position is accepted but nothing happens).
- **General's powers** need their science: `use_ability` refuses with `NOT_AVAILABLE` "… requires the science X". The catalog's abilities list `required_science`.
- **Sciences:** `purchase_science` needs `purchasable_now` in the catalog (prerequisites and points). `prerequisites_met` without `purchasable_now` means "not enough points yet".
- **Capturing buildings** (oil derricks, civilian structures): infantry can't `enter` them to capture. Research the capture upgrade (`Upgrade_InfantryCaptureBuilding` at the Barracks for America), then use the capture ability (`Command_AmericaRangerCaptureBuilding`) with the building as target.
- **Selling** pays when the building has finished deconstructing; a building destroyed while being sold pays nothing.
- **`resume_construction`** tells you why it was refused: not under construction, or a dozer is already building it.
- Orders count towards the APM cap if the match uses `-scriptApiApm`; refused orders and queries don't.
