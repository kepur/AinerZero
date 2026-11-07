import sys, time, numpy as np
sys.path.insert(0, "tests/v9/experiments")
import test_s2_learned_planning as T
from ainerzero.v9.experiments.s2 import eval as E, planner, learned_planning as lp
from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter
W = T._worlds(2, 6)
def make(arm, cfg):
    def plan_fn(obs, goal_obs, k, counter, rng):
        enc = counter.wrap("encode", arm.encode); p1 = counter.wrap("predict_l1", arm.predict_l1)
        return planner.flat_cem_plan(encode=enc, predict_l1=p1, obs=lp.featurize_obs(obs,k), goal_obs=lp.featurize_goal(goal_obs), config=cfg, rng=rng, counter=counter, dts=lp._dts(k, cfg.horizon, 1.7))
    return plan_fn
def trial(name, H, pop, iters, elite, n_exec, m):
    ok=0; t=time.time(); n=0
    for w,(layout, specs) in enumerate(W):
        for i, ep in enumerate(specs):
            arm=T.GeoPoseArm(layout, E._to_state(ep["goal"]))
            cfg=planner.FlatCEMConfig(horizon=H, n_iters=iters, pop_size=pop, elite_frac=elite, action_dim=1, n_exec=n_exec, n_categories=4)
            r=E.run_episode(layout, ep, make(arm,cfg), ForwardCounter(budget=4096), 100*w+i, m=m, catch_budget_exceeded=True)
            ok+=int(r.success); n+=1
    print(f"{name:28s} H={H} pop={pop} it={iters} el={elite} exec={n_exec} m={m}: {ok}/{n}  {time.time()-t:.1f}s", flush=True)
trial("P154-like", 10, 16, 3, 0.25, 2, 2)
trial("P154 params m=4", 10, 16, 3, 0.25, 4, 4)
trial("D3.1 H16 elite.25", 16, 63, 4, 0.25, 4, 4)
trial("D3.1 H16 exec2 m2", 16, 63, 4, 0.1, 2, 2)
trial("H16 pop63 it4 el.25 m2", 16, 63, 4, 0.25, 2, 2)
