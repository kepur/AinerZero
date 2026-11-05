"""Contract: ``cmfl_registration.json`` freeze file (ADR-0014 r3 §3 C5 / §2 D1 M5).

Positive: the shipped example loads, self-verifies and carries the full frozen list.

Counter-examples: tampering (self-check), missing frozen key, e-LOND weights summing
above 1, copying an r5 frozen value instead of referencing it, r5 reference entries
with extra fields, unexpected top-level keys, wrong schema id, missing D_permit
provenance, empty integrator set / world family list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainerzero.v9.interfaces.cmfl_registration import (
    CMFL_SCHEMA,
    DISCOVERY_SECTION_KEYS,
    MSG_SECTION_KEYS,
    R5_FROZEN_NAMES,
    CMFLRegistration,
)
from ainerzero.v9.interfaces.errors import UnsupportedInput

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = REPO_ROOT / "reports/V9-B12/cmfl_registration.json"


def document() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def write(tmp_path: Path, doc: dict) -> Path:
    target = tmp_path / "cmfl_registration.json"
    target.write_text(json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def resign(doc: dict) -> dict:
    """Recompute the self-check digest so a negative test hits the intended guard."""
    from ainerzero.v9.interfaces.cmfl_registration import CMFLRegistration as Registration

    body = {key: value for key, value in doc.items() if key != "sha256"}
    import hashlib

    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    doc = dict(doc)
    doc["sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert Registration is not None
    return doc


# ---- positives ------------------------------------------------------------- #


def test_example_registration_loads_and_self_verifies():
    registration = CMFLRegistration.from_json(EXAMPLE)
    assert registration.digest() == registration.sha256
    assert registration.body()["schema"] == CMFL_SCHEMA
    for key in MSG_SECTION_KEYS:
        assert key in registration.msg
    for key in DISCOVERY_SECTION_KEYS:
        assert key in registration.discovery


def test_registration_references_r5_by_sha_and_copies_nothing():
    registration = CMFLRegistration.from_json(EXAMPLE)
    for name, entry in registration.r5_references.items():
        assert set(entry) == {"source", "sha256"}
        assert len(entry["sha256"]) == 64
        assert name not in R5_FROZEN_NAMES
    for frozen in R5_FROZEN_NAMES:
        assert frozen not in registration.msg
        assert frozen not in registration.discovery


def test_registration_matches_the_evidence_defaults():
    """The example is internally consistent with the contract defaults it is used with."""
    from ainerzero.v9.interfaces.types import DEFAULT_CONFORMAL_N_MIN

    registration = CMFLRegistration.from_json(EXAMPLE)
    assert registration.discovery["n_min"] == DEFAULT_CONFORMAL_N_MIN
    assert registration.discovery["alpha_dom"] == pytest.approx(0.05)
    assert sum(registration.discovery["gamma_weights"]) <= 1.0 + 1e-9


# ---- negatives ------------------------------------------------------------- #


def mutated(tmp_path: Path, mutate) -> Path:
    """Apply ``mutate`` to the shipped example, re-sign, and write it out.

    Re-signing keeps each negative test pointed at *its own* guard instead of
    tripping the self-check first.
    """
    doc = document()
    mutate(doc)
    return write(tmp_path, resign(doc))


def test_tampering_breaks_the_self_check(tmp_path):
    doc = document()
    doc["discovery"]["delta_gain"] = 0.5  # 手改冻结值，不重签
    with pytest.raises(UnsupportedInput) as caught:
        CMFLRegistration.from_json(write(tmp_path, doc))
    assert "does not match the canonical digest" in str(caught.value)


def test_missing_frozen_key_is_refused(tmp_path):
    with pytest.raises(UnsupportedInput) as caught:
        CMFLRegistration.from_json(
            mutated(tmp_path, lambda doc: doc["discovery"].pop("lambda_grid"))
        )
    assert "lambda_grid" in str(caught.value)


def test_elond_weights_must_sum_to_at_most_one(tmp_path):
    def mutate(doc):
        doc["discovery"]["gamma_weights"] = [0.9, 0.9]

    with pytest.raises(UnsupportedInput) as caught:
        CMFLRegistration.from_json(mutated(tmp_path, mutate))
    assert "sum(gamma_t) <= 1" in str(caught.value)


def test_r5_values_may_not_be_copied_into_the_registration(tmp_path):
    def mutate(doc):
        doc["msg"]["epsilon"] = 0.01  # 式 6 的 ε 只能引用，不能复制

    with pytest.raises(UnsupportedInput) as caught:
        CMFLRegistration.from_json(mutated(tmp_path, mutate))
    assert "r5 frozen value" in str(caught.value)


def test_r5_reference_entries_may_only_carry_source_and_sha(tmp_path):
    def add_value(doc):
        doc["r5_references"]["ARCHITECTURE_V9_r5"]["value"] = 0.01

    with pytest.raises(UnsupportedInput) as caught:
        CMFLRegistration.from_json(mutated(tmp_path, add_value))
    assert "reference, do not copy" in str(caught.value)

    def add_frozen_key(doc):
        doc["r5_references"]["epsilon"] = {"source": "x", "sha256": "a" * 64}

    with pytest.raises(UnsupportedInput):
        CMFLRegistration.from_json(mutated(tmp_path, add_frozen_key))


def test_unexpected_top_level_keys_are_refused(tmp_path):
    def mutate(doc):
        doc["tau_override"] = 0.3

    with pytest.raises(UnsupportedInput) as caught:
        CMFLRegistration.from_json(mutated(tmp_path, mutate))
    assert "unexpected top-level" in str(caught.value)


def test_schema_id_must_match(tmp_path):
    def mutate(doc):
        doc["schema"] = "cmfl.registration.v2"

    with pytest.raises(UnsupportedInput) as caught:
        CMFLRegistration.from_json(mutated(tmp_path, mutate))
    assert CMFL_SCHEMA in str(caught.value)


def test_d_permit_requires_a_provenance_digest(tmp_path):
    with pytest.raises(UnsupportedInput) as caught:
        CMFLRegistration.from_json(
            mutated(tmp_path, lambda doc: doc["msg"]["d_permit"].pop("provenance_sha256"))
        )
    assert "d_permit" in str(caught.value)


def test_integrators_and_world_families_must_be_declared(tmp_path):
    def clear_integrators(doc):
        doc["msg"]["integrators"] = []

    with pytest.raises(UnsupportedInput):
        CMFLRegistration.from_json(mutated(tmp_path, clear_integrators))

    def clear_families(doc):
        doc["discovery"]["env_families"] = []

    with pytest.raises(UnsupportedInput):
        CMFLRegistration.from_json(mutated(tmp_path, clear_families))


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(UnsupportedInput) as caught:
        CMFLRegistration.from_json(tmp_path / "absent.json")
    assert "not found" in str(caught.value)
