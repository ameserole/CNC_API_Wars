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

## Session 2: tournament t1, game 1 vs Bravo (2026-11-01, live)
- Started macro_bot.py (practice version) at 08:25; power 08:25:55, SC 08:26:18, WF done 08:26:40 (frame 3720).
- Added v2 during the game: general's powers from the CC, 3rd WF/power/SC late-game rules, clean exit on 4001.
- 08:29: first wave (4 BM + 4 Gattling) hit Bravo's base and met 8 Battlemasters (Bravo = China Tank General too).
  Lost the wave, killed 3 BMs. Added a retreat rule, BM-heavy mix, ATTACK_SIZE 12 (v4/v5).
- 08:32 (frame ~13800, 7:40 game time): 7 BM + 2 Gattling, 2 war factories, 1 SC, 4 trucks, money 2100 and rising.
  Bot v7 (macro_bot.py) runs on alone: 2nd SC at the guessed east dock at 8 tanks, attack at 12 tanks with retreat.
  Session handed back while the game was still running (harness required the report); the bot keeps playing.
- Lesson: never attack into an unscouted base with Gattlings; vs a mirror the first wave must be BM-heavy and larger.
- 08:35:27 **GAME OVER: victory** (10.24 game minutes). Stats: 36 units built, 14 destroyed, 9 lost, 6 buildings,
  4 destroyed, 22800 earned; Bravo 14 units, 3300 earned. Second wave of 12 BM + 3 Gattling with Artillery
  Barrage and Emergency Repair crushed the base. Report in reports/game-1.json. Next: final (Alpha or Delta).
- Decision: keep bot.json FactionChinaTankGeneral and macro_bot.py v7 for the final.
