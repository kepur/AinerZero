"""Tests for E1 Phase 2 spec and prereg modules (ainerzero.V9.P71).

Verifies:
1. Frozen specification constants and anchor fail-closed behavior.
2. Canonical JSON formatting and freeze determinism (key order independence).
3. Strict validation: schema, arm parameter counts (6150), gates, partitions, budget math.
4. Approval line scanner: exactly 1 matching line in ## R20261029-E1-approval,
   rejecting 0 lines, multiple lines, duplicate sections, fenced/quoted/indented code,
   and digest mismatches.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import pytest

from ainerzero.v9.experiments.e1 import prereg, spec


def _make_test_draft(**kwargs) -> dict[str, Any]:
    """Helper to build test draft."""
    return prereg.build_draft(**kwargs)


def test_spec_constants():
    """Verify frozen spec constants align with PREREG_DRAFT r4 candidate."""
    assert spec.SPEC_NAME == "e1-phase2-v1"
    assert spec.TASK_ID == "ainerzero.V9.P71"
    assert spec.EXPERIMENT_ID == "e1-phase2-20261029-r0"
    assert spec.PREREG_DRAFT_PATH == "reports/V9-P48/PREREG_DRAFT_r4_candidate.md"
    assert spec.PREREG_DRAFT_SHA256 == "ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e"
    assert spec.PREREG_DRAFT_SHA256_PREFIX == "ef7856e7f757"
    assert spec.PREREG_DRAFT_SHA256.startswith(spec.PREREG_DRAFT_SHA256_PREFIX)
    assert len(spec.ARM_SPECS) == 7

    # Arms 2, 3, 6 are trainable with registered net parameter count 6150
    assert spec.REGISTERED_NET_PARAMETER_COUNT == 6150
    for arm_id in spec.TRAINABLE_ARM_IDS:
        arm = spec.ARMS_BY_ID[arm_id]
        assert arm.trainable is True
        assert arm.parameter_count == 6150

    # Arm 4 is diagnostic upper bound, non-trainable, params 0
    arm4 = spec.ARMS_BY_ID[4]
    assert arm4.trainable is False
    assert arm4.parameter_count == 0
    assert arm4.tag == "diagnostic"

    # Non-trainable arms have parameter count 0
    for arm_id in spec.NON_TRAINABLE_ARM_IDS:
        arm = spec.ARMS_BY_ID[arm_id]
        assert arm.trainable is False
        assert arm.parameter_count == 0

    # Families and partitions
    assert spec.FAMILIES == ("P", "S")
    assert spec.PARTITIONS == ("train", "development", "final")
    assert spec.TRAIN_WORLDS_PER_FAMILY == 1000
    assert spec.DEV_WORLDS_PER_FAMILY == 200
    assert spec.FINAL_WORLDS_PER_FAMILY == 200
    assert spec.TOTAL_EXPERIMENT_WORLDS == 2800

    # Primary gate
    assert spec.PRIMARY_GATE_NAME == "H-E1"
    assert spec.PRIMARY_ERROR_REDUCTION_MIN == 0.10
    assert spec.COLLISION_F1_NON_DECREASING is True

    # Training step ceiling and early stopping constants (r4)
    assert spec.DEFAULT_TRAIN_STEPS == 64000
    assert spec.EARLY_STOP_EVAL_EVERY == 500
    assert spec.EARLY_STOP_PATIENCE == 10
    assert spec.VALIDATION_FRACTION == 0.1

    # Budget caps (r4 §6)
    caps = spec.BUDGET_CAPS
    assert caps["data_generation_max_seconds"] == 3600.0
    assert caps["training_duty_cycle"] == 0.25
    assert caps["train_cell_wall_max_seconds"] == 1200.0
    assert caps["train_cell_compute_max_seconds"] == 300.0
    assert caps["train_cells_count"] == 18
    assert caps["train_total_wall_max_seconds"] == 10800.0
    assert caps["dev_eval_train_cell_max_seconds"] == 180.0
    assert caps["dev_eval_nontrain_cell_max_seconds"] == 60.0
    assert caps["dev_eval_total_max_seconds"] == 1800.0
    assert caps["final_eval_max_seconds"] == 1800.0
    assert caps["phase_total_wall_ceiling_seconds"] == 18000.0  # 5 h

    # Budget components sum equality assertion (3600 + 10800 + 1800 + 1800 == 18000)
    assert (
        caps["data_generation_max_seconds"]
        + caps["train_total_wall_max_seconds"]
        + caps["dev_eval_total_max_seconds"]
        + caps["final_eval_max_seconds"]
    ) == caps["phase_total_wall_ceiling_seconds"]


def test_host_anchor():
    """Verify host anchor fail-closed state resolution."""
    state = spec.host_anchor_state()
    assert state["schema"] == spec.HOST_ANCHOR_SCHEMA
    assert state["status"] == "ok"
    assert Path(state["root"]).is_dir()
    assert Path(state["approval_log"]).is_file()

    # Anchor to non-existent dir fails closed
    bogus = spec.host_anchor_state("/tmp/nonexistent_host_anchor_dir")
    assert bogus["status"] != "ok"
    with pytest.raises(RuntimeError):
        spec.host_anchor("/tmp/nonexistent_host_anchor_dir")


def test_freeze_determinism_and_key_independence(tmp_path):
    """Verify freeze produces identical SHA256 regardless of dict insertion order."""
    draft1 = _make_test_draft(draft_time_utc="2026-10-29T12:00:00Z")
    frozen1, digest1 = prereg.freeze(draft1)

    # Reverse key order in draft
    reversed_keys = list(draft1.keys())[::-1]
    draft2 = {k: draft1[k] for k in reversed_keys}
    frozen2, digest2 = prereg.freeze(draft2)

    assert digest1 == digest2
    assert prereg.canonical_bytes(frozen1) == prereg.canonical_bytes(frozen2)

    # Mutating a valid field (e.g. created_utc) must change the SHA256
    draft3 = copy.deepcopy(draft1)
    draft3["created_utc"] = "2026-10-30T00:00:00Z"
    _, digest3 = prereg.freeze(draft3)
    assert digest3 != digest1


def test_freeze_writes_file_and_sha256(tmp_path):
    """Verify freeze writes canonical json and companion .sha256 file."""
    draft = _make_test_draft(draft_time_utc="2026-10-29T12:00:00Z")
    out_file = tmp_path / "prereg.json"
    frozen, digest = prereg.freeze(draft, output_path=out_file)

    assert out_file.is_file()
    checksum_file = tmp_path / "prereg.json.sha256"
    assert checksum_file.is_file()

    content = out_file.read_bytes()
    assert hashlib.sha256(content).hexdigest() == digest
    assert checksum_file.read_text(encoding="utf-8") == f"{digest}  prereg.json\n"


def test_validate_rejects_schema_and_identity_mutations():
    """Verify validator catches corrupted schema or experiment identity."""
    draft = _make_test_draft(draft_time_utc="2026-10-29T12:00:00Z")

    bad_schema = copy.deepcopy(draft)
    bad_schema["schema"] = "invalid.schema.v9"
    with pytest.raises(prereg.SpecValidationError, match="Invalid schema"):
        prereg.validate(bad_schema)

    bad_spec = copy.deepcopy(draft)
    bad_spec["spec_name"] = "wrong-spec"
    with pytest.raises(prereg.SpecValidationError, match="Invalid spec_name"):
        prereg.validate(bad_spec)

    bad_exp = copy.deepcopy(draft)
    bad_exp["experiment_id"] = "e1-wrong-exp-id"
    with pytest.raises(prereg.SpecValidationError, match="Invalid experiment_id"):
        prereg.validate(bad_exp)

    bad_draft_ref = copy.deepcopy(draft)
    bad_draft_ref["prereg_draft_ref"]["sha256"] = "deadbeef1234"
    with pytest.raises(prereg.SpecValidationError, match="Draft SHA256 must start with prefix"):
        prereg.validate(bad_draft_ref)


def test_validate_rejects_arm_parameter_mismatches():
    """Verify validator strictly enforces parameter counts for all arms."""
    draft = _make_test_draft(draft_time_utc="2026-10-29T12:00:00Z")

    # Arm 2 parameter count != 6150
    bad_arm2 = copy.deepcopy(draft)
    bad_arm2["arms"][1]["parameter_count"] = 6149
    with pytest.raises(prereg.SpecValidationError, match="Trainable Arm 2 parameter count must equal"):
        prereg.validate(bad_arm2)

    # Arm 3 parameter count != 6150
    bad_arm3 = copy.deepcopy(draft)
    bad_arm3["arms"][2]["parameter_count"] = 0
    with pytest.raises(prereg.SpecValidationError, match="Trainable Arm 3 parameter count must equal"):
        prereg.validate(bad_arm3)

    # Arm 6 parameter count != 6150
    bad_arm6 = copy.deepcopy(draft)
    bad_arm6["arms"][5]["parameter_count"] = 6200
    with pytest.raises(prereg.SpecValidationError, match="Trainable Arm 6 parameter count must equal"):
        prereg.validate(bad_arm6)

    # Arm 1 (non-trainable) having parameters
    bad_arm1 = copy.deepcopy(draft)
    bad_arm1["arms"][0]["parameter_count"] = 100
    with pytest.raises(prereg.SpecValidationError, match="Non-trainable Arm 1 parameter count must be 0"):
        prereg.validate(bad_arm1)

    # Arm 4 missing diagnostic tag
    bad_arm4 = copy.deepcopy(draft)
    bad_arm4["arms"][3]["tag"] = "regular"
    with pytest.raises(prereg.SpecValidationError, match="Arm 4 must have tag 'diagnostic'"):
        prereg.validate(bad_arm4)

    # Missing arm
    fewer_arms = copy.deepcopy(draft)
    fewer_arms["arms"] = fewer_arms["arms"][:6]
    with pytest.raises(prereg.SpecValidationError, match="Expected exactly 7 arms"):
        prereg.validate(fewer_arms)


def test_validate_rejects_hypothesis_mutations():
    """Verify validator rejects loosened decision thresholds."""
    draft = _make_test_draft(draft_time_utc="2026-10-29T12:00:00Z")

    # Loosened primary error reduction
    bad_thresh = copy.deepcopy(draft)
    bad_thresh["hypotheses"]["primary_error_reduction_min"] = 0.05
    with pytest.raises(prereg.SpecValidationError, match="primary_error_reduction_min must be 0.1"):
        prereg.validate(bad_thresh)

    # Dropped collision constraint
    bad_f1 = copy.deepcopy(draft)
    bad_f1["hypotheses"]["collision_f1_non_decreasing"] = False
    with pytest.raises(prereg.SpecValidationError, match="collision_f1_non_decreasing must be True"):
        prereg.validate(bad_f1)

    # Primary k step altered
    bad_k = copy.deepcopy(draft)
    bad_k["metrics"]["eval_primary_k"] = 5
    with pytest.raises(prereg.SpecValidationError, match="eval_primary_k must be 10"):
        prereg.validate(bad_k)


def test_validate_rejects_budget_math_violations():
    """Verify validator checks budget math and ceiling."""
    draft = _make_test_draft(draft_time_utc="2026-10-29T12:00:00Z")

    # Train total wall > cells_count * cell_wall (25000 > 18 * 1200 = 21600)
    bad_train_wall_high = copy.deepcopy(draft)
    bad_train_wall_high["budget_caps"]["train_total_wall_max_seconds"] = 25000.0
    with pytest.raises(prereg.SpecValidationError, match="out of bounds"):
        prereg.validate(bad_train_wall_high)

    # Train total wall < cell_wall (1000 < 1200)
    bad_train_wall_low = copy.deepcopy(draft)
    bad_train_wall_low["budget_caps"]["train_total_wall_max_seconds"] = 1000.0
    with pytest.raises(prereg.SpecValidationError, match="out of bounds"):
        prereg.validate(bad_train_wall_low)

    # Duty cycle math: compute != wall * duty
    bad_compute = copy.deepcopy(draft)
    bad_compute["budget_caps"]["train_cell_compute_max_seconds"] = 400.0
    with pytest.raises(prereg.SpecValidationError, match="does not equal train_cell_wall_max_seconds \\* training_duty_cycle"):
        prereg.validate(bad_compute)

    # Components exceed total ceiling
    exceed_ceiling = copy.deepcopy(draft)
    exceed_ceiling["budget_caps"]["data_generation_max_seconds"] = 50000.0
    with pytest.raises(prereg.SpecValidationError, match="exceeds total ceiling"):
        prereg.validate(exceed_ceiling)

    # Negative budget cap
    neg_cap = copy.deepcopy(draft)
    neg_cap["budget_caps"]["final_eval_max_seconds"] = -10.0
    with pytest.raises(prereg.SpecValidationError, match="must be positive number"):
        prereg.validate(neg_cap)


def test_isolated_subprocess_draft_and_freeze():
    """Verify validate(build_draft()) and freeze() succeed in clean python -I subprocess (no conftest patches).

    Also verifies:
    1. In-process build_draft() matches spec and has not been monkey-patched by conftest
    2. Subprocess clean draft validate & freeze pass without patches
    3. Three negative controls in subprocess:
       - total > count * wall is rejected
       - wall > total is rejected
       - compute != wall * duty is rejected
    """
    # 0. In-process check: build_draft must not be monkey-patched by conftest
    direct_draft = prereg.build_draft()
    assert direct_draft["budget_caps"]["train_cell_wall_max_seconds"] == spec.BUDGET_CAPS["train_cell_wall_max_seconds"], (
        f"conftest patch detected! train_cell_wall_max_seconds was altered to {direct_draft['budget_caps']['train_cell_wall_max_seconds']}"
    )
    prereg.validate(direct_draft)

    import subprocess
    import sys

    code = """
import sys
sys.path.insert(0, 'src')
from ainerzero.v9.experiments.e1 import prereg, spec

# 1. Production draft validate & freeze pass without patches
draft = prereg.build_draft()
prereg.validate(draft)
frozen_doc, digest = prereg.freeze(draft)
assert len(digest) == 64
assert frozen_doc["schema"] == prereg.SCHEMA

# 2. Negative controls
import copy

# Bad control 1: total > count * wall
bad1 = copy.deepcopy(draft)
bad1["budget_caps"]["train_total_wall_max_seconds"] = 25000.0
try:
    prereg.validate(bad1)
    raise AssertionError("bad1 should have been rejected")
except prereg.SpecValidationError as e:
    assert "out of bounds" in str(e)

# Bad control 2: wall > total
bad2 = copy.deepcopy(draft)
bad2["budget_caps"]["train_total_wall_max_seconds"] = 1000.0
try:
    prereg.validate(bad2)
    raise AssertionError("bad2 should have been rejected")
except prereg.SpecValidationError as e:
    assert "out of bounds" in str(e)

# Bad control 3: compute != wall * duty
bad3 = copy.deepcopy(draft)
bad3["budget_caps"]["train_cell_compute_max_seconds"] = 400.0
try:
    prereg.validate(bad3)
    raise AssertionError("bad3 should have been rejected")
except prereg.SpecValidationError as e:
    assert "does not equal" in str(e)

print("SUBPROCESS_VERIFIED_OK")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Subprocess failed:\\nstdout: {result.stdout}\\nstderr: {result.stderr}"
    assert "SUBPROCESS_VERIFIED_OK" in result.stdout


def test_approval_line():
    """Verify approval line string formatting."""
    sha = "b3481a89d16ce794eecb4eff3c30be325b3838e546233670b479335ec8447d76"
    expected = f"APPROVED e1-phase2 prereg document_sha256={sha}"
    assert prereg.approval_line(sha) == expected


def test_find_approval_success(tmp_path):
    """Verify find_approval succeeds with single valid line inside ## R20261029-E1-approval."""
    sha = "a" * 64
    valid_log = f"""# Research Log

## R20261021-P1-stageA-budget
Some older section.

## R20261029-E1-approval
Coordinator notes:
APPROVED e1-phase2 prereg document_sha256={sha}

## Next Section
Other things.
"""
    log_file = tmp_path / "RESEARCH_LOG.md"
    log_file.write_text(valid_log, encoding="utf-8")

    res = prereg.find_approval(log_file, expected_sha256=sha)
    assert res["status"] == prereg.STATUS_APPROVED
    assert res["document_sha256"] == sha
    assert res["line_number"] == 8


def test_find_approval_rejects_missing_or_duplicate_section(tmp_path):
    """Verify find_approval rejects missing or ambiguous duplicate sections."""
    log_file = tmp_path / "RESEARCH_LOG.md"

    # Missing section
    log_file.write_text("# Research Log\n## Other Section\n", encoding="utf-8")
    with pytest.raises(prereg.ApprovalRefused, match="approval section '## R20261029-E1-approval' not found"):
        prereg.find_approval(log_file)

    # Duplicate section
    duplicate_log = """# Log
## R20261029-E1-approval
APPROVED e1-phase2 prereg document_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
## Other
## R20261029-E1-approval
APPROVED e1-phase2 prereg document_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
"""
    log_file.write_text(duplicate_log, encoding="utf-8")
    with pytest.raises(prereg.ApprovalRefused, match="multiple '## R20261029-E1-approval' sections found"):
        prereg.find_approval(log_file)


def test_find_approval_rejects_multiple_lines_in_section(tmp_path):
    """Verify find_approval refuses when multiple approval lines exist in the section."""
    sha1 = "a" * 64
    sha2 = "b" * 64
    multi_log = f"""# Log
## R20261029-E1-approval
APPROVED e1-phase2 prereg document_sha256={sha1}
APPROVED e1-phase2 prereg document_sha256={sha2}
## Next
"""
    log_file = tmp_path / "RESEARCH_LOG.md"
    log_file.write_text(multi_log, encoding="utf-8")
    with pytest.raises(prereg.ApprovalRefused, match="multiple \\(2\\) qualifying approval lines found"):
        prereg.find_approval(log_file)


def test_find_approval_rejects_digest_mismatch(tmp_path):
    """Verify find_approval refuses when digest does not match expected_sha256."""
    sha = "a" * 64
    diff_sha = "b" * 64
    log_text = f"""# Log
## R20261029-E1-approval
APPROVED e1-phase2 prereg document_sha256={sha}
"""
    log_file = tmp_path / "RESEARCH_LOG.md"
    log_file.write_text(log_text, encoding="utf-8")
    with pytest.raises(prereg.ApprovalRefused, match="document SHA256 mismatch"):
        prereg.find_approval(log_file, expected_sha256=diff_sha)


def test_find_approval_ignores_fences_blockquotes_and_indented_code(tmp_path):
    """Verify find_approval ignores code fences, blockquotes, and indented code."""
    sha = "a" * 64
    bogus = "c" * 64
    log_text = f"""# Log
## R20261029-E1-approval
Here is an example in a blockquote:
> APPROVED e1-phase2 prereg document_sha256={bogus}

And an example in a fenced block:
```
APPROVED e1-phase2 prereg document_sha256={bogus}
```

And in indented code:
    APPROVED e1-phase2 prereg document_sha256={bogus}

Actual approval:
APPROVED e1-phase2 prereg document_sha256={sha}
"""
    log_file = tmp_path / "RESEARCH_LOG.md"
    log_file.write_text(log_text, encoding="utf-8")

    res = prereg.find_approval(log_file, expected_sha256=sha)
    assert res["document_sha256"] == sha
    assert res["line_number"] == 15

    # If the real line is omitted and only fences/quotes exist, it must raise ApprovalRefused
    no_real_line = f"""# Log
## R20261029-E1-approval
> APPROVED e1-phase2 prereg document_sha256={bogus}
```
APPROVED e1-phase2 prereg document_sha256={bogus}
```
    APPROVED e1-phase2 prereg document_sha256={bogus}
"""
    log_file.write_text(no_real_line, encoding="utf-8")
    with pytest.raises(prereg.ApprovalRefused, match="no qualifying approval line found"):
        prereg.find_approval(log_file)


def test_implementation_sources_exact_match():
    """Verify that spec.IMPLEMENTATION_SOURCES exactly matches all .py files in e1 directory."""
    e1_dir = Path(spec.REPO_ROOT) / "src" / "ainerzero" / "v9" / "experiments" / "e1"
    disk_files = {
        p.relative_to(spec.REPO_ROOT).as_posix()
        for p in e1_dir.glob("*.py")
    }
    declared_files = set(spec.IMPLEMENTATION_SOURCES)
    assert declared_files == disk_files, (
        f"Mismatch between spec.IMPLEMENTATION_SOURCES and files on disk: "
        f"extra={declared_files - disk_files}, missing={disk_files - declared_files}"
    )
    # Also verify it is strictly sorted alphabetically
    assert list(spec.IMPLEMENTATION_SOURCES) == sorted(spec.IMPLEMENTATION_SOURCES)


def test_collect_source_digests_missing_file_raises_error(tmp_path):
    """Verify collect_source_digests raises FileNotFoundError when a file is missing."""
    with pytest.raises(FileNotFoundError, match="Implementation source file missing"):
        prereg.collect_source_digests(tmp_path)


def test_collect_generator_digests_missing_file_raises_error(tmp_path):
    """Verify collect_generator_digests raises FileNotFoundError when a file is missing."""
    with pytest.raises(FileNotFoundError, match="Generator source file missing"):
        prereg.collect_generator_digests(tmp_path)


def test_validate_rejects_missing_or_corrupted_generator_digests_and_velocity():
    """Verify validate rejects missing or invalid generator_digests and required_velocity_injection."""
    draft = _make_test_draft(draft_time_utc="2026-10-29T12:00:00Z")

    # Missing generator_digests
    bad_gen = copy.deepcopy(draft)
    del bad_gen["generator_digests"]
    with pytest.raises(prereg.SpecValidationError, match="Missing generator_digests mapping"):
        prereg.validate(bad_gen)

    # Incomplete generator_digests
    incomplete_gen = copy.deepcopy(draft)
    first_gen_src = spec.GENERATOR_SOURCES[0]
    del incomplete_gen["generator_digests"][first_gen_src]
    with pytest.raises(prereg.SpecValidationError, match="Missing generator digest for"):
        prereg.validate(incomplete_gen)

    # Missing required_velocity_injection
    bad_vel = copy.deepcopy(draft)
    del bad_vel["required_velocity_injection"]
    with pytest.raises(prereg.SpecValidationError, match="Missing required_velocity_injection"):
        prereg.validate(bad_vel)

    # Corrupted required_velocity_injection
    wrong_vel = copy.deepcopy(draft)
    wrong_vel["required_velocity_injection"] = "wrong_version"
    with pytest.raises(prereg.SpecValidationError, match="required_velocity_injection mismatch"):
        prereg.validate(wrong_vel)

