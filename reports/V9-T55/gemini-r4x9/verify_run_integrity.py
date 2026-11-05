#!/usr/bin/env python3
"""Verification of run execution and evidence integrity for T54:
1. forward_accounting: planned == actual == 9 calls / 25 views for both DA3-SMALL and DA3-BASE, complete == true.
2. All stages exist: first_frame, calibration, frame_order_adverse, cpu_parity.
3. failures list contains exactly one failure: DA3-SMALL/frame_order_adverse: adverse control did not turn red.
4. run.stderr.log contains relay exec supervision evidence: confirmed_empty=true, no remaining processes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LOG_FILE = HERE / "logs" / "run_integrity.log"

EVIDENCE_PATH = REPO / "reports" / "V9-T54" / "calibration_evidence.json"
STDERR_PATH = REPO / "reports" / "V9-T54" / "run.stderr.log"


def main():
    log = []
    log.append("=== Verification of T54 Run Integrity & Evidence ===")

    ev = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))

    # 1. Forward Accounting
    fa = ev["forward_accounting"]
    log.append("\n1. Forward Accounting Verification:")
    for variant in ["DA3-SMALL", "DA3-BASE"]:
        assert variant in fa, f"Missing {variant} in forward_accounting"
        v_data = fa[variant]
        log.append(f"  Variant {variant}:")
        log.append(f"    calls: planned={v_data['calls_planned']}, actual={v_data['calls_actual']}")
        log.append(f"    views: planned={v_data['views_planned']}, actual={v_data['views_actual']}")
        log.append(f"    complete: {v_data['complete']}")

        assert v_data["calls_planned"] == 9, f"calls_planned != 9 ({v_data['calls_planned']})"
        assert v_data["calls_actual"] == 9, f"calls_actual != 9 ({v_data['calls_actual']})"
        assert v_data["views_planned"] == 25, f"views_planned != 25 ({v_data['views_planned']})"
        assert v_data["views_actual"] == 25, f"views_actual != 25 ({v_data['views_actual']})"
        assert v_data["complete"] is True, f"complete is not True ({v_data['complete']})"

    log.append("Check passed: forward_accounting planned == actual (9 calls / 25 views), complete == true.")

    # 2. Stages
    stages = ev["stages"]
    required_stages = ["first_frame", "calibration", "frame_order_adverse", "cpu_parity"]
    log.append("\n2. Stages Verification:")
    for variant in ["DA3-SMALL", "DA3-BASE"]:
        assert variant in stages, f"Missing {variant} in stages"
        var_stages = stages[variant]
        log.append(f"  Variant {variant} stages: {list(var_stages.keys())}")
        for s in required_stages:
            assert s in var_stages, f"Missing stage {s} in {variant}"
            assert var_stages[s].get("wall_s") is not None, f"Missing wall_s in {variant}/{s}"

    log.append("Check passed: All stages present for both DA3-SMALL and DA3-BASE.")

    # 3. Failures
    failures = ev.get("failures", [])
    log.append(f"\n3. Failures Verification:\n  Count: {len(failures)}")
    log.append(f"  Failures list: {json.dumps(failures, indent=2)}")
    assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}"
    expected_failure = "DA3-SMALL/frame_order_adverse: adverse control did not turn red"
    assert failures[0] == expected_failure, f"Unexpected failure: {failures[0]} vs {expected_failure}"
    log.append("Check passed: failures contains exactly the single adverse control failure.")

    # 4. relay exec supervision in run.stderr.log
    stderr_content = STDERR_PATH.read_text(encoding="utf-8")
    log.append(f"\n4. Process Supervision Evidence in run.stderr.log:\n{stderr_content}")
    assert "confirmed_empty" in stderr_content
    # Parse json in stderr
    supervision_found = False
    for line in stderr_content.splitlines():
        if "墙钟监督证据：" in line:
            json_part = line.split("墙钟监督证据：", 1)[1].strip()
            sup_data = json.loads(json_part)
            assert sup_data["confirmed_empty"] is True, f"confirmed_empty is not True: {sup_data}"
            assert len(sup_data["members_left"]) == 0, f"members_left is not empty: {sup_data['members_left']}"
            supervision_found = True
            log.append(f"  Parsed supervision data:\n    confirmed_empty={sup_data['confirmed_empty']}, members_left={sup_data['members_left']}")
            break

    assert supervision_found, "Relay exec supervision evidence not found in run.stderr.log"
    log.append("Check passed: Process supervision confirmed empty, no residual processes.")

    out_str = "\n".join(log)
    print(out_str)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(out_str + "\n", encoding="utf-8")
    print("\nRUN INTEGRITY VERIFICATION STATUS: PASS")


if __name__ == "__main__":
    main()
