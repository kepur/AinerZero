#!/usr/bin/env python3
"""P31 independent verification probes (CPU only; no MLX; no approval writes)."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sqlite3
import sys
import tempfile
import time
from copy import deepcopy
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT = ROOT / "reports/V9-P31/evidence"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests/v9/experiments"))
os.chdir(ROOT)

from ainerzero.v9.experiments.s1 import identity, prereg, spec, worker  # noqa: E402
from s1_testkit import fake_smoke  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")


results: dict = {"ok": True, "checks": {}}


def record(name: str, passed: bool, detail) -> None:
    results["checks"][name] = {"passed": bool(passed), "detail": detail}
    if not passed:
        results["ok"] = False
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")


r11_path = ROOT / "artifacts/v9/s1/phase1/r11/pre_registration.json"
r10_path = ROOT / "artifacts/v9/s1/phase1/r10/pre_registration.json"
r11_raw = r11_path.read_bytes()
r10_raw = r10_path.read_bytes()
r11 = json.loads(r11_raw)
r10 = json.loads(r10_raw)
doc_sha = prereg.document_sha256(r11)
file_sha = hashlib.sha256(r11_raw).hexdigest()

record(
    "r11_file_sha",
    file_sha == "aeb8a7a800deab87bce08940489796edb0cc1949cde0f4999163f52decc1f105",
    {"file_sha": file_sha, "bytes": len(r11_raw)},
)
record(
    "r11_document_sha",
    doc_sha == "b73b558953a06ce551c2e8613a09d0785b1c0222f8ff57f99c49da2ec812fb4e",
    {"document_sha": doc_sha},
)
record(
    "r10_file_sha_unchanged",
    hashlib.sha256(r10_raw).hexdigest()
    == "5fea3ca73da29658753932ff8d38c96dadd33314b1db022576caea505c20d1ff",
    {"file_sha": hashlib.sha256(r10_raw).hexdigest()},
)

timing = r11["timing"]
tp = r11["training_protocol"]
frozen_detail = {
    "updates": tp["updates"],
    "eval_batches": tp["eval_batches"],
    "seeds": tp["seeds"],
    "checkpoint_updates": tp["checkpoint_updates"],
    "deadline_seconds": timing["deadline_seconds"],
    "supervision_seconds": timing["supervision_seconds"],
    "deadline_source": timing.get("deadline_source"),
    "arm1_deadline_seconds": timing["arm1_deadline_seconds"],
    "derived_deadline_seconds": timing.get("derived_deadline_seconds"),
    "phase_wall_max_seconds": timing["phase_wall_max_seconds"],
    "phase_wall_seconds": timing.get("phase_wall_seconds"),
    "experiment_id": r11["experiment_id"],
    "status": r11.get("status"),
}
record(
    "frozen_registered_values",
    (
        tp["updates"] == 3510
        and tp["eval_batches"] == 175
        and tp["seeds"] == [0, 1, 2]
        and tp["checkpoint_updates"] == [0, 439, 878, 1755, 3510]
        and timing["deadline_seconds"] == 1200
        and timing["supervision_seconds"] == 1250
        and timing.get("deadline_source") == spec.R11_DEADLINE_SOURCE
        and timing["arm1_deadline_seconds"] == 7
        and float(timing["phase_wall_max_seconds"]) == 14400.0
        and r11["experiment_id"] == "s1-phase1-20261023-r11"
    ),
    frozen_detail,
)

smoke = json.loads((ROOT / "reports/V9-P9/r1-archive/smoke_metrics.json").read_text())
budget = prereg.registered_budget(smoke)
record(
    "independent_registered_budget_recalc",
    (
        budget["updates"] == 3510
        and budget["deadline_seconds"] == 1200
        and budget["supervision_seconds"] == 1250
        and budget["derived_deadline_seconds"] == 477
        and budget["arm1_deadline_seconds"] == 7
        and abs(budget["estimate_seconds"] - 381.1528007568777) < 1e-9
        and abs(budget["phase_wall_seconds"] - 10854.605202458999) < 1e-6
        and timing.get("derived_deadline_seconds") == 477
        and timing["arm1_deadline_seconds"] == 7
        and abs(float(timing["phase_wall_seconds"]) - budget["phase_wall_seconds"]) < 1e-6
    ),
    {
        k: budget[k]
        for k in (
            "updates",
            "deadline_seconds",
            "supervision_seconds",
            "derived_deadline_seconds",
            "arm1_deadline_seconds",
            "estimate_seconds",
            "phase_wall_seconds",
            "fits_phase_cap",
            "fits_per_run_cap",
        )
        if k in budget
    },
)

worst = 9 * 1250
record(
    "worst_case_phase_under_14400",
    worst <= 14400 and bool(budget.get("fits_phase_cap", True)),
    {"nine_times_supervision": worst, "phase_wall_max": 14400},
)
record(
    "derived_477_not_the_run_deadline",
    timing["deadline_seconds"] == 1200 and timing.get("derived_deadline_seconds") == 477,
    {
        "deadline_seconds": timing["deadline_seconds"],
        "derived_deadline_seconds": timing.get("derived_deadline_seconds"),
        "per_run_wall_max_seconds": timing.get("per_run_wall_max_seconds"),
    },
)

# Fail-closed deadline path
fail_closed: dict = {}
tampered = deepcopy(r11)
tampered["timing"]["deadline_seconds"] = 1150
reasons = prereg.validate(tampered)
fail_closed["tamper_deadline_1150"] = {"refused": bool(reasons), "reasons": reasons[:8]}

tampered2 = deepcopy(r11)
tampered2["timing"]["registered_updates"] = 3299
tampered2["training_protocol"]["updates"] = 3299
for arm in ("arm2", "arm3", "arm4"):
    tampered2["arms"][arm]["training_updates"] = 3299
reasons2 = prereg.validate(tampered2)
fail_closed["shrink_updates_3299"] = {"refused": bool(reasons2), "reasons": reasons2[:8]}

slow_refused = False
slow_msg = ""
try:
    prereg.registered_budget(fake_smoke(step_seconds=0.02))
except Exception as exc:
    slow_refused = "shrink" in str(exc).lower()
    slow_msg = str(exc)[:400]
fail_closed["slow_smoke_shrink_path"] = {"refused": slow_refused, "message": slow_msg}


def broken_validate_without_1200_guard(doc):
    """Isolation bad-control: drop the user-approved-1200 guard only.

    Still checks structural positivity so it is a validator, but a deadline of
    1150 (with matching supervision) is accepted — proving the real refusal
    comes from the 1200 registration guard.
    """
    t = doc["timing"]
    reasons_b = []
    if not isinstance(t.get("deadline_seconds"), int) or t["deadline_seconds"] <= 0:
        reasons_b.append("deadline not positive int")
    if t.get("supervision_seconds") != t.get("deadline_seconds") + 50:
        reasons_b.append("supervision")
    return reasons_b


# Align supervision so only the missing 1200 guard differs from a green path.
broken_doc = deepcopy(r11)
broken_doc["timing"]["deadline_seconds"] = 1150
broken_doc["timing"]["supervision_seconds"] = 1200
broken_on_1150 = broken_validate_without_1200_guard(broken_doc)
real_on_broken_doc = prereg.validate(broken_doc)
fail_closed["isolated_broken_control"] = {
    "tampered_1150_accepted_by_broken": broken_on_1150 == [],
    "real_validate_refuses_1150": bool(real_on_broken_doc),
    "real_reasons": real_on_broken_doc[:6],
    "turns_red": broken_on_1150 == [] and bool(real_on_broken_doc),
}
record(
    "fail_closed_deadline_path",
    (
        fail_closed["tamper_deadline_1150"]["refused"]
        and fail_closed["shrink_updates_3299"]["refused"]
        and fail_closed["slow_smoke_shrink_path"]["refused"]
        and fail_closed["isolated_broken_control"]["turns_red"]
    ),
    fail_closed,
)

# T1 arms
arm_diff = {}
for arm_id in sorted(set(r10["arms"]) | set(r11["arms"])):
    a0 = json.dumps(r10["arms"].get(arm_id), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    a1 = json.dumps(r11["arms"].get(arm_id), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    arm_diff[arm_id] = {"byte_equal": a0 == a1}
arm1_id = r11["arms"]["arm1"].get("identity", {})
missing_keys = [
    k
    for k in ("frozen_manifest_file_sha256", "frozen_manifest_digest_rule")
    if k not in arm1_id
]
identity_src = Path(identity.__file__).read_text(encoding="utf-8")
verify_src = inspect.getsource(identity.verify_d_candidate_identity)
_identity_src = inspect.getsource(identity._identity)
spec_arm1 = spec.ARM_SPECS["arm1"]["identity"]
# Runtime paths that would require the *document* arm1 identity to carry the
# two trust-root keys (excluding spec.py which defines ARM_SPECS itself, and
# identity.py which reads ARM_SPECS).
pkg_hits = []
needle_patterns = (
    'document["arms"]["arm1"]',
    "document['arms']['arm1']",
    'document.get("arms"',
    "arms\"][\"arm1\"][\"identity\"]",
)
for p in (ROOT / "src/ainerzero/v9/experiments/s1").glob("*.py"):
    if p.name in {"spec.py", "identity.py"}:
        continue
    text = p.read_text(encoding="utf-8")
    if "frozen_manifest_file_sha256" not in text and "frozen_manifest_digest_rule" not in text:
        continue
    # Only count if the file also reaches into a document's arm1 identity.
    if any(n in text for n in needle_patterns) or (
        "document" in text and "arm1" in text and "identity" in text and "frozen_manifest_file_sha256" in text
    ):
        # Heuristic refinement: require reading document arms identity keys
        if "document" in text and "arms" in text:
            pkg_hits.append(str(p.relative_to(ROOT)))
validate_src = inspect.getsource(prereg.validate)
# validate() may mention the keys only as structural optional checks — that is OK
# per T1 ("除 validate() 的结构检查外")
record(
    "T1_arms_and_identity",
    (
        all(v["byte_equal"] for v in arm_diff.values())
        and missing_keys == ["frozen_manifest_file_sha256", "frozen_manifest_digest_rule"]
        and "spec.ARM_SPECS" in _identity_src
        and "frozen_manifest_file_sha256" in spec_arm1
        and "frozen_manifest_digest_rule" in spec_arm1
        and "document[" not in verify_src
        and pkg_hits == []
    ),
    {
        "arms_byte_equal": arm_diff,
        "arm1_doc_missing_keys": missing_keys,
        "_identity_uses_ARM_SPECS": "spec.ARM_SPECS" in _identity_src,
        "spec_ARM_SPECS_has_trust_keys": {
            "frozen_manifest_file_sha256": "frozen_manifest_file_sha256" in spec_arm1,
            "frozen_manifest_digest_rule": "frozen_manifest_digest_rule" in spec_arm1,
        },
        "verify_d_reads_document_arms": "document[" in verify_src,
        "other_runtime_hits_requiring_doc_arm1_keys": pkg_hits,
        "validate_mentions_manifest_file_sha": "frozen_manifest_file_sha256" in validate_src,
        "known_note": "arm1 doc identity missing trust-root keys since r8-r10; runtime uses ARM_SPECS",
    },
)

# Leaf diff
leaf = json.loads((ROOT / "reports/V9-P9/r11/prereg-leaf-diff.json").read_text())
changed_paths = [c["path"] for c in leaf.get("changes", [])]
# Science fields that must remain equal: metrics definitions, data_identity digest, etc.
science_prefixes = (
    "metrics",
    "data_identity",
    "evaluation.metrics",
    "arms.",  # arms already byte-equal above
)
# Allowed change path prefixes (registration scheme A)
allowed_prefixes = (
    "budget_estimate.",
    "timing.",
    "training_protocol.",
    "budget_registration",
    "experiment_id",
    "created_unix",
    "source_identity.",
    "effective_metadata.",
    "commands.",
    "approval_rule.",
    "stop_rules.",
    "storage.",
    "resource_limit",
    "phase",
    "task",
    "schema",
    "spec.",
    "status",
)
# More precise: use leaf file's own allowlist semantics + check arms.* not in changes
arm_changes = [p for p in changed_paths if p.startswith("arms.")]
science_changes = [
    p
    for p in changed_paths
    if p.startswith("metrics")
    or p.startswith("data_identity")
    or p.startswith("evaluation.")
    and not p.startswith("evaluation.")  # keep evaluation for inspection
]
# Independent: compare science subtrees
science_equal = (
    r10.get("metrics") == r11.get("metrics")
    and r10.get("data_identity") == r11.get("data_identity")
    and r10.get("evaluation") == r11.get("evaluation")  # may differ on eval_batches notes?
)
# evaluation may include eval-related registered fields — inspect diffs carefully
eval_r10 = json.dumps(r10.get("evaluation"), sort_keys=True)
eval_r11 = json.dumps(r11.get("evaluation"), sort_keys=True)
metrics_equal = r10.get("metrics") == r11.get("metrics")
data_equal = r10.get("data_identity") == r11.get("data_identity")
record(
    "leaf_diff_and_science",
    (
        leaf.get("bound_files_outside_allowlist") == []
        and leaf.get("non_identity_leaves_outside_allowlist") == []
        and arm_changes == []
        and metrics_equal
        and data_equal
    ),
    {
        "leaf_count": leaf.get("leaf_count"),
        "changed_leaf_count": leaf.get("changed_leaf_count"),
        "bound_files_outside_allowlist": leaf.get("bound_files_outside_allowlist"),
        "non_identity_leaves_outside_allowlist": leaf.get("non_identity_leaves_outside_allowlist"),
        "arm_leaf_changes": arm_changes,
        "metrics_equal": metrics_equal,
        "data_identity_equal": data_equal,
        "evaluation_equal": eval_r10 == eval_r11,
        "changed_bound_files": [x["path"] for x in leaf.get("changed_bound_files", [])],
        "changed_paths": changed_paths,
    },
)

# T5 control.sqlite3
ctl = ROOT / "artifacts/v9/s1/phase1/control.sqlite3"
ctl_sha = sha256_file(ctl)
pin_ctl = "a5fd11ffd0c41e20456cedd6c6ed7e1b38dc62b479f8ccb65132683aab4163c3"
con = sqlite3.connect(f"file:{ctl.resolve()}?mode=ro", uri=True)
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
r11_hits = {}
for t in tables:
    rows = list(con.execute(f"SELECT * FROM {t}"))
    found = 0
    for row in rows:
        blob = " ".join("" if v is None else str(v) for v in row)
        if "s1-phase1-20261023-r11" in blob:
            found += 1
    r11_hits[t] = {"row_count": len(rows), "r11_mentions": found}
record(
    "T5_control_sqlite_no_r11",
    ctl_sha == pin_ctl and all(v["r11_mentions"] == 0 for v in r11_hits.values()),
    {"sha256": ctl_sha, "pin_match": ctl_sha == pin_ctl, "r11_hits": r11_hits},
)

# New experiment identity (temp ledger)
OLD = spec.EXPERIMENT_ID
R11 = spec.R11_EXPERIMENT_ID


def _started_run(ledger, *, experiment_id: str, arm_id: str, seed: int, run_id: str):
    snapshot = worker.run_config_snapshot(
        wall_budget_seconds=1200.0, purpose=f"s1_phase1_training_run:{arm_id}:seed{seed}"
    )
    snapshot["arm_id"] = arm_id
    snapshot["seed"] = int(seed)
    snapshot["updates"] = 3510
    ledger.store.create_run(
        snapshot,
        f"{experiment_id}:{arm_id}:{seed}:{run_id}",
        run_id,
        experiment_id=experiment_id,
        role="model",
    )
    ledger.store.transition(run_id, "initializing", reason="train_prereg_approved")
    ledger.store.transition(run_id, "training", reason="worker_started")
    return run_id


with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "control.sqlite3"
    ledger = worker.PrepLedger(path)
    try:
        ledger.store.create_experiment(
            worker.train_experiment_manifest(updates=3510), f"{OLD}:training", OLD
        )
        old_run = _started_run(
            ledger, experiment_id=OLD, arm_id="arm2", seed=0, run_id="old-arm2-seed0"
        )
        ledger.store.create_experiment(
            worker.train_experiment_manifest(updates=3510), f"{R11}:training", R11
        )
        # fill old experiment toward run cap evidence: attempt guard still works
        runs = ledger.store.list_runs()
    finally:
        ledger.close()
    new_attempts = worker.train_attempts(runs, arm_id="arm2", seed=0, experiment_id=R11)
    old_attempts = worker.train_attempts(runs, arm_id="arm2", seed=0, experiment_id=OLD)
    phase_new = worker.phase_total_wall_seconds(runs, instant=time.time(), experiment_id=R11)
    phase_old = worker.phase_total_wall_seconds(runs, instant=time.time(), experiment_id=OLD)
    record(
        "new_experiment_attempts_start_at_zero",
        new_attempts == [] and [r.run_id for r in old_attempts] == [old_run] and phase_new == 0.0 and phase_old > 0.0,
        {
            "new_attempts": new_attempts,
            "old_attempt_ids": [r.run_id for r in old_attempts],
            "phase_new": phase_new,
            "phase_old": phase_old,
            "R11": R11,
            "OLD": OLD,
        },
    )

# RunStore generic module pin check
pin = json.loads(
    Path(
        "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/claude-20261022-e32/P30-review-inputs.json"
    ).read_text()
)
runstore_detail = {}
runstore_ok = True
for rel, meta in pin["files"].items():
    if "runstore" in rel.lower() or rel.endswith("lifecycle.py") and "runtime" in rel:
        # include runtime pieces that implement RunStore
        h = sha256_file(ROOT / rel)
        runstore_detail[rel] = {"match": h == meta["sha256"], "sha": h}
        if h != meta["sha256"]:
            runstore_ok = False
# Explicit common RunStore path
for rel in [
    "src/ainerzero/runtime/run_store.py",
    "src/ainerzero/runtime/runstore.py",
    "src/ainerzero/runtime/lifecycle.py",
]:
    p = ROOT / rel
    if p.exists() and rel in pin["files"]:
        h = sha256_file(p)
        runstore_detail[rel] = {"match": h == pin["files"][rel]["sha256"], "sha": h}
        if h != pin["files"][rel]["sha256"]:
            runstore_ok = False
record("runstore_unmodified_vs_pin", runstore_ok, runstore_detail)

# V9-S1 frozen artifact bytes
v9s1 = ROOT / "reports/V9-S1/metrics.json"
record(
    "v9_s1_metrics_unchanged",
    sha256_file(v9s1) == "8b5017c24fb710a3bf55508a8ac917d17cb41e29ba464c32b092e37b14db6ce4",
    {"sha": sha256_file(v9s1)},
)

write("verify_core.json", results)
write("fail_closed_detail.json", fail_closed)
print(json.dumps({"ok": results["ok"], "n_checks": len(results["checks"])}, indent=2))
sys.exit(0 if results["ok"] else 1)
