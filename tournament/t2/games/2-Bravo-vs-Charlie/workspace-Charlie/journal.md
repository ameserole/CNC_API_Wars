# Charlie: Journal

## Session 1 (prep, 2026-11-01)
Read BOT-NOTES, client.py, simple.py. Picked China (sturdy tanks, simple macro). Wrote bot.py (botkit loop) +
strategy.py (build order, trucks, tank production, attack/defend) + settings.json. Ran it against the Easy AI
practice game on Tournament Desert; see notes.md for what was learned.
Practice result: base up by 3:00, income by 5:40; the army phase was not reached within the session. Next session: verify tank
production/attack logic in a practice game, add Nationalism/Uranium Shells, tune `attack_size` and `reserve`.
Extended to 11:52 by the organizer: saw the army phase. Defend vs Humvees/Rangers works, attacked the forward Patriot Battery
(after fixing NOT_VISIBLE on fogged structures and the defend/clear interruption). Did not reach the 8-tank attack wave; economy
was the limit. Next: two supply centers early, keep a Gattling with trucks, then test the attack wave in a practice game.

## t2 Game 1 (2026-11-01) vs Bravo - WIN (China vs China), 25:45, score 97450
Redguard hordes hit from 3:23. Lost my first two armies chasing raiders into mid-map; fixed defend (radius 330, clamp 380 from
home, regroup), added 3 Gattling Cannons + save-for-build logic; cannons farmed the hordes (score lead). Second Supply Center at the
mid-map piles at 19:30 when the dock ran dry. Released the 16-tank army at 21:30 right after a 32-Redguard wave died; killed their
forward SC/WF then rolled the main base; CC dead ~25:00 -> victory. Series 1-0. Settings defaults for game 2 updated.

## t2 Game 2 (2026-11-01) vs Bravo - WIN (China vs China), 13:28, score 44900. Series 2-0, advance.
North start. Build order ran clean (3 cannons + 2 WF by 4:36). Bravo never attacked; it turtled 26 Redguards at home. Added an
"exclude" setting and scouted with one Gattling tank; saw no defenses at 10:19 and released 22 tanks -> horde died, base cleared
structure by structure, CC dead 13:28. Lost 2 tanks. settings.json reset to hold=true for the next game.
