# Charlie: Notes

## Faction
**FactionChinaTankGeneral** (side `ChinaTankGeneral`, templates prefixed `Tank_`). Reason: cheap tanks (Battlemaster 700,
Gattling 700), tanks are robust against scripted opponents, simple build order with few dependencies.

## Start of a game (Tournament Desert, observed)
- 10000 cash, 1 science point, 1 dozer (`Tank_ChinaVehicleDozer`, id ~144) and the Command Center.
- Map extent 2040x2700. Start positions (1004,583) and (1010,2102); I was at the north one. The enemy start is the
  farther `game_info["start_positions"]` entry.
- No supply docks in `visible` at frame 428 (docks must be out of the CC's sight); the bot falls back to placing the
  Supply Center near the CC and then looks for `supply` objects in `visible`.

## Build order (macro_bot.py)
1. Dozer #2 from CC (1000) as soon as possible.
2. Power Plant (1000, 20s) -> Supply Center (1500, needs power; place ~230 from a dock toward home) -> War Factory
   (2000, needs supply center).
3. Supply trucks to 2 per supply center +1 (600 each). War Factory: Battlemasters, 1 Gattling per 3 BM.
4. Later: second supply center at another dock, second power, second war factory (>3500), Gattling Cannon toward the
   enemy, Propaganda Center (AutoLoader 2500, Nationalism 2000), Emperors when rich.
5. Sciences in priority: BattlemasterTraining, EmergencyRepair1, ArtilleryBarrage1, TankParadrop1, Frenzy1 ...
6. Army: attack when >= 8 tanks; `attack` explicit enemy structures (`World.enemy_structures()`), attack_move
   when not possible; defend when enemies within 550 of home.

## Key prerequisites (catalog)
- SupplyCenter <- PowerPlant; WarFactory <- SupplyCenter; Airfield <- SupplyCenter; PropagandaCenter <- WarFactory;
  GattlingCannon <- PowerPlant; Bunker <- Barracks; InternetCenter <- WarFactory; Nuke <- PropagandaCenter.
- Emperor / ECM need WarFactory + PropagandaCenter. Hacker, Black Lotus need Barracks + PropagandaCenter.

## API lessons
- Status flags are lists: `"idle" in u["status"]`, `"under_construction" in status`.
- `client.catalog()["sciences"]` entries: name, cost, prerequisites_met, purchasable_now.
- `game_info()["players"]`: index, relation ("self"/"enemy"), side, type. `local_player` index.
- Snapshot `self`: money, power {consumed, produced}, rank, science_points.
- Build placement: try ring of spots, skip `ILLEGAL_LOCATION`; wait for `construction_started` event (has `id`),
  then `construction_complete` with that id.
- Probe script `probe.py` connects and disconnects quickly. Never run it while macro_bot.py runs (supersedes it).

## Running in a real game
```
C:\Users\user\Documents\CNC_Generals_AI\python\.venv\Scripts\python.exe C:\Users\user\Documents\CNC_Generals_AI\tournament\t1\agents\Charlie\macro_bot.py ws://127.0.0.1:PORT
```
Run in background; it logs to `bot_log.txt` in this folder (append). Check with `tail bot_log.txt`.

## Lessons from practice game 1 (fixed in macro_bot.py)
- `World.money` and `World.power` are properties, not methods.
- A structure under construction does NOT satisfy prerequisites: `build` returns `NOT_AVAILABLE` ("prerequisites or
  disabled factory") until the Power Plant finishes. Check `under_construction` not in status before depending on it.
- Dozer #2 (1000) from the CC arrives in ~10s; the bot's idle-dozer check uses `"idle" in status`.
- Timeline: power plant placed at frame ~430, done at frame ~4400 (about 20s game time + dozer walk).
- Supply Center comes with 2 free supply trucks; income flows even with the SC placed ~230 from the CC and no dock
  in sight at placement time (trucks find the docks themselves). Money rose ~300 per 15s with 3 trucks early on.
- Timeline achieved (practice 1): power done 08:16:20, SC started 08:16:22, WF started 08:16:46, WF done 08:17:08
  (~frame 5700 = 3:10 game time), first Battlemaster ~frame 7000.
- Mistake fixed: a 1500 money reserve for a 2nd supply center starved tank production; now only reserved once
  6 tanks exist. Gattling Cannon (1200) was built too early; now needs 3000 money and 4 Battlemasters.
- Do not start more than one bot process against the same port: stop the old one (its loops keep logging errors).

## Ideas for next sessions
- Scout the enemy with the first Gattling tank so `enemy_structures()` gets filled early.
- Use Battlemaster `SCIENCE_TankParadrop1` / `ArtilleryBarrage` powers from the CC (`use_ability` with pos) on
  the enemy base once purchasable.
- Consider ATTACK_SIZE 6 against scripted opponents that may be slow; keep reinforcing.
- Per-opponent faction picks (`"vs"` in bot.json) once I know what Alpha/Bravo/Delta play.
- Practice result: at frame ~11500 (6:25 game time) 8 tanks reached the enemy (Laser General Easy AI) base and
  destroyed structures; `enemy_structs` only fills once tanks see the base (no early scouting yet).
- One war factory is the bottleneck at ~1500+ money: the bot now builds a 2nd WF at 2200 money once 5 BMs exist.
- Build tasks run after training in the same macro step, so tanks ate the money for the 2nd war factory
  (`INSUFFICIENT_FUNDS ... 700 for orders still on their way`). Fix: reserve 2000 for the WF once 5 BMs exist.
- 2nd supply center was placed at a second dock (1435,2376) automatically once docks became visible; trucks 5.
- Sciences bought in practice: BattlemasterTraining (start), EmergencyRepair1 (~frame 13800), ArtilleryBarrage1
  (~frame 15100). Rank points come fast while fighting; the CC's ArtilleryBarrage is not used yet (TODO).
- **Practice 1: VICTORY** vs Easy AI (Laser General) at ~9:10 game time with the current macro_bot.py.

## Game 1 of tournament t1 (vs Bravo) - live notes
- Bravo played **FactionChinaTankGeneral too** (mirror): 8 Battlemasters + Barracks + 3 trucks by frame ~7600 (4:15).
- My first wave (4 BM + 4 Gattling at ATTACK_SIZE 8) walked into their 8 BMs at home and died (killed 3 BMs).
  Gattlings are useless against tanks: now 1 Gattling per 4 BM, ATTACK_SIZE 12, and a retreat rule
  (enemy combat weight within 450 of my army > 1.1x mine and army > 600 from home -> move home for 40 s).
- `Stop-Process` on my own old bot process was denied by the harness: bots must exit on their own. macro_bot.py
  now exits (`os._exit(0)`) when its connection is superseded (close 4001). Old v1 processes without this keep
  logging stale `frame=NNNN` status lines and `ConnectionClosed` errors; filter them out when reading the log.
- Catalog ability names (CC): Command_ArtilleryBarrage, Tank_Command_TankParadrop, Early_Command_EmergencyRepair,
  Command_Frenzy, Command_ClusterMines, Command_EMPPulse, Command_ChinaCarpetBomb (each needs its science).
- **RESULT game 1: VICTORY vs Bravo (mirror China Tank General) at 10:14 game time.** Score 28800 vs 6100.
  Bravo earned only 3300 total: my first (lost) wave killed their 3 supply trucks, which crippled them; they
  never attacked me. The second wave (12 BM + 3 Gattling at frame ~16400) destroyed the base in ~1.5 minutes
  with Artillery Barrage + Emergency Repair from the CC (the powers work: `POWER ...` lines in the log).
- Working timeline (v7): WF done frame 3720, 2nd WF ~frame 12400, 2nd SC frame ~14200 at guessed dock (1435,2376),
  EmergencyRepair1 science ~frame 15500, ArtilleryBarrage1 ~frame 16000, 12 tanks at frame 17300 (9:35).
- For the final: keep FactionChinaTankGeneral and macro_bot.py v7. Possible tweaks if the opponent is not a mirror:
  vs GLA (infantry/rocket buggies) more Gattlings are fine (1 per 3 BM); vs USA air, Gattlings matter too.
  Keep ATTACK_SIZE 12; the retreat rule has not been exercised in a real fight yet (no RETREAT lines logged).
- Early truck snipe is strong: the enemy's trucks were at their dock when my wave arrived. Consider sending
  the first 4 BMs to the enemy dock (dock2_guess mirrored, or the SupplyDock nearest the enemy start) rather
  than their base, if the enemy has no army visible.
- v8 (after game 1): Gattling ratio depends on the enemy side from `game_info["players"]` (1 per 4 BM vs China,
  1 per 3 otherwise). Not yet tested in a game; the change is tiny and syntax-checked.
