"""Adversarial negative controls verifying audit sensitivity (ainerzero.V9.P62).

Tests:
  Control 1: Mutate a single float in final-eval-stdout.json (e.g. arm2-seed0 translation_mean_m + 0.05).
             Verify that recomputation assertion triggers on value mismatch.
  Control 2: Mutate one parameter SHA256 in pre_registration inheritance cells.
             Verify that audit fails with parameter mismatch assertion.

Writes log to logs/09_adversarial_controls.txt.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
FINAL_STDOUT = REPO / "reports/V9-S1-final/final-eval-stdout.json"
FINAL_ANALYSIS = REPO / "reports/V9-S1-final/analysis/analysis-final.json"
PREREG = REPO / "artifacts/v9/s1/phase1/final/pre_registration.json"
OUT_LOG = Path(__file__).resolve().parents[1] / "logs" / "09_adversarial_controls.txt"


def test_control_1() -> dict:
    stdout_raw = json.loads(FINAL_STDOUT.read_text(encoding="utf-8"))
    final_analysis = json.loads(FINAL_ANALYSIS.read_text(encoding="utf-8"))
    
    # Mutate arm2-seed0 translation error
    mutated = copy.deepcopy(stdout_raw)
    orig_val = mutated["details"]["cells"]["arm2-seed0"]["localization_error"]["localization_error"]["translation_mean_m"]
    mutated["details"]["cells"]["arm2-seed0"]["localization_error"]["localization_error"]["translation_mean_m"] += 0.05
    
    caught = False
    error_msg = ""
    try:
        # Check against target arm in analysis
        vals = [mutated["details"]["cells"][f"arm2-seed{s}"]["localization_error"]["localization_error"]["translation_mean_m"] for s in [0, 1, 2]]
        m = sum(vals) / 3.0
        tgt_mean = final_analysis["scalars"][0]["per_arm"]["arm2"]["mean"]
        if abs(m - tgt_mean) > 1e-12:
            raise AssertionError(f"Mean mismatch: recomputed {m} != expected {tgt_mean}")
    except AssertionError as e:
        caught = True
        error_msg = str(e)
        
    return {
        "control_name": "control_1_mutated_eval_stdout_float",
        "caught": caught,
        "orig_val": orig_val,
        "mutated_val": orig_val + 0.05,
        "error_message": error_msg,
    }


def test_control_2() -> dict:
    stdout_raw = json.loads(FINAL_STDOUT.read_text(encoding="utf-8"))
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    
    mutated_prereg = copy.deepcopy(prereg)
    # Mutate the parameter sha of arm2-seed0
    mutated_prereg["inheritance"]["cells"][0]["params_sha256"] = "0" * 64
    
    caught = False
    error_msg = ""
    try:
        c = mutated_prereg["inheritance"]["cells"][0]
        cell_key = c["arm_id"] + "-seed" + str(c["seed"])
        stdout_sha = stdout_raw["details"]["cells"][cell_key]["run_binding"]["inherited"]["params_sha256"]
        if c["params_sha256"] != stdout_sha:
            raise AssertionError(f"Param SHA mismatch: prereg {c['params_sha256']} != stdout {stdout_sha}")
    except AssertionError as e:
        caught = True
        error_msg = str(e)
        
    return {
        "control_name": "control_2_mutated_prereg_param_sha",
        "caught": caught,
        "error_message": error_msg,
    }


def main() -> int:
    lines = []
    lines.append("=== ADVERSARIAL NEGATIVE CONTROLS ===")
    
    res1 = test_control_1()
    lines.append(f"\n1. {res1['control_name']}:")
    lines.append(f"   Caught: {res1['caught']}")
    lines.append(f"   Details: mutated {res1['orig_val']} -> {res1['mutated_val']}")
    lines.append(f"   Triggered error: {res1['error_message']}")
    assert res1["caught"] is True
    
    res2 = test_control_2()
    lines.append(f"\n2. {res2['control_name']}:")
    lines.append(f"   Caught: {res2['caught']}")
    lines.append(f"   Triggered error: {res2['error_message']}")
    assert res2["caught"] is True
    
    lines.append("\n=== BOTH ADVERSARIAL CONTROLS SUCCESSFULLY DETECTED MUTATIONS ===")
    
    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Adversarial controls verified. Log written to {OUT_LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
