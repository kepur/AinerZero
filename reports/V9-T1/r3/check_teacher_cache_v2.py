"""T1 r3 CPU 参考核对；复用冻结 r2 的 builder/规范哈希，不是产品缓存。

validate / eligible：读取 records、独立上下文与调用方预期 SHA，非零为拒绝。
--suite：生成明确 synthetic 的候选夹具，子进程验证负例及单规则破坏对照。
--disable / --schema 仅供报告目录的破坏测试，不是生产开关或授权。
"""
import argparse
import copy
import hashlib
import json
import math
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
SCHEMA_PATH=ROOT/'contracts/v9/teacher_cache.v2.schema.json'
OLD=ROOT/'reports/V9-T1/r2-archive/reports/V9-T1/r2/check_teacher_cache_v2.py'
LEG=runpy.run_path(str(OLD),run_name='t1_frozen_r2_builders')
canon,sha=LEG['canon'],LEG['sha']
REGISTRY='adr-0005-current-approved-empty-20261016'
DOMAIN={'clock':'episode_relative','episode_id':'synthetic-episode-0001','epoch_id':'synthetic-epoch-0001','tick_hz':120}

def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def entry_id(e):
    return sha({'cache_key':e['cache_key'],'world_key':e['source']['world_key'],'partition':e['source']['partition'],
                'input_sha256':e['provenance']['upstream']['input_ref']['sha256'],'use':e['provenance']['derivation']['use']})

def schema_load(path=SCHEMA_PATH):
    s=json.loads(Path(path).read_text());Draft202012Validator.check_schema(s);return s

def subvalidator(s,name):
    x=copy.deepcopy(s);x.pop('oneOf');x['$ref']='#/$defs/'+name;return Draft202012Validator(x)

def near(a,b):return math.isclose(a,b,abs_tol=1e-9,rel_tol=0)

def store_problems(records,context,expected_context_sha256,schema=None,disabled=()):
    """先 fail closed，再做跨记录核对；context 的预期身份由调用方固定。"""
    schema=schema or schema_load();problems=[]
    v=Draft202012Validator(schema)
    if not isinstance(records,list) or not records:
        return ['records_structure']
    if any(not v.is_valid(r) for r in records):return ['schema']
    if context is None:return ['trusted_context_missing']
    if not expected_context_sha256 or ('context_identity' not in disabled and sha(context)!=expected_context_sha256):
        return ['trusted_context_identity']
    if not subvalidator(schema,'trusted_context').is_valid(context):return ['trusted_context_schema']
    # The current approved set is empty. Future formats do not grant exceptions.
    registry=context['approval_registry']
    if 'approval_registry' not in disabled and (registry['registry_id']!=REGISTRY or registry['entries']):
        return ['approval_registry_not_current_empty']
    manifest=context['source_manifest'];srcs=manifest['sources']
    if len({x['source_id'] for x in srcs})!=len(srcs):return ['duplicate_source_identity']
    source_by_id={x['source_id']:x for x in srcs};obs=context['observation']
    if not near(obs['t_s'],obs['t_ticks']/120):return ['trusted_observation_clock']
    blobs={r['cache_key']:r for r in records if r['record_type']=='teacher_blob'}
    if len(blobs)!=sum(r['record_type']=='teacher_blob' for r in records):return ['duplicate_blob_key']
    parts={}
    for b in blobs.values():
        k=b['key_material'];inp=k['input']
        if 'key' not in disabled and sha(k)!=b['cache_key']:problems.append('cache_key_mismatch')
        if 'tick_seconds' not in disabled and (len(inp['timestamps_ticks'])!=len(inp['timestamps_s']) or
            any(not near(t/120,s) for t,s in zip(inp['timestamps_ticks'],inp['timestamps_s']))):
            problems.append('blob_tick_seconds_mismatch')
    for e in (r for r in records if r['record_type']=='teacher_entry'):
        b=blobs.get(e['cache_key'])
        if b is None:problems.append('orphan_entry');continue
        k=b['key_material'];inp=k['input'];source=e['source'];up=e['provenance']['upstream'];dv=e['provenance']['derivation']
        if 'eid' not in disabled and entry_id(e)!=e['entry_id']:problems.append('entry_id_mismatch')
        if 'input' not in disabled and up['input_ref']['sha256']!=inp['sha256']:problems.append('input_mismatch')
        if 'derived' not in disabled and dv['teacher_id']!=k['teacher']['teacher_id']:problems.append('derivation_teacher_mismatch')
        if 'weights' not in disabled and dv['weights_sha256']!=[w['sha256'] for w in k['teacher']['weights']]:problems.append('derivation_weights_mismatch')
        if 'preprocess' not in disabled and dv['preprocess_spec_sha256']!=k['preprocess']['spec_sha256']:problems.append('derivation_preprocess_mismatch')
        if 'noise' not in disabled and k['teacher']['teacher_kind']=='feature' and e['noise_model_ref'] is not None:problems.append('feature_with_noise_model')
        ref=source['manifest_ref'];original=source_by_id.get(ref['source_id']) if ref['manifest_id']==manifest['manifest_id'] else None
        if 'source_binding' not in disabled and (original is None or original['world_key']!=source['world_key'] or
            original['partition']!=source['partition'] or original['upstream']!=up):problems.append('original_source_binding_mismatch')
        if 'domain' not in disabled and (source['time_domain']!=inp['time_domain'] or inp['time_domain']!=obs['time_domain'] or
            original is None or original['time_domain']!=inp['time_domain']):problems.append('observation_time_domain_mismatch')
        if 'source_times' not in disabled and (source['timestamps_ticks']!=inp['timestamps_ticks'] or source['timestamps_s']!=inp['timestamps_s']):
            problems.append('source_blob_timestamps_mismatch')
        if 'cutoff' not in disabled and (e['as_of_t_ticks']!=obs['t_ticks'] or not near(e['as_of_t_s'],obs['t_ticks']/120)):
            problems.append('current_observation_cutoff_mismatch')
        if 'asof' not in disabled and dv['use']=='input' and (max(inp['timestamps_ticks'])>obs['t_ticks'] or max(inp['timestamps_s'])>obs['t_s']+1e-9):
            problems.append('input_after_trusted_observation')
        elig=up['eligibility']
        if 'approval' not in disabled and elig['basis']=='adr_0005_revision':
            # No approved exception exists in the current frozen policy. A future
            # resolver must additionally match scope; no nonempty string is authority.
            problems.append('unapproved_adr_revision')
        if source['partition'] in ('train','development','final'):parts.setdefault(e['cache_key'],set()).add(source['partition'])
    if 'cross' not in disabled and any(len(p)>1 for p in parts.values()):problems.append('cross_partition_blob')
    return sorted(set(problems))

def train_eligible(e,records,context,expected_context_sha256,schema=None,disabled=()):
    """直接入口同样先完成所有结构/绑定/策略检查，异常或不存在均拒。"""
    if 'admission_validation' not in disabled and store_problems(records,context,expected_context_sha256,schema,disabled):return False
    try:
        if e not in records:return False
        b=next(r for r in records if r.get('record_type')=='teacher_blob' and r['cache_key']==e['cache_key'])
        if 'intersection' in disabled:return bool(b['teacher_license']['scope']['train'])
        return bool(e['provenance']['upstream']['eligibility']['train'] and b['teacher_license']['scope']['train'] and
            e['license']['scope']['train'] and b['reproducibility']!='unverified' and e['source']['partition']=='train')
    except (KeyError,TypeError,StopIteration):return False

def build_store():
    blobs=[]
    for tid,kind,inp,repro in [('vjepa2.1-vitl','feature','clip-0001','numeric'),('da3-small','geometry','kf-0001','numeric'),('vjepa2.1-vitl','feature','clip-0003','unverified')]:
        k=LEG['km'](teacher_id=tid,kind=kind,inp=inp);k['teacher'].update(variant='synthetic-contract-only',code_revision='synthetic-no-model-run');k['input'].update(time_domain=copy.deepcopy(DOMAIN),timestamps_ticks=list(range(0,80,5)),timestamps_s=[t/120 for t in range(0,80,5)])
        b=LEG['blob'](k,repro);b['teacher_license'].update(license_id='SYNTHETIC-NONPRODUCTION',source_url='https://example.invalid/synthetic-license',approval_ref='SYNTHETIC-NOT-AUTHORIZATION');b['generation'].update(argv=['synthetic-fixture-no-execution'],host='synthetic-no-runtime');blobs.append(b)
    es=[]
    for b,w,system,origin,noise in [(blobs[0],'awz:w1','awz','external_derived',None),(blobs[0],'gridlab:w2','ainerzero','observed',None),
        (blobs[1],'gridlab:w3','ainerzero','observed','nc-da3-small-pose@1.0'),(blobs[2],'gridlab:w4','ainerzero','observed',None)]:
        e=LEG['entry'](b,w,'train',system=system,origin=origin,noise=noise);e['source'].update(time_domain=copy.deepcopy(DOMAIN),timestamps_ticks=list(b['key_material']['input']['timestamps_ticks']),manifest_ref={'manifest_id':'synthetic-original-sources-r3','source_id':'synthetic-source-'+str(len(es)+1)})
        e['as_of_t_ticks']=75;e['provenance']['upstream']['input_ref']['uri']='synthetic://input/'+w;e['license'].update(license_id='SYNTHETIC-NONPRODUCTION',source_url='https://example.invalid/synthetic-license',approval_ref='SYNTHETIC-NOT-AUTHORIZATION');es.append(e)
    return blobs+es

def context_for(records,cutoff=75):
    sources=[]
    for e in (r for r in records if r['record_type']=='teacher_entry'):
        sources.append({'source_id':e['source']['manifest_ref']['source_id'],'world_key':e['source']['world_key'],'partition':e['source']['partition'],
            'upstream':copy.deepcopy(e['provenance']['upstream']),'time_domain':copy.deepcopy(e['source']['time_domain'])})
    return {'schema_version':'az.v9.teacher_cache.context.v1','context_id':'synthetic-context-r3','synthetic':True,
        'source_manifest':{'manifest_id':'synthetic-original-sources-r3','sources':sources},
        'observation':{'packet_ref':{'uri':'synthetic://observation/current','sha256':sha({'synthetic':'current-packet'})},'time_domain':copy.deepcopy(DOMAIN),'t_ticks':cutoff,'t_s':cutoff/120},
        'approval_registry':{'registry_id':REGISTRY,'entries':[]}}

def schema_mutation(s,name):
    s=copy.deepcopy(s);e=s['$defs']['teacher_entry'];pv=e['properties']['provenance']
    if name=='external_derived_may_train':pv['allOf'][0]={}
    elif name=='revision_ref_optional':pv['allOf'][1]={}
    elif name=='default_deny_unchecked':pv['allOf'][2]={}
    elif name=='old_origin_native_allowed':pv['additionalProperties']=True
    elif name=='as_of_optional':e['required'].remove('as_of_t_s')
    elif name=='awz_origin_combination_off':pv['properties']['upstream'].pop('allOf')
    else:raise ValueError(name)
    return s

def build_cases():
    base=build_store();cases=[]
    def one(awz=False):return copy.deepcopy([base[0],base[3 if awz else 4]])
    def add(name,records,want,reason=None,context=None,disable=None,mutation=None,expected=None,mode='validate'):
        c=context if context is not None else context_for(records)
        cases.append({'name':name,'records':records,'context':c,'expected_context_sha256':sha(c) if expected is None else expected,'valid':want,'reason':reason,'disable':disable,'schema_mutation':mutation,'mode':mode})
    add('valid_store',copy.deepcopy(base),True)
    add('cutoff_equals_last_frame',one(),True)
    st=one();st[1]['provenance']['derivation']['use']='target';st[1]['entry_id']=entry_id(st[1]);st[1]['as_of_t_ticks']=24;st[1]['as_of_t_s']=0.2
    add('future_target_isolated',st,True,context=context_for(st,24))
    # Old structural guards remain, with candidate r3 fields present.
    old_structural=[('external_derived_claims_train',['provenance','upstream','eligibility','train'],True,'external_derived_may_train',True),
        ('revision_basis_without_ref',['provenance','upstream','eligibility'],{'train':False,'basis':'adr_0005_revision','revision_ref':None},'revision_ref_optional',True),
        ('default_deny_but_train',['provenance','upstream','eligibility','basis'],'adr_0005_default_deny','default_deny_unchecked',False),
        ('old_v1_origin_native',['provenance','origin_native'],{'system':'ainerzero','origin':'observed','derived_by':'x','use':'input'},'old_origin_native_allowed',False),
        ('missing_as_of',['as_of_t_s'],None,'as_of_optional',False)]
    for n,path,value,mut,awz in old_structural:
        st=one(awz);o=st[1]
        for k in path[:-1]:o=o[k]
        if n=='missing_as_of':del o[path[-1]]
        else:o[path[-1]]=value
        if n=='external_derived_claims_train':st[1]['provenance']['upstream']['eligibility']['basis']='admit_training'
        c=context_for(st)
        # The revision-ref structural guard can be tested without claiming an approved revision.
        add(n,st,False,'schema',context=c,mutation=mut)
    st=one();del st[1]['provenance']['upstream']['actor'];add('upstream_missing_actor',st,False,'schema')
    st=one();st[1]['source']['partition']='sim_truth';add('partition_sim_truth',st,False,'schema')
    st=one();st[1]['source']['partition']='final';add('final_in_shared_store',st,False,'schema')
    # Each following dedicated case has exactly one semantic error.
    st=one();c=context_for(st,24);st[1]['as_of_t_ticks']=24;st[1]['as_of_t_s']=0.2
    add('input_after_as_of',st,False,'input_after_trusted_observation',context=c,disable='asof')
    st=one();e=copy.deepcopy(st[1]);e['source'].update(world_key='gridlab:dev',partition='development');e['source']['manifest_ref']['source_id']='synthetic-source-dev';e['provenance']['upstream']['eligibility']={'train':False,'basis':'not_train_partition','revision_ref':None};e['entry_id']=entry_id(e);st.append(e)
    add('cross_partition_blob',st,False,'cross_partition_blob',disable='cross')
    st=one();st[1]['provenance']['derivation']['teacher_id']='other-teacher';add('derivation_teacher_wrong',st,False,'derivation_teacher_mismatch',disable='derived')
    st=one();st[1]['provenance']['upstream']['input_ref']['sha256']='b'*64;st[1]['entry_id']=entry_id(st[1]);add('upstream_input_mismatch',st,False,'input_mismatch',disable='input')
    st=one();st[1]['cache_key']='f'*64;st[1]['entry_id']=entry_id(st[1]);add('orphan_entry',st,False,'orphan_entry')
    st=one();st[1]['noise_model_ref']='nc-feature@1.0';add('feature_entry_with_noise',st,False,'feature_with_noise_model',disable='noise')
    st=one();st[1]['license']['scope']['train']=False;add('intersection_entry_license_denied',st,False,'not_train_eligible',mode='eligible',disable='intersection')
    # T17's five original probes, against the unchanged independent base context.
    original_context=context_for(base)
    st=copy.deepcopy(base);st[3]['provenance']['upstream']['origin']='observed';st[3]['provenance']['upstream']['eligibility']=copy.deepcopy(st[4]['provenance']['upstream']['eligibility'])
    add('T17_awz_mislabeled_observed_train',st,False,'schema',context=original_context)
    st=copy.deepcopy(base);st[3]['provenance']['upstream']['eligibility'].update(train=True,basis='adr_0005_revision',revision_ref='not-an-approved-adr')
    add('T17_fake_nonempty_adr_revision',st,False,'original_source_binding_mismatch',context=original_context)
    st=copy.deepcopy(base);st[4]['source']['timestamps_s']=[0,0.1];st[4]['as_of_t_s']=0.2
    add('T17_unkeyed_source_timestamps_backdated',st,False,'source_blob_timestamps_mismatch',context=original_context)
    st=copy.deepcopy(base);st[4]['provenance']['derivation']['weights_sha256']=['b'*64]
    add('T17_derivation_weights_mismatch',st,False,'derivation_weights_mismatch',context=original_context)
    st=copy.deepcopy(base);st[4]['provenance']['derivation']['preprocess_spec_sha256']='c'*64
    add('T17_derivation_preprocess_mismatch',st,False,'derivation_preprocess_mismatch',context=original_context)
    # Independent witnesses: disabling only the named guard makes its own fixture pass.
    st=one(True);st[1]['provenance']['upstream']['origin']='observed';st[1]['provenance']['upstream']['eligibility']={'train':True,'basis':'admit_training','revision_ref':None}
    add('isolate_awz_origin_combination',st,False,'schema',mutation='awz_origin_combination_off')
    st=one();c=context_for(st);st[1]['provenance']['upstream']['actor']['actor_id']='copied-other-actor'
    add('isolate_original_source_binding',st,False,'original_source_binding_mismatch',context=c,disable='source_binding')
    st=one();st[1]['source']['timestamps_s']=[0,0.1];st[1]['source']['timestamps_ticks']=[0,12]
    add('isolate_source_blob_times',st,False,'source_blob_timestamps_mismatch',disable='source_times')
    st=one(True);st[1]['provenance']['upstream']['eligibility']={'train':True,'basis':'adr_0005_revision','revision_ref':'not-an-approved-adr'}
    add('isolate_unapproved_revision',st,False,'unapproved_adr_revision',disable='approval')
    st=one();st[1]['provenance']['derivation']['weights_sha256']=['b'*64]
    add('isolate_derivation_weights',st,False,'derivation_weights_mismatch',disable='weights')
    st=one();st[1]['provenance']['derivation']['preprocess_spec_sha256']='c'*64
    add('isolate_derivation_preprocess',st,False,'derivation_preprocess_mismatch',disable='preprocess')
    for field in ('episode_id','epoch_id'):
        st=one();st[1]['source']['time_domain'][field]='synthetic-other'
        add('cross_'+field,st,False,'observation_time_domain_mismatch',disable='domain')
    st=one();st[1]['as_of_t_ticks']=999;st[1]['as_of_t_s']=999/120
    add('self_advanced_cutoff',st,False,'current_observation_cutoff_mismatch',disable='cutoff')
    st=one();c=context_for(st);add('missing_trusted_context',st,False,'trusted_context_missing',context=c,expected='missing')
    st=one();add('wrong_context_digest',st,False,'trusted_context_identity',expected='0'*64,disable='context_identity')
    st=one();c=context_for(st);pin=sha(c);c['context_id']='synthetic-replaced-context'
    add('replaced_context_with_self_recomputed_hash',st,False,'trusted_context_identity',context=c,expected=pin,disable='context_identity')
    st=one();c=context_for(st);c['source_manifest']['sources']*=2
    add('duplicate_source_identity',st,False,'duplicate_source_identity',context=c)
    st=one();c=context_for(st);st[1]['source']['manifest_ref']['manifest_id']='other-manifest'
    add('unresolved_source_manifest',st,False,'original_source_binding_mismatch',context=c)
    st=one();st[0]['key_material']['input']['timestamps_s'][1]+=0.001;st[0]['cache_key']=sha(st[0]['key_material']);st[1]['cache_key']=st[0]['cache_key'];st[1]['source']['timestamps_s']=list(st[0]['key_material']['input']['timestamps_s']);st[1]['entry_id']=entry_id(st[1])
    add('tick_seconds_not_observation_clock',st,False,'blob_tick_seconds_mismatch',disable='tick_seconds')
    st=one();c=context_for(st);c['approval_registry']['registry_id']='untrusted-new-registry'
    add('registry_identity_replaced',st,False,'approval_registry_not_current_empty',context=c,disable='approval_registry')
    st=one();st[1]['provenance']['derivation']['weights_sha256']=['b'*64]
    add('direct_admission_validates_fingerprints',st,False,'not_train_eligible',mode='eligible',disable='admission_validation')
    st=one();b,e=st;b['key_material']['teacher']['weights'].append({'file':'w2.safetensors','sha256':'d'*64});b['cache_key']=sha(b['key_material']);e['cache_key']=b['cache_key'];e['entry_id']=entry_id(e);e['provenance']['derivation']['weights_sha256']=list(reversed([w['sha256'] for w in b['key_material']['teacher']['weights']]))
    add('ordered_weights_reversed',st,False,'derivation_weights_mismatch',disable='weights')
    st=one(True);c=context_for(st);c['approval_registry']['entries']=[{'revision_ref':'not-an-approved-adr','user_decision_ref':'synthetic-not-user-approval','status':'pending','source_scopes':[{'manifest_id':st[1]['source']['manifest_ref']['manifest_id'],'source_id':st[1]['source']['manifest_ref']['source_id'],'world_key':'awz:w1','partition':'train','input_sha256':st[1]['provenance']['upstream']['input_ref']['sha256']}]}]
    add('synthetic_pending_approval_is_not_current_registry',st,False,'approval_registry_not_current_empty',context=c,disable='approval_registry')
    st=one();c=context_for(st);c['source_manifest']['sources'][0]['upstream']['eligibility']['train']=False
    add('same_blob_other_source_eligibility_not_inherited',st,False,'original_source_binding_mismatch',context=c,disable='source_binding')
    st=one();c=context_for(st);st[1]['provenance']['upstream']['input_ref']['uri']='synthetic://wrong-input-location'
    add('original_input_ref_uri_mismatch',st,False,'original_source_binding_mismatch',context=c,disable='source_binding')
    return base,cases

def worker(args):
    schema=schema_load(args.schema);records=json.loads(Path(args.records).read_text())
    context=json.loads(Path(args.context).read_text()) if args.context else None
    if args.mode=='eligible':
        e=next((r for r in records if r.get('record_type')=='teacher_entry'),{})
        allowed=train_eligible(e,records,context,args.expected_context_sha256,schema,args.disable)
        errors=[] if allowed else ['not_train_eligible']
    else:errors=store_problems(records,context,args.expected_context_sha256,schema,args.disable)
    print(json.dumps({'errors':errors,'ok':not errors},ensure_ascii=False));return int(bool(errors))

def run_process(args):
    r=subprocess.run(args,capture_output=True,text=True)
    try:payload=json.loads(r.stdout);exception=False
    except json.JSONDecodeError:payload={'stdout':r.stdout,'stderr':r.stderr};exception=True
    return {'argv':args,'returncode':r.returncode,'payload':payload,'exception':exception}

def suite():
    schema=schema_load();base,cases=build_cases();fixture=ROOT/'contracts/v9/examples/teacher_cache_v2'
    # Old files remain in byte-identical r2-archive. Candidate fixtures are replaced.
    for p in fixture.rglob('*.json'):p.unlink()
    write(fixture/'valid/store.json',base);write(fixture/'contexts/baseline.json',context_for(base))
    rows=[];controls=[]
    for case in cases:
        name=case['name'];directory='valid' if case['valid'] else 'invalid'
        rp=fixture/directory/(name+'.json');cp=fixture/'contexts'/(name+'.json');write(rp,case['records']);write(cp,case['context'])
        pin=case['expected_context_sha256'];argv=[sys.executable,'-I',str(Path(__file__)),case['mode'],'--records',str(rp),'--expected-context-sha256',pin]
        if name!='missing_trusted_context':argv += ['--context',str(cp)]
        result=run_process(argv)
        errors=result['payload'].get('errors',[])
        result.update(name=name,expected_valid=case['valid'],expected_reason=case['reason'],ok=not result['exception'] and result['returncode']==(0 if case['valid'] else 1) and (case['reason'] is None or case['reason'] in errors))
        rows.append(result)
        if case['disable'] or case['schema_mutation']:
            ca=argv[:]
            if case['disable']:ca += ['--disable',case['disable']]
            if name=='revision_basis_without_ref':ca += ['--disable','approval']
            if name=='missing_as_of':ca += ['--disable','cutoff']
            if case['schema_mutation']:
                ms=schema_mutation(schema,case['schema_mutation']);mp=OUT/'sabotage-schemas'/(case['schema_mutation']+'.json');write(mp,ms);ca += ['--schema',str(mp)]
            cr=run_process(ca);cr.update(name=name,condition=case['disable'] or case['schema_mutation'],isolated=result['returncode']==1 and cr['returncode']==0 and not cr['exception'])
            controls.append(cr)
    # Old r2 is reproduced only inside a sandbox; it may generate its own fixtures.
    legacyroot=OUT/'r2-reproduction';(legacyroot/'contracts/v9').mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'reports/V9-T1/r2-archive/contracts/v9/teacher_cache.v2.schema.json',legacyroot/'contracts/v9/teacher_cache.v2.schema.json')
    legacy=run_process([sys.executable,'-I',str(OLD),str(legacyroot),str(legacyroot/'result.json')])
    oldresult=json.loads((legacyroot/'result.json').read_text())
    old_exceptions=[x for x in oldresult['sabotage'] if any('Error:' in p or 'Exception:' in p for p in x['caught_by'])]
    legacy['ok']=legacy['returncode']==0 and not legacy['exception'] and not old_exceptions and not oldresult['failures'] and len(oldresult['sabotage'])==11 and all(x['turned_red'] for x in oldresult['sabotage'])
    # Direct qualification outcomes and five conjunction guards use valid bound contexts.
    ctx=context_for(base);pin=sha(ctx);entries=[r for r in base if r['record_type']=='teacher_entry'];expected=[False,True,True,False]
    eligibility=[{'world_key':e['source']['world_key'],'got':train_eligible(e,base,ctx,pin,schema),'expected':want} for e,want in zip(entries,expected)]
    for row in eligibility:row['ok']=row['got']==row['expected']
    gates=[]
    for gate in ('upstream','teacher_license','entry_license','reproducibility','partition'):
        st=copy.deepcopy([base[0],base[4]]);b,e=st
        if gate=='upstream':e['provenance']['upstream']['eligibility']['train']=False
        elif gate=='teacher_license':b['teacher_license']['scope']['train']=False
        elif gate=='entry_license':e['license']['scope']['train']=False
        elif gate=='reproducibility':b['reproducibility']='unverified'
        else:e['source']['partition']='development';e['entry_id']=entry_id(e)
        c=context_for(st);errors=store_problems(st,c,sha(c),schema)
        # This checks the conjunction itself with all structural bindings valid.
        allowed=train_eligible(e,st,c,sha(c),schema)
        gates.append({'gate':gate,'problems':errors,'eligible':allowed,'ok':not errors and not allowed})
    expected_pins={c['name']:c['expected_context_sha256'] for c in cases};write(fixture/'expected-context-identities.json',{'synthetic':True,'pins':expected_pins})
    archive=[]
    for line in (ROOT/'reports/V9-T1/r2-archive/SHA256SUMS').read_text().splitlines():
        digest,path=line.split(None,1);p=ROOT/'reports/V9-T1/r2-archive'/path.strip();archive.append({'path':path.strip(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'ok':hashlib.sha256(p.read_bytes()).hexdigest()==digest})
    failures=[x['name'] for x in rows if not x['ok']]
    # Defensive overlap is grouped by its boundary (schema + policy/cutoff),
    # and every witness must become accepted without an exception.
    nonisolated=[x for x in controls if not x['isolated']]
    bad_controls=[x['name'] for x in nonisolated]
    all_ok=not failures and not bad_controls and legacy['ok'] and all(x['ok'] for x in eligibility+gates+archive)
    result={'synthetic_only':True,'all_ok':all_ok,'cases':rows,'controls':controls,'nonisolated_regression_controls':[x['name'] for x in nonisolated],
        'control_failures':bad_controls,'failures':failures,'legacy_r2':legacy,'legacy_counts':oldresult['counts'],'legacy_sabotage':oldresult['sabotage'],
        'eligibility':eligibility,'intersection_gates':gates,'archives':archive,
        'counts':{'positive_cases':sum(x['expected_valid'] for x in rows),'negative_cases':sum(not x['expected_valid'] for x in rows),'r3_controls':len(controls),'r3_isolated_controls':sum(x['isolated'] for x in controls),'r2_sabotage':len(oldresult['sabotage'])}}
    write(OUT/'check_result_v2.json',result);print(json.dumps({k:result[k] for k in ['all_ok','counts','failures','control_failures','nonisolated_regression_controls']},ensure_ascii=False));return int(not all_ok)

def main():
    p=argparse.ArgumentParser();p.add_argument('--suite',action='store_true');p.add_argument('mode',nargs='?',choices=['validate','eligible']);p.add_argument('--records');p.add_argument('--context');p.add_argument('--expected-context-sha256');p.add_argument('--schema',default=str(SCHEMA_PATH));p.add_argument('--disable',action='append',default=[]);a=p.parse_args()
    if a.suite:return suite()
    if not a.mode or not a.records:p.error('validate/eligible need --records')
    return worker(a)

if __name__=='__main__':sys.exit(main())
