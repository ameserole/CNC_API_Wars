# Delta: Journal

## Session 1 (preparation)
- Read BOT-NOTES.md, client.py, world.py, bots/simple.py, launcher.py.
- Picked FactionChina (bot.json). Wrote delta_bot.py, a China version of simple.py with a war factory and a
  tunable settings.json.
- Started the practice game against Easy AI in the background (`generals_api.tournament practice t2 Delta`).
- Wrote run_delta.py (attaches delta_bot.run to a practice port as the controller) and settings.json
  (wave 5, interval 30 s).
- Practice port 49942: connected the bot. The bot built a power plant and barracks in the first minute.
- Practised the watch loop twice (`generals_api.watch --max-wait 45/60`): it works and shows built/army/money.
- Not yet verified: war factory placement, the first wave attack, the game's end. Next session: check
  delta_bot.log, then tune settings.json.
- Found why the factory never appeared: it needs a Supply Center (added to the build order), and the
  Redguard waves spent the money first (INSUFFICIENT_FUNDS). The bot now saves for the factory.
- Restarted the runner in the same match (superseded/reconnected cleanly). By 11:48 the War Factory stood,
  supply trucks gave about 600/min, and waves of Redguards were attacking an enemy Gattling cannon.
- Lesson: a silent `place()` failure hides the reason; check runner_out*.txt for refused builds.
