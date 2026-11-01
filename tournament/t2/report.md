# Tournament t2: report

1 November 2026, 11:27–13:27. The same four agents, models and seeding as [t1](../t1/report.md), with every match **best of 3** and the Phase 10 tools (watcher connections, `watch`, `order`, `botkit`). Tournament Desert, 45-minute game limit, no APM cap, 15 minutes of preparation, 5 minutes of iteration after each game. Workspaces started empty, as in t1.

## Result

| Match | Players (model) | Games | Series |
|---|---|---|---|
| Semifinal 1 | Bravo (sonnet) vs Charlie (fable) | G1 Charlie 25:45 · G2 Charlie 13:28 | **Charlie 2–0** |
| Semifinal 2 | Alpha (opus) vs Delta (haiku) | G3 Alpha 6:56 · G4 Alpha 6:22 | **Alpha 2–0** |
| Final | Charlie (fable) vs Alpha (opus) | G5 Alpha 13:04 · G6 Alpha 15:18 | **Alpha 2–0** |

**Champion: Alpha (opus).** The same finalists as t1, with the final reversed: Charlie (fable) won t1, Alpha won t2. Every game ended with a base destroyed; no game reached the time limit. Factions: everyone chose plain China; Charlie switched to China Tank General for game 6 (a blind pick).

| Game | Host (start 1) | Winner | Scores |
|---|---|---|---|
| 1 | Charlie | Charlie | 97,450 – 80,050 |
| 2 | Bravo | Charlie | 44,900 – 21,750 |
| 3 | Alpha | Alpha | 30,900 – 8,700 |
| 4 | Delta | Alpha | 27,000 – 5,200 |
| 5 | Charlie | Alpha | 58,600 – 37,725 |
| 6 | Alpha | Alpha | 74,175 – 49,600 |

Hosts alternated within each series, so each player had each start once per two games; the host won 3 of 6 (in t1 the host won all 3).

## How the agents played and adapted
- **Alpha (opus), champion.** Prepared a China macro bot with two supply centers (income 3,300–4,900/min) and `settings.json` tuning. Semifinal: held Delta's 3:45 Redguard rush, lowered its attack size live, and won both games in under 7 minutes. Final: its 6-tank wave died on Charlie's Gattling Cannons in game 5, so it changed the bot to bank for a second War Factory and won with a 15-tank wave; in game 6 Charlie dug in with bunkers and 20 Tank Hunters, so Alpha restarted its bot with Inferno Cannon production mid-game and burned the defenses from range. Each game's lesson went into the next game's settings.
- **Charlie (fable), runner-up.** A `botkit` bot with `strategy.py` edited live. Beat Bravo's Redguard hordes by parking under Gattling Cannons and pushing right after a wave died; won game 2 by scouting an undefended base and striking at 10:20. In the final, an untested auto-release sent its army out as Alpha's 22-unit wave arrived (game 5); its switch to Tank General with bunkers (game 6) lost to Alpha's artillery. Its game-6 lesson: static defenses lose to artillery and starve the economy.
- **Bravo (sonnet).** Redguard-heavy China; its main dock ran dry at 16:00 in game 1 and it never built a second supply center; in game 2 a one-off script connected as a second controller and replaced its bot for 3 minutes (it noted: use `order`).
- **Delta (haiku).** Fast economy but one supply center; its early infantry attacks walked into Alpha's army both games. It misread 0–1 as an eliminated series after game 3; its game-4 prompt added one factual sentence correcting that (see `state/sessions.json`).

## Staying live (Phase 10)

| | t1 (no watch) | t2 (watch loop) |
|---|---|---|
| Hand-backs during games | dozens (Charlie 27 in one game) | **0** in 10 of 12 sessions; Bravo's 2 were its final reports |
| Longest gap without a tool call | 52–186 s | **64–105 s** (all but one under 90 s) |
| Agents present until the game ended | rarely | **every session**, rolling into its iteration window without being resumed |

`watch` coverage was 30–76 % (median about 0.6). It counts only time inside a foreground `watch`; agents also spent time editing `strategy.py`/`settings.json`, writing orders and, for Alpha in game 6, running `watch` through its own wrapper script (`w.sh`), which the measure doesn't recognize. Delta acted most (11 and 19 actions, median reaction 5–8 s); Alpha acted mostly through bot restarts and settings files.

## Problems found while running t2
1. **Prompts:** the game prompt still said "lose and you are out" and "one connection per game" (fixed before game 1), and the preparation prompt still described one connection (fixed before preparation).
2. **Series numbering bug:** `snapshot` and `save-session --game` looked games up by matchup number; after game 2 they wrote to the wrong folder. Fixed (`game_folder` finds the recorded game) and the stray folder removed; unit-tested.
3. **Audit false positives:** a port inside a file Charlie *wrote* (now ignored: for writes and edits only the path counts), and Alpha editing its own old port out of a script (reviewed, not a violation).
4. **`watch` re-triggers:** "enemies near base" fired every few seconds while the same enemies stayed near an outlying building (Alpha wrote a filter). It should fire again only when the set of nearby enemies changes. Open.
5. **Early hand-backs in preparation:** all four agents stopped preparation early (2–7 minutes); each was told once that it had time left, as in t1.

## Cost
Total tokens processed per agent session (task notifications): preparation 61k–111k (about 370k), games 50k–124k (about 960k); about **1.33M** for t2. Wall time: 2 hours, preparation included.

## Files
`bracket.md`, `results.json`, `games/<n>-…/` (game.json with stats, factions, models, start positions, replay.rep, workspace snapshots), `sessions/<agent>/` (every conversation with its audit and liveness), `prep-snapshots/`, `agents/<agent>/` (final notes, journals, bots), `state/sessions.json` (session ids and orchestration notes).
