# Alpha: Notes

## Faction: FactionChina (plain China; templates have no prefix)

## How to start a real game
1. Bot (background): `C:\Users\user\Documents\CNC_Generals_AI\python\.venv\Scripts\python.exe C:\Users\user\Documents\CNC_Generals_AI\tournament\t2\agents\Alpha\bot.py ws://127.0.0.1:N > bot.out 2>&1`  (logs also in bot.log)
2. Foreground watch loop: `...python.exe -m generals_api.watch ws://127.0.0.1:N --max-wait 60 --state ...\Alpha\watch.json`
3. Tune live via `settings.json` (reloaded each tick): attack_size, hold, retreat, target [x,y], redguards,
   tank_hunters, gattling_every, max_dozers, trucks_per_center, extra_factory_money, upgrades.
   Restarting bot.py is safe (stateless; new controller replaces old, old exits).

## bot.py strategy
Power -> Barracks -> Supply Center (near nearest SupplyDock, 180 toward home) -> War Factory -> more power when surplus<3
-> Propaganda Center -> 2nd War Factory (money>3500) -> 2 Gattling Cannons. 2 dozers, 3 trucks/center.
Units: 6 Redguards, 4 Tank Hunters, then Battlemasters with every 3rd a Gattling tank, Overlords after Propaganda.
Attack wave at attack_size tanks; attack-move to enemy units near army, explicit `attack` on nearest known
enemy structure (<700) else attack-move to it, else enemy start. Regroup when tanks < attack_size/3.
Defend: any visible enemy within 900 of home -> whole army attack-moves there.

## API lessons (learned)
- Unit flags are in `u["status"]` list (e.g. "idle", "under_construction"), NOT top-level keys.
- Supply docks at game start appear in `known_structures` (template `SupplyDock`, `SupplyPileSmall`, owner 0/1 neutral),
  not in `visible`. `supply` field only when visible.
- Training at a building still under construction -> NOT_AVAILABLE.
- watcher snippet: `GeneralsClient(watcher_url(url))` for ad-hoc queries without displacing the bot.
- Start money 7500 in practice (Tournament Desert-like map, 2 players, start positions ~1500 apart N/S).

## Practice results (session 1)
- Bot reached WF + 2 Battlemasters + Gattling + 8 Redguards + 4 Tank Hunters by 4:10; income only ~1500/min with 1 center
  (the first center landed at mid-map piles, ~400 from home). Money was the bottleneck -> added 2nd Supply Center at the
  nearest SupplyDock >500 from existing centers, and production pauses (money<1700) until it exists. UNTESTED at end.
- TODO next session: verify 2nd center gets built; confirm attack wave + structure targeting works; consider fewer
  Redguards (8 queued > cap 6 because count checked before queue finishes) and more trucks; add Gattling Cannon earlier vs rushes.
- watch digest triggers seen: built, supply_low, max wait. It shows money/min, army, structures, nearby supply.

## Session 1, second practice game (fixes verified)
- 2nd Supply Center works: income went from ~1300/min to ~3300/min (6 trucks) by 3:30. Centers now placed 60-350 from
  the dock (spot = 180 toward home). Skip if every known SupplyDock already has a center within 500.
- bot.py now exits on ConnectionClosed (an orphan bot from a closed game used to loop forever writing bot.out).
- NOT_AVAILABLE refusals right after start are just prerequisites still under construction; harmless (retries ~6s).
- Home SupplyDock on this map (Tournament-Desert-like, me at 1005,584): SupplyDock@633,127 (~40k). Another at 1731,296.
- Attack wave verified: army reached enemy base (GLA Demo AI) by ~4:20 with 6-10 tanks, but buildings lost HP very
  slowly (CC 99%, barracks 76% after ~1.5 min). Likely cause: every 8s `push` re-targets (attack_move toward any
  visible enemy unit within 600 incl. workers -> drops building attacks; army center drifts). Enemy templates are
  not in world.templates, so kinds()-based STRUCTURE checks fail -> use `id in world.known_structures` instead (fixed).
- TOP TODO next session: in military(), keep a sticky target (only re-issue attack when the target died or
  changed), focus whole army on ONE structure (prefer CommandCenter / production / defenses), only switch to
  attack_move if armed enemy units (not workers) are near. Gather army at a rally point before pushing (units trickle).
- Also: money is always spent (~500 left) so PropagandaCenter / 2nd factory / Gattling Cannons never get built;
  consider a reserve when 2 centers exist (e.g. pause tanks every ~6 tanks to build Propaganda + 2nd WF).
- Default attack_size is 8 (settings.json empty = defaults).
- 11:41 implemented sticky targeting (focus one structure, re-issue only every 30s or on change; ignore workers/
  trucks when choosing attack_move targets). Result: GLA Barracks destroyed within ~20s of the change. Keep it.

## t2 game 3 vs Delta, game 1 of Bo3: VICTORY at ~7:00 game time
- Delta = FactionChina too. Rushed ~13 Redguards + 1-3 Battlemasters at 3:45. My defend (Gattling tanks + Redguards +
  Tank Hunters + 2 BMs) beat it cleanly; the chase reached their base (enemy start 1011,2103; me 1005,584 north).
- Delta had only 1 supply center; I had 2 (income ~4-5k/min). Set attack_size 6 at 5:10 -> wave of 7 tanks + infantry
  wiped CC/PP/Barracks/SupplyCenter/WF by 7:00. Default attack_size is now 6 in bot.py.
- Slow opening: first SupplyCenter only at 1:43 (NOT_AVAILABLE retries while dozers busy) - could start it earlier.
- `peek.py` = watcher script printing enemy and my army positions/health (World().load + apply_snapshot(state())).

## t2 game 4 vs Delta, game 2 of Bo3: VICTORY at 6:22 (series won 2-0)
- This time I spawned SOUTH (home ~1005,2400; enemy north ~1005,584). Bot handled both sides unchanged.
- Delta (China) again 1 supply center, 9 Redguards + 4 BMs at home. My 6-tank wave (4 BM + 2 Gattling + 8 RG + 4 TH)
  left at ~4:15, won the fight at their base at 4:50, all structures dead by 6:22. Income ~4.5-4.9k/min vs theirs much lower.
- Bot needed zero manual intervention. peek.py now takes the URL as argv[1].
- Still unused: Propaganda Center / 2nd WF / Overlords never built (money always spent) - fine vs this opponent.

## t2 game 5 vs Charlie (final, Bo3 game 1): VICTORY at 13:04
- Charlie = FactionChina. Turtles: 3 Gattling Cannons at its base (~900,850 when it is north) + 5 BM/3 Gattling/4 TH.
  My default 6-tank wave at 5:00 died to the cannons (lost all 8 Redguards + 2 Gattling tanks).
- Fix that won: retreat, attack_size 12-14, new `reserve` logic (after 4 tanks hold 2000 back until Propaganda + 2nd WF
  exist; settings `reserve`, `reserve_after`), extra_factory_money 2000. 2 WFs -> 15 tanks by 10:50; that wave crushed
  their army + cannons and the whole base by 13:04. Income ~4.5-5k/min, home docks ~half used by 10:00.
- Defaults now: attack_size 8, extra_factory_money 2000. Vs Charlie set attack_size ~12 from the start (settings.json).
- A NOT_AVAILABLE on a build can really be INSUFFICIENT_FUNDS (check with `order build ... --wait`).
- Bot restart mid-game is fine (it re-reads state).

## t2 game 6 vs Charlie (final, Bo3 game 2): VICTORY at ~15:20 (series won 2-0)
- Charlie switched to Tank General (templates `Tank_China...`): mass Tank Hunters (20+) + bunkers + 2 Gattling Cannons
  at its front (~890,1900 when it is south), 10 BMs later. My 12-tank wave at 6:00 lost badly to the TH blob.
- Fix that won: retreat + NEW `infernos` setting (Inferno Cannon, needs Propaganda Center). Over-queue gave 13 infernos
  (cap counts only finished units). 13 infernos + 12 tanks + 17 RG at 13:00 beat their whole army (it pushed into me)
  and razed the base by 15:20. Infernos also hurt my own units (firestorms) - lost ~5 of them.
- Next time vs turtle/infantry: set `infernos` 6-8 from the start (settings.json), attack_size ~12.
- `w.sh` = watch loop that suppresses repeated enemies_near_base-only digests (watch's base radius is large).
- TODO: inferno cap should count queued units; production QUEUE_FULL spam is harmless.
