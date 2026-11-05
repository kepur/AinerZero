"""r15 -> final leaf diff of the frozen preregistrations (ainerzero.V9.P60 reviewer gemini-b4e7).

Allowlist (task card + RESEARCH_LOG R20261028-S1-phase1-final-eval):
  * experiment_id, created_unix;
  * source binding: source_identity.*, timing.smoke_source.*;
  * the inheritance.* section (eight r13/r14 cells + r15 arm4 s0) and the new final_eval.* section.
Scientific sections and effective_metadata must be identical.
Everything else must be identical. Writes only to prereg_leaf_diff.json.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OLD = REPO / "artifacts/v9/s1/phase1/r15/pre_registration.json"
NEW = REPO / "artifacts/v9/s1/phase1/final/pre_registration.json"
OUT = Path(__file__).resolve().parent / "prereg_leaf_diff.json"


def flat(value, prefix="", out=None):
    out = {} if out is None else out
    if isinstance(value, dict):
        if not value:
            out[prefix] = value
        for key in sorted(value):
            flat(value[key], f"{prefix}.{key}" if prefix else key, out)
    elif isinstance(value, list):
        if not value:
            out[prefix] = value
        for index, item in enumerate(value):
            flat(item, f"{prefix}[{index}]", out)
    else:
        out[prefix] = value
    return out


def allowed(key: str) -> bool:
    return (
        key in ("experiment_id", "created_unix")
        or key.startswith("source_identity.")
        or key.startswith("timing.smoke_source.")
        or key.startswith("inheritance.")
        or key.startswith("final_eval.")
    )


def main() -> int:
    old, new = json.loads(OLD.read_text("utf-8")), json.loads(NEW.read_text("utf-8"))
    left, right = flat(old), flat(new)
    changed = sorted(k for k in set(left) | set(right) if left.get(k) != right.get(k))
    unexpected = [k for k in changed if not allowed(k)]
    pinned = {
        "training_protocol.updates": right.get("training_protocol.updates"),
        "timing.deadline_seconds": right.get("timing.deadline_seconds"),
        "timing.supervision_seconds": right.get("timing.supervision_seconds"),
        "training_protocol.eval_batches": right.get("training_protocol.eval_batches"),
        "timing.phase_wall_max_seconds": right.get("timing.phase_wall_max_seconds"),
        "data_identity.dataset_digest": right.get("data_identity.dataset_digest"),
    }
    sections_equal = {
        name: old.get(name) == new.get(name)
        for name in ("arms", "evaluation", "metrics", "stop_rules", "training_protocol", "data_identity", "resource_limits")
    }
    result = {
        "old": str(OLD.relative_to(REPO)),
        "new": str(NEW.relative_to(REPO)),
        "total_leaves_new": len(right),
        "changed": len(changed),
        "changed_keys_outside_inheritance": [k for k in changed if not k.startswith(("inheritance.", "final_eval."))],
        "inheritance_leaves_added": len([k for k in changed if k.startswith("inheritance.")]),
        "unexpected": unexpected,
        "pinned_values_final": pinned,
        "sections_equal_r15_final": sections_equal,
        "effective_metadata_equal": old["effective_metadata"] == new["effective_metadata"],
    }
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("changed", "unexpected", "changed_keys_outside_inheritance", "inheritance_leaves_added", "sections_equal_r15_final", "effective_metadata_equal")}, ensure_ascii=False, indent=1))
    return 0 if not unexpected and all(sections_equal.values()) and old["effective_metadata"] == new["effective_metadata"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
