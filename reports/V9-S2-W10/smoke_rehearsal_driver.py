import sys, time, json
from pathlib import Path
from ainerzero.v9.experiments.s2 import smoke
root = Path(sys.argv[1])
t = time.perf_counter()
arms, step_times, plan_times, s3, s4, dflt, reasons = smoke.measure_real_smoke(output_root=root)
el = time.perf_counter() - t
print("ELAPSED", round(el, 1))
print("REASONS", reasons)
print("STEP_TIMES", step_times)
print("PLAN_TIMES", plan_times)
print("STEP3_PASSED", s3["passed"], {k: (v["passed"], round(v["initial_sigreg"] or 0, 6), round(v["final_sigreg"] or 0, 6), round(v["mean_first_window"], 6), round(v["mean_last_window"], 6)) for k, v in s3["arms"].items()})
print("STEP4", {k: s4.get(k) for k in ("passed", "success_rate", "fuse_triggered", "n_episodes")})
b = smoke.check_smoke_budget({"shared_train_steps": 3038}, step_times, plan_times)
print("BUDGET_TOTAL", round(b["total_estimated_seconds"]), "passed", b["passed"], b["reasons"])
print("BUDGET_PARTS", {k: round(v["estimated_seconds"]) for k, v in b["breakdown"].items()})
