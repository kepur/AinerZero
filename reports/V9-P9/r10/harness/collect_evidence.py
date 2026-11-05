"""Collect r10 evidence summary (tests + freeze + prior-fix confirmation)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "reports/V9-P9/r10/evidence/r10-tests.json"


def junit_counts(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    total = fail = skip = err = 0
    for suite in suites:
        total += int(suite.attrib.get("tests", 0))
        fail += int(suite.attrib.get("failures", 0))
        skip += int(suite.attrib.get("skipped", 0))
        err += int(suite.attrib.get("errors", 0))
    return {
        "tests": total,
        "failures": fail,
        "skipped": skip,
        "errors": err,
        "passed": total - fail - skip - err,
        "path": str(path.relative_to(REPO)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> int:
    s1 = junit_counts(REPO / "reports/V9-P9/r10/logs/tests-s1-r10.xml")
    other = junit_counts(REPO / "reports/V9-P9/r10/logs/tests-v9-other-r10.xml")
    prior = json.loads((REPO / "reports/V9-P9/r10/evidence/prior-fixes.json").read_text())
    diff = json.loads((REPO / "reports/V9-P9/r10/prereg-leaf-diff.json").read_text())
    payload = {
        "schema": "ainerzero.v9.s1.r10.tests.v1",
        "tests_v9_experiments": s1,
        "tests_v9_other": other,
        "r10_new_tests": [
            "tests/v9/experiments/test_s1_r10_query_limit.py::test_draft_and_frozen_register_query_limit_and_reporting_notes",
            "tests/v9/experiments/test_s1_r10_query_limit.py::test_missing_query_limit_refuses",
            "tests/v9/experiments/test_s1_r10_query_limit.py::test_different_query_limit_refuses",
            "tests/v9/experiments/test_s1_r10_query_limit.py::test_bad_control_missing_guard_turns_red",
            "tests/v9/experiments/test_s1_r10_query_limit.py::test_split_support_query_has_no_default_query_limit",
            "tests/v9/experiments/test_s1_r10_query_limit.py::test_few_shot_requires_prereg_or_explicit_registered_limit",
            "tests/v9/experiments/test_s1_r10_query_limit.py::test_k1_stop_boundary_is_support_last_plus_two",
            "tests/v9/experiments/test_s1_r10_query_limit.py::test_reporting_notes_tamper_fails_validate",
            "tests/v9/experiments/test_s1_r10_query_limit.py::test_option_a_notes_do_not_alter_metric_definition",
        ],
        "prior_fix_regressions": prior,
        "freeze": {
            "document_sha256": diff["new_document_sha256"],
            "file_sha256": diff["new_file_sha256"],
            "base_document_sha256": diff["base_document_sha256"],
            "changed_leaf_count": diff["changed_leaf_count"],
            "outside_allowlist": diff["non_identity_leaves_outside_allowlist"],
            "frozen_values": diff["frozen_values"],
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(json.dumps({"s1": s1["passed"], "other": other["passed"], "doc": diff["new_document_sha256"][:16]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
