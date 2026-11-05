"""Prepare the r8 draft: same r7 draft, only source identity + created_unix.

The scientific fields (arms, dims, seeds, updates rule, caps, metrics, stop
rules, data identity placeholder) are copied verbatim from the archived r5
draft (r1 measurement record, unchanged k values / worlds / partitions).  Draft regeneration through ``--mode preregister`` would rebuild the arm
parameter counts on an MLX device, which this CPU-only card forbids, so the
identity is recomputed by hashing the same bound files directly.
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
DST = SRC / "r8"


def main() -> int:
    if not DST.exists():
        DST.mkdir(parents=True)
    shutil.copy2(SRC / "dataset_ref.json", DST / "dataset_ref.json")
    draft = json.loads((SRC / "r7" / "draft_preregistration.json").read_text(encoding="utf-8"))
    before = json.loads(json.dumps(draft))
    draft["source_identity"] = prereg._source_identity()
    draft["created_unix"] = time.time()
    (DST / "draft_preregistration.json").write_text(
        json.dumps(draft, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    changed = sorted(
        key for key in draft if draft[key] != before.get(key)
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "draft_path": str((DST / "draft_preregistration.json").resolve()),
                "dataset_ref": str((DST / "dataset_ref.json").resolve()),
                "changed_top_level_fields": changed,
                "old_package_map_digest": before["source_identity"]["package_map_digest"],
                "new_package_map_digest": draft["source_identity"]["package_map_digest"],
                "bound_files": len(draft["source_identity"]["package_files"]),
                "scientific_field_changes": [
                    key
                    for key in changed
                    if key not in ("source_identity", "created_unix")
                ],
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
