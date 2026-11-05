"""Confirm k=1 stop boundary and probe_graph (r,c) fixes remain in pinned sources."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "reports/V9-P9/r10/evidence/prior-fixes.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    evaluation = REPO / "src/ainerzero/v9/experiments/s1/evaluation.py"
    runtime = REPO / "src/ainerzero/v9/experiments/s1/runtime.py"
    eval_text = evaluation.read_text(encoding="utf-8")
    runtime_text = runtime.read_text(encoding="utf-8")

    stop_ok = bool(re.search(r"stop\s*=\s*support\[-1\]\s*\+\s*2", eval_text))
    remap_ok = "(int(r), int(c))" in runtime_text and "flat index" in runtime_text

    probe_test = REPO / "tests/v9/experiments/test_s1_r6_probe_graph.py"
    r10_test = REPO / "tests/v9/experiments/test_s1_r10_query_limit.py"

    payload = {
        "schema": "ainerzero.v9.s1.r10.prior_fixes.v1",
        "k1_stop_boundary": {
            "status": "present" if stop_ok else "missing",
            "pattern": "stop=support[-1]+2",
            "source": "src/ainerzero/v9/experiments/s1/evaluation.py",
            "source_sha256": sha256(evaluation),
            "regression_tests": [
                "tests/v9/experiments/test_s1_r10_query_limit.py::test_k1_stop_boundary_is_support_last_plus_two",
            ],
        },
        "probe_graph_metric_map_rc": {
            "status": "present" if remap_ok else "missing",
            "pattern": "remap uses (int(r), int(c)); rejects flat-index unpack",
            "source": "src/ainerzero/v9/experiments/s1/runtime.py",
            "source_sha256": sha256(runtime),
            "regression_tests": [
                "tests/v9/experiments/test_s1_r6_probe_graph.py",
            ],
            "probe_test_sha256": sha256(probe_test) if probe_test.is_file() else None,
        },
        "r10_query_limit_tests": {
            "path": "tests/v9/experiments/test_s1_r10_query_limit.py",
            "sha256": sha256(r10_test) if r10_test.is_file() else None,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(json.dumps(payload, indent=1))
    return 0 if stop_ok and remap_ok else 7


if __name__ == "__main__":
    raise SystemExit(main())
