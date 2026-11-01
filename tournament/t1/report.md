# Tournament t1: report

1 November 2026, 07:59–09:00. Four live AI agents, single elimination, best of one, Tournament Desert, 45-minute game limit, no APM cap, 15 minutes of preparation and 5 minutes of iteration after each game.

## Result

| Game | Round | Players (model, faction) | Winner | How | Game time | Score |
|---|---|---|---|---|---|---|
| 1 | Semifinal | Bravo (sonnet, China Tank General) vs Charlie (fable, China Tank General) | **Charlie** | destroyed the opponent | 10:14 | 28,800 – 6,100 |
| 2 | Semifinal | Alpha (opus, China Tank General) vs Delta (haiku, America) | **Alpha** | destroyed the opponent | 11:43 | 36,900 – 21,700 |
| 3 | Final | Charlie (fable) vs Alpha (opus), both China Tank General | **Charlie** | destroyed the opponent | 7:17 | 20,600 – 14,500 |

**Champion: Charlie (fable).** No game reached the time limit, so the score tiebreak was never needed.

## How each agent played

- **Charlie (fable): champion.**
  - It prepared a macro bot and beat the Easy AI in practice in about 9 minutes.
  - **Game 1:** it lost a first Gattling-heavy wave, but that wave killed Bravo's supply trucks. Bravo earned only 3,300 in the whole game. Charlie hot-patched its bot 6 times and finished Bravo with a 12-tank Battlemaster wave backed by Artillery Barrage.
  - **Final:** it started the same bot within seconds, built a second supply center 3 minutes earlier than in game 1, and destroyed Alpha's base at 6–7 minutes, losing one unit all game.
  - Its notes grew to 116 lines with a 48-line journal, and it kept versioned bots (v1, v8, v9).
- **Alpha (opus): runner-up.**
  - Its practice bot beat the Easy AI in 7.3 minutes.
  - **Semifinal:** it survived Delta's early Ranger rush. Money set aside for a second War Factory had stalled its tank production for 4 minutes. It patched in a "threat mode" and then won with three waves.
  - **Final:** it lost the economy race to Charlie. It had one supply center 460 units from its dock, so every truck trip was long, and it never had more than 6 tanks against Charlie's 12. It wrote the fixes into notes and a new bot version afterwards.
- **Bravo (sonnet): out in the semifinal.**
  - It wrote a tank-rush bot but never got supply income going: 3,300 earned against Charlie's 22,800.
  - Two of its scripts ran at once and kept replacing each other's connection.
  - It used the least of its time in every session.
- **Delta (haiku): out in the semifinal.**
  - It was the only agent to pick America, because the reference bot's America templates were known to work.
  - It first ended its preparation after 90 seconds and resumed when told it had time left.
  - **Semifinal:** its early Ranger rush nearly broke Alpha. Then its attack waves trickled in unmerged on a single Chinook's income.

## API and harness findings
1. **Agents can't stay "live" for a whole game.** The subagent harness ends an agent's turn while its background bot keeps playing. All four agents handed back mid-game, some every 10–20 seconds with status updates. Their bots played on, and the orchestrator resumed each agent for its 5-minute window at the end. In practice a game is played by the agent's script plus bursts of live patching. That worked well, and Charlie's mid-game patches mattered, but it is not continuous live play.
2. **Start positions are not random.** The host got start 2 in all three games, and the host won all three. The runner picks the host randomly, but LAN start positions follow the slot order. The next tournament should assign start positions explicitly by the seed, or swap the host, before claiming fair positions.
3. **Debug assertion dialogs** blocked the first practice games until the runner passed `-ignoreAsserts` (Phase 9, Finding 3).
4. **Audit:**
   - Every session is clean.
   - Delta read its own practice state file (`state/practice-Delta.json`) and `state/sessions.json` for its port. That breaks the "nothing outside your workspace" rule, but the files are harmless, and Delta disclosed it itself. The runner now records practice ports, so agents never need to look.
   - The audit checks only other agents' workspaces, other ports and process kills, so reads of shared tournament files like these aren't flagged.
5. **API feedback from the agents:**
   - Template names must be the full prefixed ones (`Tank_ChinaWarFactory`).
   - A War Factory needs a *finished* Supply Center.
   - A Supply Center can't be placed in the shroud.
   - `known_structures` entries have `owner` but no `relation`: neutral docks are owner 0, and Bravo attacked one. A `relation` field would help.
   - Stopping one's own old bot with `Stop-Process` was blocked by the tool sandbox; a superseded bot should exit by itself on close 4001.

## Cost
Output tokens per session (from the transcripts): preparation 11k–61k each (180k in total), games 12k–74k each (246k in total). The harness also reported total tokens processed per agent session: about 50k–120k each, about 0.87M across the 10 sessions. Wall time: about 1 hour for the whole tournament, preparation included.

## Files
- `bracket.md`, `results.json`
- `games/<n>-<a>-vs-<b>/`: `game.json` (stats, factions, models, start positions), `replay.rep`, and workspace snapshots
- `sessions/<agent>/`: every conversation and its audit
- `prep-snapshots/`: the workspaces after preparation
- `agents/<agent>/`: the final workspaces (notes, journals, bots)
