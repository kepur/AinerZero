"""Contract: SLOW promotion, revocation, demotion and supersession (ADR-0014 r3 §3 C1/C3/C4).

Positive: v2 evidence promotes an entry with provenance; the entry is usable by the
deterministic layer while encoder/prior versions still match; revocation, demotion
and supersession each leave an auditable record.

Counter-examples: v1 evidence, ``self`` producer, missing provenance, wrong entry
digest, wrong encoder version, re-promoting a revoked entry, demoting to SLOW,
superseding with a non-SLOW replacement, version drift (fail-closed revalidation).
"""

from __future__ import annotations

import dataclasses

import pytest

from ainerzero.v9.fakes import FakeSpatialMemory
from ainerzero.v9.interfaces.errors import (
    ContractViolation,
    EncoderVersionMismatch,
    EvidenceRequired,
    UnsupportedInput,
)
from ainerzero.v9.interfaces.types import Fragment, PromotionEvidence

from conftest import v2_evidence


def fragment(fid: str = "f-1", **overrides) -> Fragment:
    base = {
        "fragment_id": fid,
        "t_ticks": 100,
        "place": "room-a",
        "partition": "development",
        "encoder_version": "enc-v1",
        "metric": (0.0, 0.0),
        "provenance_ref": "obs/t0005.png",
        "object_keys": ("obj-a",),
        "action_keys": ("act-1",),
    }
    base.update(overrides)
    return Fragment(**base)


@pytest.fixture
def memory(geometry) -> FakeSpatialMemory:
    return FakeSpatialMemory(geometry)


@pytest.fixture
def entry(memory) -> Fragment:
    stored = fragment()
    memory.write(stored)
    return stored


# ---- promotion (C1 + C3) --------------------------------------------------- #


def test_v2_evidence_promotes_an_entry_with_provenance(memory, entry):
    result = memory.promote("f-1", v2_evidence(entry))
    assert result["level"] == "slow"
    assert result["entry_digest"] == entry.content_digest()
    assert result["prior_version"] == "fprior-v9-r5"
    assert memory.slow_items() == ("f-1",)
    assert memory.parameter_fingerprint()  # promotion changes no parameter


def test_v1_evidence_may_not_promote(memory, entry):
    legacy = PromotionEvidence(
        kind="independent_test",
        report_ref="reports/V9-B2/independent.md",
        producer="contract-harness",
        test_id="v9-b2-independent-1",
    )
    with pytest.raises(EvidenceRequired) as caught:
        memory.promote("f-1", legacy)
    assert "schema_version='v2'" in caught.value.detail
    assert memory.slow_items() == ()


def test_self_producer_is_refused_at_promote_time(memory, entry):
    """Defence in depth: a forged ``self`` evidence is stopped by promote() too."""
    good = v2_evidence(entry)
    forged = object.__new__(PromotionEvidence)
    for field, value in dataclasses.asdict(good).items():
        object.__setattr__(forged, field, value)
    object.__setattr__(forged, "producer", "student")
    with pytest.raises(EvidenceRequired) as caught:
        memory.promote("f-1", forged)
    assert "category 'self'" in caught.value.detail
    assert memory.slow_items() == ()


def test_fragment_without_provenance_cannot_be_promoted(memory):
    legacy = Fragment(
        fragment_id="f-legacy",
        t_ticks=10,
        place="room-a",
        partition="development",
        encoder_version="enc-v1",
        metric=(0.0, 0.0),
    )
    memory.write(legacy)
    with pytest.raises(EvidenceRequired) as caught:
        memory.promote("f-legacy", v2_evidence(legacy))
    assert "provenance_ref" in caught.value.detail
    assert memory.slow_items() == ()


def test_entry_digest_must_match_the_stored_content(memory, entry):
    other = fragment("f-other", action_keys=("act-2",))
    with pytest.raises(EvidenceRequired) as caught:
        memory.promote("f-1", v2_evidence(other))
    assert "entry_digest" in caught.value.detail
    assert memory.slow_items() == ()


def test_encoder_version_must_match_the_stored_entry(memory, entry):
    evidence = v2_evidence(entry, encoder_version="enc-v2")
    with pytest.raises(EncoderVersionMismatch):
        memory.promote("f-1", evidence)
    assert memory.slow_items() == ()


def test_promoting_twice_is_refused(memory, entry):
    memory.promote("f-1", v2_evidence(entry))
    with pytest.raises(ContractViolation) as caught:
        memory.promote("f-1", v2_evidence(entry))
    assert "already SLOW" in str(caught.value)


def test_unknown_item_is_refused(memory):
    with pytest.raises(ContractViolation) as caught:
        memory.promote("f-missing", v2_evidence())
    assert "unknown memory item" in str(caught.value)


# ---- revalidation (C4, fail-closed) ---------------------------------------- #


def test_slow_entry_is_usable_only_while_versions_match(memory, entry):
    memory.promote("f-1", v2_evidence(entry))
    assert memory.usable_slow_items(encoder_version="enc-v1", prior_version="fprior-v9-r5") == ("f-1",)
    # 编码器漂移 -> 待重验，确定性层不得使用
    assert memory.usable_slow_items(encoder_version="enc-v2", prior_version="fprior-v9-r5") == ()
    # F_prior / GeometryCore 漂移同理
    assert memory.usable_slow_items(encoder_version="enc-v1", prior_version="fprior-v9-r6") == ()


@pytest.mark.parametrize("bad", ["", None, 3])
def test_usable_slow_items_validates_versions(memory, bad):
    with pytest.raises(UnsupportedInput):
        memory.usable_slow_items(encoder_version=bad, prior_version="fprior-v9-r5")
    with pytest.raises(UnsupportedInput):
        memory.usable_slow_items(encoder_version="enc-v1", prior_version=bad)


# ---- revocation ------------------------------------------------------------ #


def test_revoke_takes_the_entry_out_of_slow(memory, entry):
    memory.promote("f-1", v2_evidence(entry))
    result = memory.revoke("f-1", "counter-example CE-7 reproduced", "counterexamples/ce-7.json")
    assert result["revoked"] is True
    assert result["level"] == "mid"
    assert result["evidence_ref"] == "counterexamples/ce-7.json"
    assert memory.slow_items() == ()
    assert memory.usable_slow_items(encoder_version="enc-v1", prior_version="fprior-v9-r5") == ()


def test_revoke_requires_reason_and_evidence(memory, entry):
    memory.promote("f-1", v2_evidence(entry))
    with pytest.raises(UnsupportedInput):
        memory.revoke("f-1", "", "counterexamples/ce-7.json")
    with pytest.raises(UnsupportedInput):
        memory.revoke("f-1", "reason", "")


def test_revoke_refuses_non_slow_and_double_revocation(memory, entry):
    with pytest.raises(ContractViolation) as caught:
        memory.revoke("f-1", "reason", "ref")
    assert "only SLOW entries can be revoked" in str(caught.value)
    memory.promote("f-1", v2_evidence(entry))
    memory.revoke("f-1", "reason", "ref")
    with pytest.raises(ContractViolation) as caught:
        memory.revoke("f-1", "reason", "ref")
    assert "already revoked" in str(caught.value)


def test_revoked_entry_cannot_be_re_promoted_with_the_old_evidence(memory, entry):
    memory.promote("f-1", v2_evidence(entry))
    memory.revoke("f-1", "counter-example", "counterexamples/ce-7.json")
    with pytest.raises(EvidenceRequired) as caught:
        memory.promote("f-1", v2_evidence(entry))
    assert "was revoked" in caught.value.detail


# ---- demotion -------------------------------------------------------------- #


@pytest.mark.parametrize("to_level", ["fast", "mid"])
def test_demote_moves_a_slow_entry_down(memory, entry, to_level):
    memory.promote("f-1", v2_evidence(entry))
    result = memory.demote("f-1", to_level, "audit upper bound too wide")
    assert result["from_level"] == "slow"
    assert result["level"] == to_level
    assert memory.slow_items() == ()


def test_demote_never_lands_on_slow(memory, entry):
    memory.promote("f-1", v2_evidence(entry))
    with pytest.raises(ContractViolation) as caught:
        memory.demote("f-1", "slow", "noop")
    assert "never lands on SLOW" in str(caught.value)


def test_demote_refuses_non_slow_entries(memory, entry):
    with pytest.raises(ContractViolation) as caught:
        memory.demote("f-1", "fast", "reason")
    assert "only SLOW entries can be demoted" in str(caught.value)


# ---- supersession ---------------------------------------------------------- #


def test_supersede_sets_a_pointer_and_retires_the_old_entry(memory):
    old = fragment("f-old")
    new = fragment("f-new", action_keys=("act-2",))
    memory.write(old)
    memory.write(new)
    memory.promote("f-old", v2_evidence(old))
    memory.promote("f-new", v2_evidence(new))
    result = memory.supersede("f-old", "f-new")
    assert result["superseded_by"] == "f-new"
    usable = memory.usable_slow_items(encoder_version="enc-v1", prior_version="fprior-v9-r5")
    assert usable == ("f-new",)  # 旧条目仍留档，但确定性层不再使用


def test_supersede_requires_a_live_slow_replacement(memory, entry):
    memory.write(fragment("f-plain", action_keys=("act-2",)))
    memory.promote("f-1", v2_evidence(entry))
    with pytest.raises(ContractViolation) as caught:
        memory.supersede("f-1", "f-plain")
    assert "live SLOW entry" in str(caught.value)
    with pytest.raises(ContractViolation) as caught:
        memory.supersede("f-1", "f-1")
    assert "cannot supersede itself" in str(caught.value)


def test_supersede_is_single_shot(memory):
    first = fragment("f-1")
    second = fragment("f-2", action_keys=("act-2",))
    third = fragment("f-3", action_keys=("act-3",))
    for stored in (first, second, third):
        memory.write(stored)
        memory.promote(stored.fragment_id, v2_evidence(stored))
    memory.supersede("f-1", "f-2")
    with pytest.raises(ContractViolation) as caught:
        memory.supersede("f-1", "f-3")
    assert "already superseded" in str(caught.value)


def test_fingerprint_is_stable_across_the_lifecycle(memory, entry):
    before = memory.parameter_fingerprint()
    memory.promote("f-1", v2_evidence(entry))
    memory.revoke("f-1", "reason", "ref")
    assert memory.parameter_fingerprint() == before
