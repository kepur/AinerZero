"""S1 preregistration build/freeze/verify tests (pure CPU, synthetic measurements)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from ainerzero.v9.experiments.s1 import commands, data, prereg, spec

FAKE_COUNTS = {"arm1": 393_232, "arm2": 207_519, "arm3": 159_455, "arm4": 274_031}
FAKE_IDENTITY = {
    "schema": "ainerzero.v9.s1.dataset_manifest.v1",
    "dataset_digest": "a" * 64,
    "plan": {
        "train": {"worlds": 2_000, "rounds_per_world": 1},
        "development": {"worlds": 200, "rounds_per_world": 1},
        "partitions": ["train", "development"],
        "final_partition": "not_generated_not_read",
        "generator_seed": "awz-v9-b3-v0",
    },
    "counts": {"train_packets": 9_500, "development_packets": 950},
    "source_identity": {"source_map_digest": "b" * 64},
    "episode_count": 2_200,
    "generation_seconds": 61.5,
}


def _smoke(step_seconds: float = 0.01) -> dict:
    return {
        "schema": "ainerzero.v9.s1.smoke.v1",
        "no_update": True,
        "gradients_computed": False,
        "updated_parameters": False,
        "parameters_unchanged": True,
        "batch_size": 16,
        "repeats": 5,
        "dataset": {"dataset_digest": FAKE_IDENTITY["dataset_digest"], "train_windows": 5_500},
        "trainable_arms": {
            arm_id: {
                "forward_loss_step_seconds": step_seconds,
                "parameter_count": FAKE_COUNTS[arm_id],
                "parameters_unchanged": True,
                "loss": 1.0,
                "parameter_sha256_before": "c" * 64,
                "parameter_sha256_after": "c" * 64,
                "peak_mlx_gib": 0.1,
            }
            for arm_id in ("arm2", "arm3", "arm4")
        },
        "d_candidate": {
            "forward_loss_step_seconds": step_seconds,
            "parameter_count": FAKE_COUNTS["arm1"],
            "parameters_unchanged": True,
            "loss": 1.0,
            "peak_mlx_gib": 0.1,
        },
        "peak_process_rss_gib": 1.2,
        "peak_mlx_gib": 0.1,
        "data_generation_seconds": 61.5,
        "measurement_note": "synthetic fixture",
    }


def _draft() -> dict:
    return prereg.build_draft(data_identity=FAKE_IDENTITY, parameter_counts=FAKE_COUNTS)


def _frozen(**kwargs) -> dict:
    smoke = kwargs.pop("smoke", None) or _smoke()
    return prereg.build_frozen(_draft(), smoke=smoke, data_identity=FAKE_IDENTITY, created_unix=1_000.0)


def test_draft_contains_four_arms_and_frozen_limits():
    draft = _draft()
    assert set(draft["arms"]) == {"arm1", "arm2", "arm3", "arm4"}
    assert draft["status"] == prereg.STATUS_DRAFT
    assert draft["arms"]["arm1"]["kind"] == "frozen_candidate"
    assert draft["arms"]["arm1"]["training_updates"] == 0
    assert draft["arms"]["arm2"]["training_updates"] is None
    assert draft["arms"]["arm1"]["incomparable"]
    for arm_id in ("arm2", "arm3", "arm4"):
        assert draft["arms"][arm_id]["kind"] == "trainable"
        assert list(draft["arms"][arm_id]["seeds"]) == [0, 1, 2]
    assert draft["resource_limits"] == spec.RESOURCE_LIMITS
    assert draft["data_identity"]["plan"]["final_partition"] == "not_generated_not_read"


def test_budget_rule_deadline_and_supervision():
    step = 0.01
    budget = prereg.estimate_budget(_smoke(step_seconds=step))
    update_cost = 3.0 * step
    # r11: the registered eval_batches is 175 (5 checkpoints x 35 window
    # batches); the derivation rule itself is unchanged.
    eval_cost = spec.TIMING["eval_batches"] * step * 5
    expected = int((360.0 * 0.25 / 1.2 - eval_cost) / update_cost)
    expected = max(spec.TRAIN_COMMON["updates_min"], min(spec.TRAIN_COMMON["updates_cap"], expected))
    assert budget["updates"] == expected
    assert budget["deadline_seconds"] == math.ceil(budget["estimate_seconds"] * 1.25)
    assert budget["supervision_seconds"] == budget["deadline_seconds"] + 50
    assert budget["fits_per_run_cap"] is True
    assert budget["fits_phase_cap"] is True
    assert budget["phase_wall_headroom_seconds"] > 0
    # The phase total is nine training deadlines + the one D-candidate deadline + data generation.
    recomputed = 9 * budget["deadline_seconds"] + budget["arm1_deadline_seconds"] + 61.5
    assert budget["phase_wall_seconds"] == pytest.approx(recomputed)


def test_budget_rule_shrinks_updates_to_fit_the_run_cap(monkeypatch):
    """The shrink loop is the defensive branch of the frozen rule.

    The target budget normally keeps the estimate near 360 s, so the derived
    deadline never reaches the 1200 s per-run cap; enlarging the target makes
    the derived deadline exceed it and forces the loop to cut the update count.
    """
    monkeypatch.setitem(spec.TRAIN_COMMON, "target_estimate_seconds", 5_000.0)
    budget = prereg.estimate_budget(_smoke(step_seconds=0.02))
    assert budget["updates"] < spec.TRAIN_COMMON["updates_cap"]
    assert budget["deadline_seconds"] <= spec.TIMING["per_run_wall_max_seconds"]


def test_impossible_measured_cost_is_refused_not_relaxed():
    with pytest.raises(ValueError):
        prereg.estimate_budget(_smoke(step_seconds=5.0))


def test_frozen_file_passes_validation_and_records_equal_budgets():
    frozen = _frozen()
    assert frozen["status"] == prereg.STATUS_FROZEN
    assert prereg.validate(frozen) == []
    updates = frozen["training_protocol"]["updates"]
    for arm_id in ("arm2", "arm3", "arm4"):
        assert frozen["arms"][arm_id]["training_updates"] == updates
    assert frozen["timing"]["deadline_seconds"] == math.ceil(
        frozen["timing"]["estimate_seconds"] * 1.25
    )
    assert frozen["timing"]["supervision_seconds"] == frozen["timing"]["deadline_seconds"] + 50
    assert frozen["timing"]["phase_wall_seconds"] <= spec.TIMING["phase_wall_max_seconds"]
    assert frozen["timing"]["smoke"]["parameters_unchanged"] is True
    for row in frozen["arms"].values():
        assert 100_000 <= row["parameter_count"] <= 2_000_000
    assert frozen["final_partition"] if "final_partition" in frozen else True


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda doc: doc["timing"].update({"deadline_seconds": doc["timing"]["deadline_seconds"] + 1}), "deadline"),
        (lambda doc: doc["timing"].update({"supervision_seconds": 1.0}), "supervision"),
        (lambda doc: doc["arms"]["arm3"].update({"training_updates": 1}), "training budget"),
        (lambda doc: doc["arms"]["arm2"].update({"parameter_count": 50_000}), "0.1M-2M"),
        (lambda doc: doc["arms"]["arm1"].update({"training_updates": 5}), "arm1"),
        (lambda doc: doc["resource_limits"].update({"process_memory_gib": 16.0}), "resource limit"),
        (lambda doc: doc["data_identity"]["plan"].update({"train": {"worlds": 2_001, "rounds_per_world": 1}}), "train world count"),
        (lambda doc: doc["data_identity"]["plan"].update({"final_partition": "generated"}), "final"),
        (lambda doc: doc["training_protocol"].update({"updates": None}), "updates"),
        (lambda doc: doc["timing"]["smoke"].update({"parameters_unchanged": False}), "unchanged"),
    ],
)
def test_validation_catches_tampering(mutate, needle):
    frozen = _frozen()
    mutate(frozen)
    reasons = prereg.validate(frozen)
    assert reasons, "mutation was not caught"
    assert any(needle in reason for reason in reasons), reasons


def test_frozen_file_sha_roundtrip_and_tamper(tmp_path):
    frozen = _frozen()
    path = tmp_path / "pre_registration.json"
    path.write_text(json.dumps(frozen, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    digest = prereg.document_sha256(frozen)
    prereg.write_sha256_file(path, digest)
    verified = prereg.verify_frozen_file(path)
    assert verified["sha256"] == digest
    # Broken control: any byte change makes the checksum fail closed.
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["timing"]["deadline_seconds"] += 1
    path.write_text(json.dumps(tampered, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        prereg.verify_frozen_file(path)
    path.write_text(json.dumps(frozen, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        # The companion checksum still points at the mutated document digest.
        path.with_suffix(".json.sha256").write_text("0" * 64 + "  pre_registration.json\n")
        prereg.verify_frozen_file(path)


def test_freeze_file_is_deterministic_for_fixed_created_unix(tmp_path):
    first = _frozen()
    second = _frozen()
    assert prereg.document_sha256(first) == prereg.document_sha256(second)


def test_train_mode_is_refused_without_coordinator_approval(tmp_path, monkeypatch, canonical_root):
    frozen = _frozen()
    assert frozen["status"] == prereg.STATUS_FROZEN  # not approved
    path = tmp_path / "pre_registration.json"
    path.write_text(json.dumps(frozen, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    prereg.write_sha256_file(path, prereg.document_sha256(frozen))
    # A temporary research log with no approval line: the real log is never read here.
    # train reads spec.RESEARCH_LOG only, so the temporary log is installed there.
    log = tmp_path / "RESEARCH_LOG.md"
    log.write_text("## R20261021-P1-stageA-budget\n\n- 无批准行。\n", encoding="utf-8")
    monkeypatch.setattr(spec, "RESEARCH_LOG", log)
    report = commands.mode_train(
        SimpleNamespace(
            output_root=canonical_root,
            prereg=path,
            limits_file=None,
            wall_budget_seconds=None,
            research_log=None,
        )
    )
    assert report["status"] == "refused"
    assert report["stage"] == "preregistration_not_approved"
    assert report["preregistration_sha256"] == prereg.document_sha256(frozen)
    assert report["approval"]["approved"] is False
    assert "approval line" in report["message"]


def _freeze_root(tmp_path, *, record_step: float, local_step: float):
    """A run root with a draft plus two smoke measurements (record + recheck)."""
    from s1_testkit import fake_smoke

    draft = _draft()
    (tmp_path / "draft_preregistration.json").write_text(
        json.dumps(draft, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    record = tmp_path / "record_smoke.json"
    record.write_text(json.dumps(fake_smoke(record_step)), encoding="utf-8")
    (tmp_path / "smoke_metrics.json").write_text(
        json.dumps(fake_smoke(local_step)), encoding="utf-8"
    )
    return record


def test_freeze_records_the_measurement_of_record_and_the_recheck(tmp_path, monkeypatch):
    record = _freeze_root(tmp_path, record_step=0.01, local_step=0.005)
    monkeypatch.setattr(commands.data, "resolve_dataset_dir", lambda root: tmp_path / "dataset")
    monkeypatch.setattr(commands.data, "load_manifest", lambda dataset_dir: FAKE_IDENTITY)
    monkeypatch.setattr(commands.data, "dataset_identity", lambda manifest: FAKE_IDENTITY)
    report = commands._freeze(tmp_path, spec.RESOURCE_LIMITS, smoke_path=record)
    assert report["status"] == "completed", report
    frozen = json.loads((tmp_path / "pre_registration.json").read_text(encoding="utf-8"))
    assert frozen["timing"]["smoke_source"]["sha256"] == spec.sha256_file(record)
    assert frozen["timing"]["smoke_source"]["in_run_root"] is False
    assert frozen["training_protocol"]["updates"] == prereg.estimate_budget(
        json.loads(record.read_text())
    )["updates"]
    # The faster re-check would derive more updates; it is recorded, not applied.
    recheck = frozen["timing"]["smoke_recheck"]
    assert recheck["usable"] is True
    assert recheck["derived_updates_if_recheck_used"] > frozen["training_protocol"]["updates"]
    assert prereg.validate(frozen) == []
    assert prereg.verify_frozen_file(tmp_path / "pre_registration.json")["sha256"] == report["preregistration_sha256"]


def test_freeze_keeps_the_budget_when_the_recheck_is_the_same_file(tmp_path, monkeypatch):
    record = _freeze_root(tmp_path, record_step=0.01, local_step=0.01)
    monkeypatch.setattr(commands.data, "resolve_dataset_dir", lambda root: tmp_path / "dataset")
    monkeypatch.setattr(commands.data, "load_manifest", lambda dataset_dir: FAKE_IDENTITY)
    monkeypatch.setattr(commands.data, "dataset_identity", lambda manifest: FAKE_IDENTITY)
    commands._freeze(tmp_path, spec.RESOURCE_LIMITS)
    frozen = json.loads((tmp_path / "pre_registration.json").read_text(encoding="utf-8"))
    assert "smoke_recheck" not in frozen["timing"]
    assert frozen["timing"]["smoke_source"]["in_run_root"] is True


def test_freeze_refuses_a_smoke_file_that_claims_an_update(tmp_path, monkeypatch):
    from s1_testkit import fake_smoke

    record = _freeze_root(tmp_path, record_step=0.01, local_step=0.01)
    bad = fake_smoke(0.01)
    bad["parameters_unchanged"] = False
    record.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(commands.data, "resolve_dataset_dir", lambda root: tmp_path / "dataset")
    monkeypatch.setattr(commands.data, "load_manifest", lambda dataset_dir: FAKE_IDENTITY)
    monkeypatch.setattr(commands.data, "dataset_identity", lambda manifest: FAKE_IDENTITY)
    with pytest.raises(ValueError):
        commands._freeze(tmp_path, spec.RESOURCE_LIMITS, smoke_path=record)
