"""Prepare the r13 draft from the r12 draft of record (CPU only, no --mode preregister).

r13 is the same user-approved registration as r12 and r11 (RESEARCH_LOG
R20261024-S1-phase1-r13-budget) under a fresh experiment identity, after the
r12 phase window expired. Nothing scientific may move: the arm rows (arm1
identity keys included), the data identity, the metric definitions, the query
limit and the reporting notes are copied verbatim, so the r12 -> r13 leaf diff
stays inside the task-card allowlist (experiment_id, source binding, time-derived
fields).
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg, spec  # noqa: E402

SRC = REPO / "artifacts/v9/s1/phase1"
DST = SRC / "r13"
BASE = SRC / "r12"


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE / "dataset_ref.json", DST / "dataset_ref.json")
    old = json.loads((BASE / "draft_preregistration.json").read_text(encoding="utf-8"))
    counts = {
        arm: old["arms"][arm]["parameter_count"] for arm in ("arm1", "arm2", "arm3", "arm4")
    }
    draft = prereg.build_draft(
        data_identity=old["data_identity"],
        parameter_counts=counts,
        created_unix=time.time(),
        experiment_id=spec.R13_EXPERIMENT_ID,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
    )
    # Preserve the r12 (== r11 == r10) scientific arm rows, identity keys included.
    draft["arms"] = copy.deepcopy(old["arms"])
    # Keep the registered evaluation block (query_limit + reporting notes).
    draft["evaluation"] = {
        "query_limit": int(old["evaluation"]["query_limit"]),
        "reporting_notes": list(old["evaluation"]["reporting_notes"]),
    }
    draft["training_protocol"]["eval_batches"] = int(spec.TIMING["eval_batches"])
    out = DST / "draft_preregistration.json"
    out.write_text(
        json.dumps(draft, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    payload = {
        "status": "completed",
        "draft_path": str(out.resolve()),
        "dataset_ref": str((DST / "dataset_ref.json").resolve()),
        "experiment_id": draft["experiment_id"],
        "budget_registration": draft["budget_registration"],
        "deadline_source": draft["timing"].get("deadline_source"),
        "registered_deadline_seconds": draft["timing"].get("registered_deadline_seconds"),
        "registered_updates": draft["timing"].get("registered_updates"),
        "eval_batches": draft["training_protocol"].get("eval_batches"),
        "package_map_digest": draft["source_identity"]["package_map_digest"],
        "bound_files": len(draft["source_identity"]["package_files"]),
        "arm1_identity_keys": sorted((draft["arms"]["arm1"].get("identity") or {})),
        "evaluation": draft["evaluation"],
    }
    print(json.dumps(payload, indent=1))
    ok = (
        draft["experiment_id"] == spec.R13_EXPERIMENT_ID
        and draft["budget_registration"] == spec.R11_BUDGET_REGISTRATION
        and draft["timing"].get("deadline_source") == spec.R11_DEADLINE_SOURCE
        and int(draft["timing"].get("registered_deadline_seconds")) == 1_200
        and int(draft["timing"].get("registered_updates")) == 3_510
        and int(draft["training_protocol"]["eval_batches"]) == 175
        and draft["arms"] == old["arms"]
    )
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
