"""P27 verification probe for query_limit fail-closed behavior.

Constructs three rejection cases and one bad control, all without MLX.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import metrics, spec


def test_missing_key():
    doc = {"evaluation": {}}
    try:
        metrics.require_query_limit(doc)
        return False, "missing key did not raise"
    except metrics.QueryLimitError as e:
        if "missing" in str(e).lower():
            return True, f"missing key refused: {e}"
        return False, f"wrong error: {e}"


def test_wrong_value():
    doc = {"evaluation": {"query_limit": 4}}
    try:
        metrics.require_query_limit(doc)
        return False, "wrong value did not raise"
    except metrics.QueryLimitError as e:
        if "differs" in str(e).lower():
            return True, f"wrong value refused: {e}"
        return False, f"wrong error: {e}"


def test_non_int():
    doc = {"evaluation": {"query_limit": "8"}}
    try:
        metrics.require_query_limit(doc)
        return False, "non-int did not raise"
    except metrics.QueryLimitError as e:
        if "int" in str(e).lower():
            return True, f"non-int refused: {e}"
        return False, f"wrong error: {e}"


def test_bad_control():
    """Only the missing-key guard is removed; should wrongly accept."""
    doc = {"evaluation": {}}
    # Simulate the broken behavior from test_s1_r10_query_limit.py
    evaluation_block = doc.get("evaluation") if isinstance(doc, dict) else None
    if not isinstance(evaluation_block, dict):
        evaluation_block = {}
    value = evaluation_block.get("query_limit", 8)  # DEFECT: silent default
    if isinstance(value, bool) or not isinstance(value, int):
        return False, "bad control raised on type"
    expected = int(spec.EVALUATION["query_limit"])
    if value != expected:
        return False, "bad control raised on value"
    return True, f"bad control wrongly returned {value} (turns red)"


def main() -> int:
    results = []
    for name, fn in [
        ("missing_key", test_missing_key),
        ("wrong_value", test_wrong_value),
        ("non_int", test_non_int),
        ("bad_control", test_bad_control),
    ]:
        ok, msg = fn()
        results.append((name, ok, msg))
        print(f"{'PASS' if ok else 'FAIL'} {name}: {msg}")
    all_ok = all(r[1] for r in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
