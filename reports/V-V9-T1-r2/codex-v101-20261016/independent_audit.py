import copy, hashlib, json, runpy, shutil, subprocess, sys
from pathlib import Path
from jsonschema import Draft202012Validator
ROOT=Path('/Users/mac/AinerWorkFlow/AinerZero');OUT=Path(__file__).parent
SC=json.loads((ROOT/'contracts/v9/teacher_cache.v2.schema.json').read_text());V=Draft202012Validator(SC)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def key(o):return hashlib.sha256(json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def eligibility(e,b,strict=False):
    u=e['provenance']['upstream'];x=u['eligibility']
    result=all((x['train'],b['teacher_license']['scope']['train'],e['license']['scope']['train'],b['reproducibility']!='unverified',e['source']['partition']=='train'))
    if strict and (u['system']=='awz' and u['origin']!='external_derived' or u['origin']=='external_derived'):result=False # Current approved ADR revision registry is empty.
    return bool(result)
def entryid(e):
    return key({'cache_key':e['cache_key'],'world_key':e['source']['world_key'],'partition':e['source']['partition'],'input_sha256':e['provenance']['upstream']['input_ref']['sha256'],'use':e['provenance']['derivation']['use']})
def validate(data,strict=False):
    if isinstance(data,dict):return [x.message for x in V.iter_errors(data)]
    errors=[x.message for r in data for x in V.iter_errors(r)]
    blobs={b['cache_key']:b for b in data if b['record_type']=='teacher_blob'};parts={}
    for b in blobs.values():
        if b['cache_key']!=key(b['key_material']):errors+=['content_key']
    for e in [r for r in data if r['record_type']=='teacher_entry']:
        b=blobs.get(e['cache_key'])
        if not b:errors+=['orphan'];continue
        k=b['key_material'];u=e['provenance']['upstream'];d=e['provenance']['derivation'];s=e['source']
        if e['entry_id']!=entryid(e):errors+=['entryid']
        if u['input_ref']['sha256']!=k['input']['sha256']:errors+=['upstream_input_digest']
        if d['teacher_id']!=k['teacher']['teacher_id']:errors+=['teacher_id']
        if k['teacher']['teacher_kind']=='feature' and e['noise_model_ref'] is not None:errors+=['feature_noise']
        if d['use']=='input' and max(s['timestamps_s'])>e['as_of_t_s']:errors+=['after_asof']
        if s['partition']!='quarantine':parts.setdefault(e['cache_key'],set()).add(s['partition'])
        if strict:
            if u['system']=='awz' and u['origin']!='external_derived':errors+=['awz_origin_laundered']
            if s['timestamps_s']!=k['input']['timestamps_s']:errors+=['timestamps_not_bound_to_blob']
            if d['use']=='input' and max(k['input']['timestamps_s'])>e['as_of_t_s']:errors+=['immutable_input_after_asof']
            if d['weights_sha256']!=[w['sha256'] for w in k['teacher']['weights']]:errors+=['derivation_weights_unbound']
            if d['preprocess_spec_sha256']!=k['preprocess']['spec_sha256']:errors+=['derivation_preprocess_unbound']
            if u['origin']=='external_derived' and u['eligibility']['train']:errors+=['no_registered_approved_adr_revision']
    if any(len(s)>1 for s in parts.values()):errors+=['cross_partition']
    return errors
if len(sys.argv)>1:
    data=json.loads(Path(sys.argv[1]).read_text())
    if '--author' in sys.argv:
        m=runpy.run_path(str(ROOT/'reports/V9-T1/r2/check_teacher_cache_v2.py'))
        errors=[x.message for r in (data if isinstance(data,list) else [data]) for x in V.iter_errors(r)]
        if isinstance(data,list):errors+=m['store_problems'](data)
    else:errors=validate(data,'--strict' in sys.argv)
    print(json.dumps(errors));sys.exit(bool(errors))
protected=[ROOT/'docs/v9/TEACHERS_AND_CACHE.md',ROOT/'contracts/v9/teacher_cache.v2.schema.json',ROOT/'reports/V9-T1/r2/REPORT.md',ROOT/'reports/V9-T1/r2/check_teacher_cache_v2.py']+list((ROOT/'contracts/v9/examples/teacher_cache_v2').rglob('*.json'))
before={str(p):sha(p) for p in protected}
ar=ROOT/'reports/V9-T1/r1-archive';archives=[]
for line in (ar/'SHA256SUMS.txt').read_text().splitlines():
    h,n=line.split(None,1);p=ar/n.strip();archives.append({'path':str(p),'sha256':sha(p),'ok':sha(p)==h})
sandbox=OUT/'author-sandbox';(sandbox/'contracts/v9').mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'contracts/v9/teacher_cache.v2.schema.json',sandbox/'contracts/v9/teacher_cache.v2.schema.json')
cmd=[sys.executable,'-I',str(ROOT/'reports/V9-T1/r2/check_teacher_cache_v2.py'),str(sandbox),str(OUT/'author_result.json')];r=subprocess.run(cmd,capture_output=True,text=True);authorrc=r.returncode;(OUT/'author_stdout.txt').write_text(r.stdout+r.stderr)
fixtures=[]
for p in sorted((ROOT/'contracts/v9/examples/teacher_cache_v2').rglob('*.json')):
    errors=validate(json.loads(p.read_text()));want='invalid' not in p.parts
    fixtures.append({'file':str(p.relative_to(ROOT)),'ok':(not errors)==want,'errors':errors[:4]})
st=json.loads((ROOT/'contracts/v9/examples/teacher_cache_v2/valid/store.json').read_text());new=[]
def case(n,d,want=False,strict=False):
    p=OUT/'new-cases'/f'{n}.json';p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(d,indent=2)+'\n')
    r=subprocess.run([sys.executable,'-I',str(Path(__file__)),str(p)]+(['--strict'] if strict else []),capture_output=True,text=True)
    ar=subprocess.run([sys.executable,'-I',str(Path(__file__)),str(p),'--author'],capture_output=True,text=True)
    blobs={b['cache_key']:b for b in d if b['record_type']=='teacher_blob'} if isinstance(d,list) else {}
    eligible={e['source']['world_key']:eligibility(e,blobs[e['cache_key']]) for e in d if e['record_type']=='teacher_entry'} if isinstance(d,list) else {}
    new.append({'name':n,'strict_candidate':strict,'expected_valid':want,'returncode':r.returncode,'author_returncode':ar.returncode,'errors':json.loads(r.stdout),'author_errors':json.loads(ar.stdout),'current_five_way_eligibility':eligible,'ok':(r.returncode==0)==want})
d=copy.deepcopy(st);u=d[3]['provenance']['upstream']['eligibility'];u.update(basis='adr_0005_revision',train=True,revision_ref='');case('revision_ref_empty',d)
d=copy.deepcopy(st);d[3]['provenance']['upstream']['eligibility']=copy.deepcopy(d[4]['provenance']['upstream']['eligibility']);case('copy_az_eligibility_to_awz',d)
d=copy.deepcopy(st);d[4]['as_of_t_s']=0.1;case('ordinary_asof_before_last_frame',d)
d=copy.deepcopy(st);del d[3]['provenance']['upstream']['actor'];case('upstream_actor_removed',d)
d=copy.deepcopy(st);d[4]['provenance']['derivation']['teacher_id']='unrelated';case('derived_teacher_replaced',d)
d=copy.deepcopy(st);d[4]['provenance']['upstream']['input_ref']['sha256']='b'*64;d[4]['entry_id']=entryid(d[4]);case('input_digest_changed_rehashed_entry',d)
d=copy.deepcopy(st);e=copy.deepcopy(d[4]);e['source']['partition']='development';e['source']['world_key']='az:other';e['provenance']['upstream']['eligibility']['train']=False;e['entry_id']=entryid(e);d.append(e);case('same_blob_cross_partition',d)
d=copy.deepcopy(st);d[3]['provenance']['upstream']['eligibility'].update(train=True,basis='adr_0005_default_deny');case('default_deny_with_train',d)
d=copy.deepcopy(st);d[4]['provenance']['derivation']['use']='target';d[4]['entry_id']=entryid(d[4]);d[4]['as_of_t_s']=0.1;case('future_target_isolated_by_use',d,True)
d=copy.deepcopy(st);d[4]['as_of_t_s']=max(d[4]['source']['timestamps_s']);case('asof_equals_last_frame',d,True)
# Missing protocol/checker binding candidates.
d=copy.deepcopy(st);u=d[3]['provenance']['upstream'];u['origin']='observed';u['eligibility']=copy.deepcopy(d[4]['provenance']['upstream']['eligibility']);case('awz_mislabeled_observed_train',d,strict=True)
d=copy.deepcopy(st);d[3]['provenance']['upstream']['eligibility'].update(train=True,basis='adr_0005_revision',revision_ref='not-an-approved-adr');case('fake_nonempty_adr_revision',d,strict=True)
d=copy.deepcopy(st);d[4]['source']['timestamps_s']=[0.0,0.1];d[4]['as_of_t_s']=0.2;case('unkeyed_source_timestamps_backdated',d,strict=True)
d=copy.deepcopy(st);d[4]['provenance']['derivation']['weights_sha256']=['b'*64];case('derivation_weights_mismatch',d,strict=True)
d=copy.deepcopy(st);d[4]['provenance']['derivation']['preprocess_spec_sha256']='c'*64;case('derivation_preprocess_mismatch',d,strict=True)
blobs={b['cache_key']:b for b in st if b['record_type']=='teacher_blob'}
elig={e['source']['world_key']:eligibility(e,blobs[e['cache_key']]) for e in st if e['record_type']=='teacher_entry'}
expected={'awz:w1':False,'gridlab:w2':True,'gridlab:w3':True,'gridlab:w4':False}
# Gate independence: each conjunct must individually reject an otherwise eligible entry.
gates={};e=copy.deepcopy(st[4]);b=copy.deepcopy(blobs[e['cache_key']])
for n in ('upstream','teacher_license','entry_license','reproducibility','partition'):
    x=copy.deepcopy(e);y=copy.deepcopy(b)
    if n=='upstream':x['provenance']['upstream']['eligibility']['train']=False
    elif n=='teacher_license':y['teacher_license']['scope']['train']=False
    elif n=='entry_license':x['license']['scope']['train']=False
    elif n=='reproducibility':y['reproducibility']='unverified'
    else:x['source']['partition']='development'
    gates[n]=not eligibility(x,y)
result={'input_sha256':{p:h for p,h in before.items() if '/examples/' not in p},'archives':archives,'author_argv':cmd,'author_returncode':authorrc,'author_stdout':(OUT/'author_stdout.txt').read_text(),'fixtures':fixtures,'baseline_eligibility':elig,'baseline_eligibility_pass':elig==expected,'independent_intersection_gates':gates,'new_cases':new,'strict_probes_accepted_by_author':[x['name'] for x in new if x['strict_candidate'] and x['author_returncode']==0],'protected_unchanged':all(sha(Path(p))==h for p,h in before.items()),'required_checks_pass':authorrc==0 and all(x['ok'] for x in archives+fixtures+new) and elig==expected and all(gates.values())}
(OUT/'metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'required_checks_pass':result['required_checks_pass'],'fixtures':len(fixtures),'accepted_strict_probes':result['strict_probes_accepted_by_author'],'protected_unchanged':result['protected_unchanged']}))
sys.exit(not result['required_checks_pass'])
