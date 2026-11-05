"""Storage-layout tests (level-1 notice #297).

The formal ledger is ``artifacts/v9/s1/phase1/``, datasets live in
``artifacts/v9/s1/datasets/<dataset_digest>/`` and ``reports/`` keeps manifests
and SHA256 only.  These tests pin the split and the fail-closed resolution of the
dataset reference.
"""

from __future__ import annotations

import json

import pytest

from ainerzero.v9.experiments.s1 import data, prereg, spec

from s1_testkit import FAKE_COUNTS, FAKE_IDENTITY, make_plan, write_staging


@pytest.fixture
def published(tmp_path, monkeypatch):
    """Publish a synthetic dataset into a temporary datasets root."""
    monkeypatch.setattr(spec, "DATASETS_DIR", tmp_path / "artifacts" / "v9" / "s1" / "datasets")
    plan = make_plan()
    staging = tmp_path / "staging"
    write_staging(staging, plan=plan)
    staged = tmp_path / "staged" / "dataset"
    manifest = data.finalize_dataset(
        staging, staged, plan=plan, generation_seconds=12.5, generation_command=["synthetic"]
    )
    dataset_dir = data.publish_dataset(staged, manifest["dataset_digest"])
    output_root = tmp_path / "artifacts" / "v9" / "s1" / "phase1"
    output_root.mkdir(parents=True)
    ref_path = data.write_dataset_ref(output_root, manifest, dataset_dir)
    return {"manifest": manifest, "dataset_dir": dataset_dir, "output_root": output_root, "ref": ref_path}


def test_dataset_is_published_under_its_digest(published):
    manifest = published["manifest"]
    dataset_dir = published["dataset_dir"]
    assert dataset_dir == spec.DATASETS_DIR / manifest["dataset_digest"]
    assert dataset_dir.name == manifest["dataset_digest"]
    assert data.verify_dataset(dataset_dir, expected_digest=manifest["dataset_digest"])
    assert not (published["output_root"] / "dataset").exists()


def test_dataset_ref_points_at_the_published_directory(published):
    ref = json.loads(published["ref"].read_text(encoding="utf-8"))
    assert ref["schema"] == "ainerzero.v9.s1.dataset_ref.v1"
    assert ref["dataset_digest"] == published["manifest"]["dataset_digest"]
    assert "artifacts/v9/s1/datasets/" in ref["dataset_dir"]
    assert ref["manifest_sha256"]
    resolved = data.resolve_dataset_dir(published["output_root"])
    assert resolved == published["dataset_dir"]


def test_resolve_refuses_a_missing_reference(tmp_path):
    with pytest.raises(data.DatasetError):
        data.resolve_dataset_dir(tmp_path / "empty-root")


def test_resolve_refuses_a_swapped_or_edited_dataset(published):
    ref_path = published["ref"]
    original = json.loads(ref_path.read_text(encoding="utf-8"))

    swapped = dict(original, dataset_dir=str(published["dataset_dir"].parent / ("0" * 64)))
    ref_path.write_text(json.dumps(swapped), encoding="utf-8")
    with pytest.raises(data.DatasetError):
        data.resolve_dataset_dir(published["output_root"])

    wrong_sha = dict(original, manifest_sha256="0" * 64)
    ref_path.write_text(json.dumps(wrong_sha), encoding="utf-8")
    with pytest.raises(data.DatasetError):
        data.resolve_dataset_dir(published["output_root"])

    ref_path.write_text(json.dumps(original), encoding="utf-8")
    assert data.resolve_dataset_dir(published["output_root"]) == published["dataset_dir"]


def test_publish_refuses_to_overwrite_a_different_dataset(published, tmp_path):
    # Publishing the same verified dataset again is idempotent...
    staged = tmp_path / "again" / "dataset"
    plan = make_plan()
    write_staging(tmp_path / "staging2", plan=plan)
    manifest = data.finalize_dataset(
        tmp_path / "staging2",
        staged,
        plan=plan,
        generation_seconds=12.5,
        generation_command=["synthetic"],
    )
    assert manifest["dataset_digest"] == published["manifest"]["dataset_digest"]
    assert data.publish_dataset(staged, manifest["dataset_digest"]) == published["dataset_dir"]


def test_prereg_commands_point_at_the_artifacts_ledger():
    draft = prereg.build_draft(data_identity=FAKE_IDENTITY, parameter_counts=FAKE_COUNTS)
    for name, command in draft["commands"].items():
        assert "reports/V9-P9" not in command, f"{name} still writes into reports/"
    assert "artifacts/v9/s1/phase1" in draft["commands"]["generate_data"]
    assert draft["storage"]["ledger_output_root"] == "artifacts/v9/s1/phase1/"
    assert draft["storage"]["datasets"] == "artifacts/v9/s1/datasets/<dataset_digest>/"
    assert spec.PHASE1_ROOT == spec.REPO_ROOT / "artifacts" / "v9" / "s1" / "phase1"
    assert spec.DATASETS_DIR == spec.REPO_ROOT / "artifacts" / "v9" / "s1" / "datasets"


def test_approval_rule_is_part_of_the_frozen_document():
    draft = prereg.build_draft(data_identity=FAKE_IDENTITY, parameter_counts=FAKE_COUNTS)
    rule = draft["approval_rule"]
    assert rule["credential"].endswith(prereg.APPROVAL_TEMPLATE)
    assert "informational only" in rule["status_field"]


def test_source_binding_is_rehashed_and_drift_is_fatal(tmp_path, monkeypatch):
    """A frozen document that binds other code than the code on disk must not verify."""
    from ainerzero.v9.experiments.s1 import commands

    from s1_testkit import frozen_document, write_frozen

    document = frozen_document()
    bound = document["source_identity"]["package_files"]
    assert "src/ainerzero/v9/experiments/s1/spec.py" in bound
    # The freshly built document binds exactly the files on disk.
    assert commands._source_binding_state(document)["status"] == "passed"

    document["source_identity"]["package_files"]["src/ainerzero/v9/experiments/s1/spec.py"] = "0" * 64
    drifted = commands._source_binding_state(document)
    assert drifted["status"] == "failed"
    assert drifted["files"]["src/ainerzero/v9/experiments/s1/spec.py"]["match"] is False

    # verify must fail closed (not report a clean pass) on that drift.
    path, _digest, document = write_frozen(tmp_path / "pre_registration.json", document=document)
    monkeypatch.setattr(commands.data, "resolve_dataset_dir", lambda root: tmp_path)
    monkeypatch.setattr(commands.data, "verify_dataset", lambda dataset_dir: {"dataset_digest": "a" * 64})
    report = commands.mode_verify(
        type("A", (), {"output_root": tmp_path, "limits_file": None, "prereg": path,
                       "research_log": None, "wall_budget_seconds": None})()
    )
    assert report["status"] == "failed"
    assert report["stage"] == "source_binding_drift"
