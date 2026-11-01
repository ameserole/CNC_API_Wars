# Delta: Notes

## Faction
- Picked FactionAmerica (bot.json). Reason: the reference bot's America templates are known good; simple catalog.

## Templates (America, verified in catalog/probe)
- Dozer: AmericaVehicleDozer. HQ: AmericaCommandCenter (start, 5000 hp).
- Buildings: AmericaPowerPlant, AmericaBarracks, AmericaWarFactory, AmericaSupplyCenter, AmericaStrategyCenter, AmericaSupplyDropZone.
- Units: AmericaInfantryRanger (barracks), AmericaTankCrusader (war factory), AmericaVehicleDozer.
- Start: 10000 money, 2 start positions on Tournament Desert (ours ~1004,583; enemy ~1010,2102).

## API lessons
- The practice game port is in tournament/t1/state/practice-Delta.json (only while the game runs).
- Background `python ... &` from a Bash task dies with the task: the practice game itself stayed alive (pid in state file), but the log was lost. Use run_in_background for the bot.
- `world.load(client)` works; `world.attach(client)` keeps money/units current via events.

## Plan
- macro.py: power, barracks, war factory, supply center; then loop: train 5 Rangers + 2 Crusaders, attack-move the army at the enemy start every 30s.
- Untested at time of writing (see journal).

## Open issues (end of session 1)
- macro.py: no construction progress seen after 2 min. Add periodic logging of own buildings and their status before relying on it.
- Verify that `build` returns a reply with `construction_started` for the power plant (the event may need a different template match; place() matches `endswith(template)`).

## Corrections (session 1, restart)
- Build works: in run 1 the power plant was built (log at 08:14:13, "built AmericaPowerPlant"). My earlier "no build" note was wrong: I checked too early, while the build was still in progress. Building takes well over 1 minute.
- AmericaBarracks placement refused with ILLEGAL_LOCATION at the first spot (ring at radius 250 from HQ). place() then tries the next spot.
- Our start was (1004,583) in run 1 and (1010,2102) in run 2: the start side is not fixed. Compute home from the HQ position each game (macro.py does).
- A closed game ends the bot with ConnectionClosed (code 1006); the bot's log then shows CRASH. Expected, not a bug.
- AmericaWarFactory: NOT_AVAILABLE until a Supply Center exists (prerequisite). Build the supply center first.
- Barracks spot: objects_in_the_way at the first spot; place() moves on to the next spot automatically.

## Working macro (macro.py, verified in practice, session 1)
- Build order that works: AmericaPowerPlant -> AmericaBarracks -> AmericaSupplyCenter -> AmericaWarFactory (about 25 s each; the factory waits for the supply center).
- Placement: first ring spot is often `objects_in_the_way`; place() tries the next one (works).
- Waves: 5 Rangers at the barracks and 2 Crusaders at the factory every ~30 s, attack-moved at the enemy start. Waves of 16-17 units by 08:19.
- Money: starting 10000 is spent in about 3 minutes. Afterwards the bot stalls on INSUFFICIENT_FUNDS. Income needs a Chinook (AmericaVehicleChinook appears from the supply center's harvester) and more supply. Not solved yet.
- `--resume` reuses existing buildings (power, barracks, supply, factory) after a restart.

## Game 2 (tournament t1, live vs Alpha = ChinaTankGeneral) - result: game_over 08:48:40, official result pending in reports\game-2.json
What the log shows (reports/macro2.log, bot scripts/macro2.py):
- Build order done by 08:40: power 152, barracks 158, supply center 160 (at home), war factory 169. Chinook harvesting from the dock.
- Waves of Rangers (5 per 25 s) and Crusaders (2 per 25 s) were attack-moved at Alpha's start from 08:40:30 with 8-20 units each time. The army trickled in, never grew into one force, and was spent in small groups.
- Money: 10000 start, down to ~700 by 08:41, bounced 700-2400 from one Chinook. Second power plant never built (code path disabled by mistake).
- By 08:48:37 only the supply center and a Chinook were left; at 08:48:47 units and buildings were empty and money was 0. The base collapsed in about 2 minutes once Alpha's army came back.
- Lessons: (1) never send a small army into the enemy base; hold at home until ~15+ units, then go as one group; (2) keep a home defence (defensive structure or the army at home) while the army is away; (3) build a second power plant and a second income source early; (4) use explicit attack orders on enemy structures (attack-move ignores plain buildings); (5) the dock at (633,127) is shrouded at start: scout first or build the supply center at home.
- Alpha's army composition was not recorded; check the report for what they fielded.
