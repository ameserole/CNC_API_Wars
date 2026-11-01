# Charlie: Notes

## Faction: China (bot.json = FactionChina)
Sturdy, simple macro: Power -> Supply Center (next to the dock) -> War Factory -> Barracks -> 2nd Power -> 2nd War Factory.
Pump Battlemasters (800, 20 s) with a Gattling tank every third for anti-infantry/anti-air. Attack at 8 tanks.
Consider FactionChinaTankGeneral later (same template names with `Tank_` prefix; strategy matches by suffix).

## How to run in a real game
1. Bot (controller) in the background, from this folder:
   `C:\Users\user\Documents\CNC_Generals_AI\python\.venv\Scripts\python.exe bot.py ws://127.0.0.1:PORT > bot.stdout 2>&1`
   It logs to `bot.log` (appends). bot.py reloads `settings.json` and `strategy.py` while running (botkit), so retune by editing those.
2. Watch loop in the foreground:
   `...python.exe -m generals_api.watch ws://127.0.0.1:PORT --max-wait 60 --state watch.json`
3. One-off orders: `...python.exe -m generals_api.order ws://127.0.0.1:PORT attack units=[1,2] target=40`

## Engine / API facts learned
- Skirmish start (Tournament Desert, 10000 cash): China gets a Command Center + ONE dozer. Bot trains a 2nd dozer first (1000).
- Starts: [1004,583] (south) and [1010,2102] (north). Map extent 2040 x 2700.
- `World.money` and `World.power` are PROPERTIES (not methods). `World.kinds(template)` is a method.
- `from generals_api.client import watcher_url` (not exported from the package).
- Snapshot own units: `status` list contains "idle", "under_construction", "harvesting"; `health`/`max_health`; `pos` is [x,y,z].
- Supply docks are only in `visible` when in sight. At frame 1270 none was visible from the CC on Tournament Desert; the bot
  falls back to placing the Supply Center near the CC when no source is visible yet (check in the log whether that happened).
- Catalog entries have `available_now` (prereqs met right now) and `cost`; use it to gate the build order.
- `game_info["players"]` has `relation` ("self"/"enemy") and `side`.
- The watch digest shows money/power/score, army and structures; exit 2 = game over.

## Build order facts (China catalog)
PowerPlant 1000/20s; Barracks 500/20s; SupplyCenter 1500/20s (needs Power); WarFactory 2000/30s (needs SupplyCenter);
PropagandaCenter 2000/90s (needs WF) unlocks Overlord 2000, Inferno 900, Nuke Cannon 1600, ECM, Hackers;
Gattling Cannon defense 1200 (needs Power); Bunker 400 (needs Barracks). Supply truck 600/20s. Dozer 1000/10s.
Upgrades of note: Upgrade_ChinaNationalism 2000 (horde bonus), Upgrade_ChinaUraniumShells 2500 (tank damage), Upgrade_ChinaRadar 500.
Sciences (1 point at start): SCIENCE_RedGuardTraining, SCIENCE_ArtilleryTraining, SCIENCE_NukeLauncher.

## TODO / ideas
- Verify the supply-dock placement and truck docking in the practice log.
- Add Upgrade_Nationalism and Uranium Shells once 2 WFs are up and money > 4000.
- Per-opponent faction picks via "vs" in bot.json once I know their factions.

## Practice game 1 findings (vs Easy AI, Tournament Desert, south start)
- NO supply dock is visible from the start position. Supply piles for the south start are at about (718,1233), (760,1229),
  (638,1457), (539,1405) = ~650 north-west of the CC (1004,583). Mirror guess for the north start: ~(1322,1467).
  settings.json `supply_hints` holds these; strategy places the Supply Center near the hint nearest home when no dock is in sight,
  and an idle truck scouts a ring around the base when no dock is known. Remembered dock ids keep working out of sight.
- Timeline achieved: Power 0:45 (after fixing bugs), SupplyCenter ~2:40, WF+Barracks ~3:00, 2nd Power ~3:30, income +689/min by 5:40
  with 4 trucks. Money hit 200 at 5:40: the bot overspends early; keep `trucks_per_center` 3 and consider `reserve`.
- Bugs hit: `world.money` is a property; catalog `available_now` is stale (World.catalog loaded once) -> check `prerequisites` against
  own finished structures; dozer orders were doubled because queued units are not in the snapshot -> 25 s cooldown.
- A dozer can show "idle" and still refuse a build with NOT_AVAILABLE for a few ticks (right after finishing a structure). Harmless retry.
- The watch tool's digest lists "supply near you" with coordinates and remaining dollars once trucks have seen docks.
- `visible` objects have `owner` (player index) but no `relation`; neutral junk (CarScrap, supply piles) is in it. Use
  `World.enemies()` / `World.enemy_structures()` to get real enemy objects. (Bug fixed: the bot "defended" against CarScrap.)
- `attack` on a remembered (fogged) structure from `known_structures` is refused with NOT_VISIBLE: attack_move to its `pos`
  first, then `attack` once `visible` is true. Strategy handles both.
- Easy AI (SupW America) built a Patriot Battery right next to my base by ~7:00 and harassed with Humvees/Rangers; it killed a
  supply truck on the long road to the docks (~650 away). Keep a Gattling tank near the trucks' route; consider a Gattling Cannon
  (1200) near the Supply Center.
- Supply piles also seen at (1421,1190): confirms the north-side docks are around x 1300-1420, y 1190-1470.
- Income: 4 trucks on one pile gave ~+1900-2600/min; the 10000 start is spent by ~5:30 with this build.
- Defend orders (every 5 s) and the forward-structure attack (every 10 s) interrupted each other; the defend branch now yields
  for 15 s after a "clear" order. General rule: give the army ONE order at a time and a cooldown; re-issuing orders resets attacks.
- By 8:00 vs Easy: 2 Battlemasters, 1 Gattling, 4 Tank Hunters, 1 WF; money-limited (~1650/min). A second supply center on the
  second pile cluster (638,1457 etc.) early would double income; consider build_order SupplyCenter x2 before 2nd WF.
- LESSON: 2 Battlemasters + 1 Gattling + 4 Tank Hunters died attacking one Patriot Battery (SupW). Never attack a defensive
  structure piecemeal: strategy now waits for a full wave (attack_size) unless the structure is within 350 of my buildings.
  Against America expect Patriots; bring 8+ tanks or Inferno Cannons/Nuke Cannons (need Propaganda Center) to outrange them.

## Real-game checklist (next session)
1. Confirm bot.json faction (FactionChina). Optionally add "vs" picks once opponents' factions are known.
2. Start bot.py in the background with the game's port; check bot.log for "connected in_game" and the first "build".
3. Watch loop in the foreground (`--max-wait 60 --state watch.json`); react by editing settings.json (attack_size, reserve,
   build_order, tank_mix) or strategy.py (reloads live; a syntax error keeps the last good version), or with generals_api.order.
4. Known weaknesses: one supply center (money-limited after 5:30), trucks travel 650 to the docks unescorted, no upgrades or
   generals' powers yet, attack wave of 8 never tested. If an opponent rushes early, lower attack_size and add a Gattling Cannon
   (needs Power) near the Supply Center; Bunker (400, needs Barracks) with Tank Hunters is cheap anti-vehicle defense.

## CORRECTION: the real supply dock (Tournament Desert)
- The MAIN `SupplyDock` (39150 supply) for the south start is at (632,127): ~570 south-west of the CC (1004,583), toward the
  map edge. The piles at y 1230-1450 are small `SupplyPileSmall` (3750 each) in the middle of the map (contested).
  Mirror guess for the north start (CC 1010,2102): dock at ~(1388,2573). settings.json `supply_hints` now holds these two.
- Trucks auto-harvested to the SupplyDock after the first pile ran dry ("harvesting" status) without an order. Prefer the dock:
  place the Supply Center near the hint (between CC and dock) and `dock` trucks on the SupplyDock (id from `visible`, kind
  SUPPLY_SOURCE) rather than the nearest pile. TODO in strategy: prefer sources with the largest `supply` within 800 of home.

## t2 Game 1 vs Bravo (China vs China) - VICTORY at 25:45, final score 97450
What Bravo did: mass Redguard hordes (12 at 3:23, 24 at 7:10, 35 at 11:49, 32 at 21:40) with a few Battlemasters, from a
FORWARD Supply Center + War Factory built mid-map near the piles (~y 1300-1500). Their main base was at the north start
(CC 1010,2102; Barracks 837,2002; Power 810/1210,2102) and ended up almost undefended.
What worked:
- 3 Gattling Cannons on the enemy-facing side of the base (home.x-120, home.y+230, radii 0..240). They farmed the hordes:
  score jumped 4-5k per wave. Build them EARLY (after the first WF) against China/infantry players.
- Holding (settings "hold": true) with the army parked at a rally under the cannons; tanks only "defend" against threats
  within 330 of a structure and the attack-move point is clamped to 380 from home. Before this fix the army chased raiders to
  mid-map and was wiped twice (lost 9 units at ~8:00 and 7 at ~21:50).
- Production saves for the next build-order item (memory["saving"] -> reserve), otherwise tanks starve every structure build.
- Second Supply Center placed by the mid-map piles (588,1281) at 19:30 when the main dock (40k) ran dry at ~17:00; income 3-6k/min.
- Attack-move (not attack) on a structure guarded by 4+ units, so tanks shoot the horde first.
- Release: set hold false + attack_size 14 at ~21:30 with 16 tanks (8 Gattling, 8 BM); clear_size 6-9 lets the "clear forward
  structure" branch roll through the enemy base structure by structure. Enemy CC died ~25:00, game over 25:45.
Mistakes: hold=true forgotten after reaching attack_size (army sat at 15 for a minute); one dozer lost delayed the first cannon
(dozer 1000 was retrained first -> set "dozers": 1 when money is tight). Trucks' "dock refused NOT_VISIBLE" on a depleted pile:
now forgets the source on NOT_VISIBLE/NOT_FOUND too.
Timeline: Power 0:45, SupplyCenter 1:39, WF 2:00, Barracks 2:11, 2nd Power 2:20, 2nd WF ~6:30, cannons 11:08/11:32/13:30.
Main SupplyDock (632,127) 40050 lasted until ~17:00 with 6 trucks (2.5-3k/min).
Opponent factions seen: Bravo = China (Redguard spam). If Bravo again: same plan, cannons right after WF1, Gattling-heavy mix,
and push at ~16 tanks when their horde has just died on my cannons (their forward base is at the mid-map piles).

## Game-2 start checklist (settings.json is pre-set: hold true, cannons early, SupplyCenter 2 last in build order)
- "rally" is unset (defaults to home-side). Set "rally": [790,1040] (south start) once the army is 10+ to cover the trucks' route
  to the mid-map piles; the mirror for a north start is about [1230,1650].
- SupplyCenter 2 is in the build order: it will be placed near the nearest known pile once the dock is dry (sources with 0
  supply are forgotten), so it comes automatically. Check that it is not placed too early (while the dock is still rich).
- Release: set "hold": false when army >= 14 AND an enemy wave has just died. clear_size 9 keeps forward clearing possible.
- If the opponent is NOT infantry-heavy (USA/GLA vehicles), switch tank_mix to BM-heavy and add a Bunker or two instead of cannon 3.

## t2 Game 2 vs Bravo (China vs China, NORTH start this time) - VICTORY at 13:28, score 44900
- Same settings as planned (hold, cannons early, Gattling/BM alternating). Timeline: Power 1:13, SC 1:44, WF 2:07, cannon 1 2:31,
  Barracks 2:25, Power 2 2:52, cannon 2 3:27, WF2 3:56, cannon 3 4:36. 14 tanks at 8:05, 22 at 10:20. Income 2.5-3.3k/min from the
  north SupplyDock@1408,2547 (40050). North start: CC (1010,2102); the bot's placements worked unchanged.
- Bravo did NOT attack at all: it turtled with ~26 Redguards + 2-3 BM + 2-3 Gattling parked at its own base (1050,750), trucks
  harvesting the mid-map piles (1385,1177 / 1534,1234). No defenses. Its structures: SC (1178,683), Barracks (1004,783), WF, 2 Power.
- SCOUTING WON THE GAME: new settings key "exclude": [ids] keeps units out of the army logic (regroup/defend/attack), so one
  Gattling tank (168) could be moved via `generals_api.order ... move units=[168] pos=[x,y]` to mid-map, then to (1150,950);
  it saw the whole enemy base at 10:19. Seeing no defenses and only infantry, I set hold false: 22 tanks (11 Gattling) rolled the
  horde (score +4k/min), then the "attack structure ... visible" branch killed Barracks, SC, Power, Barracks, CC -> game over 13:28.
- Lost only 2 tanks the whole game. The order tool uses `pos=[x,y]`, not `target=`.
- Lesson: when no enemy shows up by ~8:00 with 14 tanks, scout immediately and attack if the enemy has no static defenses.
  Against Redguard-heavy China a 50/50 Gattling/BM army of 20+ with no defenses to face is a sure win.
- Next-game ideas: automate the scout (exclude the first Gattling and walk it along the pile route from 8:00), auto-release when
  the scout sees an enemy base with no defensive structures and fewer tanks than mine. If the next opponent is USA/GLA with
  vehicles, shift tank_mix to 3 BM : 1 Gattling and keep the cannons (they also hit air).
- IMPLEMENTED after game 2 (untested in a live game): strategy.py auto-scout. With hold on and army >= "scout_at" (12), one
  Gattling tank is excluded from the army and walked home -> mid-map -> enemy_start (waypoints every 12 s). When enemy structures
  are seen with no defensive structure (GattlingCannon/Bunker/Patriot/Stinger/Tunnel/FireBase) and enemy tanks*2 < my army and
  army >= attack_size, it logs "AUTO-RELEASE" and forces hold off for the rest of the game (memory["released"]). Watch the log for
  it; if the enemy has defenses, release manually (hold false) once their wave has died on my cannons, as in game 1.
