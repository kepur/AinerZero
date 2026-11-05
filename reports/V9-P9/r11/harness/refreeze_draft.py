"""Prepare the r11 draft from the r10 draft (CPU only; no --mode preregister).

Scientific arm rows (including arm1 identity keys) are copied from the r10
draft of record so the r10→r11 leaf diff stays inside the task-card allowlist
(items 2–5 + source/time derivatives).  Only the r11 registration fields,
``training_protocol.eval_batches``, rebound ``source_identity`` and
``created_unix`` are rewritten.  Regenerating through ``build_draft`` alone
would re-emit newer arm1 identity keys that r10 never carried.
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
DST = SRC / "r11"
BASE = SRC / "r10"


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE / "dataset_ref.json", DST / "dataset_ref.json")
    old = json.loads((BASE / "draft_preregistration.json").read_text(encoding="utf-8"))
    counts = {
        arm: old["arms"][arm]["parameter_count"] for arm in ("arm1", "arm2", "arm3", "arm4")
    }
    # Build the r11 registration skeleton (experiment id, registered timing
    # fields, update_rule text, eval_batches via TRAIN_COMMON).
    draft = prereg.build_draft(
        data_identity=old["data_identity"],
        parameter_counts=counts,
        created_unix=time.time(),
        experiment_id=spec.R11_EXPERIMENT_ID,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
    )
    # Preserve r10 scientific arm rows (identity keys included).
    draft["arms"] = copy.deepcopy(old["arms"])
    # Keep r10 evaluation registration (query_limit + reporting_notes).
    draft["evaluation"] = {
        "query_limit": int(old["evaluation"]["query_limit"]),
        "reporting_notes": list(old["evaluation"]["reporting_notes"]),
    }
    # eval_batches lives on training_protocol (copied from TIMING via TRAIN_COMMON).
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
        draft["experiment_id"] == spec.R11_EXPERIMENT_ID
        and draft["budget_registration"] == spec.R11_BUDGET_REGISTRATION
        and draft["timing"].get("deadline_source") == spec.R11_DEADLINE_SOURCE
        and int(draft["timing"].get("registered_deadline_seconds"))
        == spec.R11_REGISTERED_DEADLINE_SECONDS
        and int(draft["training_protocol"]["eval_batches"]) == 175
        and "frozen_manifest_digest_rule" not in (draft["arms"]["arm1"].get("identity") or {})
    )
    return 0 if ok else 7


if __name__ == "__main__":
    raise SystemExit(main())
