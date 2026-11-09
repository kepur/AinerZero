"""S3 冻结前短训探针 P-d、P-e、P-f、P-g（DESIGN-r2 §5）。一级 claude，2026-11-09。

只用 s3p1-train 训练、s3p1-probe 评测。MLX CPU，总上限 20 分钟。不写 artifacts。
门读实测值，缺数据判未通过。
"""
import argparse, fcntl, json, sys, time
from pathlib import Path
import numpy as np
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero"); sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx, mlx.nn as nn, mlx.optimizers as optim
from ainerzero.v9.experiments.s3 import arms_mlx as A, batching as B, data as D, spec

LAM = 1.0            # S3-C2 在 s3p1-train 上拟合的结果
CHANCE = 1.0 / (len(spec.F1_TOKENS) - 1)
FLOOR = CHANCE + 0.03

def build(ns, n_worlds, n_eps, family="F1", seed_base=0):
    out = []
    for w in range(n_worlds):
        for e in range(n_eps):
            ep = D.generate_episode(D.derive_seed(ns, "world", w), D.derive_seed(ns, "ep", w, e), family=family)
            p = B.prepare_episode(ep, LAM, perm_seed=seed_base + w * 100 + e)
            if len(p.query_t): out.append(p)
    return out

def to_mx(b):
    return {k: mx.array(v) for k, v in b.items()}

def evaluate(model, episodes, bs=32):
    C, Sw, Bk = [], [], []
    for i in range(0, len(episodes), bs):
        b = B.collate(episodes[i:i + bs]); mb = to_mx(b)
        lg, _ = A.forward(model, mb, hard=True); mx.eval(lg)
        C.append(np.asarray(mx.argmax(lg, -1)) == b["answer"]); Sw.append(b["swapped"]); Bk.append(b["bucket"])
    c, s, k = np.concatenate(C), np.concatenate(Sw), np.concatenate(Bk)
    lng = k == B.BUCKET_CODE[spec.BUCKET_LONG]
    return {"long_swapped_acc": float(c[lng & s].mean()), "long_swapped_n": int((lng & s).sum()),
            "long_unswapped_acc": float(c[lng & ~s].mean()), "long_unswapped_n": int((lng & ~s).sum()), "all_acc": float(c.mean())}

def train(arm, data, steps, seed, bs=16, lr=1e-3):
    mx.random.seed(seed); rng = np.random.default_rng(seed)
    m = A.ReadoutArm(arm); mx.eval(m.parameters()); opt = optim.Adam(learning_rate=lr)
    vg = nn.value_and_grad(m, A.loss_fn); t0 = time.monotonic(); last = None
    for i in range(steps):
        idx = rng.choice(len(data), size=min(bs, len(data)), replace=False)
        mb = to_mx(B.collate([data[j] for j in idx]))
        loss, g = vg(m, mb); g, _ = optim.clip_grad_norm(g, 1.0); opt.update(m, g); mx.eval(m.parameters(), opt.state, loss); last = float(loss)
    return m, (time.monotonic() - t0) / steps, last

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--report", required=True); ap.add_argument("--smoke", action="store_true"); a = ap.parse_args()
    t0 = time.monotonic(); limit = 1200.0
    mx.set_default_device(mx.cpu)
    lock = (REPO / "artifacts/locks/m0-worker.lock").open("a+"); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    tr_w, tr_e, ev_w, st_ = (6, 2, 6, 5) if a.smoke else (100, 2, 100, 500)
    tr = build(spec.NAMESPACE_TRAIN, tr_w, tr_e); ev = build(spec.NAMESPACE_PROBE, ev_w, 1, seed_base=500000)
    R = {"chance": CHANCE, "floor": FLOOR, "train_episodes": len(tr), "eval_episodes": len(ev), "lam": LAM, "smoke": a.smoke, "probes": {}}
    p = Path(a.report); p.parent.mkdir(parents=True, exist_ok=True)
    def save(): R["elapsed_s"] = round(time.monotonic() - t0, 1); p.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
    save(); print("data", R["train_episodes"], R["eval_episodes"], R["elapsed_s"], flush=True)
    R["param_counts"] = {arm: A.param_count(A.ReadoutArm(arm)) for arm in A.ARMS}; save(); print(R["param_counts"], flush=True)
    for name, arm, gate in (("P-d", "O", lambda v: v >= 0.90), ("P-e", "A0", lambda v: v <= FLOOR), ("P-f", "N", lambda v: v <= FLOOR)):
        if time.monotonic() - t0 > limit: R["probes"][name] = {"status": "not_run_no_time", "pass": False}; save(); continue
        m, per, last = train(arm, tr, st_, 1); r = evaluate(m, ev); r.update(arm=arm, steps=st_, step_seconds=per, last_loss=last, **{"pass": bool(gate(r["long_swapped_acc"]))})
        R["probes"][name] = r; save(); print(name, r, flush=True)
    cost = {}
    for arm in A.ARMS:
        if time.monotonic() - t0 > limit: cost[arm] = None; continue
        _, per, _ = train(arm, tr, 3 if a.smoke else 40, 2); cost[arm] = per
    R["probes"]["P-g"] = {"step_seconds": cost, "pass": all(v is not None for v in cost.values())}; save(); print("P-g", cost, flush=True)
    R["all_pass"] = all(v.get("pass") for v in R["probes"].values()); save(); print("all_pass", R["all_pass"], "elapsed", R["elapsed_s"], flush=True)
main()
