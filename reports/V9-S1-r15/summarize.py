"""Summarize the r15 eval outputs (reads relay job stdout JSON; writes reports/V9-S1-r15/results_summary.json)."""
import json, subprocess, statistics
from pathlib import Path
HERE = Path(__file__).resolve().parent
led = json.loads((HERE / "run_ledger.json").read_text())
R = ["python3", "/Users/mac/AinerWorkFlow/AinerRelay/bin/relay"]
rows = []
for e in led["evals"]:
    st = json.loads(subprocess.run(R + ["job-status", "--agent", "claude", "--json", e["id"]], capture_output=True, text=True).stdout)
    d = json.loads(Path(st["logs"]["stdout"]["path"]).read_text())["details"]
    rb = d.get("run_binding") or {}
    def g(*path):
        x = d
        for p in path:
            x = x.get(p) if isinstance(x, dict) else None
        return x
    rows.append({
        "arm": d.get("arm_id"), "seed": d.get("seed"), "status": d.get("status"),
        "bound_run": rb.get("run_id"), "inherited_from": (rb.get("inherited") or {}).get("source_experiment_id"),
        "loc_err": g("localization_error", "localization_error"),
        "unseen_nll_mean": g("unseen_map_generalization", "prediction_nll_mean"),
        "unseen_trans_mean_m": g("unseen_map_generalization", "translation_mean_m"),
        "unseen_yaw_mean_deg": g("unseen_map_generalization", "yaw_mean_deg"),
        "topology_f1": g("topology_recovery", "f1"),
        "m2_worst_retention_delta": g("m2_memory_interference", "worst_retention_delta"),
        "incomparable": d.get("incomparable"),
    })
out = {"rows": rows}
agg = {}
for arm in ("arm2", "arm3", "arm4"):
    rs = [r for r in rows if r["arm"] == arm]
    def m(k):
        v = [r[k] for r in rs if isinstance(r[k], (int, float))]
        return {"mean": statistics.fmean(v), "values": v} if v else None
    agg[arm] = {k: m(k) for k in ("unseen_nll_mean", "unseen_trans_mean_m", "unseen_yaw_mean_deg", "topology_f1", "m2_worst_retention_delta")}
out["by_arm"] = agg
(HERE / "results_summary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str) + "\n")
for r in rows:
    print(r["arm"], r["seed"], r["status"], r["inherited_from"], "nll", r["unseen_nll_mean"], "trans_m", r["unseen_trans_mean_m"], "f1", r["topology_f1"], "loc", (str(r["loc_err"])[:60] if r["loc_err"] is not None else None))
for arm, a in agg.items():
    print(arm, {k: (round(v["mean"], 4) if v else None) for k, v in a.items()})
