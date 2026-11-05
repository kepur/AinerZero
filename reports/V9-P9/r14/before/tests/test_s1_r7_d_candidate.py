"""S1 r7: the D / arm1 re-verification keeps its real identity.

S1-R7-DECISION item 3: the frozen D candidate is the existing A2 manifest and
checkpoint identity, not an S1 training checkpoint.  The one registered C0
re-verification path must

* verify the authoritative A2 manifest byte-for-byte (tensors + manifest +
  metadata + candidate identity) before loading anything,
* refuse on tampering, a missing file and a second attempt,
* mark every S1-incomparable probe explicitly instead of faking a binding,
* never let a CPU forward substitute stand in for the identity check.

No MLX is imported here; the forward is a substitute, the identity validator is
the real one.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
import numpy as np
import pytest

from ainerzero.v9.experiments.s1 import arms, identity as identity_module, spec, worker

from s1_testkit import write_frozen


def _synthetic_candidate(tmp_path: Path, monkeypatch) -> dict:
    """A tiny A2-shaped manifest + pinned files, wired into spec.ARM_SPECS.

    r8 F6: the fixture pins the *manifest bytes* and computes the manifest self
    digest with the original A2 algorithm, exactly like the real trust root.  A
    synthetic placeholder digest would be refused by the trust-root check, which
    is the point of the r8 repair.
    """
    pilot = "pilot-synthetic"
    checkpoint = "ck-synthetic"
    prefix = f"{pilot}/checkpoints/{checkpoint}/"
    files = {}
    for name in ("tensors.safetensors", "manifest.json", "metadata.json"):
        path = tmp_path / pilot / "checkpoints" / checkpoint / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"payload:{name}".encode())
        files[prefix + name] = path
    files[f"{pilot}/fixed-batch.npz"] = tmp_path / pilot / "fixed-batch.npz"
    files[f"{pilot}/fixed-batch.npz"].write_bytes(b"batch")

    manifest = {
        "schema": "ainerzero.baseline_manifest.v1",
        "role": "read-only baseline freeze",
        "counts": {"files": len(files)},
        "files": [
            {"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for rel, path in files.items()
        ],
    }
    manifest_path = tmp_path / "baseline_manifest.json"
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)

    identity = {
        "frozen_manifest": str(manifest_path),
        "frozen_manifest_digest": identity_module.manifest_self_digest(manifest),
        "frozen_manifest_file_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "pilot_dir": pilot,
        "checkpoint_id": checkpoint,
        "experiment_id": "synthetic-candidate",
        "tensors_sha256": hashlib.sha256(files[prefix + "tensors.safetensors"].read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(files[prefix + "manifest.json"].read_bytes()).hexdigest(),
        "metadata_sha256": hashlib.sha256(files[prefix + "metadata.json"].read_bytes()).hexdigest(),
    }
    monkeypatch.setitem(spec.ARM_SPECS["arm1"], "identity", identity)
    monkeypatch.setitem(spec.ARM_SPECS["arm1"], "architecture", "pilot_shared_symbol_v1")
    return {"identity": identity, "files": files, "prefix": prefix, "root": tmp_path}


def test_the_real_a2_candidate_verifies_on_the_host():
    result = arms.verify_d_candidate_identity()
    identity = spec.ARM_SPECS["arm1"]["identity"]
    assert result["entries_verified"] >= 3
    assert result["tensors_sha256"] == identity["tensors_sha256"]
    assert result["pilot_dir"] == identity["pilot_dir"]
    assert result["checkpoint_id"] == identity["checkpoint_id"]


def test_a_tampered_pinned_file_is_refused(tmp_path, monkeypatch):
    candidate = _synthetic_candidate(tmp_path, monkeypatch)
    assert arms.verify_d_candidate_identity(candidate["root"])["entries_verified"] == 4
    target = candidate["files"][candidate["prefix"] + "tensors.safetensors"]
    target.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="changed"):
        arms.verify_d_candidate_identity(candidate["root"])


def test_a_missing_pinned_file_is_refused(tmp_path, monkeypatch):
    candidate = _synthetic_candidate(tmp_path, monkeypatch)
    candidate["files"][candidate["prefix"] + "metadata.json"].unlink()
    with pytest.raises(FileNotFoundError, match="missing"):
        arms.verify_d_candidate_identity(candidate["root"])


def test_a_tensor_digest_that_disagrees_with_the_registered_identity_is_refused(
    tmp_path, monkeypatch
):
    candidate = _synthetic_candidate(tmp_path, monkeypatch)
    identity = dict(candidate["identity"])
    identity["tensors_sha256"] = "f" * 64
    monkeypatch.setitem(spec.ARM_SPECS["arm1"], "identity", identity)
    with pytest.raises(RuntimeError, match="registered identity"):
        arms.verify_d_candidate_identity(candidate["root"])


def test_a_missing_manifest_is_refused(tmp_path, monkeypatch):
    candidate = _synthetic_candidate(tmp_path, monkeypatch)
    Path(candidate["identity"]["frozen_manifest"]).unlink()
    with pytest.raises(FileNotFoundError):
        arms.verify_d_candidate_identity(candidate["root"])


def test_the_eval_entry_refuses_a_failed_identity_before_opening_any_run(
    tmp_path, monkeypatch, canonical_root
):
    path, _digest, _document = write_frozen(canonical_root / "pre_registration.json")

    def _tampered(_repo_root=None):
        raise RuntimeError("A2-pinned file changed: tensors.safetensors")

    monkeypatch.setattr(identity_module, "verify_d_candidate_identity", _tampered)
    report = worker.run_worker(
        "eval",
        output_root=canonical_root,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=450.0,
        prereg_path=path,
        arm="arm1",
        seed=0,
    )
    assert report["status"] == "refused"
    assert report["refused_stage"] == "arm1_identity_verification_failed"
    with sqlite3.connect(canonical_root / "control.sqlite3") as connection:
        rows = connection.execute(
            "SELECT COUNT(*) FROM runs WHERE state != 'created'"
        ).fetchone()[0]
    assert rows == 0, "a failed identity check must not open a run"


def test_a_second_arm1_attempt_is_refused(tmp_path, monkeypatch, canonical_root):
    path, _digest, _document = write_frozen(canonical_root / "pre_registration.json")
    monkeypatch.setattr(
        identity_module,
        "verify_d_candidate_identity",
        lambda repo_root=None: {"entries_verified": 4},
    )
    snapshot = worker.run_config_snapshot(wall_budget_seconds=450.0, purpose="arm1-already")
    snapshot["arm_id"] = "arm1"
    snapshot["seed"] = 0
    ledger = worker.PrepLedger(canonical_root / "control.sqlite3")
    try:
        ledger.store.create_run(
            snapshot,
            "arm1-previous",
            "arm1-previous",
            experiment_id=worker.PREP_EXPERIMENT_ID,
            role="auxiliary",
        )
        # created -> initializing is the legal edge into a work state; only a
        # non-created row counts as a registered attempt.
        ledger.store.transition("arm1-previous", "initializing")
    finally:
        ledger.close()
    report = worker.run_worker(
        "eval",
        output_root=canonical_root,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=450.0,
        prereg_path=path,
        arm="arm1",
        seed=0,
    )
    assert report["status"] == "refused"
    assert report["refused_stage"] == "already_attempted"


class _SubstituteBackend:
    """A CPU forward substitute: it has no model and no identity of its own."""

    name = "cpu-substitute"

    def __init__(self):
        self.calls = 0
        self.d_candidate_info = {
            "parameter_count": 393_232,
            "parameter_sha256": "cbb14d878dfda5af816dbc4903c7fb811aabbcfb17ce494f00e994ab3d6b286a",
        }

    def eval_d_candidate(self, seed=0):
        self.calls += 1
        return arms.ArmOutput(
            loss=0.5,
            metrics={"symbol_nll_t0": 1.25, "symbol_nll_t1": 1.20},
            pose_belief=np.zeros((1, 4), dtype=np.float64),
            predictions=None,
        )


def test_a_substitute_cannot_bypass_the_identity_validator(tmp_path, monkeypatch):
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")
    monkeypatch.setattr(
        identity_module,
        "verify_d_candidate_identity",
        lambda repo_root=None: (_ for _ in ()).throw(RuntimeError("pinned file changed")),
    )
    monkeypatch.setattr(
        "ainerzero.v9.experiments.s1.data.resolve_dataset_dir", lambda root: tmp_path
    )
    backend = _SubstituteBackend()
    with pytest.raises(RuntimeError, match="pinned file changed"):
        worker._evaluate_arm(
            _document,
            tmp_path,
            arm_id="arm1",
            backend=backend,
            prereg_sha256="x",
        )
    assert backend.calls == 0, "no forward may run before the identity is verified"


def test_the_substitute_forward_is_marked_and_all_s1_probes_are_incomparable(
    tmp_path, monkeypatch
):
    path, _digest, document = write_frozen(tmp_path / "pre_registration.json")
    verified = {"entries_verified": 4, "tensors_sha256": "c" * 64}
    monkeypatch.setattr(
        identity_module, "verify_d_candidate_identity", lambda repo_root=None: verified
    )
    monkeypatch.setattr(
        "ainerzero.v9.experiments.s1.data.resolve_dataset_dir", lambda root: tmp_path
    )
    backend = _SubstituteBackend()
    report = worker._evaluate_arm(
        document,
        tmp_path,
        arm_id="arm1",
        backend=backend,
        prereg_sha256="x",
    )
    assert backend.calls == 1
    assert report["status"] == "completed"
    assert report["kind"] == "frozen_candidate"
    assert report["forward_substitute"] is True
    assert report["d_candidate_identity"] == verified
    assert report["incomparable"], "the S1-incomparable probes must be named"
    for probe in (
        "localization_error",
        "unseen_map_generalization",
        "topology_recovery",
        "few_shot_unseen_transition",
        "sample_efficiency",
    ):
        assert report[probe]["status"] == "not_applicable"
    assert report["m2_memory_interference"]["status"] == "not_applicable"
    assert report["d_candidate_c0_metrics"]["symbol_nll_t0"] == 1.25
