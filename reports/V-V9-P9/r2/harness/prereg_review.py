"""V9.P11 reviewer harness: preregistration identity, budget derivation, layout.

Read-only.  Recomputes every number the r2 report claims instead of trusting it:

1. document/file/sidecar SHA256 of the authoritative freeze and the reports copy;
2. the frozen budget rule applied to the r1 measurement of record (3510 steps,
   estimate 359.93 s, deadline 450 s, supervision 500 s, phase 4099.6 s) and to
   the r2 re-measurement (3749 steps) -- including whether the re-measurement
   would still fit the registered 20 min per-run cap;
3. a leaf-by-leaf diff r1 -> r2, grouped by top-level block, with an explicit
   assertion that no parameter/seed/step/budget/limit/metric/stop-rule leaf moved;
4. the notice-#297 storage split (ledger + datasets under artifacts/, reports
   only carries manifests) and the real lock/ledger mtimes.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(REAL / "src"))

from ainerzero.v9.experiments.s1 import prereg, spec  # noqa: E402

OUT = REAL / "reports" / "V-V9-P9" / "r2" / "evidence"
AUTH = REAL / "artifacts" / "v9" / "s1" / "phase1" / "pre_registration.json"
REPORTS_COPY = REAL / "reports" / "V9-P9" / "r2" / "pre_registration.json"
R1_DOC = REAL / "reports" / "V9-P9" / "r1-archive" / "pre_registration.json"
R1_SMOKE = REAL / "reports" / "V9-P9" / "r1-archive" / "smoke_metrics.json"
R2_SMOKE = REAL / "artifacts" / "v9" / "s1" / "phase1" / "smoke_metrics.json"


def sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def flatten(node, prefix=""):
    rows = []
    if isinstance(node, dict):
        for key in sorted(node):
            rows.extend(flatten(node[key], f"{prefix}.{key}" if prefix else key))
    elif isinstance(node, list):
        rows.append((prefix, node))
    else:
        rows.append((prefix, node))
    return rows


PARAMETER_BLOCKS = ("arms", "training_protocol", "resource_limits", "metrics", "stop_rules")


def main() -> int:
    doc = json.loads(AUTH.read_text(encoding="utf-8"))
    digest = prereg.document_sha256(doc)
    sidecar = AUTH.with_suffix(".json.sha256").read_text(encoding="utf-8").split()[0]
    r1_doc = json.loads(R1_DOC.read_text(encoding="utf-8"))

    identity = {
        "authoritative_document_sha256": digest,
        "sidecar_sha256": sidecar,
        "sidecar_matches": sidecar == digest,
        "reports_copy_sha256": prereg.document_sha256(
            json.loads(REPORTS_COPY.read_text(encoding="utf-8"))
        ),
        "reports_copy_byte_identical": sha_file(AUTH) == sha_file(REPORTS_COPY),
        "reports_sidecar_matches": REPORTS_COPY.with_suffix(".json.sha256").read_text().split()[0] == digest,
        "file_sha256": sha_file(AUTH),
        "r1_document_sha256": prereg.document_sha256(r1_doc),
        "report_claimed": "0547744fc142adae198b6d2fcfe6a6ac273fa092857649361bbf2dd157a14c07",
    }
    identity["claim_matches"] = identity["authoritative_document_sha256"] == identity["report_claimed"]

    # 2) budget derivation, recomputed from both smoke measurements
    r1_smoke = json.loads(R1_SMOKE.read_text(encoding="utf-8"))
    r2_smoke = json.loads(R2_SMOKE.read_text(encoding="utf-8"))
    b1 = prereg.estimate_budget(r1_smoke)
    b2 = prereg.estimate_budget(r2_smoke)
    timing = doc["timing"]
    source = timing.get("smoke_source") or {}
    recheck = timing.get("smoke_recheck") or {}
    derivation = {
        "rule": "updates = clamp(floor((target*duty/overhead - eval_cost) / (3*step)), min, cap)",
        "r1_measurement": {
            "path": source.get("path"),
            "sha256_recorded": source.get("sha256"),
            "sha256_actual": sha_file(R1_SMOKE),
            "max_trainable_step_seconds": b1["measured_forward_loss_step_seconds"],
            "updates": b1["updates"],
            "estimate_seconds": b1["estimate_seconds"],
            "deadline_seconds": b1["deadline_seconds"],
            "supervision_seconds": b1["supervision_seconds"],
            "arm1_deadline_seconds": b1["arm1_deadline_seconds"],
            "phase_wall_seconds": b1["phase_wall_seconds"],
        },
        "r2_remeasurement": {
            "path": recheck.get("path"),
            "max_trainable_step_seconds": b2["measured_forward_loss_step_seconds"],
            "updates_if_used": b2["updates"],
            "estimate_seconds": b2["estimate_seconds"],
            "deadline_seconds": b2["deadline_seconds"],
            "supervision_seconds": b2["supervision_seconds"],
            "fits_per_run_cap": b2["fits_per_run_cap"],
            "per_run_cap_seconds": spec.TIMING["per_run_wall_max_seconds"],
            "frozen_record_derived_updates": recheck.get("derived_updates_if_recheck_used"),
        },
        "frozen_values": {
            "updates_protocol": doc["training_protocol"]["updates"],
            "updates_arms": {a: doc["arms"][a]["training_updates"] for a in prereg.TRAINABLE_ARMS},
            "seeds_arms": {a: list(doc["arms"][a]["seeds"]) for a in prereg.TRAINABLE_ARMS},
            "estimate_seconds": timing["estimate_seconds"],
            "deadline_seconds": timing["deadline_seconds"],
            "supervision_seconds": timing["supervision_seconds"],
            "arm1_deadline_seconds": timing["arm1_deadline_seconds"],
            "phase_wall_seconds": timing["phase_wall_seconds"],
            "measured_step_seconds": timing.get("measured_step_seconds"),
        },
    }
    derivation["matches_r1_derivation"] = (
        b1["updates"] == doc["training_protocol"]["updates"] == 3510
        and all(doc["arms"][a]["training_updates"] == 3510 for a in prereg.TRAINABLE_ARMS)
        and abs(timing["estimate_seconds"] - b1["estimate_seconds"]) < 1e-9
        and timing["deadline_seconds"] == b1["deadline_seconds"] == 450
        and timing["supervision_seconds"] == b1["supervision_seconds"] == 500
        and abs(timing["phase_wall_seconds"] - b1["phase_wall_seconds"]) < 1e-6
        and timing["measured_step_seconds"] == b1["measured_forward_loss_step_seconds"]
    )
    derivation["r2_recheck_record_consistent"] = (
        recheck.get("derived_updates_if_recheck_used") == b2["updates"]
        and recheck.get("deadline_if_recheck_used", b2["deadline_seconds"]) == b2["deadline_seconds"]
    )
    derivation["r2_recheck_still_within_caps"] = (
        b2["fits_per_run_cap"]
        and b2["deadline_seconds"] <= spec.TIMING["per_run_wall_max_seconds"]
        and b2["fits_phase_cap"]
    )
    derivation["phase_recomputed"] = (
        spec.TIMING["trainable_runs"] * 450
        + spec.TIMING["d_candidate_eval_runs"] * doc["timing"]["arm1_deadline_seconds"]
        + float(doc["timing"]["smoke"]["data_generation_seconds"])
    )

    # 3) leaf diff r1 -> r2
    left = dict(flatten(r1_doc))
    right = dict(flatten(doc))
    changed, added, removed = [], [], []
    for path in sorted(set(left) | set(right)):
        if path not in right:
            removed.append({"path": path, "r1": left[path]})
        elif path not in left:
            added.append({"path": path, "r2": right[path]})
        elif left[path] != right[path]:
            changed.append({"path": path, "r1": left[path], "r2": right[path]})

    def block(path: str) -> str:
        return path.split(".", 1)[0]

    by_block: dict[str, int] = {}
    for row in changed + added + removed:
        by_block[block(row["path"])] = by_block.get(block(row["path"]), 0) + 1
    parameter_leaks = [
        row for row in changed + added + removed
        if block(row["path"]) in PARAMETER_BLOCKS
    ]
    plan_leaks = [
        row for row in changed + added + removed
        if row["path"].startswith("data_identity.plan")
        or row["path"].startswith("data_identity.source_identity.source_map_digest")
    ]
    diff = {
        "r1_document_sha256": prereg.document_sha256(r1_doc),
        "r2_document_sha256": digest,
        "leaf_counts": {"changed": len(changed), "added": len(added), "removed": len(removed)},
        "by_top_level_block": dict(sorted(by_block.items())),
        "changed": changed,
        "added": added,
        "removed": removed,
        "parameter_leaks": parameter_leaks,
        "data_plan_leaks": plan_leaks,
        "no_parameter_or_budget_change": not parameter_leaks and not plan_leaks,
    }

    # 4) storage split + production lock/ledger identity
    phase1 = REAL / "artifacts" / "v9" / "s1" / "phase1"
    datasets = REAL / "artifacts" / "v9" / "s1" / "datasets"
    ref = json.loads((phase1 / "dataset_ref.json").read_text(encoding="utf-8"))
    dataset_dirs = sorted(p.name for p in datasets.iterdir() if p.is_dir()) if datasets.is_dir() else []
    reports_r2 = REAL / "reports" / "V9-P9" / "r2"
    reports_big = [
        {"path": str(p.relative_to(REAL)), "bytes": p.stat().st_size}
        for p in reports_r2.rglob("*") if p.is_file() and p.stat().st_size > 3_000_000
    ]
    storage = {
        "declared_ledger_root": doc["storage"]["ledger_output_root"],
        "declared_datasets": doc["storage"]["datasets"],
        "ledger_exists": (phase1 / "control.sqlite3").is_file(),
        "ledger_path": str((phase1 / "control.sqlite3").relative_to(REAL)),
        "dataset_ref": ref,
        "dataset_dirs": dataset_dirs,
        "dataset_digest_matches_dir": ref.get("dataset_digest") in dataset_dirs,
        "dataset_dir": str((datasets / ref.get("dataset_digest", "")).relative_to(REAL)),
        "reports_r2_has_dataset_bytes": reports_big,
        "doc_commands_point_at_artifacts": all(
            "reports/" not in value
            for key, value in doc["commands"].items()
            if key != "run_refused_here"
        ),
    }
    lock = REAL / "artifacts" / "locks" / "m0-worker.lock"
    ledger = REAL / "artifacts" / "control.sqlite3"
    storage["production_lock"] = {
        "path": str(lock.relative_to(REAL)),
        "mtime": lock.stat().st_mtime if lock.exists() else None,
    }
    storage["production_ledger"] = {
        "path": str(ledger.relative_to(REAL)),
        "mtime": ledger.stat().st_mtime if ledger.exists() else None,
        "sha256": sha_file(ledger) if ledger.exists() else None,
    }

    payload = {
        "harness": "reports/V-V9-P9/r2/harness/prereg_review.py",
        "identity": identity,
        "derivation": derivation,
        "diff_r1_r2": diff,
        "storage": storage,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "prereg-review.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print("identity claim matches:", identity["claim_matches"], "| reports copy identical:", identity["reports_copy_byte_identical"])
    print("derivation from r1:", derivation["matches_r1_derivation"], "| r2 recheck record:", derivation["r2_recheck_record_consistent"], "| r2 fits caps:", derivation["r2_recheck_still_within_caps"])
    print("r1 updates/est/deadline:", b1["updates"], round(b1["estimate_seconds"], 2), b1["deadline_seconds"], "| r2:", b2["updates"], round(b2["estimate_seconds"], 2), b2["deadline_seconds"])
    print("phase recomputed:", round(derivation["phase_recomputed"], 3))
    print("diff leaves:", diff["leaf_counts"], "by block:", diff["by_top_level_block"])
    print("parameter leaks:", len(diff["parameter_leaks"]), "| data plan leaks:", len(diff["data_plan_leaks"]))
    print("storage:", storage["ledger_path"], storage["dataset_dir"], "| digest dir ok:", storage["dataset_digest_matches_dir"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
