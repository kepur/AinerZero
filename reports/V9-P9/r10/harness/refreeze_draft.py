"""Prepare the r10 draft from the accepted r9 draft.

Scientific fields (arms, dims, seeds, updates rule, caps, metrics definitions,
stop rules, data identity, budget numbers) are copied from r9.  Only the
option-A evaluation registration (query_limit + reporting_notes), the rebound
source identity and created_unix are allowed to change.  Regenerating through
``--mode preregister`` would rebuild arm parameter counts on an MLX device,
which this CPU-only card forbids.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg, spec  # noqa: E402

SRC = REPO / "artifacts/v9/s1/phase1"
DST = SRC / "r10"
BASE = SRC / "r9"


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE / "dataset_ref.json", DST / "dataset_ref.json")
    draft = json.loads((BASE / "draft_preregistration.json").read_text(encoding="utf-8"))
    before = json.loads(json.dumps(draft))
    draft["evaluation"] = {
        "query_limit": int(spec.EVALUATION["query_limit"]),
        "reporting_notes": list(spec.EVALUATION["reporting_notes"]),
    }
    draft["source_identity"] = prereg._source_identity()
    draft["created_unix"] = time.time()
    (DST / "draft_preregistration.json").write_text(
        json.dumps(draft, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    changed = sorted(key for key in draft if draft[key] != before.get(key))
    scientific = [
        key for key in changed if key not in ("source_identity", "created_unix", "evaluation")
    ]
    payload = {
        "status": "completed",
        "draft_path": str((DST / "draft_preregistration.json").resolve()),
        "dataset_ref": str((DST / "dataset_ref.json").resolve()),
        "changed_top_level_fields": changed,
        "old_package_map_digest": before["source_identity"]["package_map_digest"],
        "new_package_map_digest": draft["source_identity"]["package_map_digest"],
        "bound_files": len(draft["source_identity"]["package_files"]),
        "evaluation": draft["evaluation"],
        "scientific_field_changes_outside_evaluation": scientific,
    }
    print(json.dumps(payload, indent=1))
    return 0 if not scientific else 7


if __name__ == "__main__":
    raise SystemExit(main())
