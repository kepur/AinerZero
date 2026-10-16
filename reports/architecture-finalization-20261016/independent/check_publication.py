import concurrent.futures, datetime, difflib, hashlib, json, os, re, sys, urllib.parse, urllib.request
from pathlib import Path
ROOT=Path('/Users/mac/AinerWorkFlow/AinerZero');BASE=ROOT/'reports/architecture-finalization-20261016';OUT=BASE/'independent'
manifest_path=ROOT/'docs/architecture/baseline.v1.json';manifest=json.loads(manifest_path.read_text());checks=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rec(name,ok,detail=None):checks.append({'name':name,'ok':bool(ok),'detail':detail})
protected=[manifest_path,ROOT/'ARCHITECTURE_BASELINE.md',BASE/'REPORT.md',BASE/'architecture-publication.diff',BASE/'task-status-snapshot.json',BASE/'task-requirements-updated.json',BASE/'dependency-before.json',BASE/'dependency-after.json']
for group in ['published_documents','publication_entries','accepted_contracts_limited_scope','candidate_snapshots_not_adopted']:
    protected += [Path(x['path']) for x in manifest[group]]+[ROOT/x['snapshot'] for x in manifest[group]]
before={str(p):sha(p) for p in protected}
records=[]
for group in ['published_documents','publication_entries','accepted_contracts_limited_scope','candidate_snapshots_not_adopted']:
    for r in manifest[group]:
        snap=ROOT/r['snapshot'];live=Path(r['path'])
        x={'group':group,'path':str(live),'snapshot':str(snap),'declared_sha256':r['sha256'],'snapshot_sha256':sha(snap),'live_sha256':sha(live),'declared_bytes':r['bytes'],'snapshot_bytes':snap.stat().st_size,'live_bytes':live.stat().st_size,'classification':r['classification']}
        x['ok']=x['declared_sha256']==x['snapshot_sha256'] and x['declared_bytes']==x['snapshot_bytes'] and (r['live_path_mutable'] or x['declared_sha256']==x['live_sha256'])
        records.append(x);rec('frozen:'+live.name,x['ok'])
pre=json.loads((BASE/'pre-publication/identities.json').read_text())
for r in pre:rec('pre_archive:'+Path(r['path']).name,sha(Path(r['archive']))==r['sha256'])
reviewed=BASE/'pre-publication/ARCHITECTURE_V9.md';current=ROOT/'ARCHITECTURE_V9.md'
actual=''.join(difflib.unified_diff(reviewed.read_text().splitlines(True),current.read_text().splitlines(True),fromfile='reviewed-r5',tofile='published-r5'))
rec('publication_diff_exact',actual==(BASE/'architecture-publication.diff').read_text())
rec('reviewed_r5_identity',sha(reviewed)==manifest['reviews']['main_design']['reviewed_sha256'])
landing=Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/V9_LANDING_PLAN.md').read_bytes();oldlanding=(BASE/'pre-publication/AWZ-V9_LANDING_PLAN.md').read_bytes()
rec('landing_append_only',landing.startswith(oldlanding) and landing[len(oldlanding):].decode().lstrip().startswith('## 12.'))
negative=[]
for rel in manifest['historical_negative_reports_preserved']:
    p=ROOT/rel;negative.append({'path':str(p.resolve()),'exists':p.is_file(),'sha256':sha(p) if p.is_file() else None})
rec('historical_negative_reports_preserved',all(x['exists'] for x in negative))
rec('event_negative_report_unchanged',sha(Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/reports/V-V9-A8/codex-v101-20261016/REPORT.md'))=='9820286985f71c09176b44eb08959dafe32222407101dd956678ca7310f8c6d2')
rec('teacher_negative_report_unchanged',sha(ROOT/'reports/V-V9-T1-r2/codex-v101-20261016/REPORT.md')=='1df793d54a6e65cc635ead6dc3914d65d0f4596a0e22555a6e53bc23980419e5')
links=[]
for p in [ROOT/'ARCHITECTURE_BASELINE.md']:
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',p.read_text()):
        if re.match(r'^[a-z]+://',target) or target.startswith('#'):continue
        dst=(p.parent/urllib.parse.unquote(target.split('#')[0])).resolve()
        links.append({'source':str(p),'target':target,'resolved':str(dst),'exists':dst.exists()})
rec('new_index_local_links_exist',all(x['exists'] for x in links))
for n in ['README.md','COORDINATION.md','AGENT_TASKS.md']:
    intro='\n'.join((ROOT/n).read_text().splitlines()[:16]);rec('entry_pointer:'+n,'ARCHITECTURE_BASELINE.md' in intro and ('V9-r5-20261016' in intro or 'v9 r5' in intro))
rec('no_new_run_authorization',manifest['implementation_authorized'] is False and manifest['training_authorized'] is False and manifest['runtime_or_scientific_acceptance'] is False and not manifest['training_policy']['new_exception_approvals_in_this_baseline'])
rec('candidate_status_separate',all(r['classification']=='request_changes_not_adopted' for r in manifest['candidate_snapshots_not_adopted']) and len(manifest['pending_contract_work'])==2)

# Live independent HTTP reads. No relay.server/db import and no database access.
url=os.environ.get('RELAY_URL','http://127.0.0.1:8790').rstrip('/');headers={}
if os.environ.get('RELAY_TOKEN'):headers['X-Relay-Token']=os.environ['RELAY_TOKEN']
def get(path):
    request=urllib.request.Request(url+path,headers=headers)
    with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
health=get('/api/health');snapshot=json.loads((BASE/'task-status-snapshot.json').read_text());updates=json.loads((BASE/'task-requirements-updated.json').read_text())
ids={t['id'] for t in snapshot['tasks']} | {'awz.V9.A12','ainerzero.V9.T18','awz.V9.A10','ainerzero.V9.A7','ainerzero.V9.A8'}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: live=dict(zip(sorted(ids),pool.map(lambda i:get('/api/tasks/'+urllib.parse.quote(i,safe='')),sorted(ids))))
live_out=[]
for i,t in live.items():
    live_out.append({k:t.get(k) for k in ['id','status','kind','tier','author','assignee','depends_on','verifies','params','acceptance','prompt','updated_at']})
(OUT/'live-http-tasks.json').write_text(json.dumps({'captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'health':health,'tasks':live_out},ensure_ascii=False,indent=2)+'\n')
original=[]
for r in snapshot['original_19_checks']:
    t=live[r['id']];deps=set(t.get('depends_on') or []);old=set(r['original_dependencies'])
    x={'id':r['id'],'status':t['status'],'original_dependencies':sorted(old),'live_dependencies':sorted(deps),'ok':t['status']=='blocked' and old<=deps and 'awz.V9.A10' in deps};original.append(x)
rec('original_19_blocked_and_original_dependencies',len(original)==19 and all(x['ok'] for x in original))
rec('gated_21_exact_set',set(manifest['gated_21'])==set(manifest['paused_original_19'])|{'awz.V9.B9','awz.V9.B11'} and all('awz.V9.A10' in (live[i].get('depends_on') or []) for i in manifest['gated_21']))
rec('two_new_implementations_draft',all(live[i]['status']=='draft' for i in ['awz.V9.B9','awz.V9.B11']))
rec('gate_still_draft',live['awz.V9.A10']['status']=='draft')
rec('main_and_integration_design_accepted',all(live[i]['status']=='accepted' for i in ['ainerzero.V9.A5','awz.V9.A5']))
rec('negative_reviews_accepted_as_reports',all(live[i]['status']=='accepted' for i in ['awz.V9.A9','ainerzero.V9.T17']))
rec('candidate_designs_not_accepted',all(live[i]['status']!='accepted' for i in ['awz.V9.A8','ainerzero.V9.T1']))
rec('new_reviews_correct_verifies',live['awz.V9.A12'].get('verifies')==['awz.V9.A8'] and live['ainerzero.V9.T18'].get('verifies')==['ainerzero.V9.T1'])
updatechecks=[]
for x in updates:
    t=live[x['id']];old=x['preserved'];ok=t['status']==old['status'] and set(t.get('depends_on') or [])==set(old['depends_on']) and t.get('params')==old['params']
    updatechecks.append({'id':x['id'],'ok':ok,'recorded_preserved':old,'live_status':t['status'],'live_dependencies':t.get('depends_on'),'live_params':t.get('params')})
rec('eight_requirement_updates_preserve_other_fields',len(updatechecks)==8 and all(x['ok'] for x in updatechecks))
dep_before=json.loads((BASE/'dependency-before.json').read_text());dep_after=json.loads((BASE/'dependency-after.json').read_text())
rec('a3_dependency_restoration_only',dep_before['depends_on']==['awz.V9.A10'] and set(dep_after['depends_on'])=={'awz.P3.A2','awz.V9.A10'} and set(live['awz.P3.A3']['depends_on'])==set(dep_after['depends_on']) and all(dep_before[k]==dep_after[k] for k in ['status','params','acceptance','prompt','file_scope']))
modules=json.loads(Path('/Users/mac/AinerWorkFlow/AinerRelay/modules/modules.v1.json').read_text())['modules'];membership={}
for m in modules:
    for i in m.get('tasks',[]):membership.setdefault(i,[]).append(m['code'])
moduleids=['awz.V9.A12','ainerzero.V9.T18','ainerzero.V9.A7','ainerzero.V9.A8']
rec('new_publication_tasks_archived_once',all(len(membership.get(i,[]))==1 for i in moduleids),{i:membership.get(i) for i in moduleids})
rec('author_module_check_clean','未归档的未完成任务：无' in (BASE/'module-check.txt').read_text() and '登记表里写了但接力台找不到的任务：无' in (BASE/'module-check.txt').read_text())
rec('protected_inputs_unchanged',all(sha(Path(p))==h for p,h in before.items()))
result={'decision':'accept_design_publication' if all(x['ok'] for x in checks) else 'request_changes','checks':checks,'failures':[x for x in checks if not x['ok']],'frozen_records':records,'pre_archive_records':pre,'original_19_live_checks':original,'task_requirement_live_checks':updatechecks,'negative_reports':negative,'links':links,'input_sha256':{p:h for p,h in before.items() if p in [str(manifest_path),str(ROOT/'ARCHITECTURE_BASELINE.md'),str(ROOT/'ARCHITECTURE_V9.md'),str(BASE/'REPORT.md')]},'scope':'document_baseline_publication_only; no consumer/runtime/model/scientific acceptance'}
(OUT/'metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'decision':result['decision'],'checks':len(checks),'failures':result['failures'],'frozen_files':len(records),'live_tasks':len(live),'snapshot_created':True},ensure_ascii=False))
sys.exit(bool(result['failures']))
