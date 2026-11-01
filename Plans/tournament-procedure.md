# Running a tournament (orchestrator procedure)

How a Claude Code session runs an agent tournament with `python -m generals_api.tournament` (from `python/`, with the venv's Python). Design and rules: [Phase 9](Phase-9-Bot-Tournament.md). Every command below is run by the orchestrating session, never by the agents, except `practice` (which a preparation agent starts for itself).

Paths: `T = tournament/<id>` at the repo root. Agent transcripts live in the session's `subagents/agent-<agentId>.jsonl` (under `~/.claude/projects/<project>/<session>/`); the task `.output` link can be empty, so use the `subagents` file.

## 0. Before starting
- No game windows open (`Get-Process generalszh` is empty), and the deployed exe is current.
- Decide the agents and models (any of `opus`, `sonnet`, `haiku`, `fable`).

## 1. Init
```
python -m generals_api.tournament init <id> Alpha:opus Bravo:sonnet Charlie:opus Delta:haiku [--seed N]
```
Creates `T/` (agents' workspaces with empty `notes.md`/`journal.md`, `games/`, `sessions/`, `state/`), draws the seeding, and writes `T/factions/*.json` (one catalog per faction; it starts a game instance for about a minute). Prints the empty bracket.

## 2. Preparation (per agent; one or two at a time)
1. `python -m generals_api.tournament prompt <id> prep <agent>` → the prompt.
2. Spawn the agent with the Agent tool: `subagent_type: general-purpose`, `model: <the agent's model>`, `run_in_background: true`, the prompt.
3. Wait the preparation cap (15 min, `config.prep_minutes`) with a Monitor or wakeup, then **TaskStop** the agent if it is still running.
4. `python -m generals_api.tournament cleanup <id>` (kills a practice game left running).
5. `python -m generals_api.tournament save-session <id> <agent> prep <subagents/agent-<agentId>.jsonl> --port <practice port>` — copies the transcript to `T/sessions/<agent>/prep.jsonl` and audits it (the practice port is in `T/agents/<agent>/reports/practice-*.json` or the transcript; with no port, any port use is flagged for review). Exit code 1 means violations: read `prep.audit.json`; redo the preparation if they are real.
6. Check `T/agents/<agent>/bot.json` exists and is valid; if not, the agent can't play (redo or disqualify).

## 3. Each bracket game
1. `python -m generals_api.tournament run-game <id>` **in the background** (Bash `run_in_background`), logging to `T/games/run-<n>.log`. It sets up the next game and prints `READY {...}` with each agent's port once the game is in progress; then it referees: at `game_over`, or at 45 minutes of game time (score decides), it ends the game, saves the replay, closes every instance and records `game.json`, `results.json`, `bracket.md` and each agent's report. It prints `RESULT {...}` and exits.
2. When `READY` appears (Monitor on the log), for each of the two agents: `python -m generals_api.tournament prompt <id> game <agent>` → spawn it (its model, background).
3. When `RESULT` appears, note the time. Each agent now has **5 minutes** (`config.iteration_minutes`). Wait them out (or until the agent finishes), then **TaskStop** any agent still running.
4. For each agent: `python -m generals_api.tournament snapshot <id> <n> <agent>`, then `save-session <id> <agent> game-<n> <transcript> --port <its port from game.json> --game <n>`. `--game` adds a **liveness** section to the audit (longest gap without a tool call, share of the game inside `watch`, hand-backs, actions, median reaction time); put it in the report. A real violation forfeits the game: edit `results.json` by hand (swap winner/loser, reason `forfeit`) and run `bracket <id>`.
5. Repeat until `run-game` prints `no game left; champion: <name>`.

**Agents should not hand back mid-game.** The game prompt teaches the `watch` loop (Phase 10), which keeps an agent in one turn until `watch` reports the game over. If one still hands back before the end, resume it once with "the game is still running; continue the watch loop". When `RESULT` appears, resume each agent with SendMessage ("game over at <time>; your window runs until <time+5 min>") and stop it at the cap. A finished agent can't be stopped with TaskStop (already completed); just save its session.

**Preparation that ends early:** an agent that hands back well before its cap may be told once that it has time left (its practice game is closed when it stops; it can start another).

## 4. After the tournament
- `python -m generals_api.tournament bracket <id>`.
- Write the final report (Phase 9 acceptance): bracket, models and factions, how each agent's notes and scripts evolved (journals, workspace snapshots), API issues the agents reported, cost (tokens per agent from the task notifications, wall time).
