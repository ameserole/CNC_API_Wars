"""Starts a LAN match between two script-controlled players (Bot1 and Bot2, both America) plus a human
observer window, on Tournament Desert.

Sets the match up, disconnects from every client so the agents can connect to their own ports, writes
the ports to match.json, then waits until both bot games exit.
"""
import asyncio, json, sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\user\Documents\CNC_Generals_AI\python")
from generals_api import GeneralsClient, launcher

HERE = Path(__file__).parent


async def main():
    args = launcher.parse_args(["--bot1", "unused.py", "--bot2", "unused.py", "--observer"])
    plan = launcher.make_plan(args)
    procs, clients = {}, {}
    for inst in plan.instances:
        procs[inst.role] = launcher.launch(inst, launcher.DEFAULT_GAME_DIR, ["-ignoreAsserts"])
    for inst in plan.instances:
        await launcher.wait_for_port(inst.port, procs[inst.role])
        clients[inst.role] = await GeneralsClient(f"ws://127.0.0.1:{inst.port}", request_timeout=60).connect()
        await clients[inst.role].hello()
    map_name = launcher.pick_map(await clients["bot1"].skirmish_options(), args.map)
    await launcher.setup_lan(plan, clients, map_name)
    for inst in plan.instances:
        await clients[inst.role].wait_for_state("in_game", timeout=launcher.LOAD_TIMEOUT)
    for c in clients.values():
        await c.close()
    info = {"bot1_url": f"ws://127.0.0.1:{plan.instance('bot1').port}",
            "bot2_url": f"ws://127.0.0.1:{plan.instance('bot2').port}",
            "observer_port": plan.instance("observer").port, "map": map_name,
            "pids": {r: p.pid for r, p in procs.items()}}
    (HERE / "match.json").write_text(json.dumps(info, indent=2))
    print("MATCH READY", json.dumps(info), flush=True)
    while procs["bot1"].poll() is None or procs["bot2"].poll() is None:
        await asyncio.sleep(5)
    print("bot games exited:", procs["bot1"].returncode, procs["bot2"].returncode, flush=True)

asyncio.run(main())
