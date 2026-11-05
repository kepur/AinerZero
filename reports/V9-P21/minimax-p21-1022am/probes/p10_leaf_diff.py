"""P21 probe 10: the r6 -> r7 leaf diff and the frozen-source identity gap.

An independent leaf-by-leaf comparison of the two frozen preregistration
documents: the changed leaves must be inside the registered allow list, the
scientific values (data digest, 48 eval batches, the three seeds, the 450 s
deadline, the 500 s supervision, the 4 h phase cap, 3510 updates, the checkpoint
set, the resource lines, the metric definitions and the stop rules) must not
have moved, and the generic RunStore module must be unchanged *and* reported as
not frozen by the preregistration.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402

R6 = lib.REPO / "artifacts/v9/s1/phase1/r6/pre_registration.json"
R7 = lib.REPO / "artifacts/v9/s1/phase1/r7/pre_registration.json"
LIFECYCLE = lib.REPO / "src/ainerzero/runtime/lifecycle.py"

ALLOWLIST_PREFIXES = (
    "created_unix",
    "source_identity.package_files.src/ainerzero/v9/experiments/s1/arms.py",
    "source_identity.package_files.src/ainerzero/v9/experiments/s1/commands.py",
    "source_identity.package_files.src/ainerzero/v9/experiments/s1/spec.py",
    "source_identity.package_files.src/ainerzero/v9/experiments/s1/worker.py",
    "source_identity.package_map_digest",
    "source_identity.spec.sha256",
)

SCIENTIFIC = {
    "data_identity.dataset_digest": "8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26",
    "training_protocol.eval_batches": 48,
    "training_protocol.seeds": [0, 1, 2],
    "training_protocol.updates": 3510,
    "training_protocol.checkpoint_updates": [0, 439, 878, 1755, 3510],
    "training_protocol.batch_size": 16,
    "training_protocol.learning_rate": 0.0003,
    "timing.deadline_seconds": 450,
    "timing.supervision_seconds": 500,
    "timing.phase_wall_max_seconds": 14400,
    "timing.per_run_wall_max_seconds": 1200,
    "resource_limits.training_duty_cycle": 0.25,
    "resource_limits.process_memory_gib": 8.0,
    "resource_limits.mlx_memory_gib": 4.0,
    "resource_limits.system_reserve_gib": 16.0,
    "resource_limits.swap_growth_gib": 1.0,
}


def leaves(payload, prefix: str = "") -> dict:
    out = {}
    if isinstance(payload, dict):
        for key in payload:
            out.update(leaves(payload[key], f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            out.update(leaves(item, f"{prefix}[{index}]"))
    else:
        out[prefix] = payload
    return out


def get_path(payload, path: str):
    current = payload
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part.strip("[]"))]
        else:
            current = current[part]
    return current


def main() -> int:
    doc6 = json.loads(R6.read_text(encoding="utf-8"))
    doc7 = json.loads(R7.read_text(encoding="utf-8"))
    leaves6 = leaves(doc6)
    leaves7 = leaves(doc7)
    all_paths = sorted(set(leaves6) | set(leaves7))
    changed = []
    for path in all_paths:
        before = leaves6.get(path, "<missing>")
        after = leaves7.get(path, "<missing>")
        if before != after:
            changed.append(
                {
                    "path": path,
                    "r6": before,
                    "r7": after,
                    "inside_allowlist": any(
                        path == prefix or path.startswith(prefix + ".") or path.startswith(prefix)
                        for prefix in ALLOWLIST_PREFIXES
                    ),
                }
            )
    outside = [row for row in changed if not row["inside_allowlist"]]

    scientific_rows = []
    for path, expected in SCIENTIFIC.items():
        actual = get_path(doc7, path)
        scientific_rows.append(
            {"path": path, "expected": expected, "actual": actual, "match": actual == expected}
        )

    # the generic RunStore module: unchanged by the authors, but not frozen
    review = lib.frozen_review_inputs()
    lifecycle_row = next(
        (row for row in review["files"] if row["path"].endswith("runtime/lifecycle.py")), None
    )
    bound = doc7["source_identity"]["package_files"]
    identity_gap = {
        "lifecycle_sha256_now": lib.sha256_file(LIFECYCLE),
        "lifecycle_sha256_in_the_review_inputs": lifecycle_row["sha256"] if lifecycle_row else None,
        "lifecycle_unchanged_since_the_freeze": bool(
            lifecycle_row and lib.sha256_file(LIFECYCLE) == lifecycle_row["sha256"]
        ),
        "lifecycle_is_bound_by_the_preregistration": "src/ainerzero/runtime/lifecycle.py" in bound,
        "bound_source_file_count": len(bound),
        "a2_manifest_is_bound": "reports/V9-baseline/r3/baseline_manifest.json" in bound,
        "pilot_model_is_bound": "src/ainerzero/learning/pilot_model.py" in bound,
        "checkpoints_module_is_bound": "src/ainerzero/runtime/checkpoints.py" in bound,
    }

    payload = {
        "schema": "ainerzero.v9.p21.probe10_leaf_diff.v1",
        "r6": str(R6),
        "r7": str(R7),
        "leaves_total": len(all_paths),
        "leaves_r6": len(leaves6),
        "leaves_r7": len(leaves7),
        "changed": changed,
        "changed_count": len(changed),
        "outside_allowlist": outside,
        "outside_allowlist_count": len(outside),
        "scientific_values": scientific_rows,
        "identity_gap": identity_gap,
        "r7_status_field": doc7.get("status"),
        "r6_status_field": doc6.get("status"),
    }
    payload["verdict"] = {
        "seven_changed_leaves": len(changed) == 7,
        "no_leaf_outside_the_allowlist": not outside,
        "all_scientific_values_unchanged": all(row["match"] for row in scientific_rows),
        "lifecycle_unchanged_by_the_authors": identity_gap["lifecycle_unchanged_since_the_freeze"],
        "lifecycle_identity_gap_reported": not identity_gap[
            "lifecycle_is_bound_by_the_preregistration"
        ],
        "no_approval_written": doc7.get("status") == "awaiting_coordinator_approval",
    }
    out = lib.write_json("10-leaf-diff.json", payload)
    print(json.dumps(payload["verdict"], indent=1))
    print(json.dumps([row["path"] for row in changed], indent=1))
    print(json.dumps(identity_gap, indent=1))
    print("wrote", out)
    return 0 if all(payload["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
