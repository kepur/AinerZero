"""Leaf-level diff between the frozen r11 and r12 preregistration documents.

Task card allowlist (r12 re-freeze): the only permitted differences are

  * ``experiment_id`` (the new identity),
  * source-binding fields (``source_identity.*`` and the ``timing.smoke_source``
    block that binds the measurement of record),
  * time-derived fields (``created_unix``).

Everything else -- 3510 updates, 1200 s deadline, 1250 s supervision, 175 eval
batches, the seeds, the data identity, the metric definitions, the query limit
and the reporting notes -- must be byte-equal.  Any other changed leaf is a
scientific change and fails the card.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg  # noqa: E402

BASE = REPO / "artifacts/v9/s1/phase1/r11/pre_registration.json"
NEW = REPO / "artifacts/v9/s1/phase1/r12/pre_registration.json"
OUT = REPO / "reports/V9-P9/r12/prereg-leaf-diff.json"

ALLOWED_FILES = {
    "src/ainerzero/v9/experiments/s1/spec.py",
    "src/ainerzero/v9/experiments/s1/prereg.py",
    "src/ainerzero/v9/experiments/s1/worker.py",
    "src/ainerzero/v9/experiments/s1/commands.py",
}

REGISTERED = (
    ("training_protocol", "updates"),
    ("training_protocol", "eval_batches"),
    ("training_protocol", "checkpoint_updates"),
    ("training_protocol", "seeds"),
    ("training_protocol", "batch_size"),
    ("training_protocol", "sequence_steps"),
    ("training_protocol", "learning_rate"),
    ("timing", "deadline_seconds"),
    ("timing", "supervision_seconds"),
    ("timing", "registered_updates"),
    ("timing", "registered_deadline_seconds"),
    ("timing", "registered_supervision_seconds"),
    ("timing", "deadline_source"),
    ("timing", "deadline_factor"),
    ("timing", "supervision_extra_seconds"),
    ("timing", "per_run_wall_max_seconds"),
    ("timing", "phase_wall_max_seconds"),
    ("timing", "arm1_deadline_seconds"),
    ("timing", "arm1_supervision_seconds"),
    ("timing", "estimate_seconds"),
    ("timing", "phase_wall_seconds"),
    ("timing", "measured_throughput"),
)


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
    if path in ("experiment_id", "created_unix"):
        return True
    prefixes = ("source_identity.", "timing.smoke_source.")
    return any(path.startswith(prefix) for prefix in prefixes)


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
    equal_registered = {
        f"{section}.{key}": {
            "base": (base.get(section) or {}).get(key),
            "new": (new.get(section) or {}).get(key),
            "equal": (base.get(section) or {}).get(key) == (new.get(section) or {}).get(key),
        }
        for section, key in REGISTERED
    }
    data_equal = base.get("data_identity") == new.get("data_identity")
    metrics_equal = base.get("metrics") == new.get("metrics")
    evaluation_equal = base.get("evaluation") == new.get("evaluation")
    stop_rules_equal = base.get("stop_rules") == new.get("stop_rules")
    arms_equal = base.get("arms") == new.get("arms")

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
        "registered_values": equal_registered,
        "data_identity_equal": data_equal,
        "metrics_equal": metrics_equal,
        "evaluation_equal": evaluation_equal,
        "stop_rules_equal": stop_rules_equal,
        "arms_equal": arms_equal,
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
    print("leaves outside allowlist:", [row["path"] for row in scientific])
    print("changed leaves:", [row["path"] for row in rows])
    print(
        "registered equal:",
        all(row["equal"] for row in equal_registered.values()),
        "| data", data_equal,
        "| metrics", metrics_equal,
        "| evaluation", evaluation_equal,
        "| stop_rules", stop_rules_equal,
        "| arms", arms_equal,
    )
    ok = (
        not scientific
        and not outside
        and all(row["equal"] for row in equal_registered.values())
        and data_equal
        and metrics_equal
        and evaluation_equal
        and stop_rules_equal
        and arms_equal
    )
    return 0 if ok else 7


if __name__ == "__main__":
    raise SystemExit(main())
