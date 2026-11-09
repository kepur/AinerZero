"""S3 第二阶段运行器（DESIGN-r2；预登记 reports/V9-S3-PHASE2/PREREG-r1.json）。

用法（dev、final 必须带新建的字节码目录）：
  python -I -X pycache_prefix=<新目录> run_phase2.py --stage dev --use-id dev1 --purpose <用途> --report <json>
  python -I -X pycache_prefix=<新目录> run_phase2.py --stage final --approval <批准行> --report <json>
  python -I run_phase2.py --stage probe|smoke --use-id <名字> --report <json>

启动顺序：拿锁 → 校验清单、已加载模块、git → 校验分区 → 校验请求 → 占报告和运行目录 → 记账。
任何一步失败都不扣次数。
smoke、probe 只读 s3p2-probe，不记账；预登记冻结前也能跑。
"""
import time

STARTED = time.time()
import argparse, hashlib, json, resource, sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx, mlx.nn as nn, mlx.optimizers as optim
from ainerzero.v9.experiments.s3 import analysis_p2 as G, arms_mlx as A, arms_p2_mlx as P, batching as B, data as D, replay as RP, run_guard as GD, spec
from ainerzero.v9.experiments.s3.cues import check_hit

ROOT = REPO / "artifacts/v9/s3/phase2"
PREREG = REPO / "reports/V9-S3-PHASE2/PREREG-r1.json"
LOCK = REPO / "artifacts/locks/m0-worker.lock"
LAM = 1.0
SEEDS = (1, 2, 3)
F1_STEPS, F2_STEPS = 2000, 1000
BATCH, MIX, LR = 16, 8, 1e-3
BUFFER_SEED, CN_SEED, N_SEED = 7_000_000, 7_100_000, 7_200_000
THIRD_PARTY = ("numpy", "mlx.core")
STAGES = {
    "smoke": {"ns": "probe", "train": (6, 2), "eval": (6, 2), "steps": (4, 2), "limit": 900},
    "probe": {"ns": "probe", "train": (400, 4), "eval": (100, 2), "steps": (F1_STEPS, F2_STEPS), "limit": 3600},
    "dev": {"ns": "dev", "train": (400, 4), "eval": (50, 2), "steps": (F1_STEPS, F2_STEPS), "limit": 5400},
    "final": {"ns": "final", "train": (400, 4), "eval": (100, 2), "steps": (F1_STEPS, F2_STEPS), "limit": 5400},
}


def conditions(with_a1):
    """condition -> (arm, loss, F2 treatment). 'f1' stops after the F1 stage."""
    c = {"A0": ("A0", "plain", "f1"), "O": ("O", "plain", "f1"), "N": ("N", "plain", "f1"), "A3S": ("A3", "plain", "f1")}
    for mem, arm, loss in (("A2", "A2", "plain"), ("A3H", "A3", "sampled")):
        c[f"{mem}-C0"] = (arm, loss, "none")
        for cap in G.CAPACITIES:
            c[f"{mem}-R{cap}"] = (arm, loss, f"R{cap}")
        c[f"{mem}-J"] = (arm, loss, "joint")
    c["A2-CN"] = ("A2", "plain", "CN")
    if with_a1:
        c["A1"] = ("A1", "plain", "f1")
    return c


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def visible(o):
    return o[: spec.VIEW_FEAT_DIM].reshape(9, spec.CELL_FEAT_DIM)[:, spec.NUM_TERRAIN_CLASSES:].argmax(1)


def retrieval_rows(ep, p):
    """Standing diagnostic only; reads truth-derived hit labels, never fed to a model."""
    by_t = {int(e["t"]): e for e in ep["events"]}
    rows = []
    for i, t in enumerate(p.query_t.tolist()):
        e, a, top = by_t[t], int(p.answer[i]), int(p.top1[i])
        cands = [int(c) for c, m in zip(p.candidates[i], p.cand_mask[i]) if m]
        rows.append(
            {
                "primary": bool(p.bucket[i] == G.LONG and p.swapped[i]),
                "top1_strict": check_hit(top, e, ep["steps"])[0],
                "pool_strict": any(check_hit(c, e, ep["steps"])[0] for c in cands),
                "top1_visible": a in visible(p.obs[top]),
                "pool_visible": any(a in visible(p.obs[c]) for c in cands),
            }
        )
    return rows


def build(ns, tag, n_w, n_e, family, base, want_rows=False):
    out, rows = [], []
    for w in range(n_w):
        for e in range(n_e):
            ep = D.generate_episode(D.derive_seed(ns, tag + "world", w), D.derive_seed(ns, tag + "ep", w, e), family=family)
            seed = base + w * 100 + e
            p = B.prepare_episode(ep, LAM, perm_seed=seed)
            if not len(p.query_t):
                continue
            out.append(RP.past_only_shuffle(p, N_SEED + seed))
            if want_rows:
                rows += retrieval_rows(ep, p)
    return out, rows


def retrieval_summary(rows):
    s = [r for r in rows if r["primary"]]
    if not s:
        raise ValueError("no primary events for the retrieval summary")
    return {k: float(np.mean([r[k] for r in s])) for k in ("top1_strict", "pool_strict", "top1_visible", "pool_visible")} | {"n": len(s)}


def to_mx(b):
    return {k: mx.array(v) for k, v in b.items()}


def pick(data, n):
    return lambda rng: [data[j] for j in rng.choice(len(data), size=min(n, len(data)), replace=False)]


def mixed(a, b, na, nb):
    def f(rng):
        return [a[j] for j in rng.choice(len(a), size=min(na, len(a)), replace=False)] + [b[j] for j in rng.choice(len(b), size=min(nb, len(b)), replace=False)]

    return f


def train(m, opt, sampler, steps, seed, loss_kind, deadline):
    rng = np.random.default_rng(seed)
    sampled = loss_kind == "sampled"
    vg = nn.value_and_grad(m, P.a3_sampled_loss if sampled else A.loss_fn)
    key = mx.random.key(seed)
    t0 = time.monotonic()
    for step in range(steps):
        if step % 50 == 0:
            deadline.check()
        b = to_mx(B.collate(sampler(rng)))
        if sampled:
            key, sub = mx.random.split(key)
            loss, g = vg(m, b, sub)
        else:
            loss, g = vg(m, b)
        g, _ = optim.clip_grad_norm(g, 1.0)
        opt.update(m, g)
        mx.eval(m.parameters(), opt.state, loss)
        if not np.isfinite(float(loss)):
            raise FloatingPointError("loss not finite")
    return time.monotonic() - t0


def per_event(m, eps, tokens, bs=32):
    keep = np.zeros(spec.NUM_TOKEN_CLASSES, bool)
    keep[list(tokens)] = True
    parts = {k: [] for k in ("correct", "correct_8", "pred", "pred_8", "swapped", "bucket", "ep", "query_t", "answer")}
    for i in range(0, len(eps), bs):
        b = B.collate(eps[i : i + bs])
        logits, _ = A.forward(m, to_mx(b), hard=True)
        mx.eval(logits)
        L = np.asarray(logits)
        pred, pred_8 = L.argmax(-1), np.where(keep, L, -np.inf).argmax(-1)
        for k, v in (("correct", pred == b["answer"]), ("correct_8", pred_8 == b["answer"]), ("pred", pred), ("pred_8", pred_8), ("swapped", b["swapped"]), ("bucket", b["bucket"]), ("ep", b["ep"] + i), ("query_t", b["query_t"]), ("answer", b["answer"])):
            parts[k].append(v)
    return {k: np.concatenate(v) for k, v in parts.items()}


def zero_state_penalty(m, eps, with_memory, bs=32):
    """Standing diagnostic: per-bucket accuracy with memory minus accuracy with memory zeroed."""
    correct = []
    for i in range(0, len(eps), bs):
        b = B.collate(eps[i : i + bs])
        logits = P.zero_memory_logits(m, to_mx(b))
        mx.eval(logits)
        correct.append(np.asarray(logits).argmax(-1) == b["answer"])
    zero = np.concatenate(correct)
    out = {}
    for code, name in G.BUCKET_NAMES.items():
        sel = with_memory["bucket"] == code
        if sel.any():
            out[name] = {"memory": float(with_memory["correct"][sel].mean()), "zero": float(zero[sel].mean()), "penalty": float(with_memory["correct"][sel].mean() - zero[sel].mean()), "n": int(sel.sum())}
    return out


def summary(r):
    m = G.primary_mask(r)
    u = G.unswapped_mask(r)
    return {
        "primary": float(r["correct"][m].mean()) if m.any() else None,
        "primary_8": float(r["correct_8"][m].mean()) if m.any() else None,
        "n_primary": int(m.sum()),
        "unswapped": float(r["correct"][u].mean()) if u.any() else None,
        "balanced_primary": G.balanced_accuracy(r["correct"][m], r["answer"][m]) if m.any() else None,
        "buckets": G.bucket_table(r),
    }


def startup_checks(stage):
    """Run after the lock is held. Returns (prereg or None, its sha, git head, versions)."""
    versions = GD.third_party_versions(REPO, THIRD_PARTY)
    if stage not in ("dev", "final"):
        return None, None, None, versions
    if not sys.flags.isolated:
        raise GD.GuardError("dev and final must run with python -I")
    GD.require_fresh_pycache(STARTED)
    pre = json.loads(PREREG.read_text(encoding="utf-8"))
    bad = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])
    if bad:
        raise GD.GuardError("frozen manifest does not hold: " + "; ".join(bad[:6]))
    if versions != pre["third_party"]:
        raise GD.GuardError(f"library versions differ from the preregistration: {versions}")
    head, dirty = GD.check_git_clean(REPO, list(pre["manifest"]) + [str(PREREG.relative_to(REPO))])
    if dirty:
        raise GD.GuardError("frozen files are not committed: " + "; ".join(dirty[:6]))
    return pre, sha(PREREG), head, versions


def check_request(a, pre):
    """Refuse a malformed request before anything is claimed or spent."""
    if a.use_id is not None and not GD.valid_use_id(a.use_id):
        raise GD.GuardError(f"invalid use id: {a.use_id!r}")
    if a.stage == "dev" and (not a.use_id or not (a.purpose or "").strip()):
        raise GD.GuardError("a dev use needs both a use id and a purpose")
    if a.stage == "final" and (a.approval or "").strip() != pre["final_approval_line"]:
        raise GD.GuardError("missing the unique approval line")


def f2_sampler(how, tr1, tr2, seed, *, clamp):
    """Batch source for the F2 stage and the number of replayed episodes."""
    if how == "none":
        return pick(tr2, BATCH), 0
    cap = 64 if how == "CN" else int(how[1:])
    if clamp:
        cap = min(cap, len(tr1))
    buf = [tr1[j] for j in RP.buffer_indices(len(tr1), cap, BUFFER_SEED + seed)]
    if how == "CN":
        buf = RP.permute_answers(buf, CN_SEED + seed)
    return mixed(tr2, buf, MIX, MIX), len(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=sorted(STAGES))
    ap.add_argument("--use-id")
    ap.add_argument("--purpose")
    ap.add_argument("--approval")
    ap.add_argument("--report", required=True)
    a = ap.parse_args()
    cfg = STAGES[a.stage]
    deadline = GD.Deadline(cfg["limit"])
    t0 = time.monotonic()

    with GD.RunLock(LOCK) as lock:
        pre, pre_sha, head, versions = startup_checks(a.stage)
        ns_eval = G.NAMESPACES[cfg["ns"]]
        GD.check_stage_namespace(a.stage, ns_eval, **G.NAMESPACES)
        check_request(a, pre)
        report = Path(a.report)
        run_id = f"{a.stage}-{a.use_id or 'final'}"
        out = ROOT / run_id
        if out.exists():
            raise GD.GuardError(f"run directory already exists: {out}")
        GD.claim_report(report)
        out.mkdir(parents=True)
        try:
            if a.stage == "dev":
                GD.consume_dev_use(lock, ROOT / "dev_uses.json", a.use_id, a.purpose, max_uses=pre["dev_max_uses"], expected_lock=LOCK)
            elif a.stage == "final":
                GD.consume_final_read(lock, ROOT / "FINAL_READ_ONCE.json", a.approval, pre["final_approval_line"], prereg_sha256=pre_sha, expected_lock=LOCK)
        except GD.GuardError:
            out.rmdir()
            report.unlink()
            raise

        mx.set_default_device(mx.cpu)
        capacity = pre["h3_capacity"] if pre else 64
        with_a1 = a.stage != "probe"

        R = {"schema": "s3.phase2.v1", "stage": a.stage, "use_id": a.use_id, "purpose": a.purpose, "seeds": SEEDS, "prereg_sha256": pre_sha, "git_head": head, "third_party": versions, "h3_capacity": capacity, "cells": {}}

        def save():
            R["elapsed_s"] = round(time.monotonic() - t0, 1)
            R["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report.write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")

        def say(*x):
            print(f"[{time.monotonic() - t0:8.1f}s]", *x, flush=True)

        tw, te = cfg["train"]
        ew, ee = cfg["eval"]
        f1s, f2s = cfg["steps"]
        tr1, _ = build(G.NAMESPACES["train"], "", tw, te, "F1", 0)
        tr2, _ = build(G.NAMESPACES["train"], "f2-", tw, te, "F2", 10_000_000)
        ev1, rows1 = build(ns_eval, "", ew, ee, "F1", 20_000_000, want_rows=True)
        ev2, rows2 = build(ns_eval, "f2-", ew, ee, "F2", 30_000_000, want_rows=True)
        R["data"] = {"train_f1": len(tr1), "train_f2": len(tr2), "eval_f1": len(ev1), "eval_f2": len(ev2)}
        R["retrieval"] = {"F1": retrieval_summary(rows1), "F2": retrieval_summary(rows2)}
        save()
        say("data", R["data"], R["retrieval"]["F1"])

        per = {}

        def record(cond, seed, phase, r, cell):
            per[cond, seed, phase] = r
            path = out / f"{cond}-s{seed}-{phase}.npz"
            np.savez_compressed(path, **r)
            cell[phase] = summary(r)
            cell.setdefault("events_sha256", {})[phase] = sha(path)

        for cond, (arm, loss, how) in conditions(with_a1).items():
            for seed in SEEDS:
                mx.random.seed(seed)
                m = A.ReadoutArm(arm)
                mx.eval(m.parameters())
                opt = optim.Adam(learning_rate=LR)
                cell = {}
                if how == "joint":
                    cell["train_seconds"] = train(m, opt, mixed(tr1, tr2, MIX, MIX), f1s + f2s, seed, loss, deadline)
                else:
                    cell["train_seconds"] = train(m, opt, pick(tr1, BATCH), f1s, seed, loss, deadline)
                    r = per_event(m, ev1, spec.F1_TOKENS)
                    record(cond, seed, "F1", r, cell)
                    if how == "none" and arm != "A1":
                        cell["zero_state"] = zero_state_penalty(m, ev1, r)
                    weights = out / f"{cond}-s{seed}-F1.weights.npz"
                    m.save_weights(str(weights))
                    cell["weights_F1_sha256"] = sha(weights)
                    if how == "f1":
                        R["cells"][f"{cond}/{seed}"] = cell
                        save()
                        say(cond, seed, cell["F1"]["primary"])
                        continue
                    sampler, cell["buffer_episodes"] = f2_sampler(how, tr1, tr2, seed, clamp=a.stage == "smoke")
                    cell["train_seconds_f2"] = train(m, opt, sampler, f2s, seed + 1000, loss, deadline)
                record(cond, seed, "F1_after", per_event(m, ev1, spec.F1_TOKENS), cell)
                record(cond, seed, "F2", per_event(m, ev2, spec.F2_TOKENS), cell)
                weights = out / f"{cond}-s{seed}-end.weights.npz"
                m.save_weights(str(weights))
                cell["weights_end_sha256"] = sha(weights)
                R["cells"][f"{cond}/{seed}"] = cell
                save()
                say(cond, seed, {k: cell[k]["primary"] for k in ("F1", "F1_after", "F2") if k in cell})

        R["result"] = G.evaluate(per, SEEDS, capacity=capacity, has_a1=with_a1, check_samples=a.stage != "smoke")
        if a.stage == "probe":
            R["selected_capacity"] = G.select_capacity(R["result"]["capacity_A2"], "A2")
        if pre:
            late = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])
            R["late_violations"] = late
            if late:
                R["result"] = G.invalidated(R["result"], "frozen files or modules changed during the run")
        save()
        say("valid", R["result"]["valid"], "selected", R.get("selected_capacity"))


if __name__ == "__main__":
    main()
