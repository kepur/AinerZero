"""Unit tests for E1 data generation runner (ainerzero.V9.P75).

Specifications:
- Real Blender smoke generation: <= 120s wall-clock time across 6 sequences (P/S x train/dev/final).
- Student side passes strict leakage guard (assert_no_leakage).
- Both P and S final partitions sealed and readable only once via open_sealed_final_once.
- Evaluator side contains mechanisms and S <-> P pairing.
- Raw sequences contain hidden_params_builder matching AWZ _pure_hidden.py SHA256.
- Budget <= 0 or past deadline immediately returns stopped without calling subprocess.
- AWZ subprocess failure raises RuntimeError without leaving half-finished datasets.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import time
from typing import Any

import pytest

from ainerzero.v9.experiments.e1 import prereg, spec
from ainerzero.v9.experiments.e1.data_runner import (
    DEFAULT_AWZ_PYTHON,
    DEFAULT_AWZ_ROOT,
    DatasetIdentityError,
    generate_and_export,
    normalize_counts,
    run_awz_generator_subprocess,
    verify_dataset_generator_identity,
)
from ainerzero.v9.experiments.e1.export import (
    FinalPartitionSealed,
    assert_no_leakage,
    open_sealed_final_once,
    verify_sealed_final,
)

pytestmark = pytest.mark.native_mlx(reason="real MLX import at collection via the e1 package (arms_net) (A39)")


# =========================================================================
# 1. Real Blender Smoke Test (<= 120s)
# =========================================================================

def test_blender_smoke_generation_and_export(tmp_path: Path):
    """Run real Blender smoke test generating 1 sequence per partition for P and S."""
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data"

    counts = {
        "P": {"train": 1, "development": 1, "final": 1},
        "S": {"train": 1, "development": 1, "final": 1},
    }

    t0 = time.time()
    res = generate_and_export(
        counts,
        raw_dir,
        data_dir,
        wall_budget_s=120.0,
        awz_root=DEFAULT_AWZ_ROOT,
        awz_python=DEFAULT_AWZ_PYTHON,
    )
    smoke_wall_clock_s = time.time() - t0

    print(f"\n[Blender Smoke] Completed in {smoke_wall_clock_s:.2f}s (budget <= 120.0s)")
    assert smoke_wall_clock_s <= 120.0, f"Blender smoke exceeded budget: {smoke_wall_clock_s:.2f}s > 120.0s"
    assert res["status"] == "completed"

    # 1. Verify export counts
    exp_counts = res["exported_counts"]
    assert exp_counts["P_train"] == 1
    assert exp_counts["P_development"] == 1
    assert exp_counts["P_final"] == 1
    assert exp_counts["S_train"] == 1
    assert exp_counts["S_development"] == 1
    assert exp_counts["S_final"] == 1

    # 2. Verify raw sequences contain builder SHA matching AWZ _pure_hidden.py
    awz_hidden_file = DEFAULT_AWZ_ROOT / "python" / "animeworld" / "e0" / "_pure_hidden.py"
    assert awz_hidden_file.is_file(), f"_pure_hidden.py missing at {awz_hidden_file}"
    expected_builder_sha = hashlib.sha256(awz_hidden_file.read_bytes()).hexdigest()

    raw_files = list(raw_dir.rglob("*.json"))
    sequence_files = [f for f in raw_files if f.name != "manifest.json"]
    assert len(sequence_files) == 6, f"Expected 6 raw sequence files, found {len(sequence_files)}"

    for sf in sequence_files:
        data = json.loads(sf.read_text(encoding="utf-8"))
        builder_info = data.get("metadata", {}).get("hidden_params_builder")
        assert builder_info is not None, f"Raw sequence {sf.name} missing hidden_params_builder"
        assert builder_info["sha256"] == expected_builder_sha, (
            f"Builder SHA mismatch in {sf.name}: {builder_info['sha256']} != {expected_builder_sha}"
        )

    # 3. Verify student side passes leakage guard and no unsealed final files exist
    student_dir = data_dir / "student"
    evaluator_dir = data_dir / "evaluator"

    for fam in ("P", "S"):
        # Train & development student views
        for part in ("train", "development"):
            part_files = list((student_dir / fam / part).glob("*.json"))
            assert len(part_files) == 1
            s_content = json.loads(part_files[0].read_text(encoding="utf-8"))
            assert_no_leakage(s_content)

        # Unsealed final directories must NOT exist
        assert not (student_dir / fam / "final").exists()
        assert not (evaluator_dir / fam / "final").exists()

    # 4. Verify S-family evaluator views contain mechanisms and S <-> P pairing
    for part in ("train", "development"):
        p_student_file = list((student_dir / "P" / part).glob("*.json"))[0]
        p_student_id = json.loads(p_student_file.read_text(encoding="utf-8"))["sequence_id"]

        s_eval_file = list((evaluator_dir / "S" / part).glob("*.json"))[0]
        s_eval_data = json.loads(s_eval_file.read_text(encoding="utf-8"))

        assert "mechanisms" in s_eval_data
        assert len(s_eval_data["mechanisms"]) > 0
        assert s_eval_data["mechanisms"][0]["id"] == "quadratic_drag_v1"
        assert s_eval_data["paired_p_opaque_id"] == p_student_id

    # 5. Verify both P and S final partitions are sealed under sealed_final/<fam>/<digest>
    sealed_info = res["sealed_final"]
    assert "P" in sealed_info, "P family final partition must be sealed"
    assert "S" in sealed_info, "S family final partition must be sealed"

    for fam in ("P", "S"):
        fam_sealed = sealed_info[fam]
        sealed_dir = Path(fam_sealed["sealed_dir"])
        digest = fam_sealed["dataset_digest"]

        # Verify integrity
        v_res = verify_sealed_final(sealed_dir, expected_digest=digest)
        assert v_res["status"] == "passed"
        assert not v_res["already_read"]

        # First read succeeds
        token = open_sealed_final_once(
            sealed_dir,
            expected_digest=digest,
            reader={"purpose": f"smoke_test_verify_{fam}"},
        )
        assert token.dataset_digest == digest

        # Second read raises FinalPartitionSealed
        with pytest.raises(FinalPartitionSealed):
            open_sealed_final_once(
                sealed_dir,
                expected_digest=digest,
                reader={"purpose": "second_read_attempt"},
            )


# =========================================================================
# 2. Budget and Deadline Fail-Closed Tests
# =========================================================================

def test_zero_budget_immediately_stopped_without_calling_subprocess(tmp_path: Path):
    """Verify generate_and_export with budget <= 0 immediately stops without calling runner."""
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data"

    called = False

    def mock_runner(raw_path: Path, norm_counts: Any):
        nonlocal called
        called = True
        pytest.fail("Generator runner must NOT be called when budget <= 0")

    res = generate_and_export(
        {"train": 1},
        raw_dir,
        data_dir,
        wall_budget_s=0.0,
        runner_fn=mock_runner,
    )

    assert not called
    assert res["status"] == "stopped"
    assert "budget" in res["reason"]


def test_past_deadline_immediately_stopped_without_calling_subprocess(tmp_path: Path):
    """Verify generate_and_export past deadline immediately stops without calling runner."""
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data"

    called = False

    def mock_runner(raw_path: Path, norm_counts: Any):
        nonlocal called
        called = True
        pytest.fail("Generator runner must NOT be called when past deadline")

    res = generate_and_export(
        {"train": 1},
        raw_dir,
        data_dir,
        wall_budget_s=100.0,
        deadline=50.0,
        clock=lambda: 60.0,  # current time is past deadline
        runner_fn=mock_runner,
    )

    assert not called
    assert res["status"] == "stopped"
    assert "deadline" in res["reason"]


# =========================================================================
# 3. Subprocess Failure and Error Handling
# =========================================================================

def test_generator_subprocess_failure_raises_error(tmp_path: Path):
    """Verify that a generator subprocess failure raises RuntimeError without half-finished data."""
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data"

    def failing_runner(raw_path: Path, norm_counts: Any):
        raise RuntimeError("Simulation failed with non-zero exit code: 1")

    with pytest.raises(RuntimeError, match="Simulation failed"):
        generate_and_export(
            {"train": 1},
            raw_dir,
            data_dir,
            wall_budget_s=60.0,
            runner_fn=failing_runner,
        )

    # Verify no student or evaluator files were created
    assert not (data_dir / "student").exists()
    assert not (data_dir / "evaluator").exists()
    assert not (data_dir / "sealed_final").exists()


# =========================================================================
# 4. Generator Identity & Velocity Injection Verification Tests (r2)
# =========================================================================

def _make_dummy_raw_sequence(
    seq_id: str,
    partition: str,
    family: str,
    velocity_injection: str | None = spec.REQUIRED_VELOCITY_INJECTION,
    top_level_injection_only: bool = False,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "fps": 60,
        "total_frames": 10,
        "hidden_params_side": "world",
        "hidden_params_builder": {"sha256": "fake_sha"},
        "hidden_parameters": {"obj": {"mass": 1.0}},
    }
    if top_level_injection_only:
        meta["velocity_injection"] = velocity_injection
    elif velocity_injection is not None:
        meta["velocity_specification"] = {
            "source": "central_diff_unrounded_2dt",
            "velocity_injection": velocity_injection,
        }
    return {
        "sequence_id": seq_id,
        "world_id": f"world_{seq_id}",
        "world_key": f"key_{seq_id}",
        "family": family,
        "partition": partition,
        "seed": 1001,
        "scenario_type": "ramp_roll",
        "metadata": meta,
        "frames": [{"tick": i, "objects": {}} for i in range(10)],
    }


def test_top_level_only_velocity_injection_raises_error(tmp_path: Path):
    """(i) Raw sequence with velocity_injection only in top-level metadata must raise error (catches forgery)."""
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data"

    def forged_runner(raw_path: Path, norm_counts: Any):
        p_dir = raw_path / "P" / "train"
        p_dir.mkdir(parents=True, exist_ok=True)
        # Only set top-level metadata, no velocity_specification
        seq = _make_dummy_raw_sequence("seq_train_000", "train", "P", top_level_injection_only=True)
        (p_dir / "seq_train_000.json").write_text(json.dumps(seq), encoding="utf-8")

    with pytest.raises(ValueError, match="missing metadata.velocity_specification.velocity_injection"):
        generate_and_export(
            {"P": {"train": 1}},
            raw_dir,
            data_dir,
            wall_budget_s=60.0,
            runner_fn=forged_runner,
        )


def test_wrong_velocity_specification_injection_raises_error(tmp_path: Path):
    """(ii) Velocity_specification value mismatch raises ValueError with filename."""
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data"

    def wrong_vel_runner(raw_path: Path, norm_counts: Any):
        p_dir = raw_path / "P" / "train"
        p_dir.mkdir(parents=True, exist_ok=True)
        seq = _make_dummy_raw_sequence("seq_train_000", "train", "P", velocity_injection="wrong_v2")
        (p_dir / "seq_train_000.json").write_text(json.dumps(seq), encoding="utf-8")

    with pytest.raises(ValueError, match="velocity_injection mismatch: observed 'wrong_v2'"):
        generate_and_export(
            {"P": {"train": 1}},
            raw_dir,
            data_dir,
            wall_budget_s=60.0,
            runner_fn=wrong_vel_runner,
        )


def test_corrupted_json_file_raises_error(tmp_path: Path):
    """(iii) Corrupted raw json file must raise ValueError and state filename."""
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data"

    def corrupted_file_runner(raw_path: Path, norm_counts: Any):
        p_dir = raw_path / "P" / "train"
        p_dir.mkdir(parents=True, exist_ok=True)
        (p_dir / "broken_seq.json").write_text("{corrupted_json: incomplete...", encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupted or unreadable raw sequence file broken_seq.json"):
        generate_and_export(
            {"P": {"train": 1}},
            raw_dir,
            data_dir,
            wall_budget_s=60.0,
            runner_fn=corrupted_file_runner,
        )


def test_generator_identity_observed_from_trajectories(tmp_path: Path):
    """(iv) generator_identity.json records observed value and count; multiple distinct injections fail."""
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data"

    def valid_runner(raw_path: Path, norm_counts: Any):
        p_dir = raw_path / "P" / "train"
        p_dir.mkdir(parents=True, exist_ok=True)
        seq = _make_dummy_raw_sequence("seq_train_000", "train", "P", velocity_injection=spec.REQUIRED_VELOCITY_INJECTION)
        (p_dir / "seq_train_000.json").write_text(json.dumps(seq), encoding="utf-8")

    res = generate_and_export(
        {"P": {"train": 1}},
        raw_dir,
        data_dir,
        wall_budget_s=60.0,
        runner_fn=valid_runner,
    )
    assert res["status"] == "completed"

    gen_id_file = data_dir / "generator_identity.json"
    assert gen_id_file.is_file()
    payload = json.loads(gen_id_file.read_text(encoding="utf-8"))
    assert payload["velocity_injection"] == spec.REQUIRED_VELOCITY_INJECTION
    assert payload["observed_sequence_count"] == 1
    assert "generator_digests" in payload

    # Build prereg document matching
    draft = prereg.build_draft()
    v_res = verify_dataset_generator_identity(data_dir, draft)
    assert v_res["status"] == "ok"

    # Mismatched digests must raise DatasetIdentityError
    bad_draft = copy.deepcopy(draft)
    bad_draft["generator_digests"] = {"mismatched": "sha"}
    with pytest.raises(DatasetIdentityError, match="generator_digests in .* mismatch"):
        verify_dataset_generator_identity(data_dir, bad_draft)


def test_differing_observed_velocity_injections_fails_generation(tmp_path: Path):
    """(iv-b) When raw trajectories have conflicting velocity injections, generation must fail."""
    raw_dir = tmp_path / "raw"
    data_dir = tmp_path / "data"

    def conflicting_runner(raw_path: Path, norm_counts: Any):
        p_dir = raw_path / "P" / "train"
        p_dir.mkdir(parents=True, exist_ok=True)
        seq1 = _make_dummy_raw_sequence("seq_train_000", "train", "P", velocity_injection=spec.REQUIRED_VELOCITY_INJECTION)
        seq2 = _make_dummy_raw_sequence("seq_train_001", "train", "P", velocity_injection="conflicting_v2")
        (p_dir / "seq_train_000.json").write_text(json.dumps(seq1), encoding="utf-8")
        (p_dir / "seq_train_001.json").write_text(json.dumps(seq2), encoding="utf-8")

    with pytest.raises(ValueError):
        generate_and_export(
            {"P": {"train": 2}},
            raw_dir,
            data_dir,
            wall_budget_s=60.0,
            runner_fn=conflicting_runner,
        )


def test_driver_script_does_not_forge_velocity_injection():
    """(v) Source inspection: AWZ driver script must not contain velocity_injection assignment."""
    from ainerzero.v9.experiments.e1.data_runner import AWZ_DRIVER_CODE
    # Ensure no assignments to velocity_injection
    assert "velocity_injection" not in AWZ_DRIVER_CODE, (
        "Driver script must not contain any reference or assignment to velocity_injection"
    )

