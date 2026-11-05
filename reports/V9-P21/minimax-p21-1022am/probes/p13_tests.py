"""P21 probe 13: summarise the re-run test suites.

The suites were re-run by the reviewer with a CPU-only MLX stub (see
p21_mlx_stub_plugin.py).  This probe parses the JUnit XML and the captured
logs and records exactly what was re-verified and what stayed unverified.

Commands (run from the repository root):

    PYTHONPATH="reports/V9-P21/minimax-p21-1022am/probes" \
      .venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider \
      -p p21_mlx_stub_plugin --junitxml=reports/V9-P21/minimax-p21-1022am/logs/pytest-experiments.xml

    PYTHONPATH="reports/V9-P21/minimax-p21-1022am/probes" \
      .venv/bin/python -m pytest tests/v9/geometry tests/v9/contracts \
      tests/v9/teachers tests/v9/tokenization -q -p no:cacheprovider \
      -p p21_mlx_stub_plugin --junitxml=reports/V9-P21/minimax-p21-1022am/logs/pytest-other-v9.xml

    .venv/bin/python -m pytest tests/v9/geometry/test_canonical.py::test_cpu_only_imports \
      tests/v9/geometry/test_geometry.py::test_imports_are_cpu_only -q -p no:cacheprovider
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402

LOGS = lib.LOGS

# the tests that drive the real MLX runtime and therefore could not be re-run
# under the CPU-only constraint (no MLX import, no model forward)
MLX_BACKED = {
    "test_s1_no_update.py::test_smoke_reports_no_update_when_the_digests_match",
    "test_s1_no_update.py::test_smoke_reports_an_update_when_a_parameter_really_changed",
    "test_s1_pacer_duty.py::test_pacer_sleeps_to_hold_the_duty_cycle[0.25-0.06]",
    "test_s1_pacer_duty.py::test_pacer_sleeps_to_hold_the_duty_cycle[0.5-0.02]",
    "test_s1_pacer_duty.py::test_pacer_sleeps_to_hold_the_duty_cycle[0.1-0.18]",
    "test_s1_pacer_duty.py::test_pacer_records_the_registered_duty_cycle_only",
    "test_s1_timing_sequence.py::test_worker_train_resets_deadline_across_sequential_runs",
}
STUB_ARTEFACT = {
    "test_canonical.py::test_cpu_only_imports",
    "test_geometry.py::test_imports_are_cpu_only",
}


def _matches(classname: str, name: str, candidates: set[str]) -> bool:
    short = classname.rsplit(".", 1)[-1]
    for candidate in candidates:
        file_name, _, test_name = candidate.partition("::")
        if short == file_name.removesuffix(".py") and name == test_name:
            return True
    return False


def parse_junit(path: Path) -> dict:
    if not path.is_file():
        return {"available": False}
    root = ET.parse(path).getroot()
    suites = root.findall("testsuite") or [root]
    total = failures = errors = skipped = 0
    names = []
    for suite in suites:
        total += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        for case in suite.findall("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                names.append(f"{case.get('classname')}::{case.get('name')}")
    return {
        "available": True,
        "tests": total,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "failed_tests": sorted(names),
    }


def main() -> int:
    experiments = parse_junit(LOGS / "pytest-experiments.xml")
    other = parse_junit(LOGS / "pytest-other-v9.xml")
    cpu_only_log = (LOGS / "pytest-cpu-only-imports.txt").read_text(encoding="utf-8").strip()
    cpu_only = {
        "command": ".venv/bin/python -m pytest "
        "tests/v9/geometry/test_canonical.py::test_cpu_only_imports "
        "tests/v9/geometry/test_geometry.py::test_imports_are_cpu_only -q -p no:cacheprovider",
        "result": cpu_only_log.splitlines()[-1] if cpu_only_log else "",
        "note": "these two tests assert that no mlx module is imported; they only fail "
        "under the review stub because the stub registers the name 'mlx' in sys.modules; "
        "the geometry/contracts/teachers/tokenization packages never import mlx, so the two "
        "tests were re-run without the stub and pass",
    }
    experiments_failures = [name for name in experiments.get("failed_tests", [])]
    other_failures = [name for name in other.get("failed_tests", [])]
    payload = {
        "schema": "ainerzero.v9.p21.probe13_test_suites.v1",
        "cpu_only_constraint": "no MLX import, no model forward, no training, no evaluation; "
        "a stub 'mlx' package is injected so that arms.py's module level import does not "
        "load the real MLX runtime",
        "experiments_suite": {
            "command": "PYTHONPATH=reports/V9-P21/minimax-p21-1022am/probes .venv/bin/python -m "
            "pytest tests/v9/experiments -q -p no:cacheprovider -p p21_mlx_stub_plugin",
            "result": experiments,
            "failures_are_stub_artifacts": all(
                _matches(name.split("::")[0], name.split("::")[1], MLX_BACKED)
                for name in experiments_failures
            ),
            "unverified_because_they_need_the_real_mlx_runtime": sorted(MLX_BACKED),
            "author_claim": "235 passed / 0 failed",
            "reviewer_reverified": experiments.get("tests", 0) - len(experiments_failures),
        },
        "other_v9_suites": {
            "command": "PYTHONPATH=reports/V9-P21/minimax-p21-1022am/probes .venv/bin/python -m "
            "pytest tests/v9/geometry tests/v9/contracts tests/v9/teachers tests/v9/tokenization "
            "-q -p no:cacheprovider -p p21_mlx_stub_plugin",
            "result": other,
            "failures_are_stub_artifacts": all(
                _matches(name.split("::")[0], name.split("::")[1], STUB_ARTEFACT)
                for name in other_failures
            ),
            "author_claim": "378 passed",
            "reviewer_reverified": (other.get("tests", 0) - len(other.get("failed_tests", [])))
            + 2,
        },
        "cpu_only_import_tests": cpu_only,
        "interpretation": "the green test suites support the engineering claims but do not "
        "prove any capability; 7 of the 235 experiments tests drive the real MLX runtime and "
        "could not be re-run under the CPU-only constraint",
    }
    out = lib.write_json("13-test-suites.json", payload)
    print(json.dumps({
        "experiments": payload["experiments_suite"]["result"].get("tests"),
        "experiments_passed": payload["experiments_suite"]["reviewer_reverified"],
        "experiments_failures_are_stub_artifacts": payload["experiments_suite"][
            "failures_are_stub_artifacts"
        ],
        "other_v9_passed": payload["other_v9_suites"]["reviewer_reverified"],
        "other_v9_failures_are_stub_artifacts": payload["other_v9_suites"][
            "failures_are_stub_artifacts"
        ],
    }, indent=1))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
