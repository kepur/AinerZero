"""P61 post-run check: a second final-eval on an isolated copy of the production host is refused (ainerzero.V9.P61).

``data.open_sealed_final_once`` is replaced by a tripwire, so the real sealed final data is never read
again.  The copy carries the production ledger (with the completed final-eval run) and RESEARCH_LOG.md
(with the single valid final approval line).  Writes only ../second-call-refusal.json and a temp dir.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import data, spec, worker  # noqa: E402

PRODUCTION = REPO / "artifacts/v9/s1/phase1"
OUT = Path(__file__).resolve().parents[1] / "second-call-refusal.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tripwire(*_a, **_k):
    raise AssertionError("post-run check must never open the real sealed final dataset")


def main() -> int:
    data.open_sealed_final_once = _tripwire
    production_before = sha256(PRODUCTION / "control.sqlite3")
    workdir = Path(tempfile.mkdtemp(prefix="s1-final-second-"))
    host = workdir / "host"
    copy_root = host / "artifacts/v9/s1/phase1"
    copy_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PRODUCTION, copy_root)
    shutil.copy2(REPO / "RESEARCH_LOG.md", host / "RESEARCH_LOG.md")
    ledger = copy_root / "control.sqlite3"
    copy_before = sha256(ledger)
    original = (spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG)
    spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG = host, copy_root, host / "RESEARCH_LOG.md"
    try:
        report = worker.run_worker("final-eval", output_root=copy_root, limits=spec.RESOURCE_LIMITS,
                                   wall_budget_seconds=spec.FINAL_EVAL_WALL_SECONDS,
                                   prereg_path=copy_root / "final/pre_registration.json")
    finally:
        spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG = original
    payload = {"status": report.get("status"), "refused_stage": report.get("refused_stage"),
               "reasons": report.get("reasons") or report.get("error"),
               "copy_ledger_unchanged": sha256(ledger) == copy_before,
               "production_unchanged": sha256(PRODUCTION / "control.sqlite3") == production_before,
               "production_ledger_sha256": production_before}
    payload["passed"] = (payload["status"] == "refused"
                         and payload["refused_stage"] in {"final_already_read", "final_already_attempted"}
                         and payload["copy_ledger_unchanged"] and payload["production_unchanged"])
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=1, default=str))
    shutil.rmtree(workdir, ignore_errors=True)
    return 0 if payload["passed"] else 9


if __name__ == "__main__":
    raise SystemExit(main())
