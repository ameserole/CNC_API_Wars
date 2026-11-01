# Alpha: Notes

## Faction
FactionChinaTankGeneral (bot.json). Templates are prefixed `Tank_` (e.g. Tank_ChinaTankBattleMaster); bot resolves by suffix.
Key costs: PowerPlant 1000, SupplyCenter 1500 (needs Power), Barracks 500, WarFactory 2000 (needs SupplyCenter),
PropagandaCenter 2000 (needs WF), BattleMaster 700/24s, Gattling tank 700/20s (anti-air+inf), Emperor 1900 (needs Prop).
Upgrades at PropagandaCenter: Nationalism 2000, UraniumShells 2500, Tank AutoLoader 2500, NuclearTanks 2000.
Sciences: BattlemasterTraining, EmergencyRepair, TankParadrop1-3, ArtilleryBarrage, EMPPulse, CarpetBomb.

## How to play a real game
Start the macro bot in the background as soon as you have the port:
  cd C:\Users\user\Documents\CNC_Generals_AI\tournament\t1\agents\Alpha
  ..\..\..\..\python\.venv\Scripts\python.exe -u alpha_bot.py PORT  (logs to bot.log)
It is a polling loop (state() every 2 s): build order Power -> Supply(near nearest dock) -> Barracks -> WarFactory,
more power when spare<3, 2nd supply/WF, Propaganda, 2 Gattling cannons, 3rd WF; trains BattleMasters (+1 Gattling per 3),
Emperors once Propaganda exists; waves of 6 then 5; idle attackers hit nearest known enemy structure (explicit attack
when visible & close), else attack-move to start positions; home army defends vs enemies within 900 of HQ.
Only ONE connection per game: don't run probes while the bot runs (kills it).

## API lessons
- practice reads bot.json at setup: write bot.json BEFORE starting practice.
- see BOT-NOTES.md in python/ for gotchas (attack-move ignores plain buildings, money committed on accept).

## Practice 1 findings (vs Easy AI, Tournament map, we spawned at (1010,2102), enemy (1004,583))
- Own unit dict: {"id","template","pos":[x,y,z],"health","max_health","status":["idle"|"harvesting"|"under_construction"...],
  "veterancy","contained_by"}. self: {"money","power":{"produced","consumed"},"rank","science_points"}. Start cash 10000.
- Structure prerequisites must be COMPLETE, else build -> NOT_AVAILABLE. Bot now checks catalog prerequisites vs finished
  buildings and lets several dozers build in parallel (Power + Barracks at once).
- Tank General vehicles come out veterancy 1. SCIENCE_BattlemasterTraining purchasable at rank 1.
- Early economy was the bottleneck: 1 supply center + 4 trucks gives ~1 tank / 20 s; extra dozers (2000) were wasted.
  Fix: dozer cap 2, money "reserve" so a 2nd SupplyCenter (at a dock >500 from existing centers, <1400 from HQ) and
  2nd WarFactory get funded before tanks.
- Restarting the bot mid-game is safe (new connection supersedes the old; old one exits cleanly).
- RESULT practice 1: VICTORY vs Easy AI at frame ~13200 (~7.3 game min). Timeline: WF done ~frame 2000, first wave (6)
  at frame ~6400, 2nd supply center ~7200, 2nd WF ~9000, waves of 5 after. No tank losses to Easy AI.
- Against real opponents expect much more resistance: consider the ideas in journal.md (faster econ, Gattling cannon at
  home, Propaganda upgrades, general's powers). Only 1 power plant was ever needed for this build (spare power 6).

## TODO / ideas
- Abilities: find ability names in catalog() ("abilities", required_science) to use Tank Paradrop / Artillery Barrage.
- When no enemy structures known, scouting only cycles start positions; add map-wide sweep if enemy expands.
- Army is recalled when >=4 enemies are within 900 of HQ and outnumber the home guard (untested in practice).

## Game 2 (t1, vs Delta, LIVE) - VICTORY at frame ~21000 (~11.7 game min)
- Delta played America (AmericaInfantryRanger x14 + 1 Crusader) and rushed our base at frame ~7700 (4.3 min).
  They parked next to the HQ for ~4 min killing dozers (all 3 lost) and each tank as it left the War Factory.
- Root cause of weakness: the v1 money "reserve" for the 2nd War Factory blocked ALL tank production from frame
  ~3000 to ~7100, so we had 1 unit when the rush hit. FIXED: reserve only applies when tanks>=4 (or for the first
  of a building), never under threat.
- Fixes added live (now in alpha_bot.py; v1 kept as alpha_bot_v1.py):
  * THREAT detection (>=2 enemies within 1100 of HQ) logs composition + centroid.
  * Under threat: only essential buildings + Gattling cannons, no money reserve, dozer cap 1, Barracks trains Red Guard
    (up to 6), War Factories prefer Gattling tanks (also whenever >=4 enemy infantry visible).
  * Home army gathers at a rally point behind the HQ (away from enemy) until its strength
    (tank=2, infantry=1) >= max(4, 0.6*enemies), then attack-moves. This broke the rush: army massed to 9, cleared it.
  * When no dozers and no threat, reserve 1000 for a new dozer.
- After the rush cleared, waves of 6/5/15 Gattling+Battlemaster+RedGuard wiped Delta's base in ~3 min.
  Delta seemed to have spent everything on the infantry rush (few defenses).
- Income is weak (~600 per 20 s real with 6 trucks / 2 centers). Investigate dock distance; a 3rd center could help.
- Game runs ~30 logic frames per real second; the game had already reached frame ~1100 when the bot connected.
