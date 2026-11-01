# Bot1 notes
- We are north (CC ~1010,2102), enemy start (1004,583). Own player index 2, enemy 3. Owners 0/1 = neutral/civilian.
- Supply docks near us: (1408,2547) main, (268,2397) secondary. Oil derrick (1764,1876).
- Plan: power -> supply center (3 chinooks) -> barracks -> 2-3 war factories pumping Paladin/Crusader/Tomahawk,
  strategy center (bombardment plan, composite armor), patriots at front. Defend when enemies within 900 of CC,
  attack-move waves (8, then grow) to nearest known enemy structure.
- Bot: bot.py (logs bot.log). Bought SCIENCE_PaladinTank at start.

## Learned (live)
- Snapshot status flags are lowercase (`under_construction`); own buildings have `construction_percent`.
- Neutral SupplyDock disappears from known_structures once visible -> it's in `visible` instead. Union both.
- Gameplay: Money is deducted when the dozer starts building; if spent on units meanwhile, construction_started never comes. Added budget reservation.
- `enter` on TechOilDerrick with a Ranger -> CANNOT_ENTER (capture needs Upgrade_InfantryCaptureBuilding / no neutral capture path).
- use_ability accepted Command_SpectreGunship / Command_Paradrop / Command_DaisyCutter on the CC without owning those sciences (reply ok).
  Suspected API bug (button availability doesn't check science). Restricted bot to powers we bought.
- Enemy (Bot2) built a forward line in the middle (~800-1000, 1100) with Patriots + Fire Bases. First 8-unit attacks died there.
- Restarting the bot resets job lists; it skips structures already owned.
- Docks ran dry around frame 34k; enemy used a Supply Drop Zone + Particle Cannon. Lost at frame 64924 (defeat).
