import sys, asyncio; sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, World
from generals_api.client import watcher_url
async def m():
    c = await GeneralsClient(watcher_url(sys.argv[1])).connect()
    await c.hello()
    w = World(); await w.load(c); w.apply_snapshot(await c.state())
    for e in w.enemies(): print('EN', e['id'], e['template'], [round(v) for v in e['pos'][:2]], e.get('health'))
    for u in w.units.values():
        if any(x in u['template'] for x in ('Tank','Infantry')): print('ME', u['id'], u['template'][5:], [round(v) for v in u['pos'][:2]], u.get('health'))
asyncio.run(m())
