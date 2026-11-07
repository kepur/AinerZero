"""Tests for S2 preregistration draft generation, parameter counting, and validation (ainerzero.V9.P124).

Verifies:
- Closed-form parameter counting matches NumPy layer-by-layer reference exactly for all arms.
- All three arms are within 300k +/- 10% ([270k, 330k]).
- Boundary step-up tests: stepping any arm hidden width up one standard tier breaches the 330k ceiling.
- validate(build_draft()) succeeds cleanly.
- Subprocess direct run under `.venv/bin/python -I` without conftest succeeds.
- Five distinct tampering modes each reliably raise SpecValidationError:
  1. Deleting a required top-level key.
  2. Modifying delta_pred to 2.0.
  3. Doubling Arm A hidden width (causing parameter count overflow).
  4. Setting calendar_window_hours to 5 h (less than 10 h wallclock time).
  5. Setting n_fwd to 1000.
"""

from __future__ import annotations

import copy
import subprocess
import sys
import pytest

from ainerzero.v9.experiments.s2 import param_count, prereg, spec


def test_closed_form_matches_numpy_reference_per_arm() -> None:
    """Verify that closed-form parameter counting equals NumPy reference accumulation for each arm."""
    counts_closed = param_count.count_all_arms_closed_form()
    counts_numpy = param_count.count_all_arms_numpy_reference()

    for arm in ("arm_a", "arm_b", "arm_c"):
        c_closed = counts_closed[arm]
        c_numpy = counts_numpy[arm]
        assert (
            c_closed == c_numpy
        ), f"Parameter count mismatch for {arm}: closed={c_closed}, numpy={c_numpy}"


def test_all_arms_within_300k_pm_10_percent() -> None:
    """Verify all three arms land strictly within 300k +/- 10% (270,000 to 330,000)."""
    counts = param_count.count_all_arms_closed_form()

    for arm, count in counts.items():
        assert (
            spec.PARAM_COUNT_MIN <= count <= spec.PARAM_COUNT_MAX
        ), f"{arm} count {count} outside [{spec.PARAM_COUNT_MIN}, {spec.PARAM_COUNT_MAX}]"
        # Also ensure relative gap to 300,000 is small (< 5%)
        rel_diff = abs(count - spec.TARGET_PARAMETER_COUNT) / spec.TARGET_PARAMETER_COUNT
        assert rel_diff < 0.05, f"{arm} difference from 300k is {rel_diff:.2%}, expected < 5%"


def test_stepping_width_up_exceeds_upper_bound() -> None:
    """Boundary test: stepping up hidden width by one standard tier breaches the 330k upper bound."""
    # Arm A: stepping gru_hidden from 160 up to 196 (the initial estimate tier) breaches 330k
    cfg_a_over = copy.deepcopy(spec.ARM_DIMS["arm_a"])
    cfg_a_over["gru_hidden"] = 196
    count_a_over = param_count.count_arm_a_closed_form(cfg_a_over)
    assert (
        count_a_over > spec.PARAM_COUNT_MAX
    ), f"Stepped-up Arm A count {count_a_over} did not breach {spec.PARAM_COUNT_MAX}"

    # Arm B: stepping p1_hidden from 320 up to 352 breaches 330k
    cfg_b_over = copy.deepcopy(spec.ARM_DIMS["arm_b"])
    cfg_b_over["p1_hidden_1"] = 352
    cfg_b_over["p1_hidden_2"] = 352
    count_b_over = param_count.count_arm_b_closed_form(cfg_b_over)
    assert (
        count_b_over > spec.PARAM_COUNT_MAX
    ), f"Stepped-up Arm B count {count_b_over} did not breach {spec.PARAM_COUNT_MAX}"

    # Arm C: stepping p1_hidden from 256 up to 300 breaches 330k
    cfg_c_over = copy.deepcopy(spec.ARM_DIMS["arm_c"])
    cfg_c_over["p1_hidden_1"] = 300
    cfg_c_over["p1_hidden_2"] = 300
    count_c_over = param_count.count_arm_c_closed_form(cfg_c_over)
    assert (
        count_c_over > spec.PARAM_COUNT_MAX
    ), f"Stepped-up Arm C count {count_c_over} did not breach {spec.PARAM_COUNT_MAX}"


def test_build_draft_and_validate_clean() -> None:
    """Verify build_draft produces a valid document that passes validate()."""
    draft = prereg.build_draft()
    assert draft["schema"] == prereg.SCHEMA
    assert draft["spec_name"] == spec.SPEC_NAME
    assert draft["experiment_id"] == spec.EXPERIMENT_ID
    assert draft["task_id"] == spec.TASK_ID
    assert draft["status"] == prereg.STATUS_DRAFT
    # Must validate cleanly without exception
    prereg.validate(draft)


def test_direct_python_isolated_subprocess() -> None:
    """Verify validation passes in an isolated Python subprocess without pytest/conftest."""
    cmd = [
        sys.executable,
        "-I",
        "-c",
        "from ainerzero.v9.experiments.s2 import prereg; prereg.validate(prereg.build_draft())",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert (
        res.returncode == 0
    ), f"Subprocess validation failed with returncode {res.returncode}:\n{res.stderr}"


def test_tamper_delete_required_key_fails() -> None:
    """Tamper mode 1: Deleting a required key must raise SpecValidationError."""
    draft = prereg.build_draft()
    del draft["budget"]
    with pytest.raises(prereg.SpecValidationError, match="Missing required key"):
        prereg.validate(draft)


def test_tamper_delta_pred_modified_fails() -> None:
    """Tamper mode 2: Changing delta_pred to 2.0 must raise SpecValidationError."""
    draft = prereg.build_draft()
    draft["gates"]["delta_pred"] = 2.0
    with pytest.raises(prereg.SpecValidationError, match="delta_pred mismatch"):
        prereg.validate(draft)


def test_tamper_double_arm_a_width_fails() -> None:
    """Tamper mode 3: Doubling Arm A hidden width must raise SpecValidationError."""
    draft = prereg.build_draft()
    cfg_a_doubled = copy.deepcopy(spec.ARM_DIMS["arm_a"])
    cfg_a_doubled["gru_hidden"] = cfg_a_doubled["gru_hidden"] * 2
    over_count = param_count.count_arm_a_closed_form(cfg_a_doubled)
    draft["arm_parameter_counts"]["arm_a"] = over_count
    with pytest.raises(prereg.SpecValidationError, match="Arm arm_a parameter count .* is outside"):
        prereg.validate(draft)


def test_tamper_calendar_window_smaller_than_wallclock_fails() -> None:
    """Tamper mode 4: Setting calendar_window_hours to 5 h must raise SpecValidationError."""
    draft = prereg.build_draft()
    draft["budget"]["calendar_window_hours"] = 5.0
    with pytest.raises(
        prereg.SpecValidationError, match="Calendar window .* cannot be smaller than"
    ):
        prereg.validate(draft)


def test_tamper_n_fwd_modified_fails() -> None:
    """Tamper mode 5: Setting n_fwd to 1000 must raise SpecValidationError."""
    draft = prereg.build_draft()
    draft["planning"]["n_fwd"] = 1000
    with pytest.raises(prereg.SpecValidationError, match="Planning N_fwd mismatch"):
        prereg.validate(draft)


def test_tamper_namespaces_duplicate_fails() -> None:
    """Appendix C Tamper: Duplicate seed namespaces must raise SpecValidationError."""
    draft = prereg.build_draft()
    draft["data"]["seed_namespaces"]["final"] = draft["data"]["seed_namespaces"]["dev"]
    with pytest.raises(prereg.SpecValidationError, match="Seed namespaces must be pairwise distinct"):
        prereg.validate(draft)


def test_tamper_holdout_fraction_out_of_range_fails() -> None:
    """Appendix C Tamper: Holdout fraction of 0.6 (> 0.5) must raise SpecValidationError."""
    draft = prereg.build_draft()
    draft["data"]["train_holdout_world_fraction"] = 0.6
    with pytest.raises(
        prereg.SpecValidationError, match="train_holdout_world_fraction must be strictly in"
    ):
        prereg.validate(draft)


def test_tamper_train_scale_exceeds_data_budget_fails() -> None:
    """Appendix C Tamper: Oversized train scale exceeding data budget must raise SpecValidationError."""
    draft = prereg.build_draft()
    draft["data"]["train_n_worlds"] = 10_000
    with pytest.raises(prereg.SpecValidationError, match="exceeds data budget"):
        prereg.validate(draft)


def test_trial_freeze_determinism_and_verification(tmp_path: Path) -> None:
    """Verify trial freeze in temporary directories produces identical document_sha256 and passes verify_frozen_identity."""
    from ainerzero.v9.experiments.s2 import freeze, identity

    draft = prereg.build_draft()
    dir1 = tmp_path / "trial_freeze_1"
    dir2 = tmp_path / "trial_freeze_2"

    sha1 = freeze.freeze(draft, out_dir=dir1)
    sha2 = freeze.freeze(draft, out_dir=dir2)

    assert sha1 == sha2, f"Trial freeze non-deterministic: {sha1} != {sha2}"
    assert len(sha1) == 64

    verif1 = identity.verify_frozen_identity(dir1 / "prereg.json")
    verif2 = identity.verify_frozen_identity(dir2 / "prereg.json")

    assert verif1["status"] == "passed"
    assert verif2["status"] == "passed"
    assert verif1["document_sha256"] == sha1
    assert verif2["document_sha256"] == sha2



# --- W7 (P175): r2.6 / D3.1 / D5.1 registered fields -------------------------------------

import copy as _copy

import pytest as _pytest

from ainerzero.v9.experiments.s2 import freeze as _freeze
from ainerzero.v9.experiments.s2 import prereg as _prereg
from ainerzero.v9.experiments.s2 import spec as _spec


def _w7_draft():
    from pathlib import Path

    return _prereg.build_draft(repo_root=Path(__file__).resolve().parents[3])


def test_w7_r26_and_probe_fields_match_spec():
    d = _w7_draft()
    pl = d["planning"]
    assert "replan_m_steps" not in pl
    assert pl["replan_every_obs_steps"] == _spec.PLAN_REPLAN_EVERY_OBS_STEPS == 1
    assert pl["cem_n_iters"] == _spec.CEM_N_ITERS and pl["cem_elite_frac"] == _spec.CEM_ELITE_FRAC
    assert pl["future_dt_l1"] == _spec.PLAN_FUTURE_DT_L1 and pl["future_dt_l2"] == _spec.PLAN_FUTURE_DT_L2
    assert pl["cost_mode"] == {"flat": "trajectory_sum", "upper": "trajectory_sum", "lower": "terminal"}
    pr = d["probe"]
    assert pr["gate_step"] == _spec.PROBE_GATE_STEP and pr["delta_pred"] == _spec.DELTA_PRED
    assert pr["start_points"] == list(_spec.PROBE_START_POINTS)
    _prereg.validate(d)


@_pytest.mark.parametrize(
    "path,value",
    [
        (("planning", "replan_every_obs_steps"), 4),
        (("planning", "future_dt_l1"), 1.7),
        (("planning", "cem_n_iters"), 3),
        (("probe", "delta_pred"), 2.0),
        (("probe", "gate_step"), 1),
    ],
)
def test_w7_validate_rejects_tampering(path, value):
    d = _copy.deepcopy(_w7_draft())
    d[path[0]][path[1]] = value
    with _pytest.raises(_prereg.SpecValidationError):
        _prereg.validate(d)


def test_w7_validate_rejects_old_m_key_terminal_flat_cost_and_missing_probe():
    d = _copy.deepcopy(_w7_draft())
    d["planning"]["replan_m_steps"] = 4
    with _pytest.raises(_prereg.SpecValidationError):
        _prereg.validate(d)
    d = _copy.deepcopy(_w7_draft())
    d["planning"]["cost_mode"]["flat"] = "terminal"
    with _pytest.raises(_prereg.SpecValidationError):
        _prereg.validate(d)
    d = _copy.deepcopy(_w7_draft())
    del d["probe"]
    with _pytest.raises(_prereg.SpecValidationError):
        _prereg.validate(d)


def test_w7_trial_freeze_is_deterministic(tmp_path):
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    d = _w7_draft()  # one draft: created_utc has second resolution
    a = _freeze.freeze(_copy.deepcopy(d), out_dir=tmp_path / "a", repo_root=repo)
    b = _freeze.freeze(_copy.deepcopy(d), out_dir=tmp_path / "b", repo_root=repo)
    assert a == b
