# Alpha: Journal

## Session 1 (prep, 2026-11-01)
- Picked FactionChinaTankGeneral (cheap veteran BattleMasters; Battlemaster science makes them vet 2 at build).
- Wrote alpha_bot.py (polling macro bot) and debugged it live vs Easy AI: fixed prerequisite handling
  (parallel dozers), dozer over-production, added a money reserve for 2nd supply center / 2nd war factory, truck redock.
- Result: VICTORY vs Easy AI at ~7.3 game minutes; waves of 5-6 Battlemaster/Gattling tanks, no tank losses.
- Next ideas: faster early econ (2nd supply center sooner), Propaganda Center + Nationalism/autoloader late, use
  Tank Paradrop / Artillery Barrage abilities (needs use_ability with ability names from catalog), better defense vs rush.
