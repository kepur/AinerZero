"""P27 probe: worker._evaluate_arm reads query_limit from preregistration,
not from a hard-coded spec constant.

Construct a prereg where evaluation.query_limit disagrees with spec.EVALUATION
and verify that few_shot_report refuses.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import evaluation, metrics, spec


def test_prereg_invalid_value_refused():
    """If preregistration.query_limit != spec.EVALUATION, require_query_limit refuses."""
    bad_prereg = {"evaluation": {"query_limit": 99}}
    try:
        metrics.require_query_limit(bad_prereg)
        return False, "invalid prereg limit was accepted"
    except metrics.QueryLimitError as e:
        if "differs from the registered" in str(e):
            return True, f"invalid prereg refused: {e}"
        return False, f"wrong error: {e}"


def test_caller_limit_must_match_prereg():
    """caller query_limit must match resolved preregistration value."""
    good_prereg = {"evaluation": {"query_limit": 8}}
    try:
        evaluation.few_shot_report(
            None, None, [], [],
            preregistration=good_prereg,
            query_limit=4,  # caller says 4, prereg says 8
        )
        return False, "mismatching caller limit was accepted"
    except metrics.QueryLimitError as e:
        if "differs from preregistration" in str(e):
            return True, f"caller/prereg mismatch refused: {e}"
        return False, f"wrong error: {e}"


def test_prereg_reads_from_document():
    """few_shot_report with preregistration=document succeeds when values match."""
    good_prereg = {"evaluation": {"query_limit": 8}}
    try:
        val = metrics.require_query_limit(good_prereg)
        if val != 8:
            return False, f"expected 8, got {val}"
        return True, f"prereg returned {val}"
    except metrics.QueryLimitError as e:
        return False, f"good prereg was refused: {e}"


def test_worker_evaluate_arm_passes_prereg():
    """Code inspection: _evaluate_arm passes document as preregistration."""
    import inspect
    import ainerzero.v9.experiments.s1.worker as worker_module
    src2 = inspect.getsource(worker_module._evaluate_arm)
    if 'preregistration=document' in src2:
        return True, "_evaluate_arm passes preregistration=document to few_shot_report"
    return False, "_evaluate_arm does not pass preregistration=document"


def main() -> int:
    all_ok = True
    for name, fn in [
        ("prereg_invalid_refused", test_prereg_invalid_value_refused),
        ("caller_limit_match_prereg", test_caller_limit_must_match_prereg),
        ("prereg_reads_from_doc", test_prereg_reads_from_document),
        ("worker_passes_prereg", test_worker_evaluate_arm_passes_prereg),
    ]:
        ok, msg = fn()
        print(f"{'PASS' if ok else 'FAIL'} {name}: {msg}")
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
