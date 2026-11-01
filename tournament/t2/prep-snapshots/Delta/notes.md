# Delta: Notes

## Faction
- FactionChina (base side, no general). Chosen for a full tech tree, cheap Redguards, Battlemaster tanks.
- Templates (base side, names as in the catalog): ChinaVehicleDozer, ChinaPowerPlant, ChinaBarracks,
  ChinaWarFactory, ChinaInfantryRedguard, ChinaTankBattleMaster. Check the real names via `catalog()`:
  delta_bot.py resolves them by suffix so it works with the generals' prefixes too.

## Bot
- `delta_bot.py`: power plant, barracks (rally at HQ), war factory, then every `wave_interval` s trains a
  wave and attack-moves it to the enemy start. Tunables (`wave`, `wave_interval`, `tank`, `infantry`) are
  re-read from `settings.json` each wave, so you can retune during a game (via the watch loop or edit).
- Built from `python/bots/simple.py` (proven to run on any faction).

## API lessons (from the reference bots and BOT-NOTES.md)
- Start: `client.wait_for_state("in_game")`, then `world.load(client)`.
- `place()` tries a ring of spots; keep structures off the enemy side.
- Attack-move ignores plain buildings: to finish a base, send `attack` at `world.enemy_structures()`.
- Money is committed when an order is accepted; `INSUFFICIENT_FUNDS` means it was not.
- `build_failed` event means the spot was blocked when executing; retry another spot.

## Practice game observations (session 1)
- Practice game starts with about 8500 money; power plant and barracks were built within the first minute.
- The practice harness does NOT run your bot: it only starts the game and leaves the controller free.
  Attach with `run_delta.py ws://127.0.0.1:PORT` (logs to delta_bot.log).
- The watch digest shows built/army/structures and money; `built:` lists new structures.
- Power 10/0 means 10 produced, 0 consumed: no units were in production yet.
- Still open: whether the 30 s wave timing is too fast for the economy. Check delta_bot.log.

## Build-order lessons (practice, session 1)
- **War Factory needs a ChinaSupplyCenter** (catalog `prerequisites`). Without one, `build` is refused and
  `place()` returns None silently. Build the Supply Center right after the barracks.
- **Save money for the factory.** Redguard waves spent it first and the factory was refused with
  `INSUFFICIENT_FUNDS`. The bot now waits for `world.money >= cost` before the factory.
- A refused build prints in the runner's stdout (`runner_out.txt`), not in delta_bot.log.
- Restarting the runner in the same match is safe: existing structures are reused (`existing_or_build`).
  The old controller ends with close 4001 `superseded`; that line in delta_bot.log is expected.
- Supply trucks (`ChinaVehicleSupplyTruck`) raised income to about 625/min once the Supply Center stood.
- At 6:00 the War Factory stood, but income dropped to +0/min with 200 money left: the supply truck likely
  went idle. Next: check `idle`/`harvesting` on the truck and re-`dock` it on a visible supply pile.
- Waves get picked off by an enemy Gattling cannon near the enemy base: 7 Redguards lost by 6 minutes.
  Next: attack the cannon with the whole wave, or keep the wave at home until it reaches 8 units.
