#!/usr/bin/env python3
"""Audit 3: Arm1 evaluation entrypoint functionality audit.
Audits the fact that Arm1 (the approved frozen D candidate) is unconditionally
refused by S1 evaluation with refused_stage='arm1_has_no_checkpoint_binding'.
"""

import json
import sys
from pathlib import Path

REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
sys.path.insert(0, str(REAL_REPO / "src"))

from ainerzero.v9.experiments.s1 import spec, worker

def main():
    # Inspect spec for arm1
    arm1_spec = spec.ARM_SPECS.get("arm1", {})
    arm1_kind = arm1_spec.get("kind")
    arm1_identity = arm1_spec.get("identity", {})

    # Call worker.run_worker("eval", arm="arm1") with output_root=spec.PHASE1_ROOT
    prereg = spec.PHASE1_ROOT / "r6" / "pre_registration.json"
    report = worker.run_worker(
        mode="eval",
        output_root=spec.PHASE1_ROOT,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=450.0,
        prereg_path=prereg,
        arm="arm1",
        seed=0,
    )

    is_refused = (report.get("status") == "refused")
    stage = report.get("refused_stage")
    msg = report.get("message")

    result = {
        "arm1_kind": arm1_kind,
        "arm1_identity": arm1_identity,
        "eval_run_worker_report": report,
        "refused_as_expected": is_refused,
        "refused_stage": stage,
        "analysis": {
            "finding": (
                "Arm1 is the registered frozen D candidate with an existing frozen checkpoint identity in Phase D. "
                "However, worker.py lines 639-650 unconditionally refuse Arm1 evaluation with "
                "status='refused' and refused_stage='arm1_has_no_checkpoint_binding'. "
                "Consequently, Arm1 evaluation is NOT implemented in the S1 evaluation pipeline, "
                "and the author cannot claim that all evaluation entrypoints are complete."
            )
        }
    }

    out_file = REAL_REPO / "reports" / "V9-P17" / "evidence" / "arm1_eval_audit.json"
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("Arm1 eval audit completed.")
    print(f"Status: {report.get('status')}, Refused Stage: {stage}")

if __name__ == "__main__":
    main()
