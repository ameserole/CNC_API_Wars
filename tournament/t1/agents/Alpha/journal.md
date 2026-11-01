# Alpha: Journal

## Session 1 (prep, 2026-11-01)
- Picked FactionChinaTankGeneral (cheap veteran BattleMasters; Battlemaster science makes them vet 2 at build).
- Wrote alpha_bot.py (polling macro bot) and debugged it live vs Easy AI: fixed prerequisite handling
  (parallel dozers), dozer over-production, added a money reserve for 2nd supply center / 2nd war factory, truck redock.
- Result: VICTORY vs Easy AI at ~7.3 game minutes; waves of 5-6 Battlemaster/Gattling tanks, no tank losses.
- Next ideas: faster early econ (2nd supply center sooner), Propaganda Center + Nationalism/autoloader late, use
  Tank Paradrop / Artillery Barrage abilities (needs use_ability with ability names from catalog), better defense vs rush.

## Game 2 (t1 vs Delta, live) - VICTORY (~frame 21000)
- Delta (America) rushed with ~14 Rangers + Crusader at 4.3 min; my v1 bot had only 1 tank because the 2nd-WF money
  reserve starved production. Lost all dozers and several lone tanks.
- Patched and restarted the bot live 6 times (restart is safe): threat mode, Red Guard + Gattling priority,
  rally-and-mass before engaging. Army massed, killed the rush, then 3 waves razed Delta's base.
- Lesson: never let economy reserves block army production early; mass units before engaging; Gattling vs infantry.

## Game 3 (t1 vs Charlie, live) - DEFEAT (~frame 12700, 7 game min)
- Mirror match (both China Tank General). Charlie out-produced us ~2:1: we had 1 badly placed supply center, 3 trucks.
- Our first wave of 6 died to Charlie's 7 at mid-map; Charlie's 12-tank push ended it. Live patches (dock memory,
  center next to dock, bigger/adaptive waves, retreat) came too late.
- Lesson: economy decides mirror matches; put supply centers right next to the dock and build a 2nd early; never
  attack without a clear numbers advantage.
