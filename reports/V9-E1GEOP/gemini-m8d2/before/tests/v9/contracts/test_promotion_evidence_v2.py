"""Contract: PromotionEvidence v2 + SLOW independent-producer guard (ADR-0014 r3 §3 C1/C2).

Positive: a fully specified v2 evidence constructs; a v1 evidence still constructs
and reads (legacy), and the registry authority is untouched.

Counter-examples (one guard each):
- v1 may not promote (checked in ``test_memory_lifecycle``);
- unknown ``schema_version``;
- missing/blank applicability-domain, counter-example, regression references;
- calibration: unknown method, ``alpha_dom`` out of range, ``n_cal < n_min``,
  empty conformal certificate (``ceil((1-a)(n+1)) > n``), FPCA basis missing when
  the FPCA path is declared, ACI without reported empirical coverage;
- error control: bad ``alpha_t``/``attempts_N``, frozen ``test_id`` mismatch
  (贷前冻结), non world-level block unit;
- knowledge origin outside the registered categories;
- D/C/T data identities overlapping;
- producer guard: category ``self``, missing trusted context, missing binding,
  binding for another producer, category mismatch, cross-context binding,
  non-canonical binding digest, duplicate bindings.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from ainerzero.v9.interfaces.errors import EvidenceRequired
from ainerzero.v9.interfaces.types import (
    EVIDENCE_BLOCK_UNITS,
    KNOWLEDGE_ORIGIN_CATEGORIES,
    PROMOTION_CALIBRATION_METHODS,
    PROMOTION_EVIDENCE_SCHEMA_VERSIONS,
    PromotionEvidence,
)
from ainerzero.v9.interfaces.validation import (
    PRODUCER_REGISTRY,
    require_independent_slow_producer,
    slow_binding_digest,
    validate_producer,
)

from conftest import trusted_context_for, v2_evidence


# ---- positives ------------------------------------------------------------- #


def test_v2_evidence_constructs_and_is_flagged_v2():
    evidence = v2_evidence()
    assert evidence.is_v2()
    assert evidence.schema_version == "v2"
    assert evidence.domain_ref
    assert evidence.calibration["n_cal"] >= evidence.calibration["n_min"]


def test_v1_evidence_still_constructs_and_reads():
    """Migration clause: v1 objects stay readable; only ``promote`` refuses them."""
    legacy = PromotionEvidence(
        kind="independent_test",
        report_ref="reports/V9-B2/independent.md",
        producer="contract-harness",
        test_id="v9-b2-independent-1",
    )
    assert legacy.schema_version == "v1"
    assert not legacy.is_v2()
    assert legacy.domain_ref == ""  # v1 carries none of the v2 fields


def test_registry_authority_is_untouched_by_the_slow_guard():
    """C2 方案 (b): ``validate_producer`` keeps its single-argument signature."""
    signature = inspect.signature(validate_producer)
    assert list(signature.parameters) == ["producer"]
    assert PRODUCER_REGISTRY["student"] == "self"  # 登记表原样保留
    # 学生自证在登记表层面仍然"合法"——这正是 C2 要在 SLOW 路径上另加守卫的原因
    assert validate_producer("student") == "self"


def test_slow_guard_accepts_a_bound_independent_producer():
    context = trusted_context_for("independent_test")
    assert require_independent_slow_producer("independent_test", trusted_context=context) == "baseline"


# ---- C1 negatives ---------------------------------------------------------- #


def test_unknown_schema_version_is_refused():
    with pytest.raises(ValueError) as caught:
        v2_evidence(schema_version="v3")
    assert "schema_version" in str(caught.value)
    assert PROMOTION_EVIDENCE_SCHEMA_VERSIONS == ("v1", "v2")


@pytest.mark.parametrize("field", ["domain_ref", "counterexample_ref", "regression_ref", "prior_version"])
def test_blank_reference_fields_are_refused(field):
    with pytest.raises(ValueError) as caught:
        v2_evidence(**{field: ""})
    assert field in str(caught.value)


def test_calibration_method_must_be_registered():
    calibration = dict(v2_evidence().calibration)
    calibration["method"] = "vibes"
    with pytest.raises(ValueError) as caught:
        v2_evidence(calibration=calibration)
    assert "calibration.method" in str(caught.value)
    assert "split_conformal" in PROMOTION_CALIBRATION_METHODS


@pytest.mark.parametrize("alpha_dom", [0.0, 1.0, -0.1, 1.5])
def test_alpha_dom_must_be_a_probability(alpha_dom):
    calibration = dict(v2_evidence().calibration)
    calibration["alpha_dom"] = alpha_dom
    with pytest.raises(ValueError):
        v2_evidence(calibration=calibration)


def test_n_cal_below_n_min_empties_the_certificate():
    calibration = dict(v2_evidence().calibration)
    calibration["n_cal"] = 9  # n_min = 10
    with pytest.raises(ValueError) as caught:
        v2_evidence(calibration=calibration)
    assert "n_min" in str(caught.value)


def test_empty_conformal_certificate_is_refused():
    """k = ceil((1-alpha_dom)(n_cal+1)) must not exceed n_cal (split conformal lemma)."""
    calibration = dict(v2_evidence().calibration)
    calibration["alpha_dom"] = 0.01
    calibration["n_cal"] = 10  # ceil(0.99*11) = 11 > 10
    with pytest.raises(ValueError) as caught:
        v2_evidence(calibration=calibration)
    assert "conformal certificate is empty" in str(caught.value)


def test_fpca_path_requires_a_basis_identity():
    calibration = dict(v2_evidence().calibration)
    calibration["method"] = "fpca_split_conformal"
    calibration["fpca_basis_ref"] = "none"
    with pytest.raises(ValueError) as caught:
        v2_evidence(calibration=calibration)
    assert "fpca_basis_ref" in str(caught.value)


def test_aci_requires_reported_empirical_coverage():
    calibration = dict(v2_evidence().calibration)
    calibration["method"] = "aci_conformal"
    with pytest.raises(ValueError) as caught:
        v2_evidence(calibration=calibration)
    assert "empirical_coverage" in str(caught.value)
    calibration["empirical_coverage"] = 0.94
    assert v2_evidence(calibration=calibration).calibration["method"] == "aci_conformal"


def test_missing_error_control_key_is_refused():
    error_control = dict(v2_evidence().error_control)
    del error_control["elond_state_ref"]
    with pytest.raises(ValueError) as caught:
        v2_evidence(error_control=error_control)
    assert "elond_state_ref" in str(caught.value)


@pytest.mark.parametrize("alpha_t", [0.0, 1.0, 2])
def test_alpha_t_must_be_a_probability(alpha_t):
    error_control = dict(v2_evidence().error_control)
    error_control["alpha_t"] = alpha_t
    with pytest.raises(ValueError):
        v2_evidence(error_control=error_control)


def test_attempts_n_must_be_positive():
    error_control = dict(v2_evidence().error_control)
    error_control["attempts_N"] = 0
    with pytest.raises(ValueError) as caught:
        v2_evidence(error_control=error_control)
    assert "attempts_N" in str(caught.value)


def test_frozen_test_id_must_match_the_evidence_test_id():
    """EGR 定理 2 (i) 贷前冻结：冻结记录里的 test_id 必须就是本次检验的 test_id。"""
    error_control = dict(v2_evidence().error_control)
    error_control["frozen_test_id"] = "some-other-run"
    with pytest.raises(ValueError) as caught:
        v2_evidence(error_control=error_control)
    assert "frozen_test_id" in str(caught.value)


@pytest.mark.parametrize("block_unit", ["trajectory_step", "episode", "frame"])
def test_evidence_unit_must_be_world_level(block_unit):
    error_control = dict(v2_evidence().error_control)
    error_control["block_unit"] = block_unit
    with pytest.raises(ValueError) as caught:
        v2_evidence(error_control=error_control)
    assert "block_unit" in str(caught.value)
    assert EVIDENCE_BLOCK_UNITS == ("world_instance", "world_cluster")


def test_knowledge_origin_must_be_registered():
    with pytest.raises(ValueError) as caught:
        v2_evidence(origin_category="intuition")
    assert "origin_category" in str(caught.value)
    assert "sindy" in KNOWLEDGE_ORIGIN_CATEGORIES


def test_discovery_calibration_test_identities_must_be_pairwise_disjoint():
    for overlap in (("discovery", "test"), ("calibration", "discovery"), ("test", "calibration")):
        identity = dict(v2_evidence().data_identity)
        identity[overlap[1]] = identity[overlap[0]]
        with pytest.raises(ValueError) as caught:
            v2_evidence(data_identity=identity)
        assert "pairwise disjoint" in str(caught.value)


def test_entry_digest_must_be_a_sha256():
    with pytest.raises(ValueError) as caught:
        v2_evidence(entry_digest="not-a-digest")
    assert "entry_digest" in str(caught.value)


# ---- C2 negatives: the independent-producer guard -------------------------- #


def test_student_self_evidence_is_refused_on_the_slow_path():
    """The whole point of C2: ``producer="student"`` must not issue SLOW evidence."""
    context = trusted_context_for("student")
    assert context["admission_bindings"][0]["category"] == "self"
    with pytest.raises(EvidenceRequired) as caught:
        require_independent_slow_producer("student", trusted_context=context)
    assert "category 'self'" in caught.value.detail
    with pytest.raises(EvidenceRequired):
        v2_evidence(producer="student")


def test_missing_trusted_context_is_refused():
    with pytest.raises(EvidenceRequired) as caught:
        require_independent_slow_producer("contract-harness", trusted_context=None)
    assert caught.value.code == "evidence_required"
    assert "trusted_context_missing" in caught.value.detail


def test_incomplete_trusted_context_is_refused():
    context = trusted_context_for()
    del context["issuer"]
    with pytest.raises(EvidenceRequired) as caught:
        require_independent_slow_producer("contract-harness", trusted_context=context)
    assert "trusted_context_schema" in caught.value.detail


def test_bare_self_reported_string_without_binding_is_refused():
    """A context that merely exists is not enough: the producer needs a binding."""
    context = trusted_context_for("independent_test")
    with pytest.raises(EvidenceRequired) as caught:
        require_independent_slow_producer("contract-harness", trusted_context=context)
    assert "trusted_context_binding" in caught.value.detail


def test_binding_category_must_match_the_registry():
    context = trusted_context_for()
    context["admission_bindings"][0]["category"] = "teacher"  # registry says "baseline"
    with pytest.raises(EvidenceRequired) as caught:
        require_independent_slow_producer("contract-harness", trusted_context=context)
    assert "declares category" in caught.value.detail


def test_binding_cannot_be_transplanted_across_contexts():
    context = trusted_context_for(context_id="ctx-b12")
    context["admission_bindings"][0]["context_id"] = "ctx-elsewhere"
    with pytest.raises(EvidenceRequired) as caught:
        require_independent_slow_producer("contract-harness", trusted_context=context)
    assert "belongs to context" in caught.value.detail


def test_binding_digest_must_be_canonical():
    context = trusted_context_for()
    context["admission_bindings"][0]["binding_sha256"] = "b" * 64
    with pytest.raises(EvidenceRequired) as caught:
        require_independent_slow_producer("contract-harness", trusted_context=context)
    assert "binding_sha256" in caught.value.detail


def test_duplicate_bindings_are_refused():
    context = trusted_context_for()
    context["admission_bindings"].append(dict(context["admission_bindings"][0]))
    with pytest.raises(EvidenceRequired) as caught:
        require_independent_slow_producer("contract-harness", trusted_context=context)
    assert "duplicate admission binding" in caught.value.detail


def test_teacher_producer_is_still_refused_before_the_slow_guard():
    """The registry keeps its own rejections (teacher/LLM never write SLOW directly)."""
    with pytest.raises(EvidenceRequired) as caught:
        require_independent_slow_producer("teacher", trusted_context=trusted_context_for("teacher"))
    assert "never write SLOW" in caught.value.detail or "not allowed" in caught.value.detail


def test_binding_digest_is_context_bound():
    first = slow_binding_digest(context_id="ctx-a", producer="contract-harness", category="baseline")
    second = slow_binding_digest(context_id="ctx-b", producer="contract-harness", category="baseline")
    assert first != second and len(first) == 64


def test_forged_evidence_cannot_bypass_the_guard_at_construction():
    """``object.__new__`` forgery must still be stopped by the guard's own checks."""
    forged = object.__new__(PromotionEvidence)
    for field, value in dataclasses.asdict(v2_evidence()).items():
        object.__setattr__(forged, field, value)
    object.__setattr__(forged, "producer", "student")  # 与 trusted_context 里的绑定不一致
    with pytest.raises(EvidenceRequired) as caught:
        require_independent_slow_producer(forged.producer, trusted_context=forged.trusted_context)
    assert "category 'self'" in caught.value.detail
