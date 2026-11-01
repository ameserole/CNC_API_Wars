# Bravo: Notes
Faction: FactionChinaTankGeneral (bot.json). Plan: macro.py = power -> supply center (+2 trucks) -> barracks -> war factory -> mass BattleMasters, attack-move at 8+ tanks toward farthest start position.
Run: .venv python macro.py ws://127.0.0.1:PORT [logfile]  (from workspace; background it).
## API lessons
- Use FULL template names with prefix: Tank_ChinaPowerPlant, Tank_ChinaSupplyCenter, Tank_ChinaBarracks, Tank_ChinaWarFactory, Tank_ChinaTankBattleMaster, Tank_ChinaVehicleSupplyTruck, Tank_ChinaVehicleDozer. Suffix names give NOT_AVAILABLE.
- Costs: power 1000, supply 1500, barracks 500, WF 2000, battlemaster 700. Build order worked from start (~70s to WF).
- Needs: attack_move doesn't hit buildings; send explicit attack on enemy_structures at the end (TODO in macro.py). No defense/repair/upgrades yet.
- Practice launcher can fail on assertion; just restart it.
- known_structures targeting added untested (check relation field names). Economy: only 1 supply center; INSUFFICIENT_FUNDS constant -> add 2nd center/more trucks next time. 13 tanks by 5min.
