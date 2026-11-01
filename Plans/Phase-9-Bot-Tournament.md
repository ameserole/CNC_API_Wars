# Phase 9 — Agent Bot Tournament

Parent plan: [PLAN-script-api.md](../PLAN-script-api.md) · Previous: [Phase 8](Phase-8-Agent-Match-Fixes.md)
Status: **Done**. Tournament t1 played 2026-11-01; champion Charlie (fable). Report: [tournament/t1/report.md](../tournament/t1/report.md)

## Goal
Run a tournament between AI agents that play Zero Hour live through the script API:
1. **Preparation:** each agent researches strategy and the API, picks a faction, and plays a live practice game against the Easy AI to learn how to interact with the game.
2. **Tournament:** agents play each other live in a single-elimination bracket. Each agent keeps its workspace (scripts, notes, logs) for the whole tournament and gets a short iteration window after every game to improve it.
3. **Record:** every game is kept: replay, logs, the agents' conversations, workspaces, and a bracket anyone can follow.

## Decisions
| | Decision |
|---|---|
| D1 Play mode | **Every game is played by a live agent**, as in the two test matches: the agent connects to its player's API during the game and runs and adjusts its own scripts. No unattended bots |
| D2 Participants | **4 agents**. The **model is set per agent** in the tournament config (any model the Agent tool accepts: `opus`, `sonnet`, `haiku`, `fable`) |
| D3 Map | **Tournament Desert** only. Factions are each agent's choice (see [Factions](#factions)) |
| D4 Limits | **No APM cap.** **45 minutes of game time** per game. **5 minutes** of iteration per agent after each game. **15 minutes** of preparation per agent |
| Format | **Bracket**: single elimination, **best of one** for every matchup, **no 3rd-place game** |

## Lessons from the two agent matches
- **Live play works but restarts are expensive.** Both agents lost most of their time to restarting buggy bots mid-game, and each restart lost in-memory state. Carrying scripts and notes between games is exactly what fixes this: an agent can arrive with a tested macro script instead of writing one under fire.
- **The winner kept a stable plan** and changed strategy deliberately (turtle, then one big wave). Notes that record what worked matter more than code volume.
- **Fairness must be enforced, not just asked for.** Both agents could have read each other's folders. Neither did, but the tournament audits it.
- **Cost:** about 200k tokens and 50 minutes of wall time per agent per game.

## Format: the bracket
```
Semifinal 1:  Seed 1 vs Seed 4  ─┐
                                  ├─ Final
Semifinal 2:  Seed 2 vs Seed 3  ─┘
```
No 3rd-place game.
- **Seeding:** random, drawn once by the runner with a recorded seed.
- **Best of one** for every matchup, the final included. Start positions are random (recorded seed).
- **A game ends** with `game_over` (a player has nothing left that counts for victory), or at 45 minutes of game time. At the time limit the higher **score** wins: the engine's own `ScoreKeeper::calculateScore()`, the number the score screen shows. Equal scores (very unlikely) go to the player with more buildings destroyed.
- **Iteration:** after each game, both agents get 5 minutes (wall time) to update their scripts and notes, then their session ends. Winners carry their workspace into the next round; eliminated agents' workspaces are archived.
- **Semifinals run one after the other**, not at once: a LAN game is three full game instances (two players and an observer), and two at once plus four agents would slow everything.

## Factions
Choosing a faction is part of each agent's strategy. It's made during preparation and may change before any game.

### Choosing
- **What can be chosen:** the factions `skirmish_options()` lists, which is the skirmish menu's list: America, China, GLA and the nine generals (e.g. `FactionAmericaAirForceGeneral`, `FactionChinaTankGeneral`, `FactionGLAToxinGeneral`). Not `random`. Mirrors are allowed.
- **Researching it:**
  - `faction_catalog {faction}` (new, see Engine / API): from the menus, the structures, units, upgrades and sciences of any faction, with costs, build times and prerequisites. It's the game's static data, which a human can read in the game's own menus and manual, so it's fair. Without it an agent only sees the catalog of the faction it is playing.
  - The practice game against the Easy AI, played with the chosen faction.
  - ❓ Web research (Generals strategy guides): recommended yes, the same for every agent.
- **Declaring it:** the agent's workspace has a manifest, `bot.json`:
  ```json
  {
    "faction": "FactionChina",
    "vs": {"Bravo": "FactionAmericaLaserGeneral"}
  }
  ```
  - `faction` is the default; `vs` optionally overrides it per opponent. An agent knows past opponents' factions only from what it saw in its own games, never from their files.
  - **Blind picks:** the runner reads both manifests when it sets up the game. Each agent's last chance to change it is its previous iteration window, which ends before the next game's setup, so neither can react to the other's pick for that game.
  - Switching to a faction the agent hasn't practiced is allowed; the risk is the agent's. Scripts must not assume template names: `catalog()` gives them, and its `faction` field tells the bot which faction it is playing.

### Game startup with the chosen faction
1. The runner reads both manifests, resolves each side's faction (`vs[opponent]`, else `faction`) and checks it against `skirmish_options()["factions"]` on the host instance.
2. It sets up the LAN game through the launcher's existing faction support: the host sets its slot with `lan_slot {faction}`, the joiner sets its slot after joining, the observer takes the observer slot, and everyone accepts afterwards (accepting resets on every slot change).
3. In the game, before the agents connect, each side's `catalog()["faction"]` must be the requested faction's side; a mismatch stops the setup with an error. Both factions go into `game.json` and the bracket.
4. **Invalid manifest** (unknown faction, `random`, bad JSON): the agent's previous valid manifest is used, and the agent is told in its game prompt. Preparation ends only with a valid manifest, so there is always one.

## How a live game runs
1. **Setup** (`tournament run-game <id>`, one command for setup, refereeing and records; the orchestrator runs it in the background): starts the three instances, sets up the LAN game with both factions, waits for `in_game`, disconnects, and writes `games/<n>/game.json` with each agent's API port. Like `host_match.py` from the test matches.
2. **Agents:** the orchestrating Claude Code session spawns both agents in the background with the Agent tool, each with **its configured model**, the shared game prompt, its own name, port and workspace. Each agent starts fresh: it reads its `notes.md` and `journal.md`, then plays.
3. **Referee** (the same `run-game` process) owns the observer instance's connection (agents never use it):
   - watches the game time, and records `game_over` from the observer's `game_state` and from the stats;
   - at 45 minutes, reads both players' scores and stats (`player_stats`, see Engine / API), then ends the game by connecting to each player instance, which supersedes the agent's connection (close 4001), and quitting;
   - after either ending, saves the replay under the game's name and closes the instances.
4. **End for the agents:** an agent sees `game_over`, or its connection closed with 4001 after the time limit. Either way its prompt says: you now have 5 minutes to update `notes.md`, `journal.md` and your scripts, then stop.
5. **Iteration cap:** the orchestrator stops each agent (TaskStop) 5 minutes after the game ended if it hasn't finished. The workspace is snapshotted right then (copied to `games/<n>/workspace-<name>/`), so edits after the cutoff can't count.
6. **Records:** the runner writes `game.json` (result, reason, duration, factions, scores, stats), updates the bracket, and copies both conversations into `sessions/`.

## Workspaces and memory
```
tournament/<id>/
  config.json                 # participants (name, model), map, limits, bracket seed
  bracket.md, results.json    # updated after every game
  agents/<name>/              # the agent's own workspace, kept for the whole tournament
    bot.json                  # faction manifest
    *.py                      # its scripts (macro bot, helpers, probes)
    notes.md                  # strategy, what it learned, plans: its long-term memory
    journal.md                # one entry per session: what it did and changed, and why
    reports/                  # copied in by the runner after each of its games
  games/<n>-<a>-vs-<b>/
    game.json                 # who, models, when, factions, start positions, result, reason, duration, scores, stats
    replay.rep
    workspace-<a>/, workspace-<b>/   # snapshot at the end of the iteration window
  sessions/<name>/<k>.jsonl   # every agent session's conversation (copied from the subagent transcripts)
```
- **Memory between sessions** is the workspace. Each session starts fresh (no resumed conversation), reads `notes.md` and `journal.md` first, and must update both before it ends.
- **What an agent sees of its games:** everything it saw live, its own logs, the result and its own end-of-game stats. Not the opponent's code, notes or conversation. Replays are for humans; agents can't read them (no replay API).

## Infrastructure to build

### 1. Tournament runner (`python/generals_api/tournament.py`)
- `tournament init <id> Alpha:opus Bravo:sonnet …`: creates the folders and `config.json`, draws the seeding, and writes `factions/<Faction>.json` (every faction's `faction_catalog`) as shared reference data for the agents.
- `tournament practice <id> <agent>`: started by the preparation agent itself: a skirmish against the Easy AI with the faction in its `bot.json`; prints `PRACTICE READY port N`; ends at `game_over` or after the preparation time and writes a practice report. `tournament cleanup <id>` kills one left running.
- `tournament run-game <id>`: the steps of [How a live game runs](#how-a-live-game-runs) for the next bracket game. `prompt`, `snapshot` and `save-session` (copy and audit a transcript) serve the orchestrator; see [tournament-procedure.md](tournament-procedure.md).
- `tournament bracket`: renders `bracket.md`.
- Validates manifests before setup; resumes from `results.json` after a crash.

### 2. Orchestration (a Claude Code session)
The runner manages games; spawning agents needs the Agent tool, so a Claude Code session runs the tournament, following a checked-in procedure (`Plans/tournament-procedure.md`, written in this phase):
- **Preparation**, per agent (model from config; **15 minutes of wall time**, enforced like the iteration window: the agent is stopped and its workspace snapshotted at the cap):
  1. Research: `BOT-NOTES.md`, the client, the phase docs, `faction_catalog`, and the web if allowed.
  2. Pick a faction and write `bot.json`.
  3. Play a live practice game against the Easy AI (`tournament practice`), building the scripts it will reuse. The game is started for the agent at the beginning of the session, so it can switch between research and play. It need not be won: 15 minutes is less than a typical game (the test matches took 36 minutes of game time), and the practice game is closed at the cap.
  4. Keep `notes.md` and `journal.md` current throughout; only what is on disk at the cap carries over.

  Preparations run one or two at a time (each practice game is two instances).
- **Each bracket game:** setup → spawn both agents (their models) → referee → stop after the 5-minute window → record.
- **Prompts:** one shared preparation prompt and one shared game prompt (rules, layout, time limit, iteration window, deliverables), plus the agent's name, port and workspace. Agents never see each other's prompts or files.

### 3. Engine / API
- **`player_stats`:** `ScoreKeeper` numbers per player: score (`calculateScore`), units built, lost and destroyed, buildings built, lost and destroyed, money earned and spent. A player gets its own stats any time. An **observer** gets every player's (the referee uses it), and every client gets all players' once the game is over, as the score screen shows them. `game_over` also carries the final stats.
- **`faction_catalog {faction}`:** the catalog for any selectable faction, built from the template store (templates whose side matches the faction and that its command sets can build), without the per-player fields (`available_now`, `purchasable_now`). The game-independent grouping and JSON go in `core_scriptapi` with unit tests.
- **Probes first:** every faction in `skirmish_options()` can be set through `lan_slot` and starts with its own command center and workers; the generals' template names (e.g. `AirF_AmericaVehicleDozer`) show up in `catalog()`; a superseding connection plus `quit_game` ends a LAN game cleanly for all instances and the replay still plays back.

### 4. Bug: finished games don't close
**Report:** after the Bot1-vs-Bot2 match ended (`game_over` for both players), all three game windows sat in the end-of-game screens until the user closed them by hand; only then did `host_match.py` see the processes exit (`bot games exited: 0 0`).

**What is known:** `host_match.py` only waited for the processes, and the agents had been told to leave the windows running, so nothing asked the games to leave. Whether the API *could* have closed them from that screen was never tested: the launcher's tests end matches by their time limit (`--duration`), before `game_over`, so the path "game over → score screen → `quit_game` / `save_replay` / `exit`" has no coverage, and neither has an observer's instance after the players' game ends.

**To find out** (probe first, then fix):
1. After `game_over` in a LAN game, what does each instance report: the `game_state` of each player and of the observer, and which screen is up (the "game over" message box, then the score screen)?
2. Do `quit_game`, `save_replay` and `exit` work from there, for a player and for the observer? `quit_game` may refuse (`WRONG_STATE`) or do nothing, because it was written for an interactive game, and the score screen is a shell screen that a player leaves by clicking.
3. Does the observer get any end signal at all? It isn't a player, so it gets no victory or defeat.

**Fix:** make the scripted path work from every end-of-game state: `quit_game` leaves the score screen for the main menu, `exit` closes the game from any state, the observer reports the end of the game (`game_state` `game_over`, or a `game_ended` event), and `save_replay` works once the score screen is up. The referee and launcher then close everything without help. Add a `CLAUDE.md` engine fact for whatever the cause turns out to be.

**Tests:** a LAN game with an observer played to a real `game_over` (one side calls `surrender`, the quickest way to a genuine victory and defeat), after which the launcher or referee saves the replay and all three instances exit by themselves within 60 seconds.

### 5. Fairness and audit
- Each agent is told to stay inside its workspace and its own port. The runner and referee own the observer instance and all setup, so agents never touch another player's instance.
- **Audit after each session:** scan the transcript for paths in other agents' workspaces, ports other than its own, or game processes touched. A violation in a game forfeits that game; in preparation, it is reported and the session redone.
- ❓ Stronger isolation: each agent in its own git worktree or OS user.
- **Models differ by design (D2).** A faster model reacts faster in a live game. That's part of what the tournament measures, and `game.json` records each side's model.

## Tests
- **C++ unit:** `faction_catalog` grouping and JSON; the visibility rule for `player_stats` (own, observer, after game over).
- **Python unit:** bracket seeding, advancing winners, the time-limit tiebreak, `bracket.md` rendering, resuming; manifests (parsing, rejecting unknown factions and `random`, `vs` overrides, falling back to the previous valid one); the audit's path and port matching; `config.json` with a model per agent.
- **Integration:**
  - `faction_catalog` for every faction in `skirmish_options()` is non-empty and includes the faction's command center and worker; unknown names get `INVALID_ARGUMENT`.
  - A LAN game set up with two different factions (e.g. China vs GLA Toxin General): each side's `catalog()["faction"]` and starting units match.
  - `player_stats`: a player gets only its own during the game, the observer gets both, everyone gets both after `game_over`; the numbers agree with events (units lost ≥ `unit_destroyed` count).
  - Referee: with a short time limit, it ends a running game, both player connections close with 4001, the scores are recorded, and the saved replay plays back without a CRC mismatch.
  - A bracket of four with scripted stand-ins for the agents (`bots/simple.py`, made faction-agnostic: it reads the generals' prefixed template names from the catalog; connected by the test in place of an agent) runs end to end with short time limits: three games, results, bracket, replays.

## Acceptance criteria
- [x] Decisions D1–D4 and the format made
- [x] Faction probes done; every selectable faction starts and plays through the API (Finding 6)
- [x] Finished games close by themselves: the cause found (Finding 1), observer `game_over` and the launcher fixed, tested
- [x] Runner, referee, `player_stats`, `faction_catalog` and manifests implemented and tested (C++ 115, Python unit 76, 4 new integration tests); one full-suite sweep: 157 passed, 1 skipped, 1 failed (a test bug, fixed and rerun; Finding 5)
- [x] Tournament procedure ([tournament-procedure.md](tournament-procedure.md)) and prompts (`python/generals_api/tournament_prompts/`) written
- [x] Preparation done for all four agents, each with a valid `bot.json` and a practice game played
- [x] Bracket played, with every game, session transcript and workspace snapshot archived (`tournament/t1/`)
- [x] Final report: [tournament/t1/report.md](../tournament/t1/report.md)

## Risks
- **Cost:** 4 preparation sessions of 15 minutes, then 3 bracket games with 2 live agents each: 6 full live agent games at around 200k tokens each, plus the shorter preparations.
- **15 minutes of preparation is tight.** Agents will arrive with partly tested scripts and must keep developing them during the semifinal. The preparation prompt points them at `BOT-NOTES.md` and `World` helpers to save time.
- **Wall time:** each game takes up to 45 minutes of game time; debug builds and observers may run slower than real time. One game at a time.
- **The 5-minute window is short.** Agents must keep notes as they play, not only afterwards. The game prompt says so.
- **Single games are noisy.** A best-of-one bracket may be decided by a bad start. Accepted for the first tournament; series can come later.
- **Untested factions.** The API has mostly been exercised with America. Other factions have their own mechanics (GLA workers and supply stashes, China's hackers, the generals' unique units). The faction probes come first; findings go into `BOT-NOTES.md`.
- **Engine crashes** void a game; it is replayed once from setup, then decided by score at the crash.
- **Agents interfering with the game process** (killing or restarting it): forbidden by the prompt, checked by the audit; a game where it happens is forfeited by that agent.

## Findings
1. **Finished games close fine; nobody asked them to.** Probe: a LAN game with two players and an observer, ended by `surrender`. Both players got `game_over` at once; about 12 seconds later every instance, the observer included, moved to the score screen and reported `game_state` `shell`. From there `save_replay` and `exit` worked on all three and the processes exited with 0. `quit_game` there is `WRONG_STATE` (correct: the game is over). So the Bot1-vs-Bot2 windows stayed open because `host_match.py` only waited for the processes and the agents had been told to leave the windows open. The real gaps:
   - **The observer gets no `game_over`**, only the `shell` state 12 s later, and doesn't learn who won. Fixed: observers get `game_over {result: "ended", winners}`.
   - **The launcher called `quit_game` right after `game_over`** to save the replay, racing the engine's own exit to the score screen (and sending a surrender into a finished game). Fixed: after `game_over` it waits for `shell`; it only quits a game that is still running (the `--duration` limit).
   - **`keep_observer`** leaves the observer window open by design for a human; the referee closes everything.
3. **Tournament games need `-ignoreAsserts`.** The first preparation sessions' practice games stopped on the debug build's known assertion dialogs, because the runner didn't pass the flag the test harness always uses. Tournament, practice and catalog-dump games now start with `GAME_ARGS = ("-ignoreAsserts",)`; the assertions still go to the log. The two practice games were restarted and the agents' preparation extended by 5 minutes.
4. **Exiting can take most of a minute.** With two practice games running, an idle instance took 46 s from `exit` to process end (the debug build's shutdown checks). The runner waits up to 2 minutes before killing an instance.
5. **Full-suite sweep:** 157 passed, 1 skipped, 1 failed: the new end-of-game test left its replay behind and failed when run again (`save_replay` correctly refuses to overwrite). The test now deletes it first; rerun passed.
6. **All 12 factions start through the API** (probe: a skirmish per faction against the Easy AI). Each starts with its own command center and worker (`AirF_AmericaVehicleDozer`, `Chem_GLAInfantryWorker`, …), and `catalog()["faction"]` is the faction's *side*: the faction name without `Faction` (`FactionChinaTankGeneral` → `ChinaTankGeneral`). Catalogs have 10–12 structures and 14–19 units.

## API design (from the probes)
- **`player_stats`** → `{players: [{index, side, score, units_built, units_lost, units_destroyed, buildings_built, buildings_lost, buildings_destroyed, money_earned, money_spent}], all: bool}`. Players are the playable, non-observer ones (as in `game_info`). A player gets only its own entry until the game is over; an observer, or anyone after the game is over, gets every player (`all: true`). Score is `ScoreKeeper::calculateScore()`.
- **`game_over`** → `{result, winners: [player indices], stats: <player_stats players>}`. `result` is `victory`/`defeat` for players and `ended` for an observer.
- **`faction_catalog {faction}`** → `{faction, side, structures, units, upgrades, sciences}` from the faction's starting objects' command sets (the same walk as `catalog()`). Costs and build times are the base values (computed for the neutral player, which has no handicap). Structures and units carry `built_by`, `abilities`, `prerequisites`, `science_prerequisites`; sciences come from the faction's three general's-promotion command sets with `tier` 1–3 and `cost`. Works in the shell and in a game.
7. **Subagents can't stay live for a whole game.** The subagent harness ends an agent's turn while its background bot keeps playing; every agent handed back mid-game, often repeatedly with status updates. The bots played on, and the orchestrator resumed each agent (SendMessage) for its 5-minute window at the end. Games were played by the agents' scripts plus bursts of live patching.
8. **Start positions follow the slot order, not chance.** The host got start 2 in all three games and won all three. The runner randomizes the host only. Next time: set start positions explicitly from the seed (needs a `start` field in `lan_host`/`lan_slot`), so position is random and recorded.
9. **Audit gaps.** Delta read its own practice state file and `state/sessions.json` for its port (disclosed, harmless). The audit only flags other agents' workspaces, other ports and process kills; the runner now records practice ports (`state/practice-ports-<agent>.json`) so agents never need the state files.
10. **Agents' API feedback** (for `BOT-NOTES.md` or the API): full prefixed template names are required; a War Factory needs a finished Supply Center; buildings can't be placed in the shroud; `known_structures` lacks `relation` (Bravo attacked a neutral dock, owner 0); a superseded bot should exit by itself on close 4001 (agents can't stop processes).
