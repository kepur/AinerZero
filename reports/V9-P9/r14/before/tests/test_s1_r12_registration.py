"""r12 experiment identity: the same registration under a fresh experiment ID.

The r11 identity was consumed by the P31 ledger incident: the real CLI eval that
ran during the review started the r11 four-hour experiment window at 16:32:18.
``P31-LEDGER-INCIDENT-RULING`` keeps every r11 row as the incident record and
re-freezes the *same* user-approved registration (RESEARCH_LOG
R20261023-S1-phase1-r11-budget) as ``s1-phase1-20261023-r12``, so the attempt
guards, the phase wall clock and the D guard start from zero again without
touching a single historical row.

These tests are pure CPU and touch no ledger: they pin the identity rules (which
id may be frozen, which ids scope the guards, which values must stay equal) and
the scientific values, which may not move between r11 and r12.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import prereg, spec, worker

from s1_testkit import FAKE_COUNTS, FAKE_IDENTITY, fake_smoke

R12 = spec.R12_EXPERIMENT_ID
R11 = spec.R11_EXPERIMENT_ID
OLD = spec.EXPERIMENT_ID
SMOKE_OF_RECORD = (
    Path(__file__).resolve().parents[3]
    / "reports"
    / "V9-P9"
    / "r1-archive"
    / "smoke_metrics.json"
)


def _draft(experiment_id: str | None = R12):
    return prereg.build_draft(
        data_identity=FAKE_IDENTITY,
        parameter_counts=FAKE_COUNTS,
        created_unix=1_000.0,
        experiment_id=experiment_id,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
    )


def _frozen(experiment_id: str | None = R12, *, smoke=None):
    return prereg.build_frozen(
        _draft(experiment_id),
        smoke=smoke or fake_smoke(),
        data_identity=FAKE_IDENTITY,
        created_unix=1_000.0,
    )


# --- identity --------------------------------------------------------------
def test_the_current_registration_defaults_to_r12():
    assert R12 == "s1-phase1-20261023-r12"
    # Note: updated for r13 per task P38 rule: current identity is r13
    assert spec.CURRENT_EXPERIMENT_ID == spec.R13_EXPERIMENT_ID
    # r11 stays a registered identity: it is archived history, not an error.
    assert R11 in spec.REGISTERED_EXPERIMENT_IDS
    assert R12 in spec.REGISTERED_EXPERIMENT_IDS
    # the old (r1-r10) experiment is not a registered-budget identity
    assert OLD not in spec.REGISTERED_EXPERIMENT_IDS
    draft = prereg.build_draft(
        data_identity=FAKE_IDENTITY,
        parameter_counts=FAKE_COUNTS,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
    )
    assert draft["experiment_id"] == spec.R13_EXPERIMENT_ID


def test_freeze_accepts_both_registered_identities_and_refuses_anything_else():
    assert _frozen(R12)["experiment_id"] == R12
    assert _frozen(R11)["experiment_id"] == R11  # archived history still freezes
    foreign = _draft(R12)
    foreign["experiment_id"] = "s1-phase1-20261023-r13"
    with pytest.raises(ValueError, match="registered experiment id"):
        prereg.build_frozen(
            foreign, smoke=fake_smoke(), data_identity=FAKE_IDENTITY, created_unix=1_000.0
        )
    old = _draft(R12)
    old["experiment_id"] = OLD
    with pytest.raises(ValueError, match="registered experiment id"):
        prereg.build_frozen(
            old, smoke=fake_smoke(), data_identity=FAKE_IDENTITY, created_unix=1_000.0
        )


def test_validate_refuses_an_unregistered_experiment_id():
    frozen = _frozen(R12)
    assert prereg.validate(frozen) == []
    frozen["experiment_id"] = "s1-phase1-20261023-r13"
    reasons = prereg.validate(frozen)
    assert any("registered experiment id" in reason for reason in reasons)


def test_the_guard_scope_covers_r12_and_r11_only():
    assert worker.document_experiment_scope({"experiment_id": R12}) == R12
    assert worker.document_experiment_scope({"experiment_id": R11}) == R11
    # the shared r1-r10 experiment and any unregistered id keep the whole-ledger
    # guard, so no earlier refusal is weakened
    assert worker.document_experiment_scope({"experiment_id": OLD}) is None
    assert worker.document_experiment_scope({"experiment_id": "s1-phase1-20261023-r13"}) is None
    assert worker.document_experiment_scope({}) is None
    # the run-registration id still follows the document
    assert worker.document_experiment_id({"experiment_id": R12}) == R12


# --- the registered values do not move -------------------------------------
def test_r12_registers_the_same_values_as_the_approved_r11_registration():
    smoke = json.loads(SMOKE_OF_RECORD.read_text(encoding="utf-8"))
    budget = prereg.registered_budget(smoke)
    assert budget["updates"] == 3_510
    assert budget["deadline_seconds"] == 1_200
    assert budget["supervision_seconds"] == 1_250
    assert budget["arm1_deadline_seconds"] == 7
    assert budget["arm1_supervision_seconds"] == 57
    assert budget["phase_wall_seconds"] == pytest.approx(10_854.605202458999)

    frozen = _frozen(R12, smoke=smoke)
    timing = frozen["timing"]
    protocol = frozen["training_protocol"]
    assert timing["deadline_seconds"] == 1_200
    assert timing["supervision_seconds"] == 1_250
    assert timing["deadline_source"] == spec.R11_DEADLINE_SOURCE
    assert timing["registered_updates"] == 3_510
    assert timing["registered_deadline_seconds"] == 1_200
    assert timing["registered_supervision_seconds"] == 1_250
    assert timing["phase_wall_max_seconds"] == 14_400
    assert timing["per_run_wall_max_seconds"] == 1_200
    assert protocol["updates"] == 3_510
    assert protocol["eval_batches"] == 175
    assert protocol["checkpoint_updates"] == [0, 439, 878, 1_755, 3_510]
    assert protocol["seeds"] == [0, 1, 2]
    assert frozen["evaluation"]["query_limit"] == 8
    assert timing["measured_throughput"] == dict(spec.R11_MEASURED_THROUGHPUT)
    for arm_id in ("arm2", "arm3", "arm4"):
        assert frozen["arms"][arm_id]["training_updates"] == 3_510
        assert frozen["arms"][arm_id]["seeds"] == [0, 1, 2]


def test_r12_document_differs_from_r11_only_in_identity_and_bindings():
    """Rebuild r12 from the archived r11 draft and diff it leaf by leaf.

    This is the freeze path the r12 artifact is produced with: the r11 draft of
    record supplies the scientific rows, the registration supplies the budget,
    and the smoke of record supplies the measurement.  The only permitted
    differences are the experiment id, the source binding and the time-derived
    fields; every registered and scientific value must be identical.
    """
    artifacts = Path(__file__).resolve().parents[3] / "artifacts" / "v9" / "s1" / "phase1"
    r11_draft_path = artifacts / "r11" / "draft_preregistration.json"
    r11_frozen_path = artifacts / "r11" / "pre_registration.json"
    if not (r11_draft_path.is_file() and r11_frozen_path.is_file()):
        pytest.skip("the r11 artifacts are not present in this checkout")

    archived = json.loads(r11_frozen_path.read_text(encoding="utf-8"))
    old_draft = json.loads(r11_draft_path.read_text(encoding="utf-8"))
    smoke = json.loads(SMOKE_OF_RECORD.read_text(encoding="utf-8"))
    counts = {arm: old_draft["arms"][arm]["parameter_count"] for arm in ("arm1", "arm2", "arm3", "arm4")}
    draft = prereg.build_draft(
        data_identity=old_draft["data_identity"],
        parameter_counts=counts,
        created_unix=1_000.0,
        experiment_id=R12,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
    )
    # the scientific arm rows (identity keys included) come from the draft of record
    draft["arms"] = json.loads(json.dumps(old_draft["arms"]))
    draft["evaluation"] = {
        "query_limit": int(old_draft["evaluation"]["query_limit"]),
        "reporting_notes": list(old_draft["evaluation"]["reporting_notes"]),
    }
    fresh = prereg.build_frozen(
        draft,
        smoke=smoke,
        data_identity=old_draft["data_identity"],
        created_unix=1_000.0,
    )
    assert archived["experiment_id"] == R11
    assert fresh["experiment_id"] == R12

    # ``timing.smoke_source`` is written by the CLI freeze step (a source
    # binding of the measurement of record), not by ``build_frozen``.
    # V9.P47 (2026-10-28)：r14 冻结前把 effective_metadata.equivariant_source 改成与实现一致的表述（旧句声称 G3 位姿＋协方差注入，arms.py 并不如此）。
    # 这是唯一被允许的科学文本差异，且下面单独断言：归档值仍是旧句、新值明确写了「not G3 CanonicalBelief」，所以不是对该键的放行式豁免。
    allowed = {"experiment_id", "created_unix", "effective_metadata.equivariant_source"}
    assert "G3 estimated pose" in archived["effective_metadata"]["equivariant_source"]
    assert "not G3 CanonicalBelief" in fresh["effective_metadata"]["equivariant_source"]

    def flat(value, prefix="", out=None):
        out = {} if out is None else out
        if isinstance(value, dict):
            if not value:
                out[prefix] = value
            for key in sorted(value):
                flat(value[key], f"{prefix}.{key}" if prefix else key, out)
        elif isinstance(value, list):
            if not value:
                out[prefix] = value
            for index, item in enumerate(value):
                flat(item, f"{prefix}[{index}]", out)
        else:
            out[prefix] = value
        return out

    left, right = flat(archived), flat(fresh)
    changed = sorted(
        key for key in set(left) | set(right) if left.get(key) != right.get(key)
    )
    unexpected = [
        key
        for key in changed
        if not (
            key in allowed
            or key.startswith("source_identity.")
            or key.startswith("timing.smoke_source")
        )
    ]
    assert unexpected == [], f"values moved between r11 and r12: {unexpected}"
    # the diff is not empty: the identity and the source binding did change
    assert "experiment_id" in changed
    assert any(key.startswith("source_identity.") for key in changed)
