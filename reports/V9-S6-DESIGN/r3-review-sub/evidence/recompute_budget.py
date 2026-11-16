#!/usr/bin/env python3
"""S6 r3 review, item 1: recompute the freeze-entry budget extrapolation from the probe's EVAL-probe.json
with prereg_evidence.estimate_budget's formula (restated here, then also called directly on the r2 and r3
caps), and the margins DESIGN-r3 §5 quotes. Pure CPU; imports prereg_evidence only if it does not import
MLX (checked)."""
import json
import sys

R = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-PHASE1"
pr = json.load(open(f"{R}/probe/EVAL-probe.json"))
final = pr["sets"]["final"]
print("probe train_seconds", pr["train_seconds"]); print("verify_seconds", pr["verify_seconds"], "eval_seconds", pr["eval_seconds"])
print("probe worlds", pr["config"]["worlds"], "final worlds", final["worlds"], "final reps", final["reps"])
print("final caps in EVAL-probe.json (r2):", final["train_cap_s"], final["eval_limit_s"])
n_final = sum(final["reps"].values())
train_core = sum(pr["train_seconds"][a + "-r0"] * k for a, k in final["reps"].items())
est_train = 1.15 * (train_core + 5 * 90)
est_eval = 1.30 * (pr["verify_seconds"] * n_final / 6 + pr["eval_seconds"] * n_final / 6 * sum(final["worlds"]) / sum(pr["config"]["worlds"]))
print(f"n_final cells {n_final}; sum train_seconds x reps = {train_core:.2f}")
print(f"est_train = 1.15 x ({train_core:.2f} + 450) = {est_train:.6f}")
print(f"est_eval  = 1.30 x ({pr['verify_seconds']} x {n_final}/6 + {pr['eval_seconds']} x {n_final}/6 x {sum(final['worlds'])}/{sum(pr['config']['worlds'])}) = {est_eval:.6f}")
v_part = 1.30 * pr["verify_seconds"] * n_final / 6
e_part = 1.30 * pr["eval_seconds"] * n_final / 6 * sum(final["worlds"]) / sum(pr["config"]["worlds"])
print(f"  of which verify {v_part:.2f} s ({v_part / est_eval:.1%}), eval {e_part:.2f} s")
for name, (tc, ec) in {"r2": (21600, 3600), "r3": (19800, 5400)}.items():
    print(f"{name}: train {est_train:.2f} <= {tc}: {est_train <= tc} (margin {tc - est_train:.2f} s, {tc / est_train - 1:.1%}); "
          f"eval {est_eval:.2f} <= {ec}: {est_eval <= ec} (margin {ec - est_eval:.2f} s, {ec / est_eval - 1:.1%})")
# raw (no safety factor) projections, to see what the caps cover
raw_train = train_core + 450
print(f"raw train (no 1.15) {raw_train:.1f} s -> r3 cap / raw = {19800 / raw_train:.3f}; raw train without the 450 s = {train_core:.1f} -> {19800 / train_core:.3f}")
raw_eval = est_eval / 1.30
print(f"raw eval (no 1.30) {raw_eval:.1f} s -> r3 cap / raw = {5400 / raw_eval:.3f}")
# call the implementation itself
sys.path.insert(0, R)
import importlib
pe = importlib.import_module("prereg_evidence")
print("prereg_evidence imported; mlx in sys.modules:", any(m.startswith("mlx") for m in sys.modules))
for name, (tc, ec) in {"r2": (21600, 3600), "r3": (19800, 5400)}.items():
    p2 = json.loads(json.dumps(pr)); p2["sets"]["final"]["train_cap_s"] = tc; p2["sets"]["final"]["eval_limit_s"] = ec
    try:
        print(f"estimate_budget with {name} caps ->", pe.estimate_budget(p2))
    except Exception as ex:
        print(f"estimate_budget with {name} caps refuses: {type(ex).__name__}: {ex}")
