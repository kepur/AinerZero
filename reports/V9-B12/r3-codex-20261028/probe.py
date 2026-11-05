"""Same inputs for ordinary rejection and isolated actual-promotion controls."""
import json
import sys
from dataclasses import fields

from ainerzero.v9.fakes import FakeGeometryCore, FakeSpatialMemory
from ainerzero.v9.interfaces.types import PromotionEvidence
from ainerzero.v9.interfaces.errors import EvidenceRequired
from conftest import trusted_context_for, v2_evidence
from test_spatial_memory import promotable

rows = []
for case in ('positive', 'G1', 'G5', 'origin', 'overlap', 'kind'):
    memory = FakeSpatialMemory(FakeGeometryCore())
    fragment = promotable('r3-' + case)
    item = memory.write(fragment)
    evidence = v2_evidence(fragment)
    if case in ('G1', 'kind'):
        forged = object.__new__(PromotionEvidence)
        for field in fields(PromotionEvidence):
            object.__setattr__(forged, field.name, getattr(evidence, field.name))
        object.__setattr__(forged, 'schema_version' if case == 'G1' else 'kind',
                           'v1' if case == 'G1' else 'self_report')
        evidence = forged
    if case == 'G5':
        evidence.trusted_context['admission_bindings'] = trusted_context_for('independent_test')['admission_bindings']
    if case == 'origin':
        # Valid v2 origin: removing only the SLOW origin gate is sufficient.
        object.__setattr__(evidence, 'origin_category', 'llm')
    if case == 'overlap':
        evidence.data_identity['test'] = evidence.data_identity['discovery']
    try:
        result = memory.promote(item, evidence)
        usable = memory.usable_slow_items(encoder_version='enc-v1', prior_version='fprior-v9-r5')
        assert result['level'] == 'slow' and item in usable
        rows.append({'case': case, 'outcome': 'promoted_and_usable'})
    except EvidenceRequired as exc:
        assert not memory.slow_items()
        assert memory.query_topology('room-a', encoder_version='enc-v1').entries
        rows.append({'case': case, 'outcome': 'rejected', 'reason': str(exc)})
    except Exception as exc:
        rows.append({'case': case, 'outcome': 'unexpected_exception', 'type': type(exc).__name__, 'reason': str(exc)})
loaded = sorted(x for x in sys.modules if x.split('.')[0] in ('mlx', 'torch', 'onnxruntime', 'transformers'))
print(json.dumps({'rows': rows, 'loaded_models': loaded}, allow_nan=False))
assert not loaded
assert all(row['outcome'] != 'unexpected_exception' for row in rows)
