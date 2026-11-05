"""r8 F6/F7: the D trust root is verified against its pinned bytes, and the CPU
identity entry point does not drag the MLX runtime in.

P21 F6: r7 computed a local ``digest`` in ``verify_d_candidate_identity`` and
never read it; the registered ``frozen_manifest_digest`` was only reported as a
hint and compared with nothing, so the A2 trust root could be replaced without
being noticed.  The generic RunStore, the D loader modules and the A2 manifest
were also outside the frozen source identity.

P21 F7: the r7 test claimed "No MLX is imported here" while ``arms.py`` imported
``mlx.core`` at module level, so importing the identity test loaded the runtime.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import identity, prereg, spec

from s1_testkit import FAKE_COUNTS, FAKE_IDENTITY, frozen_document

PINNED_MANIFEST_SHA = "2c991f052f322112fa97c57f52585bd99779c3178b21108efdc494596184be5b"
REGISTERED_MANIFEST_DIGEST = "3481b6ad70991478c658fa2de87d5621208fe69fc50369705cbaaa7492eb45e9"


# --- F6: the trust chain --------------------------------------------------
def test_the_a2_manifest_bytes_and_self_digest_are_actually_verified():
    report = identity.verify_d_candidate_identity()
    assert report["frozen_manifest_file_sha256"] == PINNED_MANIFEST_SHA
    assert report["frozen_manifest_digest"] == REGISTERED_MANIFEST_DIGEST
    assert report["manifest_digest_match"] is True
    assert report["entries_verified"] == 9
    assert report["tensors_sha256"].startswith("cbb14d87")
    assert report["mlx_imported"] is False


def test_the_self_digest_uses_the_original_a2_algorithm_not_a_lookalike():
    """Recompute with the r3 builder's own rule and compare, never just report."""
    manifest = json.loads(Path(spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest"]).read_text())
    # scripts/v9_baseline_manifest_r3.py: sha256 over canonical JSON of every
    # top-level field except generated_at / manifest_digest / policy_check.
    payload = {
        key: value
        for key, value in manifest.items()
        if key not in ("generated_at", "manifest_digest", "policy_check")
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    import hashlib

    assert hashlib.sha256(canonical).hexdigest() == REGISTERED_MANIFEST_DIGEST
    assert identity.manifest_self_digest(manifest) == REGISTERED_MANIFEST_DIGEST


def test_a_manifest_with_replaced_bytes_is_refused(tmp_path):
    identity_dict = dict(spec.ARM_SPECS["arm1"]["identity"])
    forged = tmp_path / "baseline_manifest.json"
    manifest = json.loads(Path(identity_dict["frozen_manifest"]).read_text())
    manifest["files"] = manifest["files"][:-1]
    forged.write_text(json.dumps(manifest, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest"] = str(forged)
    try:
        with pytest.raises(identity.DIdentityError) as excinfo:
            identity.verify_d_candidate_identity()
    finally:
        spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest"] = identity_dict["frozen_manifest"]
    assert "A2 manifest bytes differ from the registered trust root" in str(excinfo.value)


def test_a_registered_digest_that_disagrees_with_the_manifest_is_refused(monkeypatch):
    monkeypatch.setitem(
        spec.ARM_SPECS["arm1"]["identity"], "frozen_manifest_digest", "0" * 64
    )
    with pytest.raises(identity.DIdentityError) as excinfo:
        identity.verify_d_candidate_identity()
    assert "self digest does not match the registered digest" in str(excinfo.value)


def test_a_registered_manifest_without_pinned_bytes_is_refused(monkeypatch):
    monkeypatch.setitem(spec.ARM_SPECS["arm1"]["identity"], "frozen_manifest_file_sha256", None)
    with pytest.raises(identity.DIdentityError) as excinfo:
        identity.verify_d_candidate_identity()
    assert "does not pin the A2 manifest bytes" in str(excinfo.value)


@pytest.mark.parametrize("field", ["tensors_sha256", "manifest_sha256", "metadata_sha256"])
def test_each_registered_checkpoint_field_is_compared_not_assumed(monkeypatch, field):
    monkeypatch.setitem(spec.ARM_SPECS["arm1"]["identity"], field, "f" * 64)
    with pytest.raises(identity.DIdentityError) as excinfo:
        identity.verify_d_candidate_identity()
    assert field in str(excinfo.value)


def test_a_manifest_without_the_pilot_directory_is_refused(monkeypatch):
    monkeypatch.setitem(spec.ARM_SPECS["arm1"]["identity"], "pilot_dir", "artifacts/pilot/absent")
    with pytest.raises(identity.DIdentityError) as excinfo:
        identity.verify_d_candidate_identity()
    assert "no entry for the D candidate pilot directory" in str(excinfo.value)


def test_a_changed_pinned_file_is_refused(tmp_path, monkeypatch):
    """A single flipped byte under the pinned tree is caught by the file walk."""
    source = Path(spec.REPO_ROOT)
    identity_dict = spec.ARM_SPECS["arm1"]["identity"]
    target = tmp_path / "repo"
    pilot_rel = identity_dict["pilot_dir"]
    import shutil

    shutil.copytree(source / pilot_rel, target / pilot_rel)
    manifest = json.loads(Path(identity_dict["frozen_manifest"]).read_text())
    victim = next(
        row["path"] for row in manifest["files"]
        if row["path"].startswith(f"{pilot_rel}/checkpoints/") and row["path"].endswith("metadata.json")
    )
    path = target / victim
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(identity.DIdentityError) as excinfo:
        identity.verify_d_candidate_identity(repo_root=target)
    assert "A2-pinned file changed" in str(excinfo.value)


# --- F6: the frozen source identity carries the implementation ------------
def test_the_frozen_document_binds_the_generic_lifecycle_and_d_loaders():
    document = prereg.build_frozen(
        prereg.build_draft(data_identity=FAKE_IDENTITY, parameter_counts=FAKE_COUNTS),
        smoke=frozen_document()["timing"]["smoke"],
        data_identity=FAKE_IDENTITY,
        created_unix=1_000.0,
    )
    bound = json.dumps(document)
    for rel in prereg.IMPLEMENTATION_SOURCES:
        assert rel in bound, f"{rel} is not bound by the frozen document"
    state = prereg.source_binding_state(document)
    assert state["status"] == "passed", state.get("mismatches")


# --- F7: the CPU identity path is MLX-free --------------------------------
def test_importing_the_identity_and_worker_modules_does_not_load_mlx():
    script = (
        "import sys, json;"
        "from ainerzero.v9.experiments.s1 import identity, worker;"
        "print(json.dumps({'mlx': 'mlx' in sys.modules,"
        "'arms': any(m.endswith('.arms') for m in sys.modules)}))"
    )
    env = {
        "PYTHONPATH": str(Path(spec.REPO_ROOT) / "src"),
        "PATH": "/usr/bin:/bin",
    }
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, cwd=str(spec.REPO_ROOT)
    )
    assert out.returncode == 0, out.stderr
    state = json.loads(out.stdout)
    assert state == {"mlx": False, "arms": False}, (
        "the identity/CPU entry path must not import the MLX runtime"
    )
