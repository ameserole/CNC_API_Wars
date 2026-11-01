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
