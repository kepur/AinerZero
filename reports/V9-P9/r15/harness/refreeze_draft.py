"""Prepare the r15 draft from the r14 draft of record (CPU only, no --mode preregister).

Adapted from reports/V9-P9/r14/harness/refreeze_draft.py (ainerzero.V9.P53).  r15 is the
same user-approved registration under a fresh identity (RESEARCH_LOG
R20261028-S1-phase1-r15-budget) plus the registered multi-source inheritance
section.  Arm rows, data identity, metrics, query limit and reporting notes are
copied verbatim from r14.
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
DST = SRC / "r15"
BASE = SRC / "r14"


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
        experiment_id=spec.R15_EXPERIMENT_ID,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
    )
    # Preserve the r14 (== r13 == r12 == r11 == r10) scientific arm rows, identity keys included.
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
        "inheritance_cells": [(c["arm_id"], c["seed"], c["source_run_id"]) for c in draft["inheritance"]["cells"]],
    }
    print(json.dumps(payload, indent=1))
    ok = (
        draft["experiment_id"] == spec.R15_EXPERIMENT_ID
        and draft.get("inheritance") == json.loads(json.dumps(spec.R15_INHERITANCE))
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
