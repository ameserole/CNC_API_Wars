# Bravo: Notes
Faction: FactionChinaTankGeneral (bot.json). Plan: macro.py = power -> supply center (+2 trucks) -> barracks -> war factory -> mass BattleMasters, attack-move at 8+ tanks toward farthest start position.
Run: .venv python macro.py ws://127.0.0.1:PORT [logfile]  (from workspace; background it).
## API lessons
- Use FULL template names with prefix: Tank_ChinaPowerPlant, Tank_ChinaSupplyCenter, Tank_ChinaBarracks, Tank_ChinaWarFactory, Tank_ChinaTankBattleMaster, Tank_ChinaVehicleSupplyTruck, Tank_ChinaVehicleDozer. Suffix names give NOT_AVAILABLE.
- Costs: power 1000, supply 1500, barracks 500, WF 2000, battlemaster 700. Build order worked from start (~70s to WF).
- Needs: attack_move doesn't hit buildings; send explicit attack on enemy_structures at the end (TODO in macro.py). No defense/repair/upgrades yet.
- Practice launcher can fail on assertion; just restart it.
- known_structures targeting added untested (check relation field names). Economy: only 1 supply center; INSUFFICIENT_FUNDS constant -> add 2nd center/more trucks next time. 13 tanks by 5min.
## Game 1 vs Charlie (lost/collapsing at ~9 min)
- macro.py ran fine through WF; economy died: only 2 trucks never built (INSUFFICIENT_FUNDS constantly, money None in state), tanks stalled at 6-8 and trickled into enemy, then WF/barracks lost, no defense.
- known_structures entries have keys: id,last_seen_frame,owner,pos,template,visible (no relation). owner 0 = neutral.
- Do NOT launch scripts twice (each new connection supersedes the old; I accidentally had two). No pkill (denied).
- TODO: build trucks BEFORE barracks, 2nd supply center, keep tanks home until 12+ and attack as one blob, defend base (keep a few tanks home), repair.
- FINAL game 1: LOSS at 10.2 min vs Charlie (also Tank General mirror). Money earned: Charlie 22800 vs me 3300 -> my supply trucks never worked/built. Charlie built 36 units vs my 14. Fix economy (trucks, 2nd center, verify income) above everything else.
