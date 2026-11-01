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

## Session 3: tournament t1, game 3 (final) vs Alpha (2026-11-01, live)
- 08:50:26 started macro_bot.py (v8: gattling ratio by enemy side) on port 56706. Alpha = ChinaTankGeneral (mirror again).
  South start again (home 1010,2102), so the dock2 guess (1435,2376) applies. Power plant started frame ~430, dozer #2 ok.
- Logs: g3_stdout.txt / g3_stderr.txt (and bot_log.txt, append). Session handed back early again by the harness;
  the bot plays on alone with the game-1 settings (ATTACK_SIZE 12, retreat rule, CC powers).
- TODO after the game: write reports lesson, check RETREAT lines (never exercised yet), consider early truck snipe.
- 08:54: found 3 Gattlings vs 5 BMs (ratio check ignored queued tanks, so two Gattlings got ordered back to back).
  Patched macro_bot.py (v9: `queued()` counts orders of the last 16 s in the ratio), saved v8 as macro_bot_v8.py,
  restarted the bot at 08:54:30 (log g3b_stdout.txt); old process exited on 4001. First contact: 4 enemy BMs near
  my rally point at frame ~7400; lost 1 Gattling; EmergencyRepair1 bought at frame 7861.
- 08:56:00 frame 10500: 10 BM + 2 Gattling = ATTACK_SIZE 12 -> attack. Reached Alpha's base ~6:00 game time, no
  enemy army there (Alpha had sent 4 BMs + Red Guards to probe me earlier and lost them). 2nd WF 6:18-6:38,
  ArtilleryBarrage1 at 08:57:09 and fired at once, Emergency Repair used. Structures fell 6 -> 5 -> 3 -> 1.
- 08:57:48 **GAME OVER: victory vs Alpha** at ~7:15 game time (frame ~13050). Army at the end 11 BM + 2 Gattling,
  7 trucks, 2 SC, 2 WF. Only 2 Gattlings lost in the whole game. Tournament t1 won (games 1 and 3).
- Official report reports/game-3.json: win, 7.28 game minutes. Charlie 25 units built, 22 destroyed, 1 lost,
  6 buildings destroyed, 14700 earned, score 20600. Alpha 27 units built, 22 lost, 1 destroyed, 11100 earned,
  score 14500. Alpha's economy was actually decent (11100 earned); they lost by throwing 22 units at my rally group
  piecemeal. **Tournament t1 won.**
