"""不用运行器、不导入项目代码，从 final-final 的 npz 独立复算全部门。只读。"""
import hashlib, json, sys
from pathlib import Path
import numpy as np
RP = Path("/Users/mac/AinerWorkFlow/AinerZero"); A = RP / "artifacts/v9/s3/phase2/final-final"; J = json.loads((RP / "reports/V9-S3-PHASE2/final.json").read_text()); R = J["result"]
SEEDS = (1, 2, 3); LONG = 3; REPS = 10000; BSEED = 20261109; FLOOR = 1 / 7 + 0.03
def load(c, s, ph):
    with np.load(A / f"{c}-s{s}-{ph}.npz") as d: return {k: d[k] for k in d.files}
_cache = {}
def stack(c, ph):
    if (c, ph) not in _cache:
        rows = [load(c, s, ph) for s in SEEDS]; _cache[c, ph] = {k: np.concatenate([r[k] for r in rows]) for k in rows[0]}
    return _cache[c, ph]
def prim(s): return (s["bucket"] == LONG) & s["swapped"]
def uns(s): return (s["bucket"] == LONG) & ~s["swapped"]
def boot(unit, a, b, reps=REPS, seed=BSEED, q=(2.5, 97.5)):
    g = {}
    for e, x, y in zip(unit.tolist(), a.astype(int).tolist(), b.astype(int).tolist()):
        v = g.setdefault(e, [0, 0, 0]); v[0] += 1; v[1] += x; v[2] += y
    keys = sorted(g); arr = np.array([g[k] for k in keys], dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(keys), size=(reps, len(keys)))
    s = arr[idx].sum(1); d = (s[:, 1] - s[:, 2]) / s[:, 0]; lo, hi = np.percentile(d, list(q))
    return {"delta": (arr[:, 1].sum() - arr[:, 2].sum()) / arr[:, 0].sum(), "ci_low": float(lo), "ci_high": float(hi), "n_episodes": len(keys), "n_events": int(arr[:, 0].sum())}
ID = ("ep", "query_t", "answer", "swapped", "bucket")
def pair(a, b, key="correct", **kw):
    sa, sb = stack(*a), stack(*b)
    for k in ID: assert np.array_equal(sa[k], sb[k]), (a, b, k)
    m = prim(sa); unit = kw.pop("unit", lambda x: x)(sa["ep"][m]); return boot(unit, sa[key][m], sb[key][m], **kw)
same = lambda a, b: all(abs(a[k] - b[k]) < 1e-12 for k in ("delta", "ci_low", "ci_high")) and a["n_episodes"] == b["n_episodes"] and a["n_events"] == b["n_events"]
short = lambda b: {k: round(b[k], 4) for k in ("delta", "ci_low", "ci_high")}
O = {}
bad = []; n = 0
for k, cell in J["cells"].items():
    c, s = k.rsplit("/", 1)
    for ph, h in cell["events_sha256"].items():
        n += 1
        if hashlib.sha256((A / f"{c}-s{s}-{ph}.npz").read_bytes()).hexdigest() != h: bad.append((k, ph))
    for key, suf in (("weights_F1_sha256", "F1"), ("weights_end_sha256", "end")):
        if key in cell:
            n += 1
            if hashlib.sha256((A / f"{c}-s{s}-{suf}.weights.npz").read_bytes()).hexdigest() != cell[key]: bad.append((k, suf))
O["sha_checked"] = n; O["sha_mismatch"] = bad; O["files_on_disk"] = len(list(A.iterdir()))
conds = sorted({k.rsplit("/", 1)[0] for k in J["cells"]})
ref = {"F1": load("A0", 1, "F1"), "F2": load("A2-C0", 1, "F2")}; issues = []; files = 0
for c in conds:
    for s in SEEDS:
        for ph in ("F1", "F1_after", "F2"):
            p = A / f"{c}-s{s}-{ph}.npz"
            if not p.exists(): continue
            r = load(c, s, ph); files += 1
            if not np.array_equal(r["correct"], r["pred"] == r["answer"]): issues.append((c, s, ph, "correct"))
            if not np.array_equal(r["correct_8"], r["pred_8"] == r["answer"]): issues.append((c, s, ph, "correct_8"))
            if (r["correct"] & ~r["correct_8"]).any(): issues.append((c, s, ph, "open_right_8_wrong"))
            fam = set(range(1, 9)) if ph != "F2" else set(range(9, 17))
            if not set(np.unique(r["pred_8"]).tolist()) <= fam or not set(np.unique(r["answer"]).tolist()) <= fam: issues.append((c, s, ph, "family"))
            for k in ID:
                if not np.array_equal(r[k], ref["F2" if ph == "F2" else "F1"][k]): issues.append((c, s, ph, "misaligned_" + k))
O["npz_checked"] = files; O["internal_issues"] = issues
# 合法性门
def acc(c, ph="F1", key="correct", mask=prim):
    s = stack(c, ph); m = mask(s); assert m.any(), (c, ph); return float(s[key][m].mean())
accs = {c: acc(c) for c in ("A0", "O", "N", "A1", "A2-C0", "A3S", "A3H-C0")}
O["accuracy_match"] = {c: abs(accs[c] - R["accuracy_F1"][c]) < 1e-12 for c in accs}; O["accuracy"] = {c: round(v, 4) for c, v in accs.items()}
def det(grp): return all(np.array_equal(load(grp[0], s, "F1")["pred"], load(c, s, "F1")["pred"]) for s in SEEDS for c in grp[1:])
def enough(c, ph):
    for s in SEEDS:
        r = load(c, s, ph); m = prim(r)
        if int(m.sum()) < 200 or len(np.unique(r["ep"][m])) < 50: return False
    return True
leg = {"floor_A0": accs["A0"] <= FLOOR, "upper_O": accs["O"] >= 0.9, "floor_N": accs["N"] <= FLOOR, "unswapped_A2": acc("A2-C0", mask=uns) >= 0.8, "unswapped_A3H": acc("A3H-C0", mask=uns) >= 0.8, "determinism_A2": det(("A2-C0", "A2-R16", "A2-R64", "A2-R256", "A2-CN")), "determinism_A3H": det(("A3H-C0", "A3H-R16", "A3H-R64", "A3H-R256")), "min_sample_F1": enough("A2-C0", "F1"), "min_sample_F2": enough("A2-C0", "F2")}
O["legality_mine"] = {k: bool(v) for k, v in leg.items()}; O["legality_match"] = {k: bool(leg[k]) == R["legality"][k] for k in leg}; O["unswapped"] = {"A2": round(acc("A2-C0", mask=uns), 4), "A3H": round(acc("A3H-C0", mask=uns), 4)}
O["per_seed_events"] = {ph: [int(prim(load("A2-C0", s, ph)).sum()) for s in SEEDS] for ph in ("F1", "F2")}
# 门
G = {"h1": (("A2-C0", "F1"), ("A1", "F1"), "correct", R["h1"]), "h2": (("A3H-C0", "F1"), ("A2-C0", "F1"), "correct", R["h2"]), "h2b": (("A3H-C0", "F1"), ("A3S", "F1"), "correct", R["h2b"]),
     "retention": (("A2-R64", "F1"), ("A2-R64", "F1_after"), "correct", R["h3_prime"]["retention"]), "plasticity": (("A2-C0", "F2"), ("A2-R64", "F2"), "correct", R["h3_prime"]["plasticity"]),
     "interference_8": (("A2-C0", "F1"), ("A2-C0", "F1_after"), "correct_8", R["h3_prime"]["interference_8class"]), "content_8": (("A2-CN", "F1"), ("A2-CN", "F1_after"), "correct_8", R["h3_prime"]["content_8class"]), "replay_minus_cn_8": (("A2-R64", "F1_after"), ("A2-CN", "F1_after"), "correct_8", R["h3_prime"]["replay_minus_cn_8class"])}
res = {}; O["gates"] = {}
for k, (a, b, key, rep) in G.items():
    res[k] = pair(a, b, key); O["gates"][k] = {**short(res[k]), "n_ep": res[k]["n_episodes"], "n_ev": res[k]["n_events"], "exact_match": bool(same(res[k], rep))}
ok = lambda b, d: b["delta"] >= d and b["ci_low"] > 0
claims = {"h1": ok(res["h1"], .10), "h2": ok(res["h2"], .05), "h2b": ok(res["h2b"], .03), "retention": res["retention"]["ci_high"] <= .05, "plasticity": res["plasticity"]["ci_high"] <= .05, "interference": res["interference_8"]["delta"] >= .10, "content": res["content_8"]["delta"] >= .10}
O["gate_decisions_mine"] = {k: bool(v) for k, v in claims.items()}; O["report_claims"] = R["claims"]; O["report_valid"] = R["valid"]
O["capacity"] = {}
for mem in ("A2", "A3H"):
    for cap in (16, 64, 256):
        c = f"{mem}-R{cap}"; row = R[f"capacity_{mem}"][c]; out = {}
        for name, a, b, key, rep in (("drop", (c, "F1"), (c, "F1_after"), "correct", row["drop"]), ("drop_8", (c, "F1"), (c, "F1_after"), "correct_8", row["drop_8class"]), ("plasticity", (f"{mem}-C0", "F2"), (c, "F2"), "correct", row["plasticity_cost"])):
            v = pair(a, b, key); out[name] = {**short(v), "match": bool(same(v, rep))}
        O["capacity"][c] = out
O["descriptive"] = {c: {"F1": round(acc(c), 4) if (A / f"{c}-s1-F1.npz").exists() else None, "F1_after_16": round(acc(c, "F1_after"), 4), "F1_after_8": round(acc(c, "F1_after", "correct_8"), 4), "F2": round(acc(c, "F2"), 4)} for c in ("A2-C0", "A2-CN", "A2-R64", "A3H-C0", "A3H-R64", "A2-J", "A3H-J")}
# 按种子与稳健性
f = lambda c, s, ph, key="correct": (lambda x: float(x[key][prim(x)].mean()))(load(c, s, ph))
O["per_seed"] = {s: {"A1": round(f("A1", s, "F1"), 4), "A2": round(f("A2-C0", s, "F1"), 4), "A3S": round(f("A3S", s, "F1"), 4), "A3H": round(f("A3H-C0", s, "F1"), 4), "h1": round(f("A2-C0", s, "F1") - f("A1", s, "F1"), 4), "h2": round(f("A3H-C0", s, "F1") - f("A2-C0", s, "F1"), 4), "h2b": round(f("A3H-C0", s, "F1") - f("A3S", s, "F1"), 4), "retention": round(f("A2-R64", s, "F1") - f("A2-R64", s, "F1_after"), 4), "plasticity": round(f("A2-C0", s, "F2") - f("A2-R64", s, "F2"), 4), "A3H_R64_drop": round(f("A3H-R64", s, "F1") - f("A3H-R64", s, "F1_after"), 4)} for s in SEEDS}
world = lambda ep: ep // 2
rob = {}
for k in ("h1", "h2", "h2b", "retention", "plasticity"):
    a, b, key, _ = G[k]
    rob[k] = {"world_cluster": short(pair(a, b, key, unit=world)), "alpha_0.0125_episode": short(pair(a, b, key, q=(0.625, 99.375))), "alt_rng_seed7": short(pair(a, b, key, seed=7))}
O["robustness"] = rob
O["world_cluster_check"] = {"F1_units": len(np.unique(world(stack("A2-C0", "F1")["ep"]))), "F2_units": len(np.unique(world(stack("A2-C0", "F2")["ep"])))}
O["a3s_minus_a2"] = short(pair(("A3S", "F1"), ("A2-C0", "F1")))
print(json.dumps(O, ensure_ascii=False, indent=1, default=str)); Path(sys.argv[1]).write_text(json.dumps(O, ensure_ascii=False, indent=1, default=str))
