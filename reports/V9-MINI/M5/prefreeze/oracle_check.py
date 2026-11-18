"""M5 冻结前检查 1：确认段留出图上的任务都可行（真值最短路 oracle 在步数预算内全部到达）。

只生成任务、只跑 oracle，不训练、不跑任何学习组，不读任何学习结果。
同时记录每套留出图的回合数、长目标与规律相关回合落在几张图上（用于按图重抽样的区间估计）。
用法：.venv/bin/python reports/V9-MINI/M5/prefreeze/oracle_check.py
"""
import json
from pathlib import Path

from ainerzero.v9.mini import agents as A, evaluate as E, world as W

N_LAYOUTS, SEEDS = 80, range(5)
out = {}
for world, cfg in (("m1", W.Config()), ("m2", W.Config(ice_rooms=2, portals=2))):
    for s in SEEDS:
        tasks = E.make_tasks(cfg, N_LAYOUTS, 400, 2, 4, eval_seed0=8_100_000 + 1000 * s)
        ok = 0
        for ti, t in enumerate(tasks):
            layout = W.make_layout(t["layout_seed"], cfg)
            ag = A.Oracle(layout, (t["goal"][0], t["goal"][1]), seed=ti)
            ok += E.run_episode(layout, t, ag, 2 * t["d_star"] + 20)["success"]
        longs = [t for t in tasks if t["kind"] == "long"]
        law = [t for t in tasks if t["law_relevant"]]
        out[f"{world}-s{s}"] = {"tasks": len(tasks), "oracle_success": ok, "long": len(longs),
                               "long_layouts": len({t["layout_seed"] for t in longs}),
                               "law_relevant": len(law), "law_layouts": len({t["layout_seed"] for t in law})}
        print(world, s, out[f"{world}-s{s}"], flush=True)
Path(__file__).with_name("oracle_check.json").write_text(json.dumps(out, indent=1))
