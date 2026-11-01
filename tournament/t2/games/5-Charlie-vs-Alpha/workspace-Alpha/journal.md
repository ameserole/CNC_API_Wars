# Alpha: Journal

## Session 1 (prep)
Read BOT-NOTES/client/world/botkit. Picked FactionChina (simple templates, strong Battlemaster/Gattling/Overlord mix).
Wrote bot.py (stateless tick macro bot + live settings.json). Practice vs Easy AI: fixed status-flag bug and
supply-dock detection (known_structures). Practiced watch loop.
Late: added 2nd supply center + economy-first pause (untested when session ended). Bot is running fine otherwise; next: verify attacks.

## Session 1, part 2 (second practice game, 11:34-11:42)
Restarted practice. Fixed: orphan bot loop on closed connection (exit on ConnectionClosed), supply-center placement
(tight radii near dock) -> 2 centers, income ~3300-4600/min. Defend uses explicit attack on structures.
Attack wave reached enemy base but did little damage to buildings: target thrashing. Fixed structure detection;
sticky targeting is the top TODO (see notes.md).
11:41: sticky targeting added -> enemy barracks died quickly. Bot is in decent shape; next: reserve money for Propaganda/2nd WF, rally before push.

## t2 game 3 (vs Delta, Bo3 game 1) - WIN
Started bot.py immediately; Delta (China) infantry rush at 3:45 was repelled by the defend logic, then a 7-tank wave
(attack_size lowered to 6 live) destroyed their whole base by ~7:00. Economy edge (2 supply centers vs 1) decided it.

## t2 game 4 (vs Delta, Bo3 game 2) - WIN, series 2-0
Started bot.py at once; no intervention needed. Spawned south. First wave (6 tanks + infantry) at ~4:15 beat Delta's
defending 9 RG + 4 BM and razed the base by 6:22. Lesson: 2-center economy + early 6-tank wave keeps beating Delta.

## t2 game 5 (vs Charlie, final Bo3 game 1) - WIN at 13:04
First 6-tank wave bounced off Charlie's 3 Gattling Cannons. Retreated, added money reserve for Propaganda + 2nd WF,
massed 15 tanks and won at 13:04. Lesson: vs a turtling China, mass 12+ tanks from 2 factories before attacking.
