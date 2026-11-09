"""S3 第一阶段运行器（DESIGN-r2 §3、§4、§6；预登记 reports/V9-S3-DESIGN/PREREG-r1.json）。一级 claude。

用法：
  run_phase1.py --stage dev   --use-id dev1 --report <json>
  run_phase1.py --stage final --approval <批准行文本> --report <json>
dev 至多使用两次（账本 artifacts/v9/s3/phase1/dev_uses.json）。final 只读一次，只在预登记冻结后生成。
持 m0-worker.lock。硬上限 3 小时。
"""
import argparse, fcntl, hashlib, json, sys, time
from pathlib import Path
import numpy as np
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero"); sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx, mlx.nn as nn, mlx.optimizers as optim
from ainerzero.v9.experiments.s3 import analysis as G, arms_mlx as A, batching as B, data as D, spec

ROOT = REPO / "artifacts/v9/s3/phase1"
PREREG = REPO / "reports/V9-S3-DESIGN/PREREG-r1.json"
LIMIT_S = 3 * 3600.0
LAM = 1.0
SEEDS = (1, 2, 3)
LONG = B.BUCKET_CODE[spec.BUCKET_LONG]
MAIN = ("A0", "A1", "A2", "A3")
AUX = ("O", "N")
F1_STEPS, F2_STEPS, AUX_STEPS = 2000, 1000, 1500
TRAIN_W, TRAIN_E, DEV_W, DEV_E, FINAL_W, FINAL_E = 400, 4, 50, 2, 100, 2
BATCH, LR = 16, 1e-3


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def build(ns, tag, n_w, n_e, family, base):
    out = []
    for w in range(n_w):
        for e in range(n_e):
            ep = D.generate_episode(D.derive_seed(ns, tag + "world", w), D.derive_seed(ns, tag + "ep", w, e), family=family)
            p = B.prepare_episode(ep, LAM, perm_seed=base + w * 100 + e)
            if len(p.query_t): out.append(p)
    return out

def to_mx(b): return {k: mx.array(v) for k, v in b.items()}

def train(m, opt, data, steps, seed):
    rng = np.random.default_rng(seed); vg = nn.value_and_grad(m, A.loss_fn); t0 = time.monotonic()
    for _ in range(steps):
        idx = rng.choice(len(data), size=min(BATCH, len(data)), replace=False)
        loss, g = vg(m, to_mx(B.collate([data[j] for j in idx])))
        g, _ = optim.clip_grad_norm(g, 1.0); opt.update(m, g); mx.eval(m.parameters(), opt.state, loss)
        if not np.isfinite(float(loss)): raise FloatingPointError("loss not finite")
    return time.monotonic() - t0

def per_event(m, eps, bs=32):
    C, Sw, Bk, Ep = [], [], [], []
    for i in range(0, len(eps), bs):
        b = B.collate(eps[i:i + bs]); lg, _ = A.forward(m, to_mx(b), hard=True); mx.eval(lg)
        C.append(np.asarray(mx.argmax(lg, -1)) == b["answer"]); Sw.append(b["swapped"]); Bk.append(b["bucket"]); Ep.append(b["ep"] + i)
    return {"correct": np.concatenate(C), "swapped": np.concatenate(Sw), "bucket": np.concatenate(Bk), "ep": np.concatenate(Ep)}

def summary(r):
    l = r["bucket"] == LONG
    return {"primary": float(r["correct"][l & r["swapped"]].mean()), "n_primary": int((l & r["swapped"]).sum()), "unswapped": float(r["correct"][l & ~r["swapped"]].mean())}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--stage", required=True, choices=["smoke", "dev", "final"]); ap.add_argument("--use-id"); ap.add_argument("--approval"); ap.add_argument("--report", required=True); a = ap.parse_args()
    t0 = time.monotonic(); left = lambda: LIMIT_S - (time.monotonic() - t0)
    smoke = a.stage == "smoke"
    pre = json.loads(PREREG.read_text(encoding="utf-8")) if not smoke else {}
    if not smoke:
        for rel, want in pre["code_sha256"].items():
            if sha(REPO / rel) != want: raise SystemExit(f"代码与预登记不一致：{rel}")
    ROOT.mkdir(parents=True, exist_ok=True)
    uses = ROOT / "dev_uses.json"
    if a.stage == "dev":
        u = json.loads(uses.read_text()) if uses.is_file() else []
        if len(u) >= 2 or a.use_id in [x["id"] for x in u] or not a.use_id: raise SystemExit("dev 使用次数已满或 use-id 无效")
        u.append({"id": a.use_id, "at": time.time()}); uses.write_text(json.dumps(u))
    if a.stage == "final":
        marker = ROOT / "FINAL_READ_ONCE.json"
        if marker.exists(): raise SystemExit("final 已读过")
        if not a.approval or a.approval.strip() != pre["final_approval_line"]: raise SystemExit("缺少唯一批准行")
        marker.write_text(json.dumps({"at": time.time(), "prereg_sha": sha(PREREG)}))
    mx.set_default_device(mx.cpu)
    lock = (REPO / "artifacts/locks/m0-worker.lock").open("a+"); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    p = Path(a.report); p.parent.mkdir(parents=True, exist_ok=True)
    R = {"schema": "s3.phase1.v1", "stage": a.stage, "use_id": a.use_id, "seeds": SEEDS, "prereg_sha256": sha(PREREG) if not smoke else None, "unreviewed_note": "运行器与各臂由一级编写；见 RESEARCH_LOG 的复核状态", "cells": {}}
    def save(): R["elapsed_s"] = round(time.monotonic() - t0, 1); p.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
    def say(*x): print(f"[{time.monotonic() - t0:8.1f}s]", *x, flush=True)
    tw, te, f1s, f2s, axs = (6, 2, 4, 2, 3) if smoke else (TRAIN_W, TRAIN_E, F1_STEPS, F2_STEPS, AUX_STEPS)
    ns_ev, ev_w, ev_e = {"smoke": (spec.NAMESPACE_DEV, 6, 2), "dev": (spec.NAMESPACE_DEV, DEV_W, DEV_E), "final": (spec.NAMESPACE_FINAL, FINAL_W, FINAL_E)}[a.stage]
    tr1 = build(spec.NAMESPACE_TRAIN, "", tw, te, "F1", 0); tr2 = build(spec.NAMESPACE_TRAIN, "f2-", tw, te, "F2", 10_000_000)
    ev1 = build(ns_ev, "", ev_w, ev_e, "F1", 20_000_000); ev2 = build(ns_ev, "f2-", ev_w, ev_e, "F2", 30_000_000)
    R["data"] = {"train_f1": len(tr1), "train_f2": len(tr2), "eval_f1": len(ev1), "eval_f2": len(ev2)}; save(); say("data", R["data"])
    per = {}
    for arm in MAIN + AUX:
        for seed in SEEDS:
            if left() < 300: raise SystemExit("超出 3 小时硬上限，停止")
            mx.random.seed(seed); m = A.ReadoutArm(arm); mx.eval(m.parameters()); opt = optim.Adam(learning_rate=LR)
            sec = train(m, opt, tr1, f1s if arm in MAIN else axs, seed)
            before = per_event(m, ev1); per[arm, seed, "F1"] = before
            cell = {"f1": summary(before), "train_seconds": sec}
            if arm in MAIN:
                sec2 = train(m, opt, tr2, f2s, seed + 1000)
                after = per_event(m, ev1); cell["f1_after_f2"] = summary(after); cell["f2"] = summary(per_event(m, ev2)); cell["train_seconds_f2"] = sec2
            m.save_weights(str(ROOT / f"{a.stage}-{a.use_id or 'final'}-{arm}-s{seed}.npz")) if not smoke else None
            R["cells"][f"{arm}/{seed}"] = cell; save(); say(arm, seed, cell)
    # 聚合：三个种子的事件拼接。三个种子用同一批回合，回合 ID 不加偏移，
    # bootstrap 以回合为单位重采样时同一回合的三个种子一起进出。
    def stack(arm):
        out = {"correct": [], "swapped": [], "bucket": [], "ep": []}
        for s in SEEDS:
            r = per[arm, s, "F1"]
            for k in out: out[k].append(r[k])
        return {k: np.concatenate(v) for k, v in out.items()}
    S = {arm: stack(arm) for arm in MAIN + AUX}
    prim = {arm: float(S[arm]["correct"][(S[arm]["bucket"] == LONG) & S[arm]["swapped"]].mean()) for arm in S}
    uns = {arm: float(S[arm]["correct"][(S[arm]["bucket"] == LONG) & ~S[arm]["swapped"]].mean()) for arm in S}
    for arm in S:
        if not (np.array_equal(S[arm]["ep"], S["A2"]["ep"]) and np.array_equal(S[arm]["bucket"], S["A2"]["bucket"]) and np.array_equal(S[arm]["swapped"], S["A2"]["swapped"])):
            raise SystemExit(f"事件对不齐：{arm}")
    mask = (S["A2"]["bucket"] == LONG) & S["A2"]["swapped"]
    h1 = G.paired_bootstrap_delta(S["A2"]["ep"][mask], S["A2"]["correct"][mask], S["A1"]["correct"][mask])
    h2 = G.paired_bootstrap_delta(S["A3"]["ep"][mask], S["A3"]["correct"][mask], S["A2"]["correct"][mask])
    drops = {arm: float(np.mean([R["cells"][f"{arm}/{s}"]["f1"]["primary"] - R["cells"][f"{arm}/{s}"]["f1_after_f2"]["primary"] for s in SEEDS])) for arm in MAIN}
    legal = G.legality(prim, uns, ("A2", "A3"))
    R["result"] = {"primary": prim, "unswapped": uns, "h1": {**h1, "pass": G.difference_gate(h1, G.H1_MIN_DELTA)}, "h2": {**h2, "pass": G.difference_gate(h2, G.H2_MIN_DELTA)},
                   "h3_drop": drops, "h3_pass": {arm: drops[arm] <= G.H3_MAX_DROP for arm in MAIN}, "legality": legal, "valid": all(legal.values())}
    save(); say("result", R["result"]); fcntl.flock(lock, fcntl.LOCK_UN)
main()
