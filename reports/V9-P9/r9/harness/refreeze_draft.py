"""Prepare the r9 draft: same r8 draft, only source identity + created_unix.

Scientific fields (arms, dims, seeds, updates rule, caps, metrics, stop rules,
data identity) are copied verbatim from the r8 draft.  Regenerating the draft
through ``--mode preregister`` would rebuild arm parameter counts on an MLX
device, which this CPU-only card forbids, so the source identity is recomputed
by hashing the same bound files directly (now including the r9 worker).
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg  # noqa: E402

SRC = REPO / "artifacts/v9/s1/phase1"
DST = SRC / "r9"


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC / "dataset_ref.json", DST / "dataset_ref.json")
    draft = json.loads((SRC / "r8" / "draft_preregistration.json").read_text(encoding="utf-8"))
    before = json.loads(json.dumps(draft))
    draft["source_identity"] = prereg._source_identity()
    draft["created_unix"] = time.time()
    (DST / "draft_preregistration.json").write_text(
        json.dumps(draft, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    changed = sorted(key for key in draft if draft[key] != before.get(key))
    payload = {
        "status": "completed",
        "draft_path": str((DST / "draft_preregistration.json").resolve()),
        "dataset_ref": str((DST / "dataset_ref.json").resolve()),
        "changed_top_level_fields": changed,
        "old_package_map_digest": before["source_identity"]["package_map_digest"],
        "new_package_map_digest": draft["source_identity"]["package_map_digest"],
        "bound_files": len(draft["source_identity"]["package_files"]),
        "scientific_field_changes": [
            key for key in changed if key not in ("source_identity", "created_unix")
        ],
    }
    print(json.dumps(payload, indent=1))
    return 0 if not payload["scientific_field_changes"] else 7


if __name__ == "__main__":
    raise SystemExit(main())
