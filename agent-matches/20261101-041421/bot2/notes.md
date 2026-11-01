# Bot2 notes (America, south base at (1005,584); enemy start (1011,2103))

## Plan
- Macro bot `bot.py` (runs in background, logs to `bot.log` / `bot.out`).
- Build order: Power -> Supply Center (dock A at (632,127)) -> Barracks -> War Factory -> Power -> Supply Center 2 (dock B at (1731,296)) -> Patriots north of base -> 2nd WF -> Strategy Center -> Airfield.
- Sciences: Paladin first, then A10 strike / Emergency repair / Spectre.
- Army: Paladins (Crusader fallback), Avengers 1 per 6 tanks, Tomahawks later; few Rangers/Missile Defenders.
- Waves: attack-move all army when >= 9 units (grows +2 per failed wave), target nearest known enemy structure.
- Defense: any visible enemy within 600 of my structures pulls the home army; A10/Spectre on enemy clusters.

## Learned
- Snapshot buildings carry `status: ['under_construction']` and `construction_percent`.
- `known_structures` lists neutral docks/supply piles from frame 3 (owner 0/1), useful for eco planning.
- Build of a structure with unmet prerequisites returns NOT_AVAILABLE "cannot be made right now (prerequisites or disabled factory)".

## Timeline / learnings (live)
- ~4:21-4:23: enemy pushed Crusaders+Missile Defenders+Rangers to mid (y~1300). My chase radius was too large; units trickled in and died. Shrunk threat radius to 420 and only y<1250.
- use_ability Command_A10ThunderboltMissileStrike returned ok at rank 1 WITHOUT the science. Engine AIGroup drops it at execution ("Nice try"), so no cheat, but the API's check misses the RequiredScience gate (button would be hidden in the UI).
- Forward firebases at y=1180 got killed with 3 dozers. Moved defenses to y~880.
- ~4:34: Home docks (632,127) and (1731,296) were exhausted around 19 min; 6 Chinooks sat idle at supply centers. Added mid supply centers + Chinook `dock` to SupplyPileSmall piles; dock sometimes NOT_AVAILABLE "none of the units can dock there" (pile empty?).
- Plan bug: 4th PLAN SupplyCenter entry re-built at dock B (wasted 2000).
- Wave of 14 into their patriots/army at y~1700 lost everything (4:40). Enemy also raided east supply center (1700,640).
- Switched to turtle: wave size 22, firebases, Particle Cannon Uplink aimed at known enemy structures (WarFactory first).
- 05:02:26 GAME OVER: victory (frame 64924). Siege mode with explicit attack orders on structures finished the base.
