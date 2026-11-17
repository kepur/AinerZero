"""评测：预测指标、代价诊断三项（r6 §5.3 / S2 收口 §8）、到达目标的回合。全部在留出图上。"""
from __future__ import annotations

import random
import time

import mlx.core as mx
import numpy as np

from . import agents as A
from . import world as W
from .data import EVAL_SEED0
from .model import WorldModel


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx = np.argsort(np.argsort(x)).astype(np.float64)
    ry = np.argsort(np.argsort(y)).astype(np.float64)
    rx -= rx.mean()
    ry -= ry.mean()
    return float((rx * ry).sum() / np.sqrt((rx ** 2).sum() * (ry ** 2).sum()))


def prediction_metrics(model: WorldModel, cfg: W.Config, n_layouts: int, horizon: int = 200, k: int = 5) -> dict:
    """一步与 k 步误差比：预测误差 / 「原地不动」的误差（S2 的一步误差比）。"""
    num1 = den1 = numk = denk = 0.0
    for i in range(n_layouts):
        layout = W.make_layout(EVAL_SEED0 + i, cfg)
        rng = random.Random(EVAL_SEED0 + 31 * i)
        poses, acts = W.walk(layout, W.random_pose(layout, rng), horizon, rng)
        z = model.encode(mx.array(W.iter_views(layout, poses)))
        a = mx.array(np.asarray(acts, dtype=np.int32))
        zp = model.predict(z[:-1], a)
        num1 += float(mx.sum((zp - z[1:]) ** 2))
        den1 += float(mx.sum((z[:-1] - z[1:]) ** 2))
        zh = z[:-k]
        for j in range(k):
            zh = model.predict(zh, a[j:len(acts) - k + j + 1])
        numk += float(mx.sum((zh - z[k:]) ** 2))
        denk += float(mx.sum((z[:-k] - z[k:]) ** 2))
    return {"one_step_ratio": num1 / den1, f"{k}_step_ratio": numk / denk}


def cost_diagnostics(model: WorldModel, cfg: W.Config, n_layouts: int, pairs_per_layout: int = 200) -> dict:
    """代价与真实最少动作数的秩相关，全部配对和长距离（真值 ≥ 20）分开报。"""
    rows = []
    for i in range(n_layouts):
        layout = W.make_layout(EVAL_SEED0 + i, cfg)
        rng = random.Random(EVAL_SEED0 + 57 * i)
        goals = [W.random_pose(layout, rng) for _ in range(8)]
        for g in goals:
            dist = W.reverse_bfs_to_cell(layout, (g[0], g[1]))
            starts = [W.random_pose(layout, rng) for _ in range(pairs_per_layout // 8)]
            zs = model.encode(mx.array(W.iter_views(layout, starts)))
            zg = mx.broadcast_to(model.encode(mx.array(W.iter_views(layout, [g]))), zs.shape)
            eu = np.array(mx.sqrt(mx.sum((zs - zg) ** 2, axis=-1)))
            le = np.array(model.reach(zs, zg))
            for s, e, l in zip(starts, eu, le):
                rows.append((dist[s], e, l))
    arr = np.array(rows, dtype=np.float64)
    out = {"n_pairs": len(rows)}
    for name, mask in (("all", np.ones(len(arr), bool)), ("far_ge20", arr[:, 0] >= 20)):
        sub = arr[mask]
        out[f"rho_euclid_{name}"] = _spearman(sub[:, 1], sub[:, 0])
        out[f"rho_learned_{name}"] = _spearman(sub[:, 2], sub[:, 0])
    return out


def _unique_views(layout: W.Layout) -> dict:
    counts: dict = {}
    for (x, y) in layout.free_cells():
        for h in range(4):
            key = (W.ego_view(layout, (x, y, h)).tobytes(), h)
            counts[key] = counts.get(key, 0) + 1
    return counts


def make_tasks(cfg: W.Config, n_layouts: int, prefix_len: int, n_short: int, n_long: int) -> list[dict]:
    """每张留出图：一段探索前缀（随机游走），任务从前缀终点出发，目标取前缀里见过的、视野唯一的位姿。"""
    tasks = []
    for i in range(n_layouts):
        layout = W.make_layout(EVAL_SEED0 + i, cfg)
        rng = random.Random(EVAL_SEED0 + 101 * i)
        uniq = _unique_views(layout)
        poses, acts = W.walk(layout, W.random_pose(layout, rng), prefix_len, rng)
        start = poses[-1]
        dstart = W.pose_bfs(layout, start)
        cell_d: dict = {}
        for (x, y, _), d in dstart.items():
            cell_d[(x, y)] = min(d, cell_d.get((x, y), 10 ** 6))
        cands = {"short": [], "long": []}
        for p in set(poses[:-1]):
            if uniq[(W.ego_view(layout, p).tobytes(), p[2])] != 1 or (p[0], p[1]) == (start[0], start[1]):
                continue
            d = cell_d.get((p[0], p[1]))
            if d is None:
                continue
            if 4 <= d <= 10:
                cands["short"].append((p, d))
            elif d >= 20:
                cands["long"].append((p, d))
        for kind, n in (("short", n_short), ("long", n_long)):
            cs = sorted(cands[kind])
            rng.shuffle(cs)
            for g, d in cs[:n]:
                tasks.append({"layout_seed": EVAL_SEED0 + i, "kind": kind, "start": start, "goal": g,
                              "d_star": d, "prefix_poses": poses, "prefix_acts": acts})
    return tasks


def run_episode(layout: W.Layout, task: dict, agent, budget: int) -> dict:
    poses = task["prefix_poses"]
    views = [W.ego_view(layout, p) for p in poses]
    obs = np.stack([W.encode_obs(v, p[2]) for v, p in zip(views, poses)])
    g = task["goal"]
    gv = W.ego_view(layout, g)
    ep = A.Episode(obs, views, [p[2] for p in poses], list(task["prefix_acts"]), W.encode_obs(gv, g[2]), gv, g[2])
    agent.reset(ep)
    pose = task["start"]
    for t in range(budget):
        if (pose[0], pose[1]) == (g[0], g[1]):
            return {"success": 1, "steps": t}
        if isinstance(agent, A.Oracle):
            a = agent.act_pose(pose)
        else:
            v = W.ego_view(layout, pose)
            a = agent.act(W.encode_obs(v, pose[2]), v, pose[2])
        pose = W.step(layout, pose, a)
    ok = int((pose[0], pose[1]) == (g[0], g[1]))
    return {"success": ok, "steps": budget}


ARMS = ("random", "latent_euclid", "latent_learned", "graph_memory", "analytic_map", "oracle")


def evaluate_tasks(model: WorldModel, cfg: W.Config, tasks: list[dict], arms=ARMS, seed: int = 0, log=print) -> dict:
    results = {arm: [] for arm in arms}
    t0 = time.time()
    for ti, task in enumerate(tasks):
        layout = W.make_layout(task["layout_seed"], cfg)
        budget = 2 * task["d_star"] + 20
        for arm in arms:
            s = seed * 100003 + ti
            if arm == "random":
                ag = A.Random(s)
            elif arm == "latent_euclid":
                ag = A.LatentTree(model, "euclid", seed=s)
            elif arm == "latent_learned":
                ag = A.LatentTree(model, "learned", seed=s)
            elif arm == "graph_memory":
                ag = A.Graph(model, seed=s)
            elif arm == "analytic_map":
                ag = A.AnalyticMap(cfg, seed=s)
            else:
                ag = A.Oracle(layout, (task["goal"][0], task["goal"][1]), seed=s)
            r = run_episode(layout, task, ag, budget)
            r.update(kind=task["kind"], d_star=task["d_star"])
            results[arm].append(r)
        if (ti + 1) % 20 == 0:
            log(f"  episodes {ti + 1}/{len(tasks)}  {time.time() - t0:.0f}s")
    summary = {}
    for arm, rs in results.items():
        for kind in ("short", "long"):
            sub = [r for r in rs if r["kind"] == kind]
            if not sub:
                continue
            succ = np.array([r["success"] for r in sub], dtype=np.float64)
            spl = np.array([r["success"] * r["d_star"] / max(r["d_star"], r["steps"]) for r in sub])
            summary[f"{arm}/{kind}"] = {"n": len(sub), "success": float(succ.mean()), "spl": float(spl.mean()),
                                        "successes": int(succ.sum())}
    return {"summary": summary, "episodes": results}
