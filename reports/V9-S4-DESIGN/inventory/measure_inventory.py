#!/usr/bin/env python3
"""S4 可行性盘点的行为实测（只读、纯 CPU）。

用法（仓库根目录）：
    PYTHONDONTWRITEBYTECODE=1 timeout 120 .venv/bin/python \
        reports/V9-S4-DESIGN/inventory/measure_inventory.py --ledger-copies <临时目录>

约束：
- 不导入 MLX / torch（下面直接屏蔽，真有人导入就报错）；
- 只写本脚本所在目录的 metrics.json；
- 对 artifacts/ 只读：S1 的 train 包与真值、E1 raw 的 train 序列；
  不读 final-sealed、raw/*/final、sealed_final；
- 账本只读传入的临时副本，不打开 artifacts/ 下的 sqlite；
- 不调用 S1、E1 的 verify/worker 入口。

「重现」定义（全文件统一）：
    对象 k 在第 a 步可见，在 a+1 .. b-1 步全部不可见（gap = b-a-1 >= 1），在第 b 步再次可见。
    - 首次出现不算；一直可见的对象没有事件；消失后回合结束没回来的只记 censored，不算事件。
    - cause：隐藏区间全是遮挡 = occluded，全是视野外 = out_of_view，否则 mixed。
    - moved：对象在 a 与 b 的真值位置不同。
    - agent_moved：智能体在 a 与 b 的位置不同（排除原地转头）。
    - ambiguous_appearance：第 b 步有另一个在此之前见过的对象，外观相同。
    - nn_confusable：第 b 步未被观察到的同外观对象里，有一个的最后观测位置
      不比 k 自己的最后观测位置更远（按最后位置最近邻会错或打平）。
    - hard = moved 且 ambiguous_appearance。这是真正需要「持久身份」的子集：
      对象不在原地，外观又认不出来。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
for _blocked in ("mlx", "mlx.core", "mlx.nn", "torch", "jax"):
    sys.modules[_blocked] = None  # type: ignore[assignment]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AWZ_ROOT = ROOT.parent / "AnimeWorldZero"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(AWZ_ROOT / "python"))

import numpy as np  # noqa: E402

GAP_BUCKETS = ((1, 2), (3, 7), (8, 29), (30, 79), (80, 10**9))
START = time.monotonic()


def budget_left(limit: float) -> float:
    return limit - (time.monotonic() - START)


# ---------------------------------------------------------------- 通用分析


def analyze_episode(vis, pos, app, agent=None, eps: float = 1e-6) -> dict:
    """vis[k][t] in {visible, occluded, out_of_view}；pos[k][t] 元组；app[k][t] 外观。"""
    n = len(vis)
    T = len(vis[0]) if n else 0
    agent = agent or [None] * T
    first_seen = [next((t for t in range(T) if vis[k][t] == "visible"), None) for k in range(n)]
    last_seen_before = [dict() for _ in range(n)]
    for k in range(n):
        last = None
        for t in range(T):
            last_seen_before[k][t] = last  # t 之前最近一次可见的步
            if vis[k][t] == "visible":
                last = t
    events, always, never, intermittent, censored = [], 0, 0, 0, 0
    visible_steps = 0
    for k in range(n):
        seen = [t for t in range(T) if vis[k][t] == "visible"]
        visible_steps += len(seen)
        if not seen:
            never += 1
            continue
        if len(seen) == T:
            always += 1
            continue
        intermittent += 1
        if seen[-1] < T - 1:
            censored += 1
        for a, b in zip(seen, seen[1:]):
            if b == a + 1:
                continue
            hidden = set(vis[k][a + 1 : b])
            cause = "occluded" if hidden == {"occluded"} else ("out_of_view" if hidden == {"out_of_view"} else "mixed")
            disp = float(math.dist(pos[k][a], pos[k][b]))
            agent_moved = None
            if agent[a] is not None and agent[b] is not None:
                agent_moved = bool(math.dist(agent[a], agent[b]) > eps)
            same_app_seen = [
                j for j in range(n)
                if j != k and first_seen[j] is not None and first_seen[j] <= b and app[j][b] == app[k][b]
            ]
            own_d = float(math.dist(pos[k][a], pos[k][b]))
            confusable = False
            for j in same_app_seen:
                if vis[j][b] == "visible":
                    continue
                ls = last_seen_before[j][b]
                if ls is not None and math.dist(pos[j][ls], pos[k][b]) <= own_d + eps:
                    confusable = True
                    break
            events.append({
                "k": k, "a": a, "b": b, "gap": b - a - 1, "cause": cause, "disp": disp,
                "moved": disp > eps, "agent_moved": agent_moved,
                "ambiguous": bool(same_app_seen), "confusable": confusable,
                "appearance_changed": app[k][a] != app[k][b],
            })
    return {"T": T, "n": n, "events": events, "always": always, "never": never,
            "intermittent": intermittent, "censored": censored, "visible_steps": visible_steps,
            "object_steps": n * T}


def q(values, p):
    return None if not values else round(float(np.percentile(values, p)), 3)


def summarize(eps: list[dict]) -> dict:
    events = [e for ep in eps for e in ep["events"]]
    per_ep = [len(ep["events"]) for ep in eps]
    gaps = [e["gap"] for e in events]
    hard = [e for e in events if e["moved"] and e["ambiguous"]]
    hist = {f"{lo}-{hi if hi < 10**9 else 'inf'}": sum(1 for g in gaps if lo <= g <= hi) for lo, hi in GAP_BUCKETS}
    object_steps = sum(ep["object_steps"] for ep in eps)
    return {
        "episodes": len(eps),
        "steps_per_episode": sorted(Counter(ep["T"] for ep in eps).items()),
        "objects_per_episode": sorted(Counter(ep["n"] for ep in eps).items()),
        "visible_fraction_of_object_steps": round(sum(ep["visible_steps"] for ep in eps) / object_steps, 4) if object_steps else None,
        "objects": {"always_visible": sum(ep["always"] for ep in eps), "never_visible": sum(ep["never"] for ep in eps),
                    "intermittent": sum(ep["intermittent"] for ep in eps), "censored_at_end": sum(ep["censored"] for ep in eps)},
        "reappearance_events": len(events),
        "events_per_episode": {"mean": round(float(np.mean(per_ep)), 3) if per_ep else None, "median": q(per_ep, 50), "p90": q(per_ep, 90),
                               "max": max(per_ep) if per_ep else None,
                               "fraction_of_episodes_with_event": round(sum(1 for x in per_ep if x) / len(per_ep), 4) if per_ep else None},
        "by_cause": dict(Counter(e["cause"] for e in events)),
        "gap": {"median": q(gaps, 50), "p10": q(gaps, 10), "p90": q(gaps, 90), "max": max(gaps) if gaps else None, "histogram": hist},
        "strata": {
            "moved": sum(e["moved"] for e in events),
            "agent_did_not_move": sum(1 for e in events if e["agent_moved"] is False),
            "ambiguous_appearance": sum(e["ambiguous"] for e in events),
            "nn_confusable": sum(e["confusable"] for e in events),
            "appearance_changed_during_gap": sum(e["appearance_changed"] for e in events),
            "hard_moved_and_ambiguous": len(hard),
            "hard_gap_ge_3": sum(1 for e in hard if e["gap"] >= 3),
            "hard_gap_ge_8": sum(1 for e in hard if e["gap"] >= 8),
        },
    }


# ---------------------------------------------------------------- GridLab-v1 + 跟踪基线


def run_gridlab_v1(args, limit) -> dict:
    from ainerzero.data import gridlab_v1_trajectory as traj
    from ainerzero.environments import gridlab_v1 as v1
    from ainerzero.learning import gridlab_tracking as gt
    from ainerzero.learning import gridlab_tracking_eval as ge

    APP = {"red_disc": 0, "brown_square": 1}
    out: dict = {}
    configs = [
        ("open_16", "open", 16, {}),                # 现有 write_sample 的步数
        ("door_room_16", "door_room", 16, {}),
        ("swap_lane_16", "swap_lane", 16, {}),
        ("occlusion_walk_16", "occlusion_walk", 16, {}),
        ("open_128", "open", 128, {}),              # 拉长（非登记）
        ("door_room_128", "door_room", 128, {}),
        ("open_128_6balls_nonregistered", "open", 128, {"balls": 6, "boxes": 0}),
    ]
    n_eps = 8 if args.quick else 120
    public_key_union: set = set()
    t_steps, t_elapsed = 0, 0.0
    for name, family, steps, kw in configs:
        if budget_left(limit) <= 0:
            out[name] = {"truncated": True}
            continue
        eps, tracker_counts = [], {b: Counter() for b in gt.BASELINES}
        occ_k: list = []
        unbounded: Counter = Counter()
        v1_events = Counter()
        for seed in range(7000, 7000 + n_eps):
            t0 = time.perf_counter()
            sim = traj.simulate(seed, family, steps, **kw)
            t_elapsed += time.perf_counter() - t0
            t_steps += steps
            priv, pub = sim["private"], sim["public"]
            public_key_union |= set(pub[0])
            n = len(priv[0]["objects"])
            vis = [[s["objects"][k]["visibility"] for s in priv] for k in range(n)]
            pos = [[tuple(map(float, s["objects"][k]["xy"])) for s in priv] for k in range(n)]
            app = [[s["objects"][k]["appearance"] for s in priv] for k in range(n)]
            agent = [tuple(map(float, s["agent_xy"])) for s in priv]
            eps.append(analyze_episode(vis, pos, app, agent))
            v1_events.update(e["type"] for e in sim["events"])
            occ_k.extend(e["k"] for e in sim["events"] if e["type"] == "occlusion")
            # 跟踪基线要求外观是整数，这里只在副本上做映射，不改源码
            pub_i = [{**f, "visible_objects": [[d[0], d[1], APP[d[2]]] for d in f["visible_objects"]]} for f in pub]
            priv_i = [{**s, "objects": [{**o, "appearance": APP[o["appearance"]]} for o in s["objects"]]} for s in priv]
            unbounded.update(ge.evaluate_episode(
                gt.run_tracker("last_seen_nn", pub_i, l1_max=99, retention_ticks=10**6), priv_i)["counts"])
            for b in gt.BASELINES:
                res = ge.evaluate_episode(gt.run_tracker(b, pub_i), priv_i)
                tracker_counts[b].update(res["counts"])
        row = summarize(eps)
        row["generator_events"] = dict(v1_events)
        row["generator_occlusion_k"] = {"max": max(occ_k) if occ_k else None, "median": q(occ_k, 50)}
        row["tracker_baselines"] = {b: ge.metrics(dict(tracker_counts[b])) for b in gt.BASELINES}
        row["tracker_baselines"]["last_seen_nn_no_gate_no_retention_limit"] = ge.metrics(dict(unbounded))
        out[name] = row
    out["_public_observation_keys"] = sorted(public_key_union)
    out["_public_identity_keys"] = sorted(public_key_union & {"object_id", "entity_id", "track_id", "objects"})
    out["_generation_seconds_per_step"] = round(t_elapsed / t_steps, 6) if t_steps else None
    return out


# ---------------------------------------------------------------- GridLab-S3（内容格）


def run_gridlab_s3(args, limit) -> dict:
    from ainerzero.v9.experiments.s3 import spec
    from ainerzero.v9.experiments.s3.data import generate_episode
    from ainerzero.v9.experiments.s3.world import _ego_to_world_coords

    n_eps = 6 if args.quick else 100
    eps, gen_ev, t_el, t_steps = [], Counter(), 0.0, 0
    for i in range(n_eps):
        if budget_left(limit) <= 0:
            break
        t0 = time.perf_counter()
        ep = generate_episode(910000 + i, 920000 + i, "F1")
        t_el += time.perf_counter() - t0
        steps = ep["steps"]
        t_steps += len(steps)
        cs = ep["content_state"]
        cells = [tuple(c) for c in cs["content_cells"]]
        key = lambda c: f"{c[0]},{c[1]}"  # noqa: E731
        T = len(steps)
        cell_vis = {c: ["out_of_view"] * T for c in cells}
        for t, st in enumerate(steps):
            tr, obs = st["truth"], np.asarray(st["obs"])
            idx = 0
            for r in (2, 3, 4):
                for col in (2, 3, 4):
                    f = obs[idx : idx + spec.CELL_FEAT_DIM]
                    idx += spec.CELL_FEAT_DIM
                    w = _ego_to_world_coords(tr["x"], tr["y"], tr["heading"], r, col)
                    if w in cell_vis:
                        unseen = f[3] > 0.5
                        cell_vis[w][t] = "occluded" if unseen else "visible"
        vis = [cell_vis[c] for c in cells]
        pos = [[tuple(map(float, c))] * T for c in cells]
        app = []
        for c in cells:
            k = key(c)
            init, swap, new = cs["initial_tokens"][k], cs["swap_times"][k], cs["new_tokens"][k]
            app.append([new if t >= swap else init for t in range(T)])
        agent = [(float(s["truth"]["x"]), float(s["truth"]["y"])) for s in steps]
        eps.append(analyze_episode(vis, pos, app, agent))
        gen_ev.update(bucket=sum(1 for e in ep["events"]))
    row = summarize(eps)
    row["generator_readout_events_total"] = gen_ev["bucket"]
    row["generator_seconds_per_step"] = round(t_el / t_steps, 6) if t_steps else None
    row["note"] = "对象 = 8 个内容格，位置固定，只换 token；可见 = token 出现在学生 3x3 视野（从观察向量解码）"
    return row


# ---------------------------------------------------------------- S1 磁盘数据（AWZ 考场生成）


def s1_ep(row: dict) -> tuple[dict, dict]:
    """把一个 truth 行变成 analyze_episode 的输入。"""
    steps = row["steps"]
    names = sorted({e for s in steps for e in s["entities"]})
    T = len(steps)
    vis, pos, app = [], [], []
    for name in names:
        v, p, a = [], [], []
        for s in steps:
            ent = s["entities"].get(name)
            if ent is None:
                v.append("out_of_view"); p.append((math.nan, math.nan)); a.append(None)
                continue
            px, _, pz = ent["position"]
            p.append((float(px), float(pz)))
            a.append(ent["appearance_class"])
            if name in s["visible_entity_ids"]:
                v.append("visible")
                continue
            ax, _, az = s["agent_world_pose"]["position"]
            yaw = s["agent_world_pose"]["yaw_deg"]
            dx, dz = px - ax, pz - az
            dist = math.hypot(dx, dz)
            rel = ((math.degrees(math.atan2(dx, dz)) - yaw + 180.0) % 360.0) - 180.0
            v.append("occluded" if (dist <= 6.5 and dist > 1e-9 and abs(rel) <= 45.0) else "out_of_view")
        vis.append(v); pos.append(p); app.append(a)
    agent = [(float(s["agent_world_pose"]["position"][0]), float(s["agent_world_pose"]["position"][2])) for s in steps]
    return analyze_episode(vis, pos, app, agent), {"names": names, "T": T}


def scan_keys(obj, acc: set) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            scan_keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            scan_keys(v, acc)


def run_s1_disk(args, limit) -> dict:
    ds = ROOT / "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
    truth_rows = [json.loads(line) for line in (ds / "truth/train.jsonl").read_text().splitlines()]
    packets: dict = defaultdict(list)
    keys: set = set()
    for i, line in enumerate((ds / "packets/train.jsonl").read_text().splitlines()):
        p = json.loads(line)
        packets[p["episode_id"]].append(p)
        if i < 800:
            scan_keys(p, keys)
    by_family: dict = defaultdict(list)
    reissued = same_handle = 0
    det_counts: dict = defaultdict(list)
    handle_mismatch = 0
    for row in truth_rows:
        ep, meta = s1_ep(row)
        by_family[row["family"]].append(ep)
        steps = row["steps"]
        names = meta["names"]
        pkts = sorted(packets[row["episode_id"]], key=lambda p: p["seq"])
        for s, pk in zip(steps, pkts):
            chan = next(c for c in pk["payload"]["observation"]["channels"] if c["kind"] == "relative_objects")
            handles = {d["handle"] for d in chan["detections"]}
            det_counts[row["family"]].append(len(handles))
            if handles != set(s["handle_to_entity"]):
                handle_mismatch += 1
        for e in ep["events"]:
            nm = names[e["k"]]
            h_a = next((h for h, n in steps[e["a"]]["handle_to_entity"].items() if n == nm), None)
            h_b = next((h for h, n in steps[e["b"]]["handle_to_entity"].items() if n == nm), None)
            if h_a is not None and h_a == h_b:
                same_handle += 1
            else:
                reissued += 1
    out = {f: summarize(v) for f, v in sorted(by_family.items())}
    return {
        "by_family": out,
        "handle_reissued_on_reappearance": reissued,
        "handle_kept_on_reappearance": same_handle,
        "packets_vs_truth_handle_mismatch_steps": handle_mismatch,
        "detections_per_packet": {f: {"mean": round(float(np.mean(v)), 3), "max": int(np.max(v))} for f, v in sorted(det_counts.items())},
        "packet_keys_sample_800": sorted(keys),
        "packet_identity_keys": sorted(k for k in keys if k in {"entity_id", "object_id", "world_key", "scene_id", "handle_to_entity", "track_id"}),
        "source": "truth/train.jsonl + packets/train.jsonl（只读）",
    }


def run_awz_exam_resample(args, limit) -> dict:
    """直接调用 AWZ 考场生成器（不写盘），确认与磁盘数据一致，并跑一次 A3 校验。"""
    import os

    from animeworld.exams.packets import emit_stream
    from animeworld.exams.scenarios import e3_identity_world, relation_world

    # ProtocolValidator 按当前目录找 contracts/v9，这里临时切到 AWZ 根目录（只读）
    os.chdir(AWZ_ROOT)
    out = {}
    n = 6 if args.quick else 100
    for name, fn in (("e3_identity", e3_identity_world), ("relation", relation_world)):
        eps, reissue, kept = [], 0, 0
        validated = 0
        for i in range(n):
            w = fn(partition="train", scene_id=f"s4-inventory-{name}-{i:05d}")
            b = emit_stream(w, validate=i < 3)
            validated += int(i < 3)
            ids = sorted(w.frames[0].entities)
            vis = [["visible" if eid in f.visible else "hidden" for f in w.frames] for eid in ids]
            # 隐藏原因沿用 visibility 口径：视野外 / 被挡，这里统一映射，磁盘版再细分
            vis = [["out_of_view" if v == "hidden" else v for v in row] for row in vis]
            pos = [[(f.entities[eid].x, f.entities[eid].z) for f in w.frames] for eid in ids]
            app = [[f.entities[eid].appearance_class for f in w.frames] for eid in ids]
            agent = [(f.agent_x, f.agent_z) for f in w.frames]
            ep = analyze_episode(vis, pos, app, agent)
            eps.append(ep)
            for e in ep["events"]:
                h_a = b.handle_history[e["a"]].get(ids[e["k"]])
                h_b = b.handle_history[e["b"]].get(ids[e["k"]])
                if h_a == h_b:
                    kept += 1
                else:
                    reissue += 1
        row = summarize(eps)
        row["handles_reissued"] = reissue
        row["handles_kept"] = kept
        row["a3_validated_streams"] = validated
        out[name] = row
    return out


# ---------------------------------------------------------------- E1 原始序列（Blender 刚体）的遮挡几何


def _ray_obb(origin, target, center, axes, half) -> bool:
    d = target - origin
    tmin, tmax = 0.0, 1.0
    o = origin - center
    for i in range(3):
        e, f = float(axes[i] @ o), float(axes[i] @ d)
        if abs(f) < 1e-12:
            if abs(e) > half[i]:
                return False
            continue
        t1, t2 = (-half[i] - e) / f, (half[i] - e) / f
        if t1 > t2:
            t1, t2 = t2, t1
        tmin, tmax = max(tmin, t1), min(tmax, t2)
        if tmin > tmax:
            return False
    return True


def run_e1_raw(args, limit) -> dict:
    from animeworld.e0.scenarios import ScenarioBuilder

    root = ROOT / "artifacts/v9/e1/phase2/datasets/raw/P/train"
    types = {t: (12 if args.quick else 200) for t in ("occlusion_pass", "ramp_roll", "box_stack", "table_slide", "bounce_collision")}
    builder = ScenarioBuilder()
    out: dict = {}
    for st, n in types.items():
        files = sorted(root.glob(f"seq_train_{st}_*.json"))[:n]
        if budget_left(limit) <= 0:
            out[st] = {"truncated": True}
            continue
        eps_any, eps_center, mismatch = [], [], 0
        cover_min, hidden_frames_center, hidden_frames_any, frames = [], 0, 0, 0
        state_counts: Counter = Counter()
        seq_flags: Counter = Counter()
        last_x: list = []
        n_active, n_static = [], []
        for f in files:
            d = json.loads(f.read_text())
            _, seed, *_rest = d["world_key"].split("_", 2)
            index = int(d["world_key"].rsplit("_", 1)[1])
            cfg = builder.build(st, int(seed), index)
            spec = {o.name: o for o in cfg.objects}
            cam = d["metadata"]["camera"]
            M = np.array(cam["matrix_world"], float)
            R, cam_pos = M[:3, :3], M[:3, 3]
            right, up, back = R[:, 0], R[:, 1], R[:, 2]
            lens, sw, sh = cam["lens_mm"], cam["sensor_width_mm"], cam["sensor_height_mm"]
            active = [o.name for o in cfg.objects if o.is_active]
            statics = [o.name for o in cfg.objects if not o.is_active and o.shape != "PLANE"]
            n_active.append(len(active)); n_static.append(len(statics))
            for name in statics:
                fr0 = d["frames"][0]["objects"][name]
                if not np.allclose(fr0["position"], spec[name].initial_position, atol=1e-3):
                    mismatch += 1
            T = len(d["frames"])
            vis_any = [[None] * T for _ in active]
            vis_cen = [[None] * T for _ in active]
            pos = [[None] * T for _ in active]
            for t, fr in enumerate(d["frames"]):
                blockers = []
                for name in statics + active:
                    m = np.array(fr["objects"][name]["matrix_world"], float)
                    ax = m[:3, :3] / np.maximum(np.linalg.norm(m[:3, :3], axis=0, keepdims=True), 1e-9)
                    blockers.append((name, m[:3, 3], ax.T, np.array(spec[name].dimensions, float) / 2.0))
                for ki, name in enumerate(active):
                    c = np.array(fr["objects"][name]["position"], float)
                    r = float(min(spec[name].dimensions)) / 2.0
                    samples = [c] + [c + r * (math.cos(th) * right + math.sin(th) * up)
                                     for th in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
                    vis_flags, frustum_flags = [], []
                    for p in samples:
                        pc = R.T @ (p - cam_pos)
                        in_f = pc[2] < 0 and abs(pc[0] / -pc[2]) <= (sw / 2) / lens and abs(pc[1] / -pc[2]) <= (sh / 2) / lens
                        frustum_flags.append(bool(in_f))
                        blocked = any(bn != name and _ray_obb(cam_pos, p, bc, ba, bh) for bn, bc, ba, bh in blockers)
                        vis_flags.append(bool(in_f) and not blocked)
                    frac = sum(vis_flags) / len(vis_flags)
                    pos[ki][t] = tuple(c.tolist())
                    state = "visible" if frac > 0 else ("occluded" if any(frustum_flags) else "out_of_view")
                    vis_any[ki][t] = state
                    vis_cen[ki][t] = "visible" if vis_flags[0] else ("occluded" if frustum_flags[0] else "out_of_view")
                    frames += 1
                    hidden_frames_any += int(frac == 0)
                    hidden_frames_center += int(not vis_flags[0])
                    cover_min.append(frac)
            if st == "occlusion_pass":
                last_x.append(float(d["frames"][-1]["objects"]["OccludedActor"]["position"][0]))
            flat = [v for row_ in vis_any for v in row_]
            state_counts.update(flat)
            if "occluded" in flat:
                seq_flags["sequences_with_fully_occluded_frame"] += 1
            if "out_of_view" in flat:
                seq_flags["sequences_with_out_of_view_frame"] += 1
            for row_ in vis_any:
                if "occluded" in row_ and row_[-1] != "visible":
                    seq_flags["bodies_still_hidden_at_last_frame_after_occlusion"] += 1
            app = [[spec[name].shape] * T for name in active]
            eps_any.append(analyze_episode(vis_any, pos, app))
            eps_center.append(analyze_episode(vis_cen, pos, app))
        row = {
            "sequences": len(files),
            "active_bodies_per_scene": sorted(Counter(n_active).items()),
            "static_bodies_non_ground": sorted(Counter(n_static).items()),
            "scenario_config_mismatch_with_raw": mismatch,
            "frames_times_bodies": frames,
            "state_counts_definition_A": dict(state_counts),
            "sequence_flags": dict(seq_flags),
            "occlusion_pass_final_actor_x": {"min": q(last_x, 0), "median": q(last_x, 50), "max": q(last_x, 100)} if last_x else None,
            "fully_hidden_fraction_of_body_frames": round(hidden_frames_any / frames, 4) if frames else None,
            "center_hidden_fraction_of_body_frames": round(hidden_frames_center / frames, 4) if frames else None,
            "min_visible_fraction_distribution": {"p0": q(cover_min, 0), "p10": q(cover_min, 10), "p50": q(cover_min, 50)},
            "definition_A_any_sample_visible": summarize(eps_any),
            "definition_B_center_visible_only": summarize(eps_center),
            "note": "球面 9 个采样点（中心加轮廓 8 点）；遮挡体含静态非地面与其他运动体；相机外参来自 raw metadata",
        }
        out[st] = row
    return out


def e1_student_keys() -> dict:
    root = ROOT / "artifacts/v9/e1/phase2/datasets/student/P/train"
    keys: set = set()
    names: Counter = Counter()
    for f in sorted(root.glob("*.json"))[:50]:
        d = json.loads(f.read_text())
        scan_keys({k: d[k] for k in d if k != "frames"}, keys)
        scan_keys(d["frames"][0], keys)
        names.update(d["active_bodies"].keys())
    return {"top_keys": sorted(keys), "body_names_seen_in_student_file": sorted(names)}


# ---------------------------------------------------------------- 规模（E2 登记的 100/1000）


def run_scale(args, limit) -> dict:
    from ainerzero.environments import gridlab2d as g2
    from ainerzero.environments import gridlab_v1 as v1
    from ainerzero.learning import gridlab_tracking as gt
    from ainerzero.v9.experiments.s2.world import make_layout
    from ainerzero.v9.experiments.s3.content import generate_content_state

    out: dict = {"gridlab2d": {}, "gridlab_v1": {}, "gridlab_s3": {}, "awz_e2a_world": {}}
    from uuid import uuid5
    for n, w in ((100, 30), (1000, 80)):
        if budget_left(limit) <= 0:
            out["gridlab2d"][str(n)] = {"truncated": True}
            continue
        world = g2.make_world(1, width=w, height=w, pillars=max(5, w), balls=n, boxes=0, view_radius=3)
        steps, t0 = 0, time.perf_counter()
        visibles = []
        ep = uuid5(world.world_id, "scale")
        while steps < (2 if args.quick else 5) and time.perf_counter() - t0 < 6.0:
            world.apply(g2.Action.WAIT)
            pub = world.public_observation(ep, g2.Action.WAIT)
            visibles.append(len(pub["visible_objects"]))
            steps += 1
        el = time.perf_counter() - t0
        out["gridlab2d"][str(n)] = {"grid": w, "objects": len(world.objects), "steps_timed": steps,
                                    "seconds_per_step": round(el / steps, 4), "visible_objects_per_step": visibles}
    # 用 balls/boxes 比例调对象变化率（E2 登记 1/5/20%），看学生实际能看到多少
    out["gridlab2d_change_and_coverage"] = {}
    for n, w in ((100, 30), (1000, 80)):
        for pct in (5, 20):
            if budget_left(limit) <= 0:
                continue
            balls = max(1, n * pct // 100)
            world = g2.make_world(2, width=w, height=w, pillars=max(5, w), balls=balls, boxes=n - balls, view_radius=3)
            rng = random.Random(11)
            ever: set = set()
            vis_counts, changed = [], []
            steps = 16 if args.quick else (128 if n == 100 else 48)
            for _ in range(steps):
                before = {o.object_id: (o.x, o.y) for o in world.objects}
                world.apply(g2.Action(rng.choice([0, 1, 2, 3])))
                changed.append(sum((o.x, o.y) != before[o.object_id] for o in world.objects))
                seen = [o.object_id for o in world.objects if world.visibility_of(o.x, o.y) == "visible"]
                ever |= set(seen)
                vis_counts.append(len(seen))
            out["gridlab2d_change_and_coverage"][f"n{n}_dyn{pct}pct"] = {
                "objects": n, "grid": w, "steps": steps, "balls": balls,
                "mean_changed_fraction_per_step": round(float(np.mean(changed)) / n, 4),
                "mean_visible_per_step": round(float(np.mean(vis_counts)), 3),
                "max_visible_per_step": max(vis_counts),
                "objects_ever_seen": len(ever),
                "objects_ever_seen_fraction": round(len(ever) / n, 4),
            }
    for balls in (70, 100):
        try:
            world = v1.make_world(1, balls=balls, boxes=0, pillars=8)
            out["gridlab_v1"][str(balls)] = {"objects": len(world.objects), "max_grid": v1.SIZE}
        except ValueError as exc:
            out["gridlab_v1"][str(balls)] = {"error": str(exc), "max_grid": v1.SIZE}
    layout = make_layout(910000)
    for m in (100, 1000):
        try:
            cs = generate_content_state(layout, "F1", random.Random(0), m=m)
            out["gridlab_s3"][str(m)] = {"content_cells": len(cs.content_cells)}
        except RuntimeError as exc:
            out["gridlab_s3"][str(m)] = {"error": str(exc)}
    # 现有跟踪基线的穷举关联：同外观、都在门限内时组合数爆炸
    assign_t = {}
    for k in (3, 4, 5, 6):
        dets = [(i, 0, 0) for i in range(k)]
        preds = [(j, 0, (float(j), 0.0)) for j in range(k)]
        t0 = time.perf_counter()
        gt.assign(dets, preds, l1_max=99)
        assign_t[str(k)] = {"seconds": round(time.perf_counter() - t0, 5), "combinations": (k + 1) ** k}
    out["tracker_assign_exhaustive"] = assign_t
    from animeworld.sparse_update import world as e2a
    for n in (100, 1000):
        if budget_left(limit) <= 0:
            out["awz_e2a_world"][str(n)] = {"truncated": True}
            continue
        t0 = time.perf_counter()
        st = e2a.make_world(n, 0)
        st.refresh_hashes()
        ev = e2a.make_events(st, p=0.05, seed=0, tick=0)
        e2a.full_step(st, ev)
        out["awz_e2a_world"][str(n)] = {"objects": len(st.objects), "events_at_5pct": len(ev),
                                        "event_types": dict(Counter(e["event_type"] for e in ev)),
                                        "seconds_first_tick": round(time.perf_counter() - t0, 4),
                                        "has_observation_exit": False,
                                        "note": "世界侧确定性参考世界；没有传感出口，学生看不到"}
    return out


# ---------------------------------------------------------------- 账本（只读临时副本）


def t10_assets() -> dict:
    """只比对磁盘字节与下载记录里的 SHA，不加载模型。"""
    base = ROOT / "envs/teachers/t10"
    prov = json.loads((base / "LICENSE.provenance.json").read_text())
    want = {c["name"]: c for c in prov["components"] if c.get("type") == "model_weights"}
    paths = {"sam2.1-hiera-tiny (weights)": "weights/sam2.1-hiera-tiny/model.safetensors",
             "bootstapir_checkpoint_v2.pt (weights)": "weights/tapnet/bootstapir_checkpoint_v2.pt"}
    out = {}
    for name, rel in paths.items():
        p = base / rel
        out[name] = {"bytes": p.stat().st_size, "sha256": sha(p), "sha256_matches_provenance": sha(p) == want[name]["sha256"]}
    return out


def ledger_costs(copies: Path | None) -> dict:
    if copies is None or not copies.exists():
        return {"skipped": "未传 --ledger-copies"}
    out: dict = {}
    for key, label in (("s1", "S1 phase1"), ("s2", "S2 phase1"), ("e1p2", "E1 phase2"), ("e1r2", "E1 phase2 r2")):
        db = copies / key / "control.sqlite3"
        if not db.exists():
            out[label] = {"missing": True}
            continue
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        agg: dict = defaultdict(lambda: {"runs": 0, "active_seconds": 0.0, "wall_seconds": 0.0, "optimizer_steps": 0})
        for active, cfg, cr, up, state, role, opt in c.execute(
            "select active_seconds,config_json,created_at,updated_at,state,role,optimizer_steps from runs"
        ):
            j = json.loads(cfg)
            kind = str(j.get("mode") or j.get("purpose") or "?").split(":")[0]
            a = agg[f"{role}/{state}/{kind}"]
            a["runs"] += 1
            a["active_seconds"] += active or 0.0
            a["wall_seconds"] += up - cr
            a["optimizer_steps"] += opt or 0
        c.close()
        out[label] = {k: {kk: (round(vv, 1) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in sorted(agg.items())}
        out[label]["_copy_sha256"] = hashlib.sha256(db.read_bytes()).hexdigest()
    return out


# ----------------------------------------------------------------


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(p: Path) -> str:
    return subprocess.run(["git", "-C", str(p), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="小样试跑，结果写 metrics.quick.json")
    ap.add_argument("--ledger-copies", type=Path, default=None)
    ap.add_argument("--limit", type=float, default=105.0)
    args = ap.parse_args()

    metrics: dict = {
        "schema": "s4-inventory-metrics-v1",
        "environment": {"python": platform.python_version(), "machine": platform.machine(),
                        "ainerzero_head": git_head(ROOT), "awz_head": git_head(AWZ_ROOT),
                        "quick": args.quick, "time_limit_s": args.limit},
        "sources_sha256": {p: sha(ROOT / p) for p in (
            "src/ainerzero/environments/gridlab_v1.py", "src/ainerzero/environments/gridlab2d.py",
            "src/ainerzero/learning/gridlab_tracking.py", "src/ainerzero/learning/gridlab_tracking_eval.py",
            "src/ainerzero/v9/experiments/s3/tour.py", "src/ainerzero/v9/experiments/s3/world.py",
            "src/ainerzero/v9/interfaces/scheduler.py", "src/ainerzero/v9/fakes/scheduler.py",
        )},
        "awz_sources_sha256": {p: sha(AWZ_ROOT / p) for p in (
            "python/animeworld/exams/scenarios.py", "python/animeworld/exams/packets.py",
            "python/animeworld/sensing/handles.py", "python/animeworld/e0/scenarios.py",
            "python/animeworld/sparse_update/world.py",
        )},
        "reappearance_definition": __doc__.split("「重现」定义（全文件统一）：")[1].strip(),
    }
    sections = (
        ("gridlab_v1", run_gridlab_v1), ("gridlab_s3", run_gridlab_s3), ("s1_disk", run_s1_disk),
        ("awz_exam_resample", run_awz_exam_resample), ("e1_raw_train", run_e1_raw), ("scale", run_scale),
    )
    timing = {}
    for name, fn in sections:
        t0 = time.monotonic()
        metrics[name] = fn(args, args.limit)
        timing[name] = round(time.monotonic() - t0, 3)
    metrics["e1_student_view"] = e1_student_keys()
    metrics["ledger_costs"] = ledger_costs(args.ledger_copies)
    metrics["t10_assets"] = t10_assets()
    metrics["timing_seconds"] = timing
    metrics["total_seconds"] = round(time.monotonic() - START, 3)
    metrics["imports_blocked"] = {"mlx_imported": sys.modules.get("mlx") is not None, "torch_imported": sys.modules.get("torch") is not None}
    assert not metrics["imports_blocked"]["mlx_imported"]
    assert not metrics["imports_blocked"]["torch_imported"]
    name = "metrics.quick.json" if args.quick else "metrics.json"
    (HERE / name).write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print("done", metrics["total_seconds"], timing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
