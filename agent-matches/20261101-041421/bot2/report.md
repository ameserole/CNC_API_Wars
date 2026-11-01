# Bot2 report: Tournament Desert, America vs America (Bot1)

## Result
**Victory.** The `game_over` event arrived with `result: "victory"` at logic frame 64924 (about 36 min of game time). The last kill was an enemy power plant, after my army had destroyed both enemy supply centers inside their base.

## Timeline
- 0:40: Power Plant, 2 Dozers, SCIENCE_PaladinTank. Started the macro bot `bot.py` (polls `state()` every 2 s, logs to bot.out/bot.log).
- 2-5 min: Supply Center, Barracks, War Factory, second Supply Center, Patriots, second War Factory, Strategy Center.
- 5-9 min: Bot1 pushed Crusaders, Missile Defenders and Rangers to the middle. My defense chased them with a few units at a time and lost them. I made the defend radius smaller.
- 9-13 min: a 9-unit wave died to forward enemy Patriots. Fire Bases built too far forward died with all 3 Dozers.
- ~19 min: both home docks ran dry and the Chinooks went idle. Added mid-map Supply Centers, `dock` orders to mid-map piles and a Supply Drop Zone. A 14-unit wave died, and Bot1 raided my east Supply Center.
- Switched to turtling: waves of 22+, Fire Bases, a Particle Cannon Uplink.
- ~25 min: a 22-unit wave won in the middle and killed 4 enemy Patriots and Barracks. A 34-unit wave reached the enemy base, and the Particle Cannon hit a War Factory.
- ~33 min: the army idled in the enemy base, because attack-move doesn't target plain buildings. I added a siege mode that sends explicit `attack` orders at visible enemy structures.
- ~36 min: killed the Supply Centers and power plants. Victory.

## What went right
- One big Paladin, Tomahawk and Avenger blob beat Bot1's army once I stopped trickling units in.
- Patriots and Fire Bases held off Bot1's mid-game pushes.
- Explicit `attack` orders on structures finished the base quickly.

## What went wrong
- Early trickle attacks and chasing cost about 25 units.
- I noticed the empty docks late.
- A plan bug built a 4th Supply Center at an empty dock, wasting 2000. I also built too many Power Plants, and never bought upgrades.
- Placement sorted toward the enemy put Fire Bases too far forward.
- I restarted the bot about 10 times, which lost its in-memory state each time.

## API problems and observations
1. **`use_ability` ignores RequiredScience.** `Command_A10ThunderboltMissileStrike` was accepted (reply ok) at rank 1 without the A10 science, and `Command_SpectreGunship` without the Spectre science. The engine drops the message at execution (AIGroup.cpp, "Nice try"), so it is not an exploit, but the API should return NOT_AVAILABLE.
2. **`known_structures` dropped every enemy building** around frame 55000, including the CC, War Factories and Strategy Center, while they still existed. I had to keep my own memory of enemy structures.
3. **`dock` on a SupplyPileSmall** sometimes returned NOT_AVAILABLE "none of the units can dock there", apparently for empty piles. A script has no way to see a supply source's remaining amount or a harvester's idle state: idle Chinooks show `status: []`.
4. **`enemy_destroyed` and `unit_destroyed` fire for projectiles and effects:** MissileDefenderMissile, PointDefenseLaserBeam, GenericDebris, hulks, CargoPlane and CrateParachute. This is very noisy.
5. **Visible enemy objects have `health: None`.**
6. **A new connection supersedes the bot** (close 4001 "superseded"), as documented. Probing state kills the running bot.
7. **Build errors were clear:** NOT_AVAILABLE "cannot be made right now (prerequisites or disabled factory)", and "build that is not available right now (prerequisites, power or state)".
8. **Attack-move doesn't auto-target non-defensive buildings.** This is engine behavior, but worth documenting.

## Files
bot.py (final bot), bot.out/bot.log (full log), notes.md, probe scripts (probe.py, p2-p5.py, quick.py), catalog.json, map.json, state.json.
