# Charlie: Journal

## Session 1 (prep, 2026-11-01, 15 min)
- Read BOT-NOTES.md, client.py, world.py, simple.py. Chose FactionChinaTankGeneral (cheap, robust tanks).
- Probed the practice game's initial state (probe.py): 1 dozer, CC, 10000 cash, no visible supply docks at start.
- Wrote macro_bot.py (dozer#2, power -> supply center -> war factory -> Battlemaster/Gattling spam, sciences,
  attack at 8 tanks, explicit attacks on known enemy structures) and ran it against the Easy AI practice game.
- Fixed 3 bugs live (World.money property, prerequisites while under construction, missing kwarg) and tuned the
  economy (no early reserve, Gattling Cannon later, 2nd war factory at 2200 money with 5 BMs).
- Result by 08:21 (game ~7 min): 8 tanks reached the enemy base and started killing structures; economy stable
  at ~1500-1800 with 3 trucks and one war factory (production was the bottleneck, hence the 2nd WF tweak).
- Next: watch a full game to the end, scout early, use general's powers, consider ATTACK_SIZE 6.
- PRACTICE RESULT: VICTORY vs Easy Laser General at frame ~16500 (~9:10 game time), 8 BM + 3 Gattling tanks,
  2 supply centers, 5 trucks, 1 war factory. Everything is in macro_bot.py; run it as described in notes.md.
