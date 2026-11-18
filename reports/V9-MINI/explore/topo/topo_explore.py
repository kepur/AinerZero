"""探索：SPTM 式拓扑组单独跑，并用真值做诊断（真值只进诊断，不进智能体）。不算证据。"""
import argparse
import fcntl
import json
import random
import sys
import time
from pathlib import Path

import mlx.core as mx
import numpy as np

from ainerzero.v9.mini import agents as A
from ainerzero.v9.mini import data as D
from ainerzero.v9.mini import evaluate as E
from ainerzero.v9.mini import topo as T
from ainerzero.v9.mini import world as W

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")

ap = argparse.ArgumentParser()
ap.add_argument("--world", default="m1")
ap.add_argument("--layouts", type=int, default=200)
ap.add_argument("--steps", type=int, default=6000)
ap.add_argument("--eval-layouts", type=int, default=30)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--out", required=True)
ap.add_argument("--plan", default="{}", help="TopoPlanConfig 覆盖，JSON")
ap.add_argument("--nets", help="复用已训练的权重（.npz）")
ap.add_argument("--oracle-ctrl", action="store_true", help="诊断：goto 用真值最短路执行（特权上限）")
args = ap.parse_args()

fh = open(ROOT / "artifacts/locks/m0-worker.lock", "a+")
try:
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("锁忙", flush=True)
    sys.exit(75)

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
cfg = W.Config() if args.world == "m1" else W.Config(ice_rooms=2, portals=2)
t0 = time.time()
ds = D.generate(args.layouts, 4, 200, cfg, seed0=D.TRAIN_SEED0 + 1000 * args.seed)
nets = T.TopoNets(ds.obs.shape[-1])
if args.nets:
    nets.load_weights(args.nets)
    info = {"loaded": args.nets}
else:
    nets, info = T.train_topo(ds, T.TopoConfig(steps=args.steps, seed=args.seed))
    nets.save_weights(str(out / "nets.npz"))
print(f"[train] {time.time() - t0:.0f}s", flush=True)
plan = T.TopoPlanConfig(**json.loads(args.plan))

# R 在留出游走上的校准：按真值位姿距离分桶
rows = []
for li in range(12):
    lay = W.make_layout(D.EVAL_SEED0 + li, cfg)
    rng = random.Random(D.EVAL_SEED0 + 13 * li)
    poses, _ = W.walk(lay, W.random_pose(lay, rng), 200, rng)
    e = nets.embed(mx.array(W.iter_views(lay, poses)))
    p = np.array(mx.sigmoid(nets.reach_logit(e[:, None], e[None])))
    pick = [(rng.randrange(len(poses)), rng.randrange(len(poses))) for _ in range(3000)]
    bfs_cache = {}
    for i, j in pick:
        if poses[i] not in bfs_cache:
            bfs_cache[poses[i]] = W.pose_bfs(lay, poses[i])
        rows.append((bfs_cache[poses[i]].get(poses[j], 999), p[i, j]))
arr = np.array(rows)
calib = {}
for lo, hi in ((0, 0), (1, 3), (4, 6), (7, 12), (13, 999)):
    m = (arr[:, 0] >= lo) & (arr[:, 0] <= hi)
    calib[f"{lo}-{hi}"] = {"n": int(m.sum()), "p_mean": float(arr[m, 1].mean()),
                           "frac_ge_0.95": float((arr[m, 1] >= 0.95).mean()), "frac_ge_0.5": float((arr[m, 1] >= 0.5).mean())}
print("[calib] 真值位姿距离分桶的 R 概率", json.dumps(calib, ensure_ascii=False), flush=True)

tasks = E.make_tasks(cfg, args.eval_layouts, 400, 2, 4, eval_seed0=D.EVAL_SEED0)
eps = []
for ti, task in enumerate(tasks):
    lay = W.make_layout(task["layout_seed"], cfg)
    poses = task["prefix_poses"]
    views = [W.ego_view(lay, p) for p in poses]
    obs = np.stack([W.encode_obs(v, p[2]) for v, p in zip(views, poses)])
    g = task["goal"]
    gv = W.ego_view(lay, g)
    ep = A.Episode(obs, views, [p[2] for p in poses], list(task["prefix_acts"]), W.encode_obs(gv, g[2]), gv, g[2])
    ag = T.TopoAgent(nets, plan, seed=args.seed * 100003 + ti)
    ag.reset(ep)
    # 诊断：捷径边连错（两端真值位姿距离 > 6 步）的比例；目标节点对不对
    sc_bad = sc_n = 0
    pb = {}
    for v, es in enumerate(ag.out):
        for u, _, kind in es:
            if kind == T.NEAR and u > v:
                sc_n += 1
                if poses[v] not in pb:
                    pb[poses[v]] = W.pose_bfs(lay, poses[v])
                if pb[poses[v]].get(poses[u], 999) > 6:
                    sc_bad += 1
    goal_ok = all((poses[v][0], poses[v][1]) == (g[0], g[1]) for v in ag.goal_nodes)
    budget = 2 * task["d_star"] + 20
    pose = task["start"]
    loc_err = []
    rb_cache = {}
    succ, steps = 0, budget
    dgoal = W.reverse_bfs_to_cell(lay, (g[0], g[1]))
    for t in range(budget):
        if (pose[0], pose[1]) == (g[0], g[1]):
            succ, steps = 1, t
            break
        v = W.ego_view(lay, pose)
        o_now = W.encode_obs(v, pose[2])
        if args.oracle_ctrl:
            kind, val, _ = ag.decide(o_now)
            if kind == "goto":
                cell = (g[0], g[1]) if val is None else (poses[val][0], poses[val][1])
                if cell not in rb_cache:
                    rb_cache[cell] = W.reverse_bfs_to_cell(lay, cell)
                dm = rb_cache[cell]
                a = int(np.argmin([dm.get(W.step(lay, pose, aa), 10 ** 6) for aa in range(3)]))
            else:
                a = int(val)
        else:
            a = ag.act(o_now, v, pose[2])
        npose = poses[ag.cur]
        loc_err.append(abs(npose[0] - pose[0]) + abs(npose[1] - pose[1]))
        pose = W.step(lay, pose, a)
    else:
        succ = int((pose[0], pose[1]) == (g[0], g[1]))
    eps.append({"kind": task["kind"], "success": succ, "steps": steps, "d_star": task["d_star"],
                "layout_seed": task["layout_seed"], "shortcuts": sc_n, "shortcuts_bad": sc_bad, "goal_nodes": len(ag.goal_nodes),
                "goal_ok": goal_ok, "loc_err_mean": float(np.mean(loc_err)) if loc_err else 0.0,
                "loc_err_gt2": float(np.mean(np.array(loc_err) > 2)) if loc_err else 0.0, "relocs": ag.relocalizations,
                "graph_d_start": float(ag.d_goal[len(poses) - 1]), "final_dist": dgoal.get(pose, 999)})
    if (ti + 1) % 30 == 0:
        print(f"  {ti + 1}/{len(tasks)} {time.time() - t0:.0f}s", flush=True)

summ = {}
for kind in ("short", "long"):
    sub = [e for e in eps if e["kind"] == kind]
    summ[kind] = {"n": len(sub), "success": float(np.mean([e["success"] for e in sub])),
                  "goal_ok": float(np.mean([e["goal_ok"] for e in sub])),
                  "loc_err_mean": float(np.mean([e["loc_err_mean"] for e in sub])),
                  "loc_err_gt2": float(np.mean([e["loc_err_gt2"] for e in sub])),
                  "graph_reachable": float(np.mean([np.isfinite(e["graph_d_start"]) for e in sub])),
                  "shortcuts_mean": float(np.mean([e["shortcuts"] for e in sub])),
                  "shortcuts_bad_frac": float(np.sum([e["shortcuts_bad"] for e in sub]) / max(1, np.sum([e["shortcuts"] for e in sub])))}
print("[summary]", json.dumps(summ, ensure_ascii=False, indent=1), flush=True)
(out / "result.json").write_text(json.dumps({"args": vars(args), "plan": plan.__dict__, "train": info, "calib": calib,
                                             "summary": summ}, ensure_ascii=False, indent=1))
(out / "episodes.json").write_text(json.dumps(eps))
print(f"[done] {time.time() - t0:.0f}s", flush=True)
