"""S2 修数据诊断（一级 claude，2026-11-09，用户「全权接手自动授权」）。

只改一处：探索段的寻路改用反向 BFS（进程内替换 s2.data._find_path_step，不改源码）。
世界、种子、步数、臂、规划配置都与 S2 phase 1 相同。每臂只训练种子 42。
产物全部在 --out（artifacts/ 之外），不写 S2 账本，不碰 artifacts/v9/s2/phase1 的内容。
结果只作诊断，不是登记结论，不改变 S2 已收口的状态。硬上限 90 分钟。
"""
import argparse, collections, fcntl, json, random, statistics as st, sys, time
from pathlib import Path
import numpy as np
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero"); sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s2 import adapters_mlx, data as D, eval_runner, learned_planning as lp, spec, train_runner as tr, world as W
from ainerzero.v9.experiments.s3.world import compute_reverse_bfs_distances, step_to_goal

ORIG = REPO / "artifacts/v9/s2/phase1"
ARMS = ("arm_a", "arm_b", "arm_c")
BASE = {"long_success": {"arm_a": 0.0, "arm_b": 0.0, "arm_c": 0.0},
        "short_success": {"arm_a": 0.0, "arm_b": 0.0, "arm_c": 0.05},
        "spearman": {"arm_a": 0.286, "arm_b": -0.087, "arm_c": 0.127},
        "one_step_ratio": {"arm_a": 2.785, "arm_b": 0.036, "arm_c": 0.299}}
_cache = {}
def fixed_find_path_step(layout, state, target, *, dist_from_goal=None):
    if D._pose_reached_cell(state, target) and state.heading == target.heading:
        return W.ACTION_WAIT
    key = (layout.layout_sha256, target.x, target.y)
    if key not in _cache:
        if len(_cache) > 4000: _cache.clear()
        _cache[key] = compute_reverse_bfs_distances(layout, (target.x, target.y))
    return step_to_goal(layout, state, _cache[key])

def spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b)); return float(np.corrcoef(ra, rb)[0, 1])
def layout_of(train, w):
    lay = json.load(open(train / f"world_{int(w):04d}" / "layout.json"))
    return W.Layout(seed=int(lay["seed"]), terrain=[list(r) for r in lay["terrain"]], rooms=[tuple(r) for r in lay["rooms"]], doors=[tuple(x) for x in lay["doors"]], pillars=[tuple(p) for p in lay["pillars"]], layout_sha256=str(lay["layout_sha256"]))

def audit(train, limit):
    act = collections.Counter(); bfs = collections.Counter(); U = []; T = []; R = []; n = 0
    for p in sorted(train.glob("world_*/episode_*.json"))[:limit]:
        e = json.load(open(p)); n += 1; cells = []
        for s in e["steps"]:
            act[s["action"]] += s["dt"]
            if s["segment_kind"] == "bfs": bfs[s["action"]] += s["dt"]
            t = s["truth_after"]; cells.append((t["x"], t["y"]))
        c = collections.Counter(cells); U.append(len(c)); T.append(c.most_common(1)[0][1] / len(cells))
        last = {}; prev = None; r = 0
        for i, x in enumerate(cells):
            if x != prev and x in last and i - last[x] >= 60: r += 1
            last[x] = i; prev = x
        R.append(r)
    tot = sum(act.values()); tb = max(1, sum(bfs.values()))
    return {"episodes": n, "wait_share": act[W.ACTION_WAIT] / tot, "bfs_segment_wait_share": bfs[W.ACTION_WAIT] / tb,
            "unique_cells_median": st.median(U), "top_share_median": st.median(T), "return_ge60_median": st.median(R)}

def landscape(train, models, hold):
    out = {}
    trans = []
    for w in hold[:8]:
        st_ = json.load(open(train / f"world_{int(w):04d}" / "episode_0000.json"))["steps"]
        for i in range(len(st_) - 1):
            trans.append((st_[i]["student_obs"], st_[i]["action"], st_[i]["dt"], st_[i + 1]["student_obs"]))
    trans = trans[:300]
    rng = random.Random(7)
    for a, m in models.items():
        ep, ei = [], []
        for o, act, dt, o2 in trans:
            z = m.encode(lp.featurize_obs(o, int(o["dt"]))); z2 = m.encode(lp.featurize_obs(o2, int(o2["dt"])))
            p = m.predict_l1(z, int(act), float(dt)); ep.append(np.linalg.norm(p - z2)); ei.append(np.linalg.norm(z - z2))
        lat, bfs = [], []
        for w in hold[:8]:
            L = layout_of(train, w)
            for _ in range(25):
                try: s, g, go, stt = W.sample_start_goal_pair(L, rng, kind=rng.choice(["short", "long"]))
                except Exception: continue
                zg = m.encode(lp.featurize_goal(go))
                v = W.compute_ego_view(L, s.x, s.y, s.heading)
                obs = {"view": v, "heading": [1 if i == s.heading else 0 for i in range(4)], "last_action": [0, 0, 0, 1], "dt": 1}
                zs = m.encode(lp.featurize_obs(obs, 1)); lat.append(float(np.linalg.norm(zs - zg))); bfs.append(int(stt["bfs_distance"]))
        out[a] = {"one_step_ratio": float(np.mean(ep) / max(1e-12, np.mean(ei))), "spearman": spearman(np.array(lat), np.array(bfs)), "n_pairs": len(lat)}
    return out

def short_specs(train, hold, per_world):
    out = []
    for w in hold[:10]:
        L = layout_of(train, w); rng = random.Random(1000 + int(w))
        lay = json.load(open(train / f"world_{int(w):04d}" / "layout.json"))
        for _ in range(per_world):
            s, g, go, stt = W.sample_start_goal_pair(L, rng, kind="short")
            out.append({"episode_index": len(out), "world_index": int(w), "kind": "short", "start": W.truth(s), "goal": W.truth(g), "bfs_distance": int(stt["bfs_distance"]), "partition": "train", "layout": lay})
    return out

def long_specs(train, hold, cap):
    # 与 commands.py 的 plan-select 取法逐条一致
    out = []
    for w in hold:
        d = train / f"world_{int(w):04d}"; p = d / "goal_episode_specs.json"
        if not p.is_file(): continue
        for s in json.load(open(p)):
            s["partition"] = "train"
            if (d / "layout.json").is_file() and "layout" not in s: s["layout_path"] = str(d / "layout.json")
            out.append(s)
    return out[:cap]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--report", required=True); ap.add_argument("--smoke", action="store_true"); a = ap.parse_args()
    t0 = time.monotonic(); limit = 5400.0
    left = lambda: limit - (time.monotonic() - t0)
    out = Path(a.out).resolve(); report = Path(a.report).resolve(); report.parent.mkdir(parents=True, exist_ok=True)
    assert "artifacts" not in out.parts, out
    R = {"schema": "s2.fixed_data_diagnostic.v1", "smoke": a.smoke, "baseline_defective_data": BASE, "stages": {}}
    def save(): report.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
    def stage(n, v): R["stages"][n] = v; R["elapsed_s"] = round(time.monotonic() - t0, 1); save(); print(f"[{R['elapsed_s']:8.1f}s] {n}: {str(v)[:300]}", flush=True)
    n_worlds, eps, steps = (8, 8, 6) if a.smoke else (int(spec.TRAIN_N_WORLDS), int(spec.TRAIN_EPISODES_PER_WORLD), 2757)
    D._find_path_step = fixed_find_path_step
    ns = spec.SEED_NAMESPACES["train"]
    m = D.generate_partition("train", n_worlds, eps, out / "datasets", ns)
    train = out / "datasets" / "train"
    orig = json.load(open(ORIG / "datasets/train/manifest.json"))
    same = list(m["layout_digests"]) == list(orig["layout_digests"])[:n_worlds]
    stage("data", {"n_worlds": n_worlds, "episodes_per_world": eps, "layouts_identical_to_s2": same})
    if not same: raise SystemExit("世界布局与 S2 不一致，停止")
    A = audit(train, 500 if not a.smoke else 16); stage("data_audit", A)
    if not a.smoke and A["bfs_segment_wait_share"] > 0.10: raise SystemExit("修正后 BFS 段 WAIT 仍过高，停止")
    lock = (REPO / "artifacts/locks/m0-worker.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)      # 与现有 CLI 共用同一把锁，忙则直接失败
    stage("lock", {"held": True})
    for arm in ARMS:
        cap = min(1200.0, left() - 1500) if not a.smoke else 300.0
        if cap < 60: stage(f"train_{arm}", {"status": "skipped_no_time"}); continue
        r = tr.run_train_cell(lambda: adapters_mlx.make_mlx_arm(arm), arm, 42, out, out, steps, wall_budget_seconds=cap)
        stage(f"train_{arm}", {k: r.get(k) for k in ("status", "steps", "steps_completed", "wall_seconds", "elapsed_seconds", "best_step", "best_holdout", "checkpoint_sha256")})
    models = {}
    for arm in ARMS:
        ck = adapters_mlx.checkpoint_path(out, arm, 42)
        if ck.is_file():
            mdl = adapters_mlx.make_mlx_arm(adapters_mlx.canonical_arm(arm)); mdl.load(ck); models[arm] = mdl
    hold = json.load(open(train / "HOLDOUT_WORLDS.json"))["holdout_worlds"]
    stage("landscape", landscape(train, models, hold))
    pc = json.load(open(ORIG / "plan_config.json"))
    n_short = 1 if a.smoke else 2; n_long = 2 if a.smoke else 50
    sp_s = short_specs(train, hold, n_short); sp_l = long_specs(train, hold, n_long)
    stage("specs", {"short": len(sp_s), "long": len(sp_l)})
    res = {}
    for arm, mdl in models.items():
        cfg = pc["arms"][arm]["plan_choice"]; res[arm] = {"config": cfg}
        res[arm]["short_success"] = float(eval_runner._score_config_on_train(mdl, cfg, sp_s, n_fwd=int(spec.N_FWD), dataset_dir=train)); stage("short_" + arm, res[arm])
    for arm, mdl in models.items():
        if left() < 120: res[arm]["long_success"] = None; res[arm]["long_note"] = "超时未跑"; continue
        cfg = pc["arms"][arm]["plan_choice"]
        res[arm]["long_success"] = float(eval_runner._score_config_on_train(mdl, cfg, sp_l, n_fwd=int(spec.N_FWD), dataset_dir=train)); stage("long_" + arm, res[arm])
    stage("planning", res); fcntl.flock(lock, fcntl.LOCK_UN); stage("done", {"total_s": round(time.monotonic() - t0, 1)})
main()
