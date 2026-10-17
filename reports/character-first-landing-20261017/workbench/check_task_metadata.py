"""Read-only task metadata audit; no application imports, tests, DB, or API write."""
import json,hashlib,datetime,urllib.request,collections
from pathlib import Path
P=Path('/Users/mac/AinerWorkFlow/AinerZero/reports/character-first-landing-20261017/workbench')
def get(path):
 with urllib.request.urlopen('http://127.0.0.1:8790'+path,timeout=30) as r:return json.load(r)
def write(name,obj):(P/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
payloads=json.loads((P/'payloads.json').read_text()); mapping=json.loads((P/'module-mapping.json').read_text());patch=json.loads((P/'old-task-additive-patch.json').read_text())
boards={name:json.loads((P/(name+'-board.json')).read_text()) for name in ['awz','hub','ainerzero','forge']}
graph={}; raw={}
for board in boards.values():
 for phase in board['phases']:
  for track in phase['tracks']:
   for task in track['tasks']:
    graph[task['id']]=[x['id'] for x in task['deps']]
for t in payloads:
 tid=f'{t["project"]}.CF.{t["track"]}{t["seq"]}';raw[tid]=t;graph[tid]=t['depends_on']
graph['awz.P3.A3']=patch['payload']['fields']['depends_on']
missing=[];cycles=[];visited=set();active=[]
def visit(k):
 if k in active:
  cycles.append(active[active.index(k):]+[k]);return
 if k in visited:return
 if k not in graph:missing.append(k);return
 active.append(k)
 for dep in graph[k]:visit(dep)
 active.pop();visited.add(k)
for tid in raw:visit(tid)
allowed={'text','code','math','vision','godot','multimodal','longrun'}
needs_errors={k:[n for n in t['needs'] if n not in allowed] for k,t in raw.items() if any(n not in allowed for n in t['needs'])}
module_codes={m['code'] for m in json.loads((P/'modules.json').read_text())['modules']}
module_errors={k:v for k,v in mapping.items() if v not in module_codes}
verify_errors=[];product_errors=[]
for k,t in raw.items():
 for target in t['verifies']:
  if target not in raw and target not in graph:verify_errors.append({'task':k,'missing_target':target})
  if target not in t['depends_on']:verify_errors.append({'task':k,'missing_dep':target})
  if target==k:verify_errors.append({'task':k,'self_verifies':True})
 if t['params']['execution_authorization']!='design_only':
  if t['status']!='blocked' or 'awz.V9.A10' not in t['depends_on']:product_errors.append(k)
# Live metadata matches exactly, except new A2 explicit primary patch.
live={k:get('/api/tasks/'+k) for k in raw};write('live-cf-tasks.json',live)
newcard_patch=json.loads((P/'current-doc-newcard-patches.json').read_text())[0]
compare_fields=['project_id','seq','kind','tier','status','prompt','params','acceptance','context_files','file_scope','depends_on','verifies','workdirs','needs_gpu','needs','dedupe_key','max_attempts','max_stalls','lease_s']
live_errors=[]
for k,t in raw.items():
 expected=dict(t);expected['project_id']=expected['project'];expected['needs_gpu']=int(expected['needs_gpu'])
 if k=='awz.CF.A2':expected.update(newcard_patch['payload']['fields'])
 for f in compare_fields:
  # A1 has been legitimately claimed by its current document author.
  if f=='status' and k=='awz.CF.A1' and live[k]['status'] in ['claimed','reported','accepted']:continue
  if f=='status' and k=='awz.CF.A3' and live[k]['status']=='claimed':continue
  a=live[k].get(f);b=expected.get(f)
  if f=='needs_gpu':a=int(live[k].get('gpu_level',a))
  if a!=b:live_errors.append({'task':k,'field':f,'expected':b,'actual':a})
old=json.loads((P/'old-gated-fields-before.json').read_text());old_live={k:get('/api/tasks/'+k) for k in old};write('old-gated-tasks-after.json',old_live)
old_errors=[];expected_exception=[]
for k,fields in old.items():
 for f,b in fields.items():
  a=old_live[k].get(f)
  if k=='awz.P3.A3' and f=='depends_on':
   if a==patch['payload']['fields']['depends_on']:expected_exception.append({'task':k,'field':f,'before':b,'after':a})
   else:old_errors.append({'task':k,'field':f,'before':b,'actual':a})
  elif a!=b:old_errors.append({'task':k,'field':f,'before':b,'actual':a})
projects=get('/api/projects');write('projects-after.json',projects)
before_projects=json.loads((P/'projects.json').read_text())
projects_unchanged=sorted(before_projects,key=lambda x:x['id'])==sorted(projects,key=lambda x:x['id'])
result={'schema':'cf-task-metadata-check/v1','checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Task data audit only; not product tests or independent acceptance','cf_task_count':len(raw),'new_reachable_nodes':len(visited),'missing_dependencies':sorted(set(missing)),'cycles_reachable_from_cf':cycles,'needs_errors':needs_errors,'unknown_module_errors':module_errors,'verify_errors':verify_errors,'product_blocked_A10_errors':product_errors,'live_payload_mismatches':live_errors,'old_gated_captured_count':len(old),'intentional_old_changes':expected_exception,'unexpected_old_changes':old_errors,'project_metadata_unchanged':projects_unchanged,'all_new_runtime_budgets':'unapproved','document_task_statuses':{k:v['status'] for k,v in live.items() if k in ['awz.CF.A1','awz.CF.A2','awz.CF.A3']}}
result['author_metadata_checks_pass']=not any([missing,cycles,needs_errors,module_errors,verify_errors,product_errors,live_errors,old_errors]) and projects_unchanged
write('metadata-check-result.json',result)
print(json.dumps({k:v for k,v in result.items() if k not in ['intentional_old_changes']},ensure_ascii=False,indent=2))
