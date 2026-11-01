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
