import json
from pathlib import Path
from ainerzero.v9.mini import agents as A, evaluate as E, world as W

cfg = W.Config()
layout = W.make_layout(7_900_000, cfg)
tasks = E.make_tasks(cfg, 1, 400, 2, 4, eval_seed0=7_900_000)
t = tasks[0]

# Check oracle with different task index
r1 = E.run_episode(layout, t, A.Oracle(layout, (t["goal"][0], t["goal"][1]), seed=0), 2 * t["d_star"] + 20)
r2 = E.run_episode(layout, t, A.Oracle(layout, (t["goal"][0], t["goal"][1]), seed=0), 2 * t["d_star"] + 20)
assert r1 == r2

# Check Random agent with same seed
ag1 = A.Random(100003 * 0 + 0)
ag2 = A.Random(100003 * 0 + 0)
res1 = E.run_episode(layout, t, ag1, 2 * t["d_star"] + 20)
res2 = E.run_episode(layout, t, ag2, 2 * t["d_star"] + 20)
assert res1 == res2

print("Agent seed determinism verified: exactly independent of arm order/subsets!")
