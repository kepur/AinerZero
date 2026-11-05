import sys, json, hashlib, dataclasses, traceback
class BlockModels:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('mlx','torch'):
            raise RuntimeError('B14 prohibited model import: '+fullname)
sys.meta_path.insert(0, BlockModels())
from ainerzero.v9.interfaces.types import Fragment, PromotionEvidence
from ainerzero.v9.fakes.spatial_memory import FakeSpatialMemory
from ainerzero.v9.interfaces.errors import EvidenceRequired

def fixture(origin='sindy', producer='independent_test'):
    f=Fragment(fragment_id='b14-independent',t_ticks=37,place='b14-room',partition='development',encoder_version='enc-b14',metric=(2.,3.),provenance_ref='obs/b14-mechanism',object_keys=('obs/object-b14',),action_keys=('sensor/push-b14',))
    ctx='b14-independent-context'
    digest=hashlib.sha256(json.dumps(dict(category='baseline',context_id=ctx,producer=producer),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    e=PromotionEvidence(kind='independent_test',report_ref='b14/audit',producer=producer,test_id='b14-frozen-test',schema_version='v2',trusted_context=dict(context_id=ctx,issuer='b14-reviewer',admission_bindings=[dict(producer=producer,category='baseline',context_id=ctx,binding_sha256=digest)]),domain_ref='b14/domain',calibration=dict(method='split_conformal',alpha_dom=.1,n_cal=61,n_min=20,exchangeability_ref='b14/exchange',fpca_basis_ref='none'),error_control=dict(elond_state_ref='b14/elond',alpha_t=.02,attempts_N=2,test_id_frozen_ref='b14/freeze',frozen_test_id='b14-frozen-test',block_unit='world_cluster'),counterexample_ref='b14/counterexamples',origin_category=origin,data_identity=dict(discovery='b14-D',calibration='b14-C',test='b14-T'),regression_ref='b14/regression',entry_digest=f.content_digest(),encoder_version='enc-b14',prior_version='prior-b14')
    m=FakeSpatialMemory(); m.write(f)
    return m,f,e

rows=[]
def check(name, expected, fn):
    try:
        actual=fn(); ok=actual==expected
        rows.append(dict(name=name,expected=expected,actual=actual,pass_=ok))
    except Exception:
        rows.append(dict(name=name,expected=expected,error=traceback.format_exc(),pass_=False))

def promote(origin, mode='normal', field=None, value=None):
    m,f,e=fixture(origin)
    if mode=='new':
        forged=object.__new__(PromotionEvidence)
        for k,v in vars(e).items(): object.__setattr__(forged,k,v)
        e=forged
    if field: object.__setattr__(e,field,value)
    try:
        out=m.promote(f.fragment_id,e)
        assert out['level']=='slow' and f.fragment_id in m.usable_slow_items(encoder_version='enc-b14',prior_version='prior-b14')
        return 'promoted'
    except (EvidenceRequired,ValueError):
        assert not m.slow_items()
        assert m.query_topology('b14-room',encoder_version='enc-b14').entries
        return 'rejected'

for origin in ('llm','teacher'):
    check('normal_'+origin,'rejected',lambda o=origin:promote(o))
    check('object_new_'+origin,'rejected',lambda o=origin:promote(o,'new'))
    check('mutate_to_'+origin,'rejected',lambda o=origin:promote('sindy',field='origin_category',value=o))
for origin in ('sindy','symbolic','human','engineered'):
    check('positive_'+origin,'promoted',lambda o=origin:promote(o))
for origin in ('LLM','Teacher','llm ', '',None,'unregistered'):
    check('forged_unknown_'+repr(origin),'rejected',lambda o=origin:promote('sindy','new','origin_category',o))
check('forged_kind','rejected',lambda:promote('sindy','new','kind','self_report'))
check('forged_overlap','rejected',lambda:promote('sindy','new','data_identity',dict(discovery='same',calibration='same',test='same')))
for field,value in [('producer','student'),('trusted_context',{}),('schema_version','v1')]:
    check('forged_'+field,'rejected',lambda k=field,v=value:promote('sindy','new',k,v))
# Test mutable nested mappings after a valid construction, no object.__setattr__ needed.
def nested():
    m,f,e=fixture(); e.data_identity['test']=e.data_identity['discovery']
    try: m.promote(f.fragment_id,e); return 'promoted'
    except (EvidenceRequired,ValueError): return 'rejected'
check('nested_mapping_overlap','rejected',nested)
def lifecycle(action):
    m,f,e=fixture(); m.promote(f.fragment_id,e)
    if action=='revoke': m.revoke(f.fragment_id,'b14 failure','b14/new-evidence')
    else: m.demote(f.fragment_id,'mid','b14 downgrade')
    assert not m.usable_slow_items(encoder_version='enc-b14',prior_version='prior-b14')
    assert m.query_topology('b14-room',encoder_version='enc-b14').entries
    return 'excluded_and_readable'
for action in ('revoke','demote'): check(action,'excluded_and_readable',lambda a=action:lifecycle(a))
print(json.dumps(dict(rows=rows,passed=sum(r['pass_'] for r in rows),failed=sum(not r['pass_'] for r in rows),loaded_models=[x for x in sys.modules if x.split('.')[0] in ('mlx','torch')]),indent=2))
sys.exit(any(not r['pass_'] for r in rows))
