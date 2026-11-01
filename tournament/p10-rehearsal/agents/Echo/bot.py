import asyncio, math, sys
sys.path.insert(0, r'C:\Users\user\Documents\CNC_Generals_AI\python')
sys.path.insert(0, r'C:\Users\user\Documents\CNC_Generals_AI\python\bots')
from generals_api import GeneralsClient, World, ApiError
from simple import place, build, mine

async def main():
    c = GeneralsClient('ws://127.0.0.1:59985'); await c.connect()
    w = World().attach(c); await w.load(c)
    info = w.game_info
    for _ in range(20):
        snap = await c.state()
        b = mine(snap, 'ChinaVehicleDozer')
        if b: break
        await asyncio.sleep(.5)
    hq = next(u for u in snap['units'] if u['template'].endswith('CommandCenter'))
    home = hq['pos']
    enemy = max(info['start_positions'], key=lambda p: math.dist(p, home[:2]))
    dz = b[0]['id']
    async def sb(t):
        try: return await build(c, dz, t, home)
        except Exception as e: print('build fail', t, e)
    await sb('Tank_ChinaPowerPlant')
    await sb('Tank_ChinaSupplyCenter')
    wf = await sb('Tank_ChinaWarFactory')
    bar = await sb('Tank_ChinaBarracks')
    if wf: await c.set_rally_point(wf, home)
    n = 0
    while True:
        for _ in range(2):
            try: await c.train(wf, 'Tank_ChinaTankBattleMaster', count=1)
            except ApiError: pass
        await asyncio.sleep(25)
        n += 1
        if n == 6:
            await sb('Tank_ChinaPowerPlant')
        snap = await c.state()
        tanks = [u['id'] for u in snap['units'] if u['template'].endswith('TankBattleMaster') and not u.get('contained_by')]
        if len(tanks) >= 6:
            try:
                w.apply_snapshot(snap)
                st = w.enemy_structures()
                if st:
                    t = min(st, key=lambda s: math.dist(s['pos'][:2], enemy))
                    await c.attack(tanks, t['id'])
                else:
                    await c.attack_move(tanks, enemy)
            except Exception as e:
                print('atk', e)
                try: await c.attack_move(tanks, enemy)
                except Exception: pass
asyncio.run(main())
