# Bot1 match report (America vs Bot2 America, Tournament Desert)

## Result
**Defeat.** `game_over` arrived with `result: "defeat"` at frame 64924, about 36 minutes of game time (05:02:26 wall clock).

## Timeline
- **Frames 0–6k.** Bot built a power plant, a supply center at the main dock (1408,2547), a barracks and a war factory, and bought the Paladin science. A bug in my code (I checked for the status flag `UNDER_CONSTRUCTION`; the API sends `under_construction`) made it build 4 power plants, wasting about $2.4k.
- **Frames 6k–10k.** Several restarts to fix bugs:
  - build jobs were dropped on timeout;
  - the second supply center was aimed at the enemy dock, because the neutral dock near me had moved from `known_structures` to `visible`;
  - infantry spending starved the war factory.

  Built the second supply center at the west dock and reached 5 Chinooks.
- **Frames 10k–26k.** Bot2 built a forward line in mid-map: Patriots at (800,1130), (868,1116) and (1220,1130), and a Fire Base at (1004,1180). It also fielded Paladins early.
  - My "defend within 900 of the CC" rule kept pulling my units into that line.
  - I had 3 war factories, a Strategy Center (Bombardment plan, Composite Armor), 2 Patriots and the A10 strike science.
  - An 8-tank wave died at the mid line.
- **About frame 34k.** Both my supply docks ran dry, and my income dropped to 0 for good. Bot2 had a Supply Drop Zone (parachute crates at its base) and harvested the mid-map piles under its Patriots. It later built a Particle Cannon.
- **Frames 36k–48k.** Tried to recover:
  - sold the airfield, power plants, a war factory and the Strategy Center;
  - researched the Ranger capture upgrade to take the oil derrick at (1764,1876);
  - sent 9 tanks to flank through the east corridor, with waypoints taken from `map()`. They reached Bot2's east base, but the defense trigger pulled part of the group back, and the rest died to Avengers and Paladins;
  - sent Chinooks to the mid-map supply piles and lost 2 to Bot2's Patriot.
- **Frame 50k to the end.** Bot2 pushed into my base with Paladins, Avengers, Tomahawks, Crusaders and the Particle Cannon. With no money and no dozers, the bot fired A10 strikes until the end.

## What went right
- The API was reliable. These all worked as documented: build, train, rally points, sciences, `upgrade`, `sell`, `dock`, `use_ability` (A10, battle plan) and `map()`.
- Events were reliable and respected fog: `construction_*`, `unit_created`, and `unit_destroyed` with `attacker_template`. The attacker was None when it was unseen.
- Placing buildings by trying a ring of spots until one wasn't `ILLEGAL_LOCATION` worked well.
- `map(cell_size=40)` terrain was enough to plan a flank route around the cliffs.

## What went wrong (strategy)
- **Economy:** I didn't plan for the docks running dry around minute 17. Bot2 invested early in a Supply Drop Zone and in holding the mid-map piles. Selling my Strategy Center removed my only path to a drop zone.
- **Restarts:** I restarted too often. Each restart lost in-memory state, which led to duplicate builds and abandoned construction.
- **Defense:** the radius was too wide and pulled units into Bot2's fortified line. The "recent attacker" rule hijacked the flanking army.
- **Attacks:** I sent small waves of 8–9 units into fortified positions.
- **Waste:** extra power plants, and an airfield I never used.

## API observations and possible bugs
1. **Locked special powers accepted:** `use_ability` returned ok for `Command_SpectreGunship`, `Command_Paradrop` and `Command_DaisyCutter` on the Command Center without the matching sciences. I owned only Paladin, StealthFighter and A10Strike1. I didn't verify whether the logic actually fired them, and I stopped using them once I noticed. This is a **possible fair-play hole** in `requireButtonAvailable` / `canDoSpecialPowerAtLocation`, which don't seem to check the science.
2. **Silent build failure:** `build` succeeds when funds are enough. If the money is spent before the dozer arrives, `construction_started` never comes and no failure event is sent.
3. **Unclear resume error:** `resume_construction` while the dozer is already building gives `NOT_AVAILABLE: that dozer cannot resume that`.
4. **Capturing the derrick:** `enter` on `TechOilDerrick` with a Ranger gives `CANNOT_ENTER: none of the units can enter that`. `Command_AmericaRangerCaptureBuilding` gives `NOT_AVAILABLE: use that is not available right now (prerequisites, power or state)` until `Upgrade_InfantryCaptureBuilding` finishes. That matches the game, but it isn't documented.
5. **Docks change lists:** a neutral `SupplyDock` leaves `known_structures` and shows up in `visible` once seen, so scripts must union both lists.
6. **No depletion info:** snapshots don't show how much supply a dock or pile has left, so a dry dock is only noticed when income stops. A depleted flag would be fair, since a human sees the pile shrink.
7. **Possible unpaid sale:** a `sell` on a war factory returned ok and the building vanished, but money stayed at 425. It may have been destroyed during the sell animation, since enemies were in my base. Unconfirmed.
8. **Stray connection:** a second copy of my bot got `connection closed (code=4001, reason='superseded')`, as documented.

## Files
- `bot.py`: the final bot.
- `bot.log`: the full log.
- `notes.md`: running notes.
- `probe*.py`, `mapdump.py`, `map.json`, `catalog.json`, `purchased.json`: probes and data.
- `*.flag`: make the one-time sales safe to repeat across restarts.
