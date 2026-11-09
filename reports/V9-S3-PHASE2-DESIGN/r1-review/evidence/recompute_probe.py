"""不用运行器、不导入项目分析代码，从 probe-p1 的 npz 独立复算。只读。P2 r1 复核。"""
import hashlib, json, sys
from pathlib import Path
import numpy as np
RP = Path("/Users/mac/AinerWorkFlow/AinerZero")
A = RP / "artifacts/v9/s3/phase2/probe-p1"; J = json.loads((RP / "reports/V9-S3-PHASE2/probe-p1.json").read_text())
SEEDS = (1, 2, 3); LONG = 3; REPS = 10000; BSEED = 20261109
def load(c, s, ph):
    with np.load(A / f"{c}-s{s}-{ph}.npz") as d: return {k: d[k] for k in d.files}
def stack(c, ph):
    rows = [load(c, s, ph) for s in SEEDS]; return {k: np.concatenate([r[k] for r in rows]) for k in rows[0]}
def boot(ep, a, b, reps=REPS, seed=BSEED):
    """分组用字典；与生产代码同 rng 序列以便逐位比较，但聚合写法独立。"""
    g = {}
    for e, x, y in zip(ep.tolist(), a.astype(int).tolist(), b.astype(int).tolist()):
        v = g.setdefault(e, [0, 0, 0]); v[0] += 1; v[1] += x; v[2] += y
    keys = sorted(g); arr = np.array([g[k] for k in keys], dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(keys), size=(reps, len(keys)))
    s = arr[idx].sum(1); d = (s[:, 1] - s[:, 2]) / s[:, 0]
    lo, hi = np.percentile(d, [2.5, 97.5])
    return {"delta": (arr[:, 1].sum() - arr[:, 2].sum()) / arr[:, 0].sum(), "ci_low": float(lo), "ci_high": float(hi), "n_episodes": len(keys), "n_events": int(arr[:, 0].sum())}
def prim(s): return (s["bucket"] == LONG) & s["swapped"]
def uns(s): return (s["bucket"] == LONG) & ~s["swapped"]
def pair(a, b, key="correct"):
    sa, sb = stack(*a), stack(*b)
    for k in ("ep", "bucket", "swapped", "query_t", "answer"):
        assert np.array_equal(sa[k], sb[k]), (a, b, k)
    m = prim(sa); return boot(sa["ep"][m], sa[key][m], sb[key][m])
out = {"sha_checked": 0}; bad = []
for k, cell in J["cells"].items():
    c, s = k.rsplit("/", 1)
    for ph, h in cell["events_sha256"].items():
        p = A / f"{c}-s{s}-{ph}.npz"; out["sha_checked"] += 1
        if hashlib.sha256(p.read_bytes()).hexdigest() != h: bad.append(str(p))
    if "weights_F1_sha256" in cell:
        p = A / f"{c}-s{s}-F1.npz.weights.npz"; out["sha_checked"] += 1
        if hashlib.sha256(p.read_bytes()).hexdigest() != cell["weights_F1_sha256"]: bad.append(str(p))
out["sha_mismatch"] = bad
# 内部一致性与事件对齐
conds = sorted({k.rsplit("/", 1)[0] for k in J["cells"]})
ref = {"F1": load("A0", 1, "F1"), "F1_after": load("A2-C0", 1, "F1_after"), "F2": load("A2-C0", 1, "F2")}
issues = []; n_files = 0
for c in conds:
    for s in SEEDS:
        for ph in ("F1", "F1_after", "F2"):
            if not (A / f"{c}-s{s}-{ph}.npz").exists(): continue
            r = load(c, s, ph); n_files += 1
            if not np.array_equal(r["correct"], r["pred"] == r["answer"]): issues.append((c, s, ph, "correct"))
            if not np.array_equal(r["correct_8"], r["pred_8"] == r["answer"]): issues.append((c, s, ph, "correct_8"))
            if (r["correct"] & ~r["correct_8"]).any(): issues.append((c, s, ph, "open_right_but_8_wrong"))
            fam = range(1, 9) if ph != "F2" else range(9, 17)
            if not set(np.unique(r["pred_8"]).tolist()) <= set(fam): issues.append((c, s, ph, "pred_8_outside_family"))
            if not set(np.unique(r["answer"]).tolist()) <= set(fam): issues.append((c, s, ph, "answer_outside_family"))
            base = ref["F2" if ph == "F2" else "F1"]
            for k in ("ep", "query_t", "answer", "swapped", "bucket"):
                if not np.array_equal(r[k], base[k]): issues.append((c, s, ph, "misaligned_" + k))
out["files_checked"] = n_files; out["internal_issues"] = issues
# 主指标与事件数
r = J["result"]
acc = {}
for c in ("A0", "O", "N", "A2-C0", "A3S", "A3H-C0"):
    s = stack(c, "F1"); m = prim(s); acc[c] = float(s["correct"][m].mean()); assert abs(acc[c] - r["accuracy_F1"][c]) < 1e-12, c
out["accuracy_F1"] = acc
out["events"] = {"F1_primary_pooled": int(prim(stack("A2-C0", "F1")).sum()), "F1_episodes": len(np.unique(stack("A2-C0", "F1")["ep"][prim(stack("A2-C0", "F1"))])), "F2_primary_pooled": int(prim(stack("A2-C0", "F2")).sum())}
out["per_seed_primary"] = {ph: [int(prim(load("A2-C0", s, ph)).sum()) for s in SEEDS] for ph in ("F1", "F2")}
out["unswapped"] = {c: float(stack(c, "F1")["correct"][uns(stack(c, "F1"))].mean()) for c in ("A2-C0", "A3H-C0")}
# 门
gates = {
 "h2": (pair(("A3H-C0", "F1"), ("A2-C0", "F1")), r["h2"]),
 "h2b": (pair(("A3H-C0", "F1"), ("A3S", "F1")), r["h2b"]),
 "retention": (pair(("A2-R64", "F1"), ("A2-R64", "F1_after")), r["h3_prime"]["retention"]),
 "plasticity": (pair(("A2-C0", "F2"), ("A2-R64", "F2")), r["h3_prime"]["plasticity"]),
 "interference_8": (pair(("A2-C0", "F1"), ("A2-C0", "F1_after"), "correct_8"), r["h3_prime"]["interference_8class"]),
 "content_8": (pair(("A2-CN", "F1"), ("A2-CN", "F1_after"), "correct_8"), r["h3_prime"]["content_8class"]),
}
def same(a, b): return all(abs(a[k] - b[k]) < 1e-12 for k in ("delta", "ci_low", "ci_high")) and a["n_episodes"] == b["n_episodes"] and a["n_events"] == b["n_events"]
out["gates"] = {k: {"mine": {x: round(v[0][x], 4) for x in ("delta", "ci_low", "ci_high")}, "exact_match_report": bool(same(*v))} for k, v in gates.items()}
for mem in ("A2", "A3H"):
    for cap in (16, 64, 256):
        c = f"{mem}-R{cap}"; row = r[f"capacity_{mem}"][c]
        tr = {"drop": (pair((c, "F1"), (c, "F1_after")), row["drop"]), "drop_8": (pair((c, "F1"), (c, "F1_after"), "correct_8"), row["drop_8class"]), "plasticity": (pair((f"{mem}-C0", "F2"), (c, "F2")), row["plasticity_cost"])}
        out.setdefault("capacity", {})[c] = {k: {x: round(v[0][x], 4) for x in ("delta", "ci_low", "ci_high")} | {"match": bool(same(*v))} for k, v in tr.items()}
sel = next((cap for cap in (16, 64, 256) if out["capacity"][f"A2-R{cap}"]["drop"]["ci_high"] <= 0.05 and out["capacity"][f"A2-R{cap}"]["plasticity"]["ci_high"] <= 0.05), None)
out["selected_capacity"] = {"mine": sel, "report": J["selected_capacity"]}
det = {}
for name, grp in (("A2", ("A2-C0", "A2-R16", "A2-R64", "A2-R256", "A2-CN")), ("A3H", ("A3H-C0", "A3H-R16", "A3H-R64", "A3H-R256"))):
    det[name] = {str(s): [c for c in grp[1:] if not np.array_equal(load(grp[0], s, "F1")["pred"], load(c, s, "F1")["pred"])] for s in SEEDS}
out["determinism_mismatches"] = det
# 不同随机种子的区间（看区间是否依赖某个 rng 序列）
alt = {k: {x: round(boot_v[x], 4) for x in ("ci_low", "ci_high")} for k, boot_v in {"h2b_seed7": boot(*[(lambda s, sb, m: (s["ep"][m], s["correct"][m], sb["correct"][m]))(stack("A3H-C0", "F1"), stack("A3S", "F1"), prim(stack("A3H-C0", "F1")))][0], seed=7), "retention_seed7": boot(*[(lambda s, sb, m: (s["ep"][m], s["correct"][m], sb["correct"][m]))(stack("A2-R64", "F1"), stack("A2-R64", "F1_after"), prim(stack("A2-R64", "F1")))][0], seed=7)}.items()}
out["alt_rng_ci"] = alt
# 8 类与保护
out["C0_CN_R64_F1_after"] = {c: {"open": round(float(stack(c, "F1_after")["correct"][prim(stack(c, "F1_after"))].mean()), 4), "8class": round(float(stack(c, "F1_after")["correct_8"][prim(stack(c, "F1_after"))].mean()), 4)} for c in ("A2-C0", "A2-CN", "A2-R64")}
# 逐种子的 H2b 和保留
out["per_seed"] = {}
for s in SEEDS:
    f = lambda c, ph, key="correct": (lambda x: float(x[key][prim(x)].mean()))(load(c, s, ph))
    out["per_seed"][s] = {"h2": round(f("A3H-C0", "F1") - f("A2-C0", "F1"), 4), "h2b": round(f("A3H-C0", "F1") - f("A3S", "F1"), 4), "retention_R64": round(f("A2-R64", "F1") - f("A2-R64", "F1_after"), 4), "interference_8": round(f("A2-C0", "F1", "correct_8") - f("A2-C0", "F1_after", "correct_8"), 4)}
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
