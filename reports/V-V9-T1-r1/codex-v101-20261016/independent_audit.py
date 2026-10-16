import copy, hashlib, json, shutil, subprocess, sys
from pathlib import Path
from jsonschema import Draft202012Validator
ROOT=Path('/Users/mac/AinerWorkFlow/AinerZero'); OUT=Path(__file__).parent
SCHEMA=json.loads((ROOT/'contracts/v9/teacher_cache.v1.schema.json').read_text()); V=Draft202012Validator(SCHEMA)
def shaobj(d): return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def validate(records):
    if isinstance(records,dict): records=[records]
    errors=[e.message for r in records for e in V.iter_errors(r)]
    blobs={r.get('cache_key'):r for r in records if r.get('record_type')=='teacher_blob'}
    partitions={}
    for b in blobs.values():
        if shaobj(b['key_material'])!=b['cache_key']: errors+=['bad_content_key']
        if b['teacher_license']['approval_ref'] is None: errors+=['unapproved']
    for e in [r for r in records if r.get('record_type')=='teacher_entry']:
        b=blobs.get(e['cache_key'])
        if b is None: errors+=['orphan']; continue
        k=b['key_material']; src=e['source']; native=e['provenance']['origin_native']
        expected=shaobj({'cache_key':e['cache_key'],'world_key':src['world_key'],'partition':src['partition'],'input_sha256':src['input_ref']['sha256'],'use':native['use']})
        if expected!=e['entry_id']: errors+=['bad_entry_id']
        if src['input_ref']['sha256']!=k['input']['sha256']: errors+=['input_digest_mismatch']
        if native['derived_by']!=k['teacher']['teacher_id']: errors+=['teacher_mismatch']
        if k['teacher']['teacher_kind']=='feature' and e['noise_model_ref'] is not None: errors+=['feature_noise']
        if src['partition']!='quarantine': partitions.setdefault(e['cache_key'],set()).add(src['partition'])
    if any(len(ps)>1 for ps in partitions.values()): errors+=['cross_partition']
    return errors
if len(sys.argv)>1:
    errors=validate(json.loads(Path(sys.argv[1]).read_text()));print(json.dumps(errors));sys.exit(bool(errors))

protected=[ROOT/'docs/v9/TEACHERS_AND_CACHE.md',ROOT/'contracts/v9/teacher_cache.v1.schema.json',ROOT/'reports/V9-T1/r1/lock_model_check.py',ROOT/'reports/V9-T1/r1/check_teacher_cache_v1.py']+list((ROOT/'contracts/v9/examples/teacher_cache_v1').rglob('*.json'))
before={str(p):sha(p) for p in protected}
archives=[]; ar=ROOT/'reports/V9-T1/r0-archive'
mapping={'REPORT.r0.md':'reports/V9-T1/REPORT.md','TEACHERS_AND_CACHE.r0.md':'docs/v9/TEACHERS_AND_CACHE.md','check_result.r0.json':'reports/V9-T1/check_result.json','teacher_cache.v0.schema.json':'contracts/v9/teacher_cache.v0.schema.json'}
for line in (ar/'SHA256SUMS.txt').read_text().splitlines():
    expected,n=line.split(None,1); n=n.strip(); r=subprocess.run(['git','-C',str(ROOT),'show','995db72:'+mapping[n]],capture_output=True)
    archives.append({'name':n,'declared':expected,'actual':sha(ar/n),'git_path':mapping[n],'git_rc':r.returncode,'git_sha':hashlib.sha256(r.stdout).hexdigest(),'ok':r.returncode==0 and expected==sha(ar/n)==hashlib.sha256(r.stdout).hexdigest()})
sandbox=OUT/'author-sandbox';(sandbox/'contracts/v9').mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'contracts/v9/teacher_cache.v1.schema.json',sandbox/'contracts/v9/teacher_cache.v1.schema.json')
commands=[ [sys.executable,'-I',str(ROOT/'reports/V9-T1/r1/lock_model_check.py'),str(OUT/'author_lock.json')], [sys.executable,'-I',str(ROOT/'reports/V9-T1/r1/check_teacher_cache_v1.py'),str(sandbox),str(OUT/'author_cache.json')] ]
author=[]
for i,cmd in enumerate(commands):
    r=subprocess.run(cmd,capture_output=True,text=True);(OUT/f'author_{i}_stdout.txt').write_text(r.stdout+r.stderr);author.append({'argv':cmd,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
fixtures=[]
for p in sorted((ROOT/'contracts/v9/examples/teacher_cache_v1').rglob('*.json')):
    d=json.loads(p.read_text()); expected='invalid' not in p.parts
    # Single-record structure fixtures do not represent a whole store.
    errors=validate(d) if isinstance(d,list) else [e.message for e in V.iter_errors(d)]
    fixtures.append({'path':str(p.relative_to(ROOT)),'expected_valid':expected,'ok':(not errors)==expected,'errors':errors[:5]})

# Independent exhaustive state-tree search: do not import author's protocol/checker.
# Each recursive edge schedules one currently enabled process operation; failed
# nonblocking acquire terminates that process and releases its held locks.
def explore(programs):
    violations=[]; terminal=0; examined=0
    def visit(pc,owners,active,trace):
        nonlocal terminal,examined
        examined+=1
        if sum(active)>1: violations.append(trace); return
        if all(pc[i]>=len(programs[i]) for i in range(2)): terminal+=1;return
        for who in range(2):
            if pc[who]>=len(programs[who]):continue
            op,lk=programs[who][pc[who]]; p=list(pc);p[who]+=1; o=dict(owners);a=list(active)
            if op=='take':
                if lk in o:
                    p[who]=len(programs[who]);o={k:v for k,v in o.items() if v!=who};a[who]=False
                else:o[lk]=who
            elif op=='drop':o={k:v for k,v in o.items() if not(k==lk and v==who)}
            elif op=='begin':a[who]=True
            elif op=='end':a[who]=False
            visit(tuple(p),o,tuple(a),trace+[(who,op,lk)])
    visit((0,0),{},(False,False),[])
    return {'violations':len(violations),'first_trace':violations[:1],'terminal_paths':terminal,'tree_nodes':examined}
T=lambda lock: [('take',lock),('begin',''),('end',''),('drop',lock)]
r0={'teacher':[('take','m0'),('drop','m0'),('take','teacher'),('begin',''),('end',''),('drop','teacher')], 'train':[('take','m0'),('take','teacher'),('drop','teacher'),('begin',''),('end',''),('drop','m0')], 'world':T('teacher'),'legacy':T('m0')}
r1={m:T('m0') for m in ('teacher','train','world','legacy')}
indlock={'r0':{a+'|'+b:explore([r0[a],r0[b]]) for a,b in [('teacher','train'),('train','world'),('teacher','legacy')]},'r1':{a+'|'+b:explore([r1[a],r1[b]]) for a in r1 for b in r1},'mutations':{}}
indlock['mutations']['release_early']=explore([[('take','m0'),('drop','m0'),('begin',''),('end','')],T('m0')])
indlock['mutations']['occupy_before_lock']=explore([[('begin',''),('take','m0'),('end',''),('drop','m0')],T('m0')])
indlock['mutations']['world_second_lock']=explore([T('teacher'),T('m0')])
(OUT/'independent_lock.json').write_text(json.dumps(indlock,indent=2)+'\n')

store=json.loads((ROOT/'contracts/v9/examples/teacher_cache_v1/valid/store.json').read_text()); new=[]
def eid(e):
    s=e['source'];return shaobj({'cache_key':e['cache_key'],'world_key':s['world_key'],'partition':s['partition'],'input_sha256':s['input_ref']['sha256'],'use':e['provenance']['origin_native']['use']})
def case(name,d,want):
    p=OUT/'new-cases'/f'{name}.json';p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(d,indent=2)+'\n')
    r=subprocess.run([sys.executable,'-I',str(Path(__file__)),str(p)],capture_output=True,text=True)
    new.append({'name':name,'expected_valid':want,'returncode':r.returncode,'ok':(r.returncode==0)==want,'errors':json.loads(r.stdout)})
d=copy.deepcopy(store);d[0]['world_key']='awz:smuggled';case('blob_smuggles_source',d,False)
d=copy.deepcopy(store);d[-1]['store']='shared';case('final_shared',d,False)
d=copy.deepcopy(store);d[4]['source']['partition']='sim_truth';d[4]['entry_id']=eid(d[4]);case('sim_truth_partition',d,False)
d=copy.deepcopy(store);e=copy.deepcopy(d[4]);e['source']['partition']='development';e['source']['world_key']='awz:new-dev';e['entry_id']=eid(e);d.append(e);case('same_content_new_dev_world',d,False)
d=copy.deepcopy(store);d[4]['source']['input_ref']['sha256']='b'*64;d[4]['entry_id']=eid(d[4]);case('input_modified_rehashed_entry',d,False)
d=copy.deepcopy(store);d[4]['provenance']['origin_native']['derived_by']='other-teacher';case('false_teacher',d,False)
d=copy.deepcopy(store);d[0]['key_material']['teacher']['runtime']['dtype']='float16';case('runtime_modified_stale_key',d,False)
d=copy.deepcopy(store);d[0]['generation']['lease']['held_from_start_to_end']=False;case('lease_false',d,False)
d=copy.deepcopy(store);e=copy.deepcopy(d[4]);e['source']['partition']='quarantine';e['source']['world_key']='awz:new-quarantine';e['entry_id']=eid(e);d.append(e);case('same_blob_quarantine_allowed',d,True)

# Cross-contract source-preservation probe, not a new admission implementation.
external=copy.deepcopy(store);external[4]['provenance']['origin_native']['origin']='external_derived'
external_errors=[e.message for e in V.iter_errors(external[4])]
source_gap={'source_input_origin':'external_derived','source_packet_contract':'awz.observation_packet.v1.1','cache_origin_schema':SCHEMA['$defs']['teacher_entry']['properties']['provenance']['properties']['origin_native']['properties']['origin'],'preserved_origin_rejected':bool(external_errors),'schema_errors':external_errors,'observed_baseline_accepted':not validate(store),'note':'No actual image or model was used. Schema only admits observed, so AWZ provenance cannot be preserved without revision; never reinterpret actor=student as observed.'}
(OUT/'source-preservation-gap.json').write_text(json.dumps(source_gap,indent=2)+'\n')
lockok=all(x['violations']>0 for x in indlock['r0'].values()) and not any(x['violations'] for x in indlock['r1'].values()) and all(x['violations']>0 for x in indlock['mutations'].values())
metrics={'archives':archives,'author_runs':author,'independent_fixtures':fixtures,'new_cases':new,'lock_model_required_pass':lockok,'protected_unchanged':all(sha(Path(p))==h for p,h in before.items()),'input_sha256':{p:h for p,h in before.items() if '/examples/' not in p},'source_preservation':source_gap,'required_contract_checks_pass':all(x['ok'] for x in archives+fixtures+new) and all(x['returncode']==0 for x in author) and lockok,'recommend_unconditional_acceptance':False}
(OUT/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'required_contract_checks_pass':metrics['required_contract_checks_pass'],'fixtures':len(fixtures),'new_negative':sum(not x['expected_valid'] for x in new),'source_preservation_gap':bool(external_errors),'protected_unchanged':metrics['protected_unchanged']}))
sys.exit(not metrics['required_contract_checks_pass'])
