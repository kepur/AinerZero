"""B12 r3: consumption negatives; mutation success paths are recorded separately."""
import copy
from dataclasses import fields

import pytest

from ainerzero.v9.fakes import FakeSpatialMemory
from ainerzero.v9.interfaces.errors import EvidenceRequired
from ainerzero.v9.interfaces.types import PromotionEvidence
from conftest import trusted_context_for, v2_evidence
from test_spatial_memory import promotable


def candidate(geometry):
    memory = FakeSpatialMemory(geometry)
    fragment = promotable('r3-candidate')
    item = memory.write(fragment)
    return memory, fragment, item, v2_evidence(fragment)


def forge(evidence, **changes):
    obj = object.__new__(PromotionEvidence)
    for field in fields(PromotionEvidence):
        object.__setattr__(obj, field.name, copy.deepcopy(getattr(evidence, field.name)))
    for name, value in changes.items():
        object.__setattr__(obj, name, value)
    return obj


def assert_rejected(memory, item, evidence):
    with pytest.raises(EvidenceRequired):
        memory.promote(item, evidence)
    assert not memory.usable_slow_items(encoder_version='enc-v1',
                                       prior_version='fprior-v9-r5')
    assert memory.query_topology('room-a', encoder_version='enc-v1').entries


@pytest.mark.parametrize('origin', ['LLM', 'Teacher', 'llm ', '', None, 'unregistered', [], {}, 'llm', 'teacher'])
def test_forged_origin_rejected(geometry, origin):
    memory, _, item, evidence = candidate(geometry)
    assert_rejected(memory, item, forge(evidence, origin_category=origin))


INVALID_FIELDS = [
    ('kind', 'self_report'), ('report_ref', ''), ('test_id', ''),
    ('schema_version', 'v3'), ('domain_ref', ''), ('calibration', None),
    ('error_control', {}), ('counterexample_ref', ''), ('data_identity', {}),
    ('regression_ref', ''), ('entry_digest', 'bad'), ('encoder_version', ''),
    ('prior_version', ''), ('trusted_context', None), ('producer', 'student'),
]


@pytest.mark.parametrize('field,value', INVALID_FIELDS)
def test_constructor_bypass_rejected(geometry, field, value):
    memory, _, item, evidence = candidate(geometry)
    assert_rejected(memory, item, forge(evidence, **{field: value}))


NESTED = [
    ('data_identity', 'test', 'D'),
    ('calibration', 'method', 'unknown'), ('calibration', 'alpha_dom', float('nan')),
    ('calibration', 'alpha_dom', float('inf')), ('calibration', 'n_cal', 1),
    ('calibration', 'exchangeability_ref', ''), ('calibration', 'fpca_basis_ref', ''),
    ('error_control', 'alpha_t', float('nan')), ('error_control', 'attempts_N', 0),
    ('error_control', 'frozen_test_id', 'other'), ('error_control', 'block_unit', 'frame'),
    ('error_control', 'test_id_frozen_ref', ''), ('error_control', 'elond_state_ref', ''),
]


@pytest.mark.parametrize('field,key,value', NESTED)
def test_nested_mutation_rejected(geometry, field, key, value):
    memory, _, item, evidence = candidate(geometry)
    if field == 'data_identity':
        value = evidence.data_identity['discovery']
    getattr(evidence, field)[key] = value
    assert_rejected(memory, item, evidence)


@pytest.mark.parametrize('origin', ['sindy', 'symbolic', 'human', 'engineered'])
def test_legal_origin_still_usable(geometry, origin):
    memory, _, item, evidence = candidate(geometry)
    evidence = forge(evidence, origin_category=origin)
    assert memory.promote(item, evidence)['level'] == 'slow'
    assert item in memory.usable_slow_items(encoder_version=evidence.encoder_version,
                                          prior_version=evidence.prior_version)


def test_v1_with_otherwise_valid_v2_fields_rejected(geometry):
    memory, _, item, evidence = candidate(geometry)
    assert_rejected(memory, item, forge(evidence, schema_version='v1'))


def test_absent_producer_binding_rejected(geometry):
    memory, _, item, evidence = candidate(geometry)
    evidence.trusted_context['admission_bindings'] = trusted_context_for('independent_test')['admission_bindings']
    assert_rejected(memory, item, evidence)


def test_subclass_cannot_override_validation(geometry):
    memory, _, item, evidence = candidate(geometry)
    class Bypass(PromotionEvidence):
        def __post_init__(self):
            pass
        def _validate_v2(self):
            pass
        def is_v2(self):
            return True
    obj = object.__new__(Bypass)
    for field in fields(PromotionEvidence):
        object.__setattr__(obj, field.name, getattr(evidence, field.name))
    object.__setattr__(obj, 'kind', 'self_report')
    assert_rejected(memory, item, obj)


def test_missing_required_attribute_rejected(geometry):
    memory, _, item, _ = candidate(geometry)
    with pytest.raises(EvidenceRequired):
        memory.promote(item, object.__new__(PromotionEvidence))
    assert not memory.slow_items()
