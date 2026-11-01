# CNC_Generals_AI

Python bots that play **Command & Conquer Generals Zero Hour** live, under exactly the same limits as a human, and a harness for AI agents (Claude models) to write those bots and play each other in tournaments.

## Overview

The project adds a **script API** to a fork of the open-source Zero Hour engine ([TheSuperHackers/GeneralsGameCode](https://github.com/TheSuperHackers/GeneralsGameCode)). A game started with `-scriptApiPort N` opens a WebSocket server on that port; a Python client connects and plays one player.

```
 bot.py / agent ──WebSocket JSON──▶ generalszh.exe (one player)  ◀──LAN──▶ generalszh.exe (other player)
                                                                  ◀──LAN──▶ generalszh.exe (observer window)
```

**Fair by construction:**
- Bots act only through the same network messages a mouse click would send, checked like UI clicks (the button exists and is enabled, enough money, a legal build spot, a visible target).
- They see only what a human player would: fog of war, no enemy economy or production, stealth respected.
- A bot's window can't be used by a human to give orders (input lock), and an optional APM cap limits orders per minute of game time.
- Replays of API games play back without a CRC mismatch, which proves the API doesn't change the simulation.

**What you can do:**
- Write a bot (`async def run(client, world)`) and play it against the built-in AI, or against another bot over LAN with an observer window for humans to watch.
- Run a **tournament** in which AI agents prepare, pick a faction, write and tune their bots, and play each other live in a bracket, while a referee runs the games and records everything.
- Watch any game afterwards from its saved replay.

Results so far: [tournament t1](tournament/t1/report.md) (best of one) and [t2](tournament/t2/report.md) (best of three).

## Repository layout

| Path | What |
|---|---|
| `ZeroHourFork/GeneralsGameCode/` | The engine fork (its own git repository); all C++ work happens here. Its [README](ZeroHourFork/GeneralsGameCode/README.md) describes the engine changes; the upstream README is kept as `README-upstream.md` |
| `GameFiles/` | A copy of the Steam Zero Hour install; the built `generalszh.exe` is deployed and run here |
| `python/` | The `generals_api` package (client, world model, launcher, tournament runner, `watch`, `order`, `botkit`), `bots/simple.py`, [`BOT-NOTES.md`](python/BOT-NOTES.md), tests |
| `scripts/` | `build.ps1` (build, test, deploy) and `run-integration.ps1` (Python tests) |
| `Plans/` | One design doc per phase, with findings; [`tournament-procedure.md`](Plans/tournament-procedure.md) |
| `PLAN-script-api.md` | The master plan: protocol, architecture, phases |
| `tournament/<id>/` | Tournament records: bracket, games, replays, agents' workspaces, conversation audits (the transcripts themselves stay local, see `.gitignore`) |
| `agent-matches/` | Earlier one-off agent matches |
| `test-results/` | Integration-test artifacts (logs, transcripts, crash dumps) |

## Prerequisites

- **Windows 10/11.**
- **Visual Studio 2022 Build Tools** with the C++ x86/x64 tools (`build.ps1` finds them with `vswhere` and sets up an x86 environment), **CMake** and **Ninja** on the PATH. The other dependencies are fetched by CMake.
- **Python 3.12** (`py -3.12`). The test script creates `python/.venv` on first run; to create it yourself:
  ```powershell
  py -3.12 -m venv python\.venv
  python\.venv\Scripts\python.exe -m pip install -e "python[test]"
  ```
- **Zero Hour game data:** copy a Steam install of Command & Conquer Generals Zero Hour into `GameFiles/` (the folder that contains `ZH_Generals\`, `INIZH.big` and so on).
- **Install path for debug builds:** point the registry at that copy:
  ```powershell
  reg add "HKCU\Software\Electronic Arts\EA Games\Generals" /v InstallPath /t REG_SZ /d "$PWD\GameFiles\ZH_Generals\" /f
  ```

## Building

From the repository root, in PowerShell (add `powershell -ExecutionPolicy Bypass -File` in front if scripts are blocked):

```powershell
.\scripts\build.ps1 -Tests -Deploy   # build win32-debug with the script API, run the C++ unit tests, copy generalszh.exe into GameFiles
.\scripts\build.ps1                  # build only
.\scripts\build.ps1 -Deploy -Run     # deploy and start the game in a window
.\scripts\build.ps1 -Target core_scriptapi -Tests   # fast loop for the game-independent API code
```

A full build takes 3–4 minutes. Close running games before `-Deploy` (they lock the exe). The debug build is the one used everywhere; it allows several game instances on one PC.

**Tests:**
```powershell
.\scripts\run-integration.ps1                    # Python unit + integration tests (plays real games; about 35 minutes)
.\scripts\run-integration.ps1 tests/unit -q      # Python unit tests only (seconds)
.\scripts\run-integration.ps1 tests/integration/test_live_agents.py   # one module
```

## Playing a single game

Run these from `python/` with the venv's Python (`.venv\Scripts\python.exe`).

**Bot against the built-in AI** (a plain skirmish):
```powershell
.venv\Scripts\python.exe -m generals_api.launcher --bot1 bots/simple.py --vs-ai easy
.venv\Scripts\python.exe -m generals_api.launcher --bot1 bots/simple.py --vs-ai hard --ai-faction GLA --bot1-faction China --observer
```

**Bot against bot over LAN, with a window for you to watch:**
```powershell
.venv\Scripts\python.exe -m generals_api.launcher --bot1 my_bot.py --bot2 bots/simple.py --bot2-faction ChinaTankGeneral --observer
```

Useful options: `--map NAME` (default Tournament Desert), `--duration SECONDS`, `--apm N` (order cap per game minute), `--replay NAME` or `--no-replay`, `--game-arg ARG` (extra game flag). Factions are any of the 12 the skirmish menu offers (`America`, `China`, `GLA`, `AmericaAirForceGeneral`, `ChinaTankGeneral`, `GLAToxinGeneral`, …). The match is saved as a named replay at the end.

**Writing a bot:** a module with `async def run(client, world)`. `client` is a [`GeneralsClient`](python/generals_api/client.py) (every command is a method: `build`, `train`, `attack_move`, `use_ability`, …; `catalog()` lists what your faction can build), `world` a [`World`](python/generals_api/world.py) kept up to date from snapshots. Start from [`bots/simple.py`](python/bots/simple.py) (works for any faction) and read [`BOT-NOTES.md`](python/BOT-NOTES.md) for the gotchas.

**Driving a game by hand:** start the game yourself and connect any client:
```powershell
cd GameFiles
.\generalszh.exe -win -nologo -noshellmap -ignoreAsserts -scriptApiPort 5000
```
Then, from `python/`:
- `ws://127.0.0.1:5000` is the **controller** (your bot). `start_skirmish`, `quit_game`, `exit` and so on start and end games.
- `.venv\Scripts\python.exe -m generals_api.watch ws://127.0.0.1:5000` blocks until something matters in the game and prints a digest. It connects as a **watcher** (`/watch`), next to the bot.
- `.venv\Scripts\python.exe -m generals_api.order ws://127.0.0.1:5000 attack units=[12,13] target=40` sends one command as a watcher; `order --list` shows every command and its arguments.

Game flags: `-scriptApiPort N` (enable the API), `-scriptApiInput view|locked|full` (what a human can do in that window; default `view`, camera only), `-scriptApiApm N`, `-scriptApiDebug` (debug-only test commands), `-ignoreAsserts` (don't stop on the debug build's assertion dialogs).

**Watching replays:** start `GameFiles\generalszh.exe -win -ignoreAsserts`, then **Load → Replay**. Every launcher and tournament game is saved there by name (for example `t2 game 5`). Or open one directly: `.\generalszh.exe -win -ignoreAsserts -replay "t2 game 5.rep"`. The replay folder is `Documents\Command and Conquer Generals Zero Hour Data\Replays`.

## Running a tournament

AI agents (Claude models, run as Claude Code subagents) prepare, play live and improve between games. A tournament is run **from a Claude Code session**, because spawning the agents needs Claude Code's Agent tool. The Python runner does everything else: game setup, refereeing, records, audits. The full step-by-step is in [Plans/tournament-procedure.md](Plans/tournament-procedure.md); the design is in [Phase 9](Plans/Phase-9-Bot-Tournament.md) and [Phase 10](Plans/Phase-10-Live-Agents.md).

1. **Create it** (from `python/`): 2, 4 or 8 agents, each with a model; games per match with `--best-of`:
   ```powershell
   .venv\Scripts\python.exe -m generals_api.tournament init t3 Alpha:opus Bravo:sonnet Charlie:fable Delta:haiku --best-of 3
   ```
   This creates `tournament/t3/` (empty workspaces, `config.json`, the bracket) and writes every faction's catalog to `tournament/t3/factions/`.
2. **Preparation** (15 minutes per agent): `tournament prompt t3 prep <agent>` prints the prompt; spawn the agent with it and its model. It researches, picks a faction in `bot.json`, writes a bot and plays a practice game against the Easy AI (`tournament practice t3 <agent>`). Afterwards, `tournament cleanup t3` and `tournament save-session t3 <agent> prep <transcript>` keep and audit its conversation.
3. **Each game:**
   - `tournament run-game t3` sets up the next game in the background with both agents' factions and prints `READY` with their ports.
   - Spawn both agents with `tournament prompt t3 game <agent>`. They play live with the watch loop.
   - The runner referees: the game ends at `game_over`, or at 45 game minutes on the score. Then it saves the replay, records the result and updates `bracket.md`.
   - Each agent then has 5 minutes to update its notes and bot. Finish with `tournament snapshot t3 <n> <agent>` and `tournament save-session t3 <agent> game-<n> <transcript> --port <port> --game <n>`, which audits the rules and measures how live the agent stayed.
4. **Repeat** until `run-game` prints the champion. `tournament bracket t3` prints the bracket at any time.

Everything ends up in `tournament/<id>/`: `bracket.md`, `results.json`, `games/<n>-<a>-vs-<b>/` (`game.json` with scores, factions, models and start positions; `replay.rep`; workspace snapshots), `sessions/<agent>/` (every conversation with its audit; the `.jsonl` transcripts are not committed, since they carry the account's email and local paths), and `agents/<agent>/` (each agent's notes, journal and bot as they evolved).

## Documentation

- [PLAN-script-api.md](PLAN-script-api.md): protocol, commands, events, architecture and every phase.
- [Plans/](Plans/): one doc per phase (goal, design, tests, acceptance, findings).
- [python/BOT-NOTES.md](python/BOT-NOTES.md): what bot authors need to know.
- [CLAUDE.md](CLAUDE.md): working notes for Claude Code sessions on this repository (conventions, engine facts, test harness).
