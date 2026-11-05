import sys
import json
import math
import hashlib
import traceback
from dataclasses import fields

# Guard against CPU model imports
class BlockModels:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('mlx', 'torch', 'transformers', 'onnxruntime'):
            raise RuntimeError('B15 CPU-only verification blocked model import: ' + fullname)

sys.meta_path.insert(0, BlockModels())

from ainerzero.v9.interfaces.types import Fragment, PromotionEvidence
from ainerzero.v9.fakes.spatial_memory import FakeSpatialMemory
from ainerzero.v9.interfaces.errors import EvidenceRequired

def make_fixture(origin='sindy', producer='independent_test'):
    f = Fragment(
        fragment_id='b15-independent-frag',
        t_ticks=42,
        place='b15-room',
        partition='development',
        encoder_version='enc-b15',
        metric=(1.0, 2.0),
        provenance_ref='obs/b15-mechanism',
        object_keys=('obs/object-b15',),
        action_keys=('sensor/push-b15',)
    )
    ctx = 'b15-trusted-context'
    digest = hashlib.sha256(
        json.dumps(dict(category='baseline', context_id=ctx, producer=producer), sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    
    e = PromotionEvidence(
        kind='independent_test',
        report_ref='b15/audit-report',
        producer=producer,
        test_id='b15-frozen-test-id',
        schema_version='v2',
        trusted_context=dict(
            context_id=ctx,
            issuer='b15-reviewer',
            admission_bindings=[
                dict(producer=producer, category='baseline', context_id=ctx, binding_sha256=digest)
            ]
        ),
        domain_ref='b15/domain',
        calibration=dict(
            method='split_conformal',
            alpha_dom=0.05,
            n_cal=50,
            n_min=20,
            exchangeability_ref='b15/exchange',
            fpca_basis_ref='none'
        ),
        error_control=dict(
            elond_state_ref='b15/elond-state',
            alpha_t=0.01,
            attempts_N=1,
            test_id_frozen_ref='b15/freeze-ref',
            frozen_test_id='b15-frozen-test-id',
            block_unit='world_cluster'
        ),
        counterexample_ref='b15/counterexamples',
        origin_category=origin,
        data_identity=dict(discovery='b15-D', calibration='b15-C', test='b15-T'),
        regression_ref='b15/regression',
        entry_digest=f.content_digest(),
        encoder_version='enc-b15',
        prior_version='prior-b15'
    )
    m = FakeSpatialMemory()
    m.write(f)
    return m, f, e

def forge_evidence(base_evidence, **overrides):
    obj = object.__new__(PromotionEvidence)
    for field in fields(PromotionEvidence):
        val = getattr(base_evidence, field.name)
        if isinstance(val, dict):
            val = dict(val)
        object.__setattr__(obj, field.name, val)
    for k, v in overrides.items():
        object.__setattr__(obj, k, v)
    return obj

def run_probe():
    results = []

    def log_case(category, name, expected, actual, detail=''):
        passed = (expected == actual)
        results.append({
            'category': category,
            'name': name,
            'expected': expected,
            'actual': actual,
            'passed': passed,
            'detail': str(detail)
        })

    # 1. Positive controls: legal origins
    for origin in ('sindy', 'symbolic', 'human', 'engineered'):
        m, f, e = make_fixture(origin=origin)
        try:
            res = m.promote(f.fragment_id, e)
            usable = m.usable_slow_items(encoder_version='enc-b15', prior_version='prior-b15')
            if res.get('level') == 'slow' and f.fragment_id in usable:
                log_case('positive_control', f'legal_origin_{origin}', 'promoted_and_usable', 'promoted_and_usable')
            else:
                log_case('positive_control', f'legal_origin_{origin}', 'promoted_and_usable', 'partial_promotion', res)
        except Exception as exc:
            log_case('positive_control', f'legal_origin_{origin}', 'promoted_and_usable', 'exception', exc)

    # 2. Origin negatives (forbidden / unknown / malformed)
    origin_negatives = [
        ('denied_llm', 'llm'),
        ('denied_teacher', 'teacher'),
        ('forged_upper_LLM', 'LLM'),
        ('forged_title_Teacher', 'Teacher'),
        ('forged_trailing_space', 'llm '),
        ('forged_empty_str', ''),
        ('forged_none', None),
        ('forged_unregistered', 'unregistered'),
        ('forged_list', []),
        ('forged_dict', {}),
    ]
    for label, val in origin_negatives:
        m, f, e = make_fixture(origin='sindy')
        forged = forge_evidence(e, origin_category=val)
        try:
            m.promote(f.fragment_id, forged)
            log_case('origin_negative', label, 'rejected', 'promoted')
        except EvidenceRequired as exc:
            assert not m.slow_items()
            assert m.query_topology('b15-room', encoder_version='enc-b15').entries
            log_case('origin_negative', label, 'rejected', 'rejected', exc)
        except Exception as exc:
            log_case('origin_negative', label, 'rejected', f'unexpected_{type(exc).__name__}', exc)

    # 3. Constructor bypass negatives
    constructor_negatives = [
        ('kind_self_report', {'kind': 'self_report'}),
        ('schema_version_v1', {'schema_version': 'v1'}),
        ('schema_version_v3', {'schema_version': 'v3'}),
        ('producer_student', {'producer': 'student'}),
        ('empty_report_ref', {'report_ref': ''}),
        ('empty_test_id', {'test_id': ''}),
        ('empty_domain_ref', {'domain_ref': ''}),
        ('empty_counterexample_ref', {'counterexample_ref': ''}),
        ('empty_regression_ref', {'regression_ref': ''}),
        ('empty_entry_digest', {'entry_digest': 'bad'}),
        ('empty_encoder_version', {'encoder_version': ''}),
        ('empty_prior_version', {'prior_version': ''}),
        ('none_trusted_context', {'trusted_context': None}),
        ('none_calibration', {'calibration': None}),
        ('empty_error_control', {'error_control': {}}),
        ('empty_data_identity', {'data_identity': {}}),
    ]
    for label, overrides in constructor_negatives:
        m, f, e = make_fixture()
        forged = forge_evidence(e, **overrides)
        try:
            m.promote(f.fragment_id, forged)
            log_case('constructor_bypass', label, 'rejected', 'promoted')
        except EvidenceRequired as exc:
            assert not m.slow_items()
            assert m.query_topology('b15-room', encoder_version='enc-b15').entries
            log_case('constructor_bypass', label, 'rejected', 'rejected', exc)
        except Exception as exc:
            log_case('constructor_bypass', label, 'rejected', f'unexpected_{type(exc).__name__}', exc)

    # 4. Nested dictionary mutation negatives (tested on already constructed valid objects)
    nested_mutations = [
        ('data_identity_overlap_DT', ('data_identity', 'test', 'b15-D')),
        ('data_identity_overlap_DC', ('data_identity', 'calibration', 'b15-D')),
        ('data_identity_overlap_CT', ('data_identity', 'test', 'b15-C')),
        ('calibration_method_unknown', ('calibration', 'method', 'unknown_method')),
        ('calibration_alpha_nan', ('calibration', 'alpha_dom', float('nan'))),
        ('calibration_alpha_inf', ('calibration', 'alpha_dom', float('inf'))),
        ('calibration_n_cal_too_small', ('calibration', 'n_cal', 1)),
        ('calibration_empty_exchangeability', ('calibration', 'exchangeability_ref', '')),
        ('calibration_empty_fpca', ('calibration', 'fpca_basis_ref', '')),
        ('error_control_alpha_nan', ('error_control', 'alpha_t', float('nan'))),
        ('error_control_attempts_zero', ('error_control', 'attempts_N', 0)),
        ('error_control_frozen_test_mismatch', ('error_control', 'frozen_test_id', 'different-test')),
        ('error_control_invalid_block_unit', ('error_control', 'block_unit', 'frame')),
        ('error_control_empty_freeze_ref', ('error_control', 'test_id_frozen_ref', '')),
        ('error_control_empty_elond_ref', ('error_control', 'elond_state_ref', '')),
    ]
    for label, (attr, key, val) in nested_mutations:
        m, f, e = make_fixture()
        # mutate nested dict in-place
        getattr(e, attr)[key] = val
        try:
            m.promote(f.fragment_id, e)
            log_case('nested_mutation', label, 'rejected', 'promoted')
        except EvidenceRequired as exc:
            assert not m.slow_items()
            assert m.query_topology('b15-room', encoder_version='enc-b15').entries
            log_case('nested_mutation', label, 'rejected', 'rejected', exc)
        except Exception as exc:
            log_case('nested_mutation', label, 'rejected', f'unexpected_{type(exc).__name__}', exc)

    # 5. Producer & Trusted Context admission binding negatives
    producer_binding_negatives = [
        ('absent_binding', lambda ctx: dict(ctx, admission_bindings=[
            dict(producer='other_producer', category='baseline', context_id=ctx['context_id'], binding_sha256='0'*64)
        ])),
        ('duplicate_binding', lambda ctx: dict(ctx, admission_bindings=ctx['admission_bindings'] * 2)),
        ('mismatched_context_id', lambda ctx: dict(ctx, admission_bindings=[
            dict(producer=ctx['admission_bindings'][0]['producer'], category='baseline', context_id='wrong-ctx', binding_sha256=ctx['admission_bindings'][0]['binding_sha256'])
        ])),
        ('mismatched_category', lambda ctx: dict(ctx, admission_bindings=[
            dict(producer=ctx['admission_bindings'][0]['producer'], category='unregistered_cat', context_id=ctx['context_id'], binding_sha256=ctx['admission_bindings'][0]['binding_sha256'])
        ])),
        ('bad_binding_sha256', lambda ctx: dict(ctx, admission_bindings=[
            dict(producer=ctx['admission_bindings'][0]['producer'], category='baseline', context_id=ctx['context_id'], binding_sha256='a'*64)
        ])),
    ]
    for label, mutator in producer_binding_negatives:
        m, f, e = make_fixture()
        mutated_ctx = mutator(e.trusted_context)
        forged = forge_evidence(e, trusted_context=mutated_ctx)
        try:
            m.promote(f.fragment_id, forged)
            log_case('producer_binding', label, 'rejected', 'promoted')
        except EvidenceRequired as exc:
            assert not m.slow_items()
            assert m.query_topology('b15-room', encoder_version='enc-b15').entries
            log_case('producer_binding', label, 'rejected', 'rejected', exc)
        except Exception as exc:
            log_case('producer_binding', label, 'rejected', f'unexpected_{type(exc).__name__}', exc)

    # 6. Subclass & missing attribute bypass
    m, f, e = make_fixture()
    class OverridingSubclass(PromotionEvidence):
        def __post_init__(self):
            pass
        def _validate_v2(self):
            pass
        def is_v2(self):
            return True
    sub_obj = object.__new__(OverridingSubclass)
    for field in fields(PromotionEvidence):
        object.__setattr__(sub_obj, field.name, getattr(e, field.name))
    object.__setattr__(sub_obj, 'kind', 'self_report')
    try:
        m.promote(f.fragment_id, sub_obj)
        log_case('subclass_override', 'subclass_bypass_attempt', 'rejected', 'promoted')
    except EvidenceRequired as exc:
        assert not m.slow_items()
        log_case('subclass_override', 'subclass_bypass_attempt', 'rejected', 'rejected', exc)
    except Exception as exc:
        log_case('subclass_override', 'subclass_bypass_attempt', 'rejected', f'unexpected_{type(exc).__name__}', exc)

    # Empty object
    try:
        m.promote(f.fragment_id, object.__new__(PromotionEvidence))
        log_case('missing_attributes', 'empty_object_new', 'rejected', 'promoted')
    except EvidenceRequired as exc:
        assert not m.slow_items()
        log_case('missing_attributes', 'empty_object_new', 'rejected', 'rejected', exc)
    except Exception as exc:
        log_case('missing_attributes', 'empty_object_new', 'rejected', f'unexpected_{type(exc).__name__}', exc)

    # 7. Memory lifecycle & MID semantics
    # Lifecycle: revoke & demote
    for action in ('revoke', 'demote'):
        m, f, e = make_fixture()
        m.promote(f.fragment_id, e)
        assert f.fragment_id in m.usable_slow_items(encoder_version='enc-b15', prior_version='prior-b15')
        if action == 'revoke':
            m.revoke(f.fragment_id, 'b15 audit revoke', 'b15/revoke-ref')
        else:
            m.demote(f.fragment_id, 'mid', 'b15 audit demote')
        usable = m.usable_slow_items(encoder_version='enc-b15', prior_version='prior-b15')
        topo = m.query_topology('b15-room', encoder_version='enc-b15')
        if f.fragment_id not in usable and len(topo.entries) > 0:
            log_case('lifecycle_mid', f'{action}_exits_slow_preserves_topology', 'excluded_and_readable', 'excluded_and_readable')
        else:
            log_case('lifecycle_mid', f'{action}_exits_slow_preserves_topology', 'excluded_and_readable', 'state_inconsistency')

    # v1 readable in memory but not promotable
    m, f, e = make_fixture()
    forged_v1 = forge_evidence(e, schema_version='v1')
    try:
        m.promote(f.fragment_id, forged_v1)
        log_case('lifecycle_mid', 'v1_readable_not_promotable', 'rejected', 'promoted')
    except EvidenceRequired as exc:
        topo = m.query_topology('b15-room', encoder_version='enc-b15')
        if len(topo.entries) > 0 and not m.slow_items():
            log_case('lifecycle_mid', 'v1_readable_not_promotable', 'rejected', 'rejected', exc)
        else:
            log_case('lifecycle_mid', 'v1_readable_not_promotable', 'rejected', 'topology_lost')
    except Exception as exc:
        log_case('lifecycle_mid', 'v1_readable_not_promotable', 'rejected', f'unexpected_{type(exc).__name__}', exc)

    loaded = sorted(x for x in sys.modules if x.split('.')[0] in ('mlx', 'torch', 'transformers', 'onnxruntime'))
    assert not loaded, f"prohibited models loaded: {loaded}"

    passed_count = sum(1 for r in results if r['passed'])
    failed_count = sum(1 for r in results if not r['passed'])

    output = {
        'total': len(results),
        'passed': passed_count,
        'failed': failed_count,
        'loaded_models': loaded,
        'results': results
    }
    print(json.dumps(output, indent=2))
    return 0 if failed_count == 0 else 1

if __name__ == '__main__':
    sys.exit(run_probe())
