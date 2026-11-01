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
12:33:41 real game (game 3) start: controller on 56555 with wave 8 / 40s
12:35:00 lesson: my probe connection to 56555 superseded the bot; never open a controller client, use watch/order only

## Session 2 (game 3 vs Alpha, t2 game 1)
- Bot ran as controller. Power, barracks, supply center, war factory by 1:34; supply truck income ~900-1300/min.
- Waves of Redguards sent to attack-move at 4:00 were picked off by a big enemy group (7 Redguards lost).
  Pulled army home; enemy then had 12-18 units (Battlemasters, TankHunters, Gattling tanks) at my base.
- Lost the barracks, dozer and most units by about 6:10. Money stuck at 400, income flickers (truck stalls).
- Mistake: my own probe connection to 56555 superseded the controller (use watch/order only).
- Mistake: Redguards cost 300, so batch 2 was refused (INSUFFICIENT_FUNDS) with 400 money.
- Game over at 6:52: DEFEAT (the game-1 loss of best-of-3, so the series is 0-1). The bot's early waves
  were the mistake: they walked into Alpha's 12-18 unit attack. Held back army + batch training fixed too late.
- Next: defend-first build order, two supply trucks, second power plant, no early attack waves.
12:42:02 game 4 start: controller on 54163, defend-first settings (auto_attack false)
12:44:56 supply truck trains at ChinaSupplyCenter (not war factory); trucks built_by ChinaSupplyCenter
12:46:49 5:10 army collapsing vs 15-unit push; supply truck dead, income 0. batch set 0 to save money for a new truck (600 at supply center 152)

## Game 4 (t2 game 2 vs Alpha): DEFEAT at 6:22, series now 0-2 (eliminated)
- Build: power, barracks, supply center (1:21), war factory (~3:00). One supply truck, income ~400-800/min.
- Army of 16-20 Redguards and 4 Battlemasters at home by 4:30. Then 17 enemy units (Battlemasters, Tank Hunters,
  Gattlings, Redguards) pushed in.
- MISTAKE: at 4:54 I attack-moved the whole army out to a group of 7 at (1020,1190) and it was caught in the open
  by the 17-unit main army. Lost ~20 units in 2 minutes.
- Supply truck was killed at the enemy-side pile (1421,1190); income went to 0. Then the supply center fell.
- Sold the war factory for ~1000 cash at 5:31 to fund a new truck. The sale worked, but the supply center was already
  gone, so the truck had nowhere to train (trucks come from ChinaSupplyCenter, not the factory).
- Second power plant was refused with NOT_AVAILABLE (reason unclear, no time to chase).
