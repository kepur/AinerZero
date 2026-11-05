"""P14 reviewer: judge the P12 (P1-P4) and P11/F1 reruns case by case.

Reads the two evidence JSONs written by the adapted rerun harnesses and, for
every case, parses the harness's own ``expectation`` string into an expected
exit code and an expected refusal stage, then compares it with what the rerun
actually observed.  Nothing is re-executed here; this only turns the raw rerun
output into an explicit per-case verdict so the report can state "15/15" and
"9/9" with the individual rows behind it.

Parsing rules (kept deliberately small and stated, not inferred per case):
  * "released (exit 0)" / "exit 0"  -> expected exit 0, stage "completed"
  * "exit 3"                        -> expected exit 3
  * a stage name anywhere in the string is the expected stage; the alias
    "(P-4)" and "approval gate" both mean `preregistration_not_approved`
    (the P-4 gate is reported through that stage).
  * worker-direct cases state only the stage; their exit code is 2 by the
    worker's own contract, so the exit code is left unconstrained and only the
    stage is compared.

Output: reports/V9-P14/evidence/case-verdicts-p14.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
EV = REAL / "reports" / "V9-P14" / "evidence"

STAGES = (
    "research_log_not_canonical",
    "source_binding_drift",
    "dataset_identity_mismatch",
    "preregistration_not_approved",
)
ALIASES = (
    ("(P-4)", "preregistration_not_approved"),
    ("approval gate", "preregistration_not_approved"),
)


def parse_expectation(text: str) -> dict:
    expected_exit: int | None
    if "exit 0" in text:
        expected_exit = 0
    elif "exit 3" in text:
        expected_exit = 3
    else:
        expected_exit = None  # worker-direct rows state no exit code

    stage = next((s for s in STAGES if s in text), None)
    if stage is None:
        for needle, mapped in ALIASES:
            if needle in text:
                stage = mapped
                break
    if stage is None and expected_exit == 0:
        stage = "completed"  # "released (exit 0)" rows carry no refusal stage
    return {"expected_exit": expected_exit, "expected_stage": stage}


def judge(case: dict, observed_stage_key: str) -> dict:
    exp = parse_expectation(case.get("expectation") or "")
    observed_stage = case.get("stage") or case.get(observed_stage_key) or case.get("status")
    observed_exit = case.get("exit_code")

    checks = []
    if exp["expected_exit"] is not None:
        checks.append(observed_exit == exp["expected_exit"])
    else:
        # worker direct: exit 2 (refusal) or 3 (CLI refusal), stage must match
        checks.append(observed_exit in (2, 3))
    checks.append(exp["expected_stage"] is not None and observed_stage == exp["expected_stage"])

    return {
        "id": case.get("id"),
        "expectation": case.get("expectation"),
        "expected_exit": exp["expected_exit"],
        "expected_stage": exp["expected_stage"],
        "observed_exit": observed_exit,
        "observed_stage": observed_stage,
        "matched": all(checks),
    }


def run(path: Path, stage_key: str) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = [judge(c, stage_key) for c in doc["cases"]]
    matched = sum(1 for r in rows if r["matched"])
    return {
        "source": str(path.relative_to(REAL)),
        "total": len(rows),
        "matched": matched,
        "mismatches": [r for r in rows if not r["matched"]],
        "cases": rows,
    }


def main() -> int:
    p1p4 = run(EV / "p1-p4-counterexamples-rerun-p14.json", "refused_stage")
    f1 = run(EV / "f1-approval-r4-rerun-p14.json", "stage")
    verdict = "all_matched" if (
        p1p4["matched"] == p1p4["total"] and f1["matched"] == f1["total"]
    ) else "mismatches_found"
    out = {
        "harness": "reports/V9-P14/harness/case_judge.py",
        "method": "parse each harness 'expectation' string -> (exit, stage); compare to observed",
        "p1_p4_counterexamples": p1p4,
        "f1_approval": f1,
        "verdict": verdict,
        "totals": {
            "p1_p4_matched": f"{p1p4['matched']}/{p1p4['total']}",
            "f1_matched": f"{f1['matched']}/{f1['total']}",
        },
    }
    (EV / "case-verdicts-p14.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in p1p4["cases"] + f1["cases"]:
        print(f"{r['id']:5s} exp={r['expected_exit']}/{r['expected_stage']} "
              f"obs={r['observed_exit']}/{r['observed_stage']} matched={r['matched']}")
    print(f"verdict={verdict} p1_p4={out['totals']['p1_p4_matched']} f1={out['totals']['f1_matched']}")
    return 0 if verdict == "all_matched" else 1


if __name__ == "__main__":
    sys.exit(main())
