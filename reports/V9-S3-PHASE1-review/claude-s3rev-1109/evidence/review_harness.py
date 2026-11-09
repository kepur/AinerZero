"""P208 第二路非作者复核的行为校验器（claude-s3rev-1109）。

只在隔离副本里跑：REVIEW_ROOT 指向副本根，导入必须落在副本内。
只用非登记命名空间 review-s3rev，不生成 train/dev/final/probe。MLX 仅 CPU，不做参数更新。
用法：REVIEW_ROOT=<副本> PYTHONPATH=<副本>/src python review_harness.py <输出.json>
"""
import copy
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

import ainerzero

root = Path(os.environ["REVIEW_ROOT"]).resolve()
if not Path(ainerzero.__file__).resolve().is_relative_to(root):
    raise SystemExit(f"导入没有落在副本内：{ainerzero.__file__}")

import mlx.core as mx  # noqa: E402

mx.set_default_device(mx.cpu)

from ainerzero.v9.experiments.s3 import analysis as G  # noqa: E402
from ainerzero.v9.experiments.s3 import arms_mlx as A  # noqa: E402
from ainerzero.v9.experiments.s3 import batching as B  # noqa: E402
from ainerzero.v9.experiments.s3 import data as D  # noqa: E402
from ainerzero.v9.experiments.s3 import spec  # noqa: E402

NS = "review-s3rev"
RESULTS: dict[str, dict] = {}
NON_O = ("A0", "A1", "A2", "A3", "N")
ALL_FIELDS = ("obs", "query_t", "top1", "oracle", "shuffled", "candidates", "cand_feats", "cand_mask", "answer", "swapped", "bucket")


def record(name: str, ok: bool, detail) -> None:
    RESULTS[name] = {"pass": bool(ok), "detail": detail}
    print(("PASS " if ok else "FAIL ") + name + " :: " + json.dumps(detail, ensure_ascii=False, default=str), flush=True)


def gen(n=6, base=0):
    return [D.generate_episode(D.derive_seed(NS, "world", base + i), D.derive_seed(NS, "ep", base + i)) for i in range(n)]


class Spy(dict):
    """记录被读取的键；读取 forbidden 里的键立刻抛错。"""

    def __init__(self, d, read: set, forbidden=()):
        super().__init__(d)
        self.read, self.forbidden = read, set(forbidden)

    def _note(self, k):
        if k in self.forbidden:
            raise AssertionError(f"读取了禁止字段 {k!r}")
        self.read.add(k)

    def __getitem__(self, k):
        self._note(k)
        return super().__getitem__(k)

    def get(self, k, default=None):
        self._note(k)
        return super().get(k, default)


def same_arrays(a: B.PreparedEpisode, b: B.PreparedEpisode, fields) -> list[str]:
    return [f for f in fields if not np.array_equal(getattr(a, f), getattr(b, f))]


EPS = gen()
PREP = [B.prepare_episode(e, 1.0, perm_seed=i) for i, e in enumerate(EPS)]


def t1_truth_never_read():
    step_read, event_read, ep_read = set(), set(), set()
    diffs = []
    for i, e in enumerate(EPS):
        spied = Spy(
            {
                **e,
                "steps": [Spy(s, step_read, forbidden=("truth",)) for s in e["steps"]],
                "events": [Spy(v, event_read, forbidden=("cell", "lag")) for v in e["events"]],
            },
            ep_read,
            forbidden=("content_state", "summary", "layout_sha256", "world_seed", "episode_seed"),
        )
        diffs += same_arrays(B.prepare_episode(spied, 1.0, perm_seed=i), PREP[i], ALL_FIELDS)
    ok = not diffs and step_read == {"t", "obs", "est_pose"} and event_read == {"t", "prev_visit_t", "answer", "swapped", "bucket"}
    record("T1_truth_keys_never_read", ok, {"step_keys": sorted(step_read), "event_keys": sorted(event_read), "episode_keys": sorted(ep_read), "diffs": diffs})


def t2_label_fields_flow_only_to_their_slot():
    flow = {"prev_visit_t": "oracle", "answer": "answer", "swapped": "swapped", "bucket": "bucket"}
    bad = {}
    n_events = 0
    for name, target in flow.items():
        for i, e in enumerate(EPS):
            e2 = copy.copy(e)
            ev2 = []
            for v in e["events"]:
                v = dict(v)
                if name == "prev_visit_t":
                    v[name] = 0
                elif name == "answer":
                    v[name] = 16 if v[name] != 16 else 15
                elif name == "swapped":
                    v[name] = not v[name]
                else:
                    v[name] = spec.BUCKET_LONG if v[name] != spec.BUCKET_LONG else spec.BUCKET_SHORT
                ev2.append(v)
                n_events += 1
            e2["events"] = ev2
            changed = same_arrays(B.prepare_episode(e2, 1.0, perm_seed=i), PREP[i], ALL_FIELDS)
            extra = [f for f in changed if f != target]
            if extra:
                bad.setdefault(name, set()).update(extra)
    record("T2_event_labels_reach_only_their_slot", not bad, {"leaks": {k: sorted(v) for k, v in bad.items()}, "n_events_checked": n_events})


def to_b(prep=PREP):
    return {k: mx.array(v) for k, v in B.collate(prep).items()}


def perturbed(b, seed=99, keys=("oracle", "answer", "swapped", "bucket")):
    rng = np.random.default_rng(seed)
    out = dict(b)
    n = b["query_t"].shape[0]
    if "oracle" in keys:
        out["oracle"] = mx.array(rng.integers(0, spec.T, size=n), dtype=mx.int32)
    if "top1" in keys:
        out["top1"] = mx.array(rng.integers(0, spec.T, size=n), dtype=mx.int32)
    if "shuffled" in keys:
        out["shuffled"] = mx.array(rng.integers(0, spec.T, size=n), dtype=mx.int32)
    if "answer" in keys:
        out["answer"] = mx.array(rng.integers(1, 17, size=n), dtype=mx.int32)
    if "swapped" in keys:
        out["swapped"] = mx.array(rng.random(n) < 0.5)
    if "bucket" in keys:
        out["bucket"] = mx.array(rng.integers(0, 4, size=n), dtype=mx.int32)
    if "candidates" in keys:
        c = np.array(b["candidates"]).copy()
        mask = np.array(b["cand_mask"])
        c[mask] = rng.integers(0, spec.T, size=int(mask.sum()))
        out["candidates"] = mx.array(c)
    return out


def logits(arm_model, b, hard):
    lg, aux = A.forward(arm_model, b, hard=hard)
    mx.eval(lg, aux)
    return np.asarray(lg)


def model_of(arm, seed=7):
    mx.random.seed(seed)
    m = A.ReadoutArm(arm)
    mx.eval(m.parameters())
    return m


def t3_forward_invariance():
    b = to_b()
    leaks = {}
    for arm in NON_O:
        m = model_of(arm)
        for hard in (True, False):
            if not np.array_equal(logits(m, b, hard), logits(m, perturbed(b), hard)):
                leaks[f"{arm}/hard={hard}"] = "logits 依赖 oracle/answer/swapped/bucket"
    m = model_of("O")
    control = not np.array_equal(logits(m, b, True), logits(m, perturbed(b, keys=("oracle",)), True))
    record("T3_logits_ignore_oracle_and_labels", not leaks and control, {"leaks": leaks, "control_O_depends_on_oracle": control})


def t3b_cross_field_independence():
    """每条臂只能依赖它自己的检索字段。"""
    b = to_b()
    cases = {
        "A0": ("oracle", "top1", "shuffled", "candidates"),
        "A1": ("oracle", "top1", "shuffled", "candidates"),
        "A2": ("oracle", "shuffled", "candidates"),
        "N": ("oracle", "top1", "candidates"),
        "A3": ("oracle", "top1", "shuffled"),
    }
    bad = {}
    for arm, keys in cases.items():
        m = model_of(arm)
        if not np.array_equal(logits(m, b, True), logits(m, perturbed(b, keys=keys), True)):
            bad[arm] = list(keys)
    controls = {
        "A2_reads_top1": ("A2", ("top1",)),
        "N_reads_shuffled": ("N", ("shuffled",)),
        "A3_reads_candidates": ("A3", ("candidates",)),
    }
    power = {}
    for name, (arm, keys) in controls.items():
        m = model_of(arm)
        power[name] = not np.array_equal(logits(m, b, True), logits(m, perturbed(b, keys=keys), True))
    record("T3b_arms_read_only_their_own_retrieval_field", not bad and all(power.values()), {"bad": bad, "power": power})


def t4_causality():
    """打乱某事件之后的全部观察，该事件的输出不得改变。"""
    b = to_b()
    obs0 = np.array(b["obs"])
    ep = np.array(b["ep"])
    q = np.array(b["query_t"])
    rng = np.random.default_rng(5)
    picks = []
    for e in range(len(PREP)):
        idx = np.where(ep == e)[0]
        if len(idx):
            picks.append(int(rng.choice(idx)))
    bad = {}
    for arm in ("A0", "A1", "A2", "A3"):
        m = model_of(arm)
        base = logits(m, b, True)
        for i in picks:
            obs = obs0.copy()
            t = int(q[i])
            obs[ep[i], t + 1:] = 1.0 - obs[ep[i], t + 1:]
            other = dict(b)
            other["obs"] = mx.array(obs)
            if not np.array_equal(base[i], logits(m, other, True)[i]):
                bad.setdefault(arm, []).append((int(ep[i]), t))
    # 正对照：A1 必须依赖过去；A0 只看当前。
    m = model_of("A1")
    base = logits(m, b, True)
    i = int(picks[0])
    t = int(q[i])
    obs = obs0.copy()
    obs[ep[i], : t] = 1.0 - obs[ep[i], : t]
    other = dict(b)
    other["obs"] = mx.array(obs)
    a1_power = not np.array_equal(base[i], logits(m, other, True)[i])
    m = model_of("A0")
    base = logits(m, b, True)
    obs = obs0.copy()
    mask = np.ones(obs.shape[1], dtype=bool)
    mask[t] = False
    obs[ep[i], mask] = 1.0 - obs[ep[i], mask]
    other = dict(b)
    other["obs"] = mx.array(obs)
    a0_only_now = np.array_equal(base[i], logits(m, other, True)[i])
    shuffled = np.array(b["shuffled"])
    n_future = int((shuffled > q).sum())
    record(
        "T4_no_future_input_A0_A1_A2_A3",
        not bad and a1_power and a0_only_now,
        {"bad": bad, "events_checked": len(picks), "A1_depends_on_past": a1_power, "A0_only_current_obs": a0_only_now, "N_records_from_future": f"{n_future}/{len(q)}"},
    )


def t5_batching_no_future():
    """把回合截断到事件时刻，检索结果与完整回合一致；全局统计（如 z 分数）不能依赖未来。"""
    bad = []
    n = 0
    for i, e in enumerate(EPS):
        full = PREP[i]
        for j, v in enumerate(e["events"]):
            t = v["t"]
            trunc = {**e, "steps": e["steps"][: t + 1], "events": [v]}
            p = B.prepare_episode(trunc, 1.0, perm_seed=i)
            if len(p.query_t) == 0:
                continue
            k = int(np.where(full.query_t == t)[0][0])
            n += 1
            for f, a, b in (
                ("top1", p.top1[0], full.top1[k]),
                ("candidates", p.candidates[0], full.candidates[k]),
                ("cand_feats", p.cand_feats[0], full.cand_feats[k]),
                ("cand_mask", p.cand_mask[0], full.cand_mask[k]),
            ):
                if not np.array_equal(a, b):
                    bad.append((i, t, f))
    gap_ok = all(
        (p.top1 <= p.query_t - 5).all() and all((p.candidates[r][p.cand_mask[r]] <= p.query_t[r] - 5).all() for r in range(len(p.query_t))) for p in PREP
    )
    record("T5_retrieval_ignores_future_steps", not bad and gap_ok, {"events_checked": n, "bad": bad[:6], "gap_ge_5": gap_ok})


def t6_est_pose_origin_invariance():
    """est_pose 的原点取了真实起点（tour.py:122）；验证只有相对量进入检索。"""
    bad = []
    for i, e in enumerate(EPS):
        steps = [{**s, "est_pose": [s["est_pose"][0] + 1000.0, s["est_pose"][1] - 777.0, s["est_pose"][2]]} for s in e["steps"]]
        bad += same_arrays(B.prepare_episode({**e, "steps": steps}, 1.0, perm_seed=i), PREP[i], ("top1", "candidates", "cand_feats", "cand_mask", "shuffled"))
    record("T6_est_pose_origin_not_used", not bad, {"diffs": bad})


def brute_force_bootstrap(ep, a, b, resamples, seed):
    groups = {}
    for e, x, y in zip(ep.tolist(), a.astype(int).tolist(), b.astype(int).tolist()):
        g = groups.setdefault(e, [0, 0, 0])
        g[0] += 1
        g[1] += x
        g[2] += y
    keys = sorted(groups)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(resamples, len(keys)))
    out = []
    for row in idx:
        n = sa = sb = 0
        for j in row.tolist():
            g = groups[keys[j]]
            n += g[0]
            sa += g[1]
            sb += g[2]
        out.append((sa - sb) / n)
    return np.percentile(out, [2.5, 97.5])


def make_clustered(n_ep=40, n_seed=3, ev=8, seed=3):
    rng = np.random.default_rng(seed)
    ep, a, b = [], [], []
    p_a = np.clip(rng.normal(0.6, 0.25, n_ep), 0, 1)
    p_b = np.clip(p_a - rng.normal(0.1, 0.2, n_ep), 0, 1)
    for s in range(n_seed):
        for e in range(n_ep):
            ep.append(np.full(ev, e))
            a.append(rng.random(ev) < p_a[e])
            b.append(rng.random(ev) < p_b[e])
    return np.concatenate(ep), np.concatenate(a), np.concatenate(b)


def t7_bootstrap():
    ep, a, b = make_clustered()
    r = G.paired_bootstrap_delta(ep, a, b, resamples=2000, seed=11)
    lo, hi = brute_force_bootstrap(ep, a, b, 2000, 11)
    exact = abs(r["ci_low"] - lo) < 1e-12 and abs(r["ci_high"] - hi) < 1e-12
    point = abs(r["delta"] - (a.mean() - b.mean())) < 1e-12
    # 三个种子同一批回合：回合 ID 不加偏移才是对的。加偏移（把种子当独立回合）区间应变窄。
    ep_off = ep + np.repeat(np.arange(3) * 1000, len(ep) // 3)
    r_off = G.paired_bootstrap_delta(ep_off, a, b, resamples=2000, seed=11)
    r_ev = G.paired_bootstrap_delta(np.arange(len(ep)), a, b, resamples=2000, seed=11)
    wid = r["ci_high"] - r["ci_low"]
    wid_off = r_off["ci_high"] - r_off["ci_low"]
    wid_ev = r_ev["ci_high"] - r_ev["ci_low"]
    n_ok = r["n_episodes"] == 40 and r_off["n_episodes"] == 120
    ok = exact and point and n_ok and wid > wid_off and wid_off >= wid_ev * 0.95 and r["ci_low"] < r["delta"] < r["ci_high"]
    record(
        "T7_bootstrap_cluster_unit_and_seed_pooling",
        ok,
        {"exact_match_bruteforce": exact, "point_ok": point, "width_ep": wid, "width_seed_as_cluster": wid_off, "width_event": wid_ev, "n_episodes": r["n_episodes"]},
    )


def t8_fail_closed():
    """按 run_phase1.py 的写法走空数据：不能出现通过。"""
    import warnings

    c = np.array([True, False])
    empty = np.array([False, False])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prim = {k: float(c[empty].mean()) for k in ("A0", "O", "N", "A1", "A2", "A3")}
        uns = {k: float(c[empty].mean()) for k in ("A2", "A3")}
    leg = G.legality(prim, uns, ("A2", "A3"))
    raised = False
    try:
        G.paired_bootstrap_delta(np.array([], dtype=int), np.array([], dtype=bool), np.array([], dtype=bool))
    except ValueError:
        raised = True
    h3 = float("nan") <= G.H3_MAX_DROP
    nan_diff = G.difference_gate({"delta": float("nan"), "ci_low": 0.5}, 0.1) or G.difference_gate({"delta": 0.5, "ci_low": float("nan")}, 0.1)
    ok = not any(leg.values()) and raised and not h3 and not nan_diff and all(math.isnan(v) for v in prim.values())
    # 只记录：没有最小样本门，一个回合也能过 H1 形式上的门。
    one = G.paired_bootstrap_delta(np.array([0, 0]), np.array([True, True]), np.array([False, False]), resamples=100)
    record(
        "T8_empty_data_cannot_pass",
        ok,
        {"legality": leg, "bootstrap_raises": raised, "h3_nan_passes": h3, "difference_gate_nan_passes": nan_diff, "note_single_episode_gate": G.difference_gate(one, 0.1)},
    )


def t9_a3_grad_and_consistency():
    """A3：打分头梯度不进编码器，读出头梯度不进打分头；util 中的 ce_0 项对目标分布没有影响。"""
    import mlx.nn as nn
    from mlx.utils import tree_flatten

    b = to_b()
    m = model_of("A3")
    _, g = nn.value_and_grad(m, lambda mm, bb: A.forward(mm, bb, hard=False)[1])(m, b)
    gd = dict(tree_flatten(g))
    leak = [k for k in gd if k.split(".")[0] in ("enc1", "enc2", "mem1", "mem2", "head1", "head2") and float(mx.abs(gd[k]).max()) != 0.0]
    score_live = float(mx.abs(gd["score2.weight"]).max()) > 0.0

    def rd(mm, bb):
        lg, _ = A.forward(mm, bb, hard=False)
        return nn.losses.cross_entropy(lg, bb["answer"], reduction="mean")

    _, g2 = nn.value_and_grad(m, rd)(m, b)
    gd2 = dict(tree_flatten(g2))
    s_leak = [k for k in gd2 if k.startswith("score") and float(mx.abs(gd2[k]).max()) != 0.0]
    enc_live = float(mx.abs(gd2["enc1.weight"]).max()) > 0.0
    # util = ce_0 - ce_c；ce_0 对同一事件的所有候选相同，softmax 后被消去。
    util = np.array([0.3, 0.9, 1.5])
    tgt = np.exp(util / 0.5) / np.exp(util / 0.5).sum()
    tgt_shift = np.exp((util + 7.0) / 0.5) / np.exp((util + 7.0) / 0.5).sum()
    cancels = bool(np.allclose(tgt, tgt_shift))
    record(
        "T9_A3_gradient_isolation",
        not leak and score_live and not s_leak and enc_live,
        {"encoder_gets_scorer_grad": leak, "scorer_live": score_live, "scorer_gets_readout_grad": s_leak, "encoder_live": enc_live, "note_ce0_term_cancels_in_softmax": cancels},
    )



def t10_gate_constants_match_prereg():
    pre = json.loads(Path(os.environ.get("PREREG_PATH", "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S3-DESIGN/PREREG-r1.json")).read_text(encoding="utf-8"))
    g = pre["gates"]
    checks = {
        "chance": G.CHANCE == g["chance"],
        "floor": G.FLOOR == g["floor"],
        "upper_O": G.UPPER_MIN == g["upper_O"],
        "unswapped_min": G.UNSWAPPED_MIN == g["unswapped_min"],
        "resamples": G.BOOTSTRAP_RESAMPLES == g["bootstrap"]["resamples"],
        "boot_seed": G.BOOTSTRAP_SEED == g["bootstrap"]["seed"],
        "H1": G.H1_MIN_DELTA == 0.10,
        "H2": G.H2_MIN_DELTA == 0.05,
        "H3": G.H3_MAX_DROP == 0.05,
    }
    record("T10_gate_constants_match_prereg", all(checks.values()), checks)


def t11_negative_control_is_shuffled():
    frac = float(np.mean([np.mean(p.shuffled != p.top1) for p in PREP]))
    record("T11_N_record_differs_from_top1", frac > 0.9, {"fraction_differs": frac})


def main():
    for f in (t1_truth_never_read, t2_label_fields_flow_only_to_their_slot, t3_forward_invariance, t3b_cross_field_independence, t4_causality, t5_batching_no_future, t6_est_pose_origin_invariance, t7_bootstrap, t8_fail_closed, t9_a3_grad_and_consistency, t10_gate_constants_match_prereg, t11_negative_control_is_shuffled):
        try:
            f()
        except Exception as exc:  # noqa: BLE001
            record(f.__name__, False, {"exception": repr(exc)})
    n_fail = sum(not v["pass"] for v in RESULTS.values())
    print(f"SUMMARY pass={len(RESULTS) - n_fail} fail={n_fail}", flush=True)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    sys.exit(1 if n_fail else 0)


main()
