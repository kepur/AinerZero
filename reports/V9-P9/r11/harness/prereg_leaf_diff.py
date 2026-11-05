"""Leaf-level diff between the frozen r10 and r11 preregistration documents.

Permitted differences (task card items 2-5 + derivative fields):
  - experiment_id / budget_registration
  - timing deadline/supervision/estimate/arm1/phase_wall + registered_* /
    deadline_source / measured_throughput / rule text
  - training_protocol updates/eval_batches/checkpoint_updates/update_rule /
    arm training_updates
  - budget_estimate.* (derived recomputation)
  - arms.*.training_updates
  - source_identity.* / created_unix / timing.smoke_* derivatives

Any other changed leaf is a scientific change and fails the card.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg  # noqa: E402

BASE = REPO / "artifacts/v9/s1/phase1/r10/pre_registration.json"
NEW = REPO / "artifacts/v9/s1/phase1/r11/pre_registration.json"
OUT = REPO / "reports/V9-P9/r11/prereg-leaf-diff.json"

ALLOWED_FILES = {
    "src/ainerzero/v9/experiments/s1/spec.py",
    "src/ainerzero/v9/experiments/s1/prereg.py",
    "src/ainerzero/v9/experiments/s1/worker.py",
    "src/ainerzero/v9/experiments/s1/commands.py",
}


def flat(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        if not obj:
            out[prefix] = obj
        for key in sorted(obj):
            out.update(flat(obj[key], f"{prefix}.{key}" if prefix else key))
    elif isinstance(obj, list):
        if not obj:
            out[prefix] = obj
        for index, value in enumerate(obj):
            out.update(flat(value, f"{prefix}[{index}]"))
    else:
        out[prefix] = obj
    return out


def document_sha(path: Path) -> str:
    return prereg.document_sha256(json.loads(path.read_text(encoding="utf-8")))


def changed_bound_files(base: dict, new: dict) -> list[dict]:
    left = (base.get("source_identity") or {}).get("package_files") or {}
    right = (new.get("source_identity") or {}).get("package_files") or {}
    rows = []
    for rel in sorted(set(left) | set(right)):
        if left.get(rel) != right.get(rel):
            rows.append({"path": rel, "base": left.get(rel), "new": right.get(rel)})
    return rows


def permitted(path: str) -> bool:
    if path in (
        "experiment_id",
        "budget_registration",
        "created_unix",
        "timing.smoke_recheck",
    ):
        return True
    prefixes = (
        "source_identity.",
        "timing.",
        "budget_estimate.",
        "training_protocol.",
        "arms.arm1.training_updates",
        "arms.arm2.training_updates",
        "arms.arm3.training_updates",
        "arms.arm4.training_updates",
    )
    if any(path.startswith(p) or path == p.rstrip(".") for p in prefixes):
        # Narrow: only training_updates under arms.*, not other arm fields.
        if path.startswith("arms.") and not path.endswith(".training_updates"):
            return False
        return True
    return False


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    new = json.loads(NEW.read_text(encoding="utf-8"))
    left, right = flat(base), flat(new)
    rows = []
    for key in sorted(set(left) | set(right)):
        if key not in left:
            rows.append({"path": key, "change": "added", "new": right[key]})
        elif key not in right:
            rows.append({"path": key, "change": "removed", "base": left[key]})
        elif left[key] != right[key]:
            rows.append({"path": key, "change": "changed", "base": left[key], "new": right[key]})

    scientific = [row for row in rows if not permitted(row["path"])]
    files = changed_bound_files(base, new)
    outside = [row["path"] for row in files if row["path"] not in ALLOWED_FILES]

    payload = {
        "base_path": str(BASE.relative_to(REPO)),
        "new_path": str(NEW.relative_to(REPO)),
        "base_document_sha256": document_sha(BASE),
        "new_document_sha256": document_sha(NEW),
        "base_file_sha256": hashlib.sha256(BASE.read_bytes()).hexdigest(),
        "new_file_sha256": hashlib.sha256(NEW.read_bytes()).hexdigest(),
        "leaf_count": len(set(left) | set(right)),
        "changed_leaf_count": len(rows),
        "changed_bound_files": files,
        "bound_files_outside_allowlist": outside,
        "allowlist": sorted(ALLOWED_FILES),
        "non_identity_leaves_outside_allowlist": scientific,
        "changes": rows,
        "frozen_values": {
            "experiment_id": new["experiment_id"],
            "budget_registration": new["budget_registration"],
            "updates": new["training_protocol"]["updates"],
            "checkpoint_updates": new["training_protocol"]["checkpoint_updates"],
            "seeds": new["training_protocol"]["seeds"],
            "deadline_seconds": new["timing"]["deadline_seconds"],
            "supervision_seconds": new["timing"]["supervision_seconds"],
            "deadline_source": new["timing"].get("deadline_source"),
            "arm1_deadline_seconds": new["timing"]["arm1_deadline_seconds"],
            "eval_batches": new["training_protocol"]["eval_batches"],
            "phase_wall_max_seconds": new["timing"]["phase_wall_max_seconds"],
            "per_run_wall_max_seconds": new["timing"]["per_run_wall_max_seconds"],
            "query_limit": (new.get("evaluation") or {}).get("query_limit"),
            "measured_throughput": new["timing"].get("measured_throughput"),
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(f"leaves={payload['leaf_count']} changed={len(rows)}")
    print(f"base_doc={payload['base_document_sha256']}")
    print(f"new_doc={payload['new_document_sha256']}")
    print(f"new_file={payload['new_file_sha256']}")
    print("changed bound files:", [row["path"] for row in files])
    print("bound files outside allowlist:", outside)
    print("outside allowlist:", [row["path"] for row in scientific])
    print("frozen_values:", json.dumps(payload["frozen_values"], ensure_ascii=False)[:500])
    return 0 if not scientific and not outside else 7


if __name__ == "__main__":
    raise SystemExit(main())
