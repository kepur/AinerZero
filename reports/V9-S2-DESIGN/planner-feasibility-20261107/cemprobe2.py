import sys, time, numpy as np
sys.path.insert(0, "tests/v9/experiments")
import test_s2_learned_planning as T
from ainerzero.v9.experiments.s2 import eval as E, planner, learned_planning as lp
from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter
W = T._worlds(2, 6)
class R: 
    def __init__(s,a): s.actions=a; s.counts={}; s.info={}
def make(arm, H, pop, iters, elite_n, n_exec, mode, warm):
    state={"prev":None}
    def plan_fn(obs, goal_obs, k, counter, rng):
        enc = counter.wrap("encode", arm.encode); p1 = counter.wrap("predict_l1", arm.predict_l1)
        z0 = enc(lp.featurize_obs(obs,k)); zg = counter.goal_embedding(lp.featurize_goal(goal_obs), enc)
        probs = np.full((H,4), 0.25)
        if warm and state["prev"] is not None:
            prev = state["prev"][n_exec:]
            for t,a in enumerate(prev): probs[t] = 0.1; probs[t,int(a)] = 0.7
        dts = lp._dts(k,H,1.7)
        best=None; bestc=np.inf
        for it in range(iters):
            pop_a = np.stack([np.array([rng.choice(4,p=probs[t]) for t in range(H)]) for _ in range(pop)])
            costs=np.empty(pop)
            for i in range(pop):
                z=z0; acc=0.0; mn=np.inf
                for t in range(H):
                    z=p1(z, np.array([pop_a[i,t]],dtype=float), float(dts[t])); d=float(np.sum((z-zg)**2)); acc+=d; mn=min(mn,d)
                costs[i] = {"terminal": d, "sum": acc, "min": mn}[mode]
            el = pop_a[np.argsort(costs)[:elite_n]]
            if costs.min()<bestc: bestc=costs.min(); best=pop_a[np.argmin(costs)].copy()
            probs = np.stack([np.bincount(el[:,t],minlength=4)/elite_n for t in range(H)])*0.9+0.025
        state["prev"]=best
        return R(best[:n_exec].astype(float).reshape(-1,1))
    return plan_fn
def trial(name, H, pop, iters, elite_n, n_exec, mode, warm):
    ok=0; t=time.time(); n=0
    for w,(layout, specs) in enumerate(W):
        for i, ep in enumerate(specs):
            arm=T.GeoPoseArm(layout, E._to_state(ep["goal"]))
            r=E.run_episode(layout, ep, make(arm,H,pop,iters,elite_n,n_exec,mode,warm), ForwardCounter(budget=4096), 100*w+i, m=4, catch_budget_exceeded=True)
            ok+=int(r.success); n+=1
    print(f"{name:22s} H={H} pop={pop} it={iters} elite={elite_n} exec={n_exec}: {ok}/{n}  {time.time()-t:.1f}s", flush=True)
trial("terminal", 16, 60, 4, 6, 4, "terminal", False)
trial("terminal+warm", 16, 60, 4, 6, 4, "terminal", True)
trial("sum", 16, 60, 4, 6, 4, "sum", False)
trial("min", 16, 60, 4, 6, 4, "min", False)
trial("sum+warm", 16, 60, 4, 6, 4, "sum", True)
