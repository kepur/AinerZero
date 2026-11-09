"""PREREG-r1 与 95401b7 的清单、字段、分区种子核对。不导入 MLX。"""
import hashlib, importlib.metadata as md, json, re, subprocess, sys, types
from pathlib import Path
import numpy
F = Path(sys.argv[1]).resolve(); Live = Path("/Users/mac/AinerWorkFlow/AinerZero")
import ainerzero
assert Path(ainerzero.__file__).resolve().is_relative_to(F), ainerzero.__file__
from ainerzero.v9.experiments.s3 import analysis_p2 as G, data as D, run_guard as GD, spec
assert "mlx" not in sys.modules and "mlx.core" not in sys.modules
p = json.loads((F / "reports/V9-S3-PHASE2/PREREG-r1.json").read_text(encoding="utf-8")); m = p["manifest"]; sha = lambda q: hashlib.sha256(Path(q).read_bytes()).hexdigest(); O = {}
O["files_in_manifest"] = len(m)
O["sha_vs_commit_95401b7_bad"] = [k for k, v in m.items() if sha(F / k) != v]
O["sha_vs_live_tree_bad"] = [k for k, v in m.items() if sha(Live / k) != v]
rebuilt = GD.build_manifest(F, [F / "reports/V9-S3-PHASE2/run_phase2.py"], src_root=F / "src", extra=[F / "reports/V9-S3-PHASE2-DESIGN/DESIGN-r2.md"])
O["rebuilt_equals_prereg"] = rebuilt == m; O["rebuilt_only"] = sorted(set(rebuilt) - set(m)); O["prereg_only"] = sorted(set(m) - set(rebuilt))
O["categories"] = {"s3": sum("/s3/" in k for k in m), "s2": sum("/s2/" in k for k in m), "other_src": sum(k.startswith("src/") and "/s3/" not in k and "/s2/" not in k for k in m), "reports": [k for k in m if not k.startswith("src/")]}
run = (F / "reports/V9-S3-PHASE2/run_phase2.py").read_text(); arms = (F / "src/ainerzero/v9/experiments/s3/arms_mlx.py").read_text()
O["fields"] = {
 "seeds": p["seeds"] == [1, 2, 3] and "SEEDS = (1, 2, 3)" in run, "steps": p["steps"] == {"F1": 2000, "F2": 1000} and "F1_STEPS, F2_STEPS = 2000, 1000" in run,
 "batch_mix_lr": (p["batch"], p["replay_mix"], p["lr"]) == (16, [8, 8], 1e-3) and "BATCH, MIX, LR = 16, 8, 1e-3" in run, "clip": "1.0" in p["optimizer"] and "optim.clip_grad_norm(g, 1.0)" in run,
 "batch_seeds": p["batch_seeds"] == {"F1": "seed", "F2": "seed + 1000", "J": "seed"}, "key": "key = mx.random.key(seed)" in run and "split" in p["sampling_key"],
 "perm": "seed = base + w * 100 + e" in run and all(x in p["perm_seed"] for x in ("10000000", "20000000", "30000000")), "offsets": p["seed_offsets"] == {"buffer": "7000000 + seed", "CN": "7100000 + seed", "N": "7200000 + perm_seed"} and "BUFFER_SEED, CN_SEED, N_SEED = 7_000_000, 7_100_000, 7_200_000" in run,
 "temp": p["utility_temperature"] == 0.5 and "UTILITY_TEMPERATURE = 0.5" in arms, "lambda": p["cue_lambda"] == 1.0 and "LAM = 1.0" in run, "dev_max": p["dev_max_uses"] == 2, "namespaces": p["namespaces"] == G.NAMESPACES, "limit": p["budget"]["hard_limit_hours_per_run"] == 1.5 and run.count('"limit": 5400') == 2,
 "design": p["design"] == "reports/V9-S3-PHASE2-DESIGN/DESIGN-r2.md" and p["design"] in m,
}
g = p["gates"]
O["gates"] = {k: v for k, v in {"chance": g["chance"] == G.CHANCE, "floor": g["floor"] == G.FLOOR, "upper": g["upper_O"] == G.UPPER_MIN, "unswapped": g["unswapped_min"] == G.UNSWAPPED_MIN, "H1": g["H1_min_delta"] == G.H1_MIN_DELTA, "H2": g["H2_min_delta"] == G.H2_MIN_DELTA, "H2b": g["H2b_min_delta"] == G.H2B_MIN_DELTA, "H3": g["H3_margin_upper_bound"] == G.H3_MARGIN, "inter": g["interference_min_8class"] == G.INTERFERENCE_MIN, "content": g["content_min_8class"] == G.CONTENT_MIN, "events": g["min_events_per_seed"] == G.MIN_EVENTS_PER_SEED, "eps": g["min_episodes_per_seed"] == G.MIN_EPISODES_PER_SEED}.items()}
pr = F / p["probe_report"]; prj = json.loads(pr.read_text()); O["probe"] = {"sha_ok": sha(pr) == p["probe_report_sha256"], "selected": prj["selected_capacity"], "h3_capacity": p["h3_capacity"]}
O["third_party"] = {"prereg": p["third_party"], "numpy_now": numpy.__version__, "mlx_dist_now": md.version("mlx")}
O["approval_present"] = bool(p.get("final_approval_line")); O["namespaces"] = p["namespaces"]
def seeds(ns, tag, nw, ne): return {D.derive_seed(ns, tag + "world", w) for w in range(nw)} | {D.derive_seed(ns, tag + "ep", w, e) for w in range(nw) for e in range(ne)}
S = {}
for ns, nw, ne in (("s3p1-train", 400, 4), ("s3p1-dev", 50, 2), ("s3p1-final", 100, 2), ("s3p1-probe", 300, 2), ("s3p2-train", 400, 4), ("s3p2-dev", 50, 2), ("s3p2-final", 100, 2), ("s3p2-probe", 100, 2), ("s3p2b-dev", 50, 2), ("s3p2b-final", 100, 2)):
    for tag in ("", "f2-"): S[ns + "/" + tag] = seeds(ns, tag, nw, ne)
S["s3p1-probe/explore"] = seeds("s3p1-probe", "explore-", 200, 2) | seeds("s3p1-probe", "explore-f2-", 200, 2)
names = sorted(S); O["seed_collisions"] = {f"{a}&{b}": len(S[a] & S[b]) for i, a in enumerate(names) for b in names[i + 1:] if S[a] & S[b]}; O["seed_sets"] = len(names); O["total_seeds"] = sum(map(len, S.values()))
def src(rev, rel): return subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=Live, capture_output=True, text=True, check=True).stdout
def walk(c, q=""):
    yield q + c.co_name, c
    for k in c.co_consts:
        if isinstance(k, types.CodeType): yield from walk(k, q + c.co_name + ".")
def sig(c):
    cs = tuple(("<code>" if isinstance(k, types.CodeType) else (None if isinstance(k, str) and len(k) > 30 else k)) for k in c.co_consts)
    return (c.co_code, c.co_names, c.co_varnames, cs)
O["bytecode_6edc68d_to_95401b7"] = {}
for rel in ("reports/V9-S3-PHASE2/run_phase2.py", "src/ainerzero/v9/experiments/s3/analysis_p2.py", "src/ainerzero/v9/experiments/s3/run_guard.py", "src/ainerzero/v9/experiments/s3/arms_p2_mlx.py", "src/ainerzero/v9/experiments/s3/replay.py"):
    a = dict(walk(compile(src("6edc68d", rel), rel, "exec"))); b = dict(walk(compile(src("95401b7", rel), rel, "exec")))
    O["bytecode_6edc68d_to_95401b7"][rel.split("/")[-1]] = {"identical": sum(sig(a[n]) == sig(b[n]) for n in set(a) & set(b)), "changed": sorted(n for n in set(a) & set(b) if sig(a[n]) != sig(b[n])), "added": sorted(set(b) - set(a))}
O["frozen_changed_since_prereg_commit"] = subprocess.run(["git", "diff", "--name-only", "95401b7", "--"] + list(m), cwd=Live, capture_output=True, text=True).stdout.split()
print(json.dumps(O, ensure_ascii=False, indent=1))
