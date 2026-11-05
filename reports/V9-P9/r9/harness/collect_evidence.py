"""Collect the r9 evidence bundle: test counts, metrics and provenance.

Inputs are the JUnit XMLs produced by the r9 runs plus the r9 artifacts written
earlier (leaf diff, source identity, R1/R2 evidence).  Outputs live under
``reports/V9-P9/r9/`` only.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
R9 = REPO / "reports/V9-P9/r9"


def junit(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    cases = []
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, 0) or 0)
        for case in suite.iter("testcase"):
            outcome = "passed"
            if case.find("failure") is not None:
                outcome = "failed"
            elif case.find("error") is not None:
                outcome = "error"
            elif case.find("skipped") is not None:
                outcome = "skipped"
            cases.append(
                {
                    "name": case.get("name"),
                    "classname": case.get("classname"),
                    "outcome": outcome,
                    "time": case.get("time"),
                }
            )
    return {**totals, "cases": cases}


def main() -> int:
    experiments = junit(R9 / "logs/tests-s1-r9.xml")
    other = junit(R9 / "logs/tests-v9-other-r9.xml")
    new_cases = [
        case
        for case in experiments["cases"]
        if (case["classname"] or "").endswith(
            ("test_s1_r9_shared_experiment", "test_s1_r9_completion_precondition")
        )
    ]
    tests_payload = {
        "schema": "ainerzero.v9.s1.r9.tests.v1",
        "experiments_suite": {k: v for k, v in experiments.items() if k != "cases"},
        "other_v9_suite": {k: v for k, v in other.items() if k != "cases"},
        "r9_new_tests": new_cases,
        "r9_new_test_count": len(new_cases),
        "r9_new_all_passed": all(case["outcome"] == "passed" for case in new_cases),
        "command_experiments": ".venv/bin/python -m pytest tests/v9/experiments -q "
        "-p no:cacheprovider --junitxml=reports/V9-P9/r9/logs/tests-s1-r9.xml",
        "command_other": ".venv/bin/python -m pytest tests/v9 -q -p no:cacheprovider "
        "--ignore=tests/v9/experiments --junitxml=reports/V9-P9/r9/logs/tests-v9-other-r9.xml",
        "environment_note": "the WorkBuddy python shim rewrites mkdir(exist_ok=True) on a "
        "symlink into PermissionError; the suites were run with PYTHONPATH=<repo>/src so the "
        "project's own code is imported unchanged. No source or test was modified for this.",
    }
    (R9 / "evidence/r9-tests.json").write_text(
        json.dumps(tests_payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )

    diff = json.loads((R9 / "prereg-leaf-diff.json").read_text(encoding="utf-8"))
    identity = json.loads((R9 / "source-identity.json").read_text(encoding="utf-8"))
    shared = json.loads((R9 / "evidence/shared-experiment.json").read_text(encoding="utf-8"))
    completion_ev = json.loads(
        (R9 / "evidence/completion-precondition.json").read_text(encoding="utf-8")
    )
    starting = json.loads((R9 / "provenance/STARTING-BYTES.json").read_text(encoding="utf-8"))

    metrics = {
        "task": "ainerzero.V9.P15",
        "agent": "deepseek-v41f-r9x2",
        "cycle": "r9",
        "decision": "claude-20261022-e32/P15-R8-DECISION.md",
        "starting_bytes": {
            "bound_files": starting["bound_file_count"],
            "drift": starting["bound_file_drift"],
            "r8_artifact_files": len(starting["r8_artifacts"]),
            "r8_report_files": len(starting["r8_reports"]),
        },
        "freeze": {
            "path": identity["frozen_document"],
            "document_sha256": identity["document_sha256"],
            "file_sha256": identity["file_sha256"],
            "status": identity["frozen_status"],
            "updates": identity["updates"],
            "seeds": identity["seeds"],
            "timing": identity["timing"],
            "eval_batches": 48,
            "checkpoint_updates": [0, 439, 878, 1755, 3510],
        },
        "leaf_diff": {
            "leaves": diff["leaf_count"],
            "changed": diff["changed_leaf_count"],
            "changed_bound_files": [row["path"] for row in diff["changed_bound_files"]],
            "bound_files_outside_allowlist": diff["bound_files_outside_allowlist"],
            "non_identity_leaves_outside_allowlist": [
                row["path"] for row in diff["non_identity_leaves_outside_allowlist"]
            ],
        },
        "tests": {
            "experiments": experiments["tests"],
            "experiments_failures": experiments["failures"] + experiments["errors"],
            "other_v9": other["tests"],
            "other_v9_failures": other["failures"] + other["errors"],
            "r9_new": len(new_cases),
            "r9_new_failures": sum(1 for case in new_cases if case["outcome"] != "passed"),
        },
        "r1": {
            "d_then_train_ok": shared["A_d_then_train"]["error"] is None,
            "train_then_d_ok": shared["B_train_then_d"]["error"] is None,
            "same_experiment_id": shared["A_d_then_train"]["same_experiment"]
            and shared["B_train_then_d"]["same_experiment"],
            "budgets": shared["A_d_then_train"]["budgets"],
            "foreign_manifest_refused_by_d": not shared["C_foreign_manifest"]["d"]["accepted"],
            "foreign_manifest_refused_by_train": not shared["C_foreign_manifest"]["train"][
                "accepted"
            ],
            "sabotage_reuses_foreign": shared["D_sabotage_control"]["d"]["accepted"],
        },
        "r2": {
            "before_second_call": completion_ev["before_truncation"]["second_call"]["status"],
            "before_second_call_stage": completion_ev["before_truncation"]["second_call"][
                "refused_stage"
            ],
            "before_ledger_state": completion_ev["before_truncation"]["second_call"][
                "ledger_state"
            ],
            "after_second_call": completion_ev["after_truncation"]["second_call"]["status"],
            "terminal_second_call": completion_ev["terminal_without_marker"]["second_call"][
                "status"
            ],
            "markers_unchanged": completion_ev["before_truncation"]["markers_after_second"] == 1,
            "sabotage_reproduces_bug": completion_ev["sabotage_control"]["bug_reproduced"],
        },
        "not_run": [
            "real MLX forward / training / evaluation / final partition",
            "new data generation or download",
            "approval line or central ledger write",
            "P1 start",
            "generic RunStore / lifecycle change",
        ],
    }
    (R9 / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
