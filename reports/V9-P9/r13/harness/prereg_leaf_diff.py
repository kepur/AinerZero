"""Leaf-level diff between the frozen r12 and r13 preregistration documents.

Task card allowlist (r13 re-freeze): the only permitted differences are

  * ``experiment_id`` (the new identity),
  * source-binding fields (``source_identity.*`` and the ``timing.smoke_source``
    block that binds the measurement of record),
  * time-derived fields (``created_unix``).

Everything else -- 3510 updates, 1200 s deadline, 1250 s supervision, 175 eval
batches, the seeds, the data identity, the metric definitions, the query limit
and the reporting notes -- must be byte-equal. Any other changed leaf is a
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

BASE = REPO / "artifacts/v9/s1/phase1/r12/pre_registration.json"
NEW = REPO / "artifacts/v9/s1/phase1/r13/pre_registration.json"
OUT = REPO / "reports/V9-P9/r13/prereg-leaf-diff.json"

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
)


def flatten(node, prefix="", out=None):
    out = {} if out is None else out
    if isinstance(node, dict):
        if not node:
            out[prefix] = node
        for key in sorted(node):
            flatten(node[key], f"{prefix}.{key}" if prefix else key, out)
    elif isinstance(node, list):
        if not node:
            out[prefix] = node
        for idx, item in enumerate(node):
            flatten(item, f"{prefix}[{idx}]", out)
    else:
        out[prefix] = node
    return out


def main() -> int:
    old = json.loads(BASE.read_text(encoding="utf-8"))
    new = json.loads(NEW.read_text(encoding="utf-8"))
    left = flatten(old)
    right = flatten(new)

    keys = sorted(set(left) | set(right))
    changed = []
    outside_allowlist = []
    for key in keys:
        if left.get(key) != right.get(key):
            rec = {
                "leaf": key,
                "r12": left.get(key),
                "r13": right.get(key),
            }
            changed.append(rec)
            # Whitelist: experiment_id, created_unix, source_identity.*, timing.smoke_source.*
            is_allowed = (
                key == "experiment_id"
                or key == "created_unix"
                or key.startswith("source_identity.")
                or key.startswith("timing.smoke_source.")
            )
            if not is_allowed:
                outside_allowlist.append(rec)

    # Check registered values byte-equal
    registered_values = {}
    registered_equal = True
    for path in REGISTERED:
        curr_old = old
        curr_new = new
        for seg in path:
            curr_old = curr_old[seg]
            curr_new = curr_new[seg]
        name = ".".join(path)
        eq = curr_old == curr_new
        registered_values[name] = {"value": curr_new, "equal": eq}
        if not eq:
            registered_equal = False

    # Check scientific blocks identical
    arms_equal = old["arms"] == new["arms"]
    data_id_equal = old["data_identity"] == new["data_identity"]
    eval_equal = old["evaluation"] == new["evaluation"]

    # Bound package files diff
    old_files = old["source_identity"]["package_files"]
    new_files = new["source_identity"]["package_files"]
    changed_files = []
    for fn in sorted(set(old_files) | set(new_files)):
        if old_files.get(fn) != new_files.get(fn):
            changed_files.append({"file": fn, "old_sha": old_files.get(fn), "new_sha": new_files.get(fn)})

    files_outside_allowed = [cf["file"] for cf in changed_files if cf["file"] not in ALLOWED_FILES]

    result = {
        "status": "passed" if (len(outside_allowlist) == 0 and registered_equal and arms_equal and data_id_equal and eval_equal and len(files_outside_allowed) == 0) else "failed",
        "total_leaves": len(keys),
        "changed_leaves_count": len(changed),
        "changed_leaves": changed,
        "outside_allowlist_count": len(outside_allowlist),
        "outside_allowlist": outside_allowlist,
        "registered_values_equal": registered_equal,
        "registered_values": registered_values,
        "arms_equal": arms_equal,
        "data_identity_equal": data_id_equal,
        "evaluation_equal": eval_equal,
        "changed_bound_files": changed_files,
        "files_outside_allowed": files_outside_allowed,
        "old_document_sha256": prereg.document_sha256(old),
        "new_document_sha256": prereg.document_sha256(new),
        "old_file_sha256": hashlib.sha256(BASE.read_bytes()).hexdigest(),
        "new_file_sha256": hashlib.sha256(NEW.read_bytes()).hexdigest(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Diff status: {result['status']}, changed leaves: {len(changed)}, outside allowlist: {len(outside_allowlist)}")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
