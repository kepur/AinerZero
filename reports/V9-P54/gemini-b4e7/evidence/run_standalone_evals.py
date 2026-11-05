#!/usr/bin/env python3
"""Standalone real evaluation of at least two arms on an isolated copy for P54.

Task requirement:
"再在隔离副本上对至少两个臂真实跑一次评测，确认 completed。"
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import spec, worker  # noqa: E402

PRODUCTION = REPO / "artifacts/v9/s1/phase1"
EVID = REPO / "reports/V9-P54/gemini-b4e7/evidence"


def main():
    print("=== Running Standalone Real Evals on Isolated Copy ===", flush=True)

    with tempfile.TemporaryDirectory(prefix="s1-r15-standalone-eval-") as td:
        copy_root = Path(td) / "phase1"
        shutil.copytree(PRODUCTION, copy_root)
        prereg_path = copy_root / "r15/pre_registration.json"
        doc = json.loads(prereg_path.read_text(encoding="utf-8"))
        digest = spec.sha256_file(prereg_path)

        # Temporary host anchor to satisfy safety checks
        orig_ledger = worker.canonical_ledger_path
        worker.canonical_ledger_path = lambda *a, **k: copy_root / "control.sqlite3"

        eval_results = {}
        try:
            # Run arm2 seed 0 (inherited from r13)
            print("  Evaluating arm2 seed 0...", flush=True)
            res_arm2 = worker._evaluate_arm(doc, copy_root, arm_id="arm2", seed=0, prereg_sha256=digest)
            assert res_arm2.get("status") == "completed", f"arm2 s0 eval failed: {res_arm2}"
            eval_results["arm2_s0"] = {
                "status": res_arm2.get("status"),
                "arm": "arm2",
                "seed": 0,
                "bound_run_id": res_arm2.get("run_binding", {}).get("run_id"),
                "inherited_from": res_arm2.get("run_binding", {}).get("inherited", {}).get("source_experiment_id"),
                "few_shot_summary": res_arm2.get("few_shot_summary"),
            }

            # Run arm3 seed 1 (inherited from r14)
            print("  Evaluating arm3 seed 1...", flush=True)
            res_arm3 = worker._evaluate_arm(doc, copy_root, arm_id="arm3", seed=1, prereg_sha256=digest)
            assert res_arm3.get("status") == "completed", f"arm3 s1 eval failed: {res_arm3}"
            eval_results["arm3_s1"] = {
                "status": res_arm3.get("status"),
                "arm": "arm3",
                "seed": 1,
                "bound_run_id": res_arm3.get("run_binding", {}).get("run_id"),
                "inherited_from": res_arm3.get("run_binding", {}).get("inherited", {}).get("source_experiment_id"),
                "few_shot_summary": res_arm3.get("few_shot_summary"),
            }

            # Run arm4 seed 2 (inherited from r14)
            print("  Evaluating arm4 seed 2...", flush=True)
            res_arm4 = worker._evaluate_arm(doc, copy_root, arm_id="arm4", seed=2, prereg_sha256=digest)
            assert res_arm4.get("status") == "completed", f"arm4 s2 eval failed: {res_arm4}"
            eval_results["arm4_s2"] = {
                "status": res_arm4.get("status"),
                "arm": "arm4",
                "seed": 2,
                "bound_run_id": res_arm4.get("run_binding", {}).get("run_id"),
                "inherited_from": res_arm4.get("run_binding", {}).get("inherited", {}).get("source_experiment_id"),
                "few_shot_summary": res_arm4.get("few_shot_summary"),
            }

        finally:
            worker.canonical_ledger_path = orig_ledger

        out_file = EVID / "standalone_eval_results.json"
        out_file.write_text(json.dumps(eval_results, indent=2, ensure_ascii=False) + "\n")
        print(f"  All {len(eval_results)} real evals completed successfully. Results saved to {out_file}.", flush=True)


if __name__ == "__main__":
    main()
