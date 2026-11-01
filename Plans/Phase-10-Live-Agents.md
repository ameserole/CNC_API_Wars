# Phase 10 — Agents That Stay Live for the Whole Game

Parent plan: [PLAN-script-api.md](../PLAN-script-api.md) · Previous: [Phase 9](Phase-9-Bot-Tournament.md)
Status: **Done**

## Goal
In a tournament game, the agent stays engaged from start to `game_over`:
- it notices what changes in the match (an attack on its base, a lost army, a dry supply dock, the enemy's tech), within seconds, without polling blindly;
- it reacts without killing its own bot: changes orders, composition or plan while its script keeps playing;
- it rolls straight into its 5-minute iteration window when the game ends, without the orchestrator resuming it.

## What happened in tournament t1 (evidence from the transcripts)
| Session | Assistant messages | Ended a turn (no tool call) | Hand-backs |
|---|---|---|---|
| Charlie, game 1 / final | 89 / 90 | 44 / 47 | most of the 64 in total |
| Alpha, semifinal / final | 69 / 59 | 29 / 22 | |
| Delta, semifinal | 154 | 116 | |
| Bravo, semifinal | 29 | 11 | |

- **Waiting was the problem, not the harness.** Every agent tried to wait with `sleep N; tail bot.log` and was refused ("Blocked: sleep 60 … use Monitor"). They then used Monitor (26 times) on their own log files. A Monitor event wakes a subagent, it reacts, its turn ends, and it must hand back, so each wake produced a status report to the orchestrator. Charlie's 10–20 s reports were this loop working; Bravo and Delta let their watchers lapse and went quiet.
- **Reacting meant restarting.** With one connection per game, any change to orders meant stopping the bot and starting a new version (Charlie restarted 6 times in game 1; Alpha 6 times in its semifinal). Agents could not stop their old process (Stop-Process was refused by the tool sandbox), so old bots died only when superseded.
- **The agents' only window on the game was their own bot's log**, with whatever it happened to print. No common, compact "what changed" view existed.

## Design

### 1. Watcher connections (engine / server)
A player instance accepts **one controller and up to 3 watchers** (Finding 6).
- The role is part of the URL: `ws://127.0.0.1:PORT/` (or any other path) is a controller, `ws://127.0.0.1:PORT/watch` a watcher (Finding 3: the server replaces the controller when the socket opens, before any message arrives, so `hello` is too late). `hello` reports the role. A controller keeps today's rule (a new controller supersedes the old one, close 4001). A new controller never closes watchers; watchers never supersede anyone.
- A watcher gets every query (`state`, `player_stats`, `game_info`, `catalog`, `map`, `template_info`, `faction_catalog`) and every event, with its own snapshot interval. It may also send **orders**: they are the same player's orders under the same checks and APM cap, so this gives no extra power; it only lets an agent act without stopping its bot. `command_executed` goes to the connection that sent the order.
- Watchers can't run session or lifecycle commands (`start_skirmish`, `quit_game`, `exit`, `save_replay`, `lan_*`, `surrender`, `set_input_mode`, `debug_*`): `WRONG_ROLE`.
- Game-independent pieces in `core_scriptapi`: connection registry with roles, event fan-out, per-connection snapshot timers and command trackers, the role check in the router.

### 2. `watch`: one blocking call that returns when something matters
`python -m generals_api.watch ws://127.0.0.1:PORT [--max-wait 60] [--state FILE]` connects as a watcher (adding `/watch` itself), blocks, and returns **at the first trigger or after `--max-wait` seconds**, printing a compact digest (about 30 lines):
- game time, money, income per minute (from `money_changed`), power, score;
- own army and buildings by type, and what changed since the last call (built, lost, under attack);
- enemies: seen now near the base or the army, newly discovered structures, enemy templates seen so far;
- supply sources near the agent's supply centers with `supply` left;
- the triggers that fired.

Triggers (all on by default; flags to tune): own structure damaged or destroyed; 3+ enemy units within 1,000 of a base structure; half the army lost within 30 s; a structure finished; a new enemy unit type or structure seen; a supply source near a supply center below 15 %; money above 3,000 unspent for 60 s; `game_over` (exits with code 2 and prints the result).

`--state FILE` keeps "since last call" between calls. Running it in the **foreground** keeps the agent inside one turn (a blocking command is not a `sleep`, and returns well inside the 10-minute tool limit), so there is no hand-back per wake. The same command run under Monitor (`--stream`, one line per trigger) stays available for agents that prefer events.

### 3. Acting without restarting: `orders` and live-tunable bots
- **One-off orders from the agent:** `python -m generals_api.order ws://…:PORT attack --units ... --target ...` (a watcher connection) for immediate reactions: retreat, focus a target, use a general's power.
- **Live tuning:** a small library, `generals_api.botkit`, that agents may build their bot on: it reloads a `strategy.py` module when the file changes and re-reads `settings.json` every tick, so the agent edits a threshold or a build list and the running bot picks it up within seconds, without a new connection. Optional; documented with an example bot.
- **Clean exit:** a superseded controller gets close 4001; `botkit` and the reference bot exit on it, and `BOT-NOTES.md` says so (agents can't kill processes).

### 4. Prompts and orchestration
- The game prompt teaches the loop: start the bot → `watch` → read the digest → act (`order`, edit `settings.json`/`strategy.py`, or nothing) → `watch` again, until `watch` exits with `game_over`; then the 5-minute window starts immediately, in the same turn.
- "Don't end your turn before `game_over`" is stated plainly; ending early is allowed but costs the agent its live play.
- The orchestrator keeps the resume step as a fallback (an agent that hands back before `game_over` is resumed once with "the game is still running"), and keeps the hard 5-minute cap.

### 5. Measuring liveness
`save-session` adds a **liveness** section to each game's audit, from the transcript timestamps between the game's `READY` and `RESULT`:
- the longest gap between tool calls, and the share of game time covered by a running `watch`;
- the number of hand-backs, and actions taken (orders sent, settings or strategy edits);
- median wake-to-action time (digest returned → next order or edit).

The tournament report gets a liveness column. Target: no gap over 90 s and at least 90 % watch coverage.

## Probes first
Done; see Findings 1–3.
1. **One long turn:** a test subagent alternates a 60-second blocking Python command and a short action for 30 minutes. Does it stay in one turn, with no forced hand-back and no tool-call or context limit? What does each wake cost in tokens?
2. **Blocking isn't sleeping:** confirm the harness allows a foreground Python command that blocks on a WebSocket (the `sleep` rule matched `sleep`/`Start-Sleep` in the command text).
3. **Two connections:** the server's connection handling (`ScriptApiServer.cpp`) and the game thread's per-connection state (`m_commandTracker`, `m_snapshotTimer`, `sendEvent` to `activeConnection()`): list what must become per-connection.

## Tests
- **C++ unit:** connection registry (controller supersedes controller; watchers kept; at most 2 watchers, the third refused with close 4002 `too many watchers`); role check per command; event fan-out; per-connection snapshot timers and command trackers.
- **Python unit:** digest building from synthetic snapshots and events (each trigger, "since last call" state); `watch` exit codes; `botkit` reload of `settings.json` and `strategy.py`.
- **Integration:**
  - controller and watcher at once: both get events; the watcher's `attack` works and its `command_executed` goes to it alone; the watcher gets `WRONG_ROLE` for `quit_game`/`exit`; a new controller supersedes the old one but not the watcher.
  - `watch` returns within 5 s of: an own structure attacked (a Easy AI attack, or `force_attack_object` on our own building), a structure finishing, and `game_over` (surrender), and after `--max-wait` otherwise.
  - a `botkit` bot changes behavior after `settings.json` changes, without reconnecting.
- **Agent rehearsal** (not in the suite): one agent plays a 15-minute practice game with the new loop; its liveness numbers meet the target.

## Acceptance criteria
- [x] Probes done and recorded (Findings 1–3)
- [x] Watcher connections, `watch`, `order`, `botkit` implemented and tested (C++ 127, Python unit 96, 4 new integration tests); one full-suite sweep (Finding 9)
- [x] Prompts, `BOT-NOTES.md` and the tournament procedure updated; liveness in `save-session` and the report
- [x] Rehearsal: gap and hand-back targets met, coverage 75 % (Finding 4)
- [x] Tournament t2 (best of 3, same bracket as t1): Alpha (opus) champion; [report](../tournament/t2/report.md)

## Risks
- **Cost** (measured, Finding 2): a wake with a one-line result cost 250–340 output tokens and grew the context by 200–360 tokens; nearly all input was cache reads. A 30-line digest adds about 600–900 tokens of context per wake. A 45-minute game at one wake a minute plus triggers (about 60–90 wakes) grows the context by roughly 60–100k tokens and costs about 20–35k output tokens per agent, comparable to the t1 games but spread over the whole game. `--max-wait` is the lever.
- **Context growth** in one long turn: the digest is kept short and the prompt tells agents not to print logs; long games may need a mid-game summary in `notes.md` in case the context fills.
- **Two writers for one player** (bot and agent orders) can fight over the same units. That's the agent's design problem; `botkit` offers a "hold" flag per unit group for this.
- **Fairness:** watchers add no information a controller didn't already have, and orders from both count against the same APM cap. Faster models will still react faster; that is part of what the tournament measures.

## Findings
1. **One long turn works.** Two test agents (opus and haiku) each ran 20 iterations of "a 60-second blocking Python command in the foreground, then append a log line" in one continuous turn: about 21 minutes, no hand-back, no tool-call or time limit hit, every block returned `waited=60.0s`. Both followed "don't end your turn" without nudging. A real game needs 45 minutes; nothing seen suggests a limit in between, and the rehearsal will confirm it.
2. **The `sleep` block matches the command text only.** `sleep 30 && echo waited` was refused ("Blocked: sleep 30 followed by: echo waited. To wait for a condition, use Monitor with an until-loop …"); a Python script that blocks on a socket for 60 s was never refused. So `watch` must be a script that blocks in Python, and the prompt should tell agents not to use `sleep`/`Start-Sleep`. Measured cost per wake: 244 (opus) / 340 (haiku) output tokens per call, context growth 212 / 358 tokens per call, 49–60 calls for 20 wakes.
3. **What has to change for watchers.**
   - Server (`ScriptApiServer.cpp`): one `activeSocket`/`activeId`; a new socket replaces it in `onOpen`, **before any message**, and only the active id's messages are passed on. Needs a connection map (id → socket, role), the role from `openInfo.uri` at open, controller-only supersede, a watcher limit, per-connection slow-consumer drops, and `outbound.clear()` on supersede limited to the old controller's entries (the queue is already tagged by connection id).
   - Game side: `sendEvent` sends to `activeConnection()` only → send to every connection. `m_snapshotTimer` is one timer → per connection (a watcher's interval must not change the bot's). `m_commandTracker` stays one FIFO (orders execute in sending order whoever sent them), but entries carry their connection so `command_executed` goes to the sender, and `orphanAll` on supersede orphans only the old controller's entries; pending builds likewise, for `build_failed`. The router dispatches with the connection's role, and session commands are registered as controller-only.
4. **The practice game passed liveness except coverage.** A sonnet agent played a 15-minute practice game against the Easy AI with the watch loop and destroyed the enemy base at about 8:40 game time. Liveness: longest gap 66 s, 0 hand-backs, 9 actions (extra supply trucks, a manual attack, a 5-group scouting sweep after the enemy CC fell), median reaction 46 s, `watch` coverage 75 %. The first ~2 minutes went into writing the bot before the first `watch`; coverage counts from the game start, so 90 % is only reachable with a bot prepared in advance (which tournament agents have). Compared with t1's final: Charlie 27 hand-backs and no `watch`, Alpha a 186 s gap.
5. **A game can end between two `watch` calls.** The practice game ended while the agent was acting, so no `watch` connection saw `game_over`; the next call only saw the game leave for the score screen and reported "ended (shell)" without the result. Fixed: `hello` reports `game_result` once the game is over (victory, defeat or ended), and `watch` checks it when it connects and when it sees the game end.
6. **The practice runner missed the end too**: it closed its connection after starting the game, so it waited for its deadline. It now keeps a watcher connection for the whole game, so the limit is 3 watchers (the agent's `watch` and `order`, plus the runner).
7. **Agents couldn't find argument names for `order`** (the agent guessed `building=` for `train`, which takes `factory=`). `order --list` prints every command with its argument names from the client's signatures.
8. **`botkit` could miss a quick second edit**: Windows' `time.time()` ticks every ~15 ms, so two edits could share a modification time. `botkit` compares the nanosecond time and the size; found by an intermittently failing unit test.
9. **Full-suite sweep: 175 passed, 1 skipped, 2 failed.** `test_prompts_are_filled_in` failed because the game prompt gained `$series` (for tournament t2) while the sweep ran; it passes now. `test_9_launcher_bot_vs_bot_with_observer` failed 3 times in 4 runs: once with both bots building nothing, explained by `bots/simple.py` reading the state once right after a LAN start and giving up when its dozer wasn't in it yet (it now waits up to 10 s; 2 reruns passed), and twice with a `TimeoutError` inside the launcher that was not reproduced afterwards (open).
10. **Tests changed from the plan:** the `botkit` reload and the `base_attacked`/`game_over` triggers are covered by unit tests rather than integration tests (a skirmish has no cheap way to end in `game_over`); the finished-game LAN test checks `game_result` in a late `hello`.
11. **t2 confirmed the loop in real games.** 12 game sessions over six games: no mid-game hand-backs (Bravo's two were its final reports), longest gaps 64–105 s (t1: 52–186 s with dozens of hand-backs), every agent present at the end and straight into its iteration window. `watch` coverage 30–76 %, lower than the practice game because agents spent time editing strategy files and sending orders, and one ran `watch` through a wrapper the measure doesn't recognize.
12. **`watch` re-fires on an unchanged situation**: "enemies near base" triggered every few seconds while the same enemies stayed near an outlying building. Open: fire again only when the set of nearby enemies changes.
13. **Series bookkeeping bugs found in t2**, fixed during it: `snapshot`/`save-session --game` used matchup numbers; the audit flagged ports inside files an agent wrote; two stale prompt lines (single game, one connection).
