from pathlib import Path
import os,sys,json,hashlib,shutil,subprocess,time,math,re
R=Path('/Users/mac/AinerWorkFlow/AinerZero'); O=R/'reports/V-V9-B1/r5-independent-20261018'; C=R/'reports/V9-B1/r5-candidate'; S=O/'sandbox'; S.mkdir(exist_ok=True);(O/'logs').mkdir(exist_ok=True);(O/'tmp').mkdir(exist_ok=True)
(O/'CLAIM.md').write_text('ainerzero.V9.B9已由cf-b7-review-20261018领取；本执行者非B7任何版作者，只写本目录；独立新目录不接管B8，不accept或next。纯CPU，无模型/GPU/下载。\n')
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def tree(p,exclude=()):return {str(q.relative_to(p)):h(q) for q in sorted(p.rglob('*')) if q.is_file() and not any(e in q.parts for e in exclude)}
protected={'candidate':tree(C),'r4':tree(R/'reports/V9-B1',('r5-candidate',)),'old_B8':tree(R/'reports/V-V9-B1/r5-independent'),'contracts':tree(R/'contracts/v9'),'docs':tree(R/'docs/v9')}
(O/'before.json').write_text(json.dumps(protected,ensure_ascii=False,indent=2)+'\n')
for rel in ['reports/V9-B1','contracts/v9','docs/v9']:
 shutil.copytree(R/rel,S/rel,dirs_exist_ok=True)
for rel in ['ARCHITECTURE_V9.md','reports/V-V9-B1/probe_variants.json','reports/V-V9-B1/oracle_r3.py']:
 q=S/rel;q.parent.mkdir(parents=True,exist_ok=True)
 if (R/rel).is_file():shutil.copy2(R/rel,q)
script=S/'reports/V9-B1/r5-candidate/check_skill_proposal.py'; text=script.read_text();ins=S/'reports/V9-B1/r5-candidate'; data=O/'inputs';data.mkdir(exist_ok=True)
awz=Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json'); src=data/'awz-copy.json';src.write_bytes(awz.read_bytes());drift=data/'awz-drift.json';drift.write_bytes(awz.read_bytes()+b'\n');bad=data/'awz-no-permission.json';bad.write_bytes(awz.read_bytes());bad.chmod(0)
mut=O/'mutants';mut.mkdir(exist_ok=True)
strict=mut/'no_duplicate_guard.py';strict.write_text(text.replace('object_pairs_hook=_dup_guard if strict else None','object_pairs_hook=None'))
props=mut/'no_property_guards.py';props.write_text(text.replace('if is_forbidden_world_id_key(name):','if False:  # independent property guard removal'))
start=text.index('        # 运行时漂移校验：');end=text.index("        for k in ('registry_id', 'derivation'):",start)
nosrc=mut/'no_source_guard.py';nosrc.write_text(text[:start]+'        # independent runtime source guard removed\n'+text[end:])
def canon(x):
 if x is None:return 'null'
 if isinstance(x,bool):return 'true' if x else 'false'
 if isinstance(x,str):return json.dumps(x,ensure_ascii=False,separators=(',',':'))
 if isinstance(x,int):return str(x)
 if isinstance(x,float):return str(int(x)) if x.is_integer() else json.dumps(x,allow_nan=False)
 if isinstance(x,list):return '['+','.join(canon(z) for z in x)+']'
 if isinstance(x,dict):return '{'+','.join(canon(k)+':'+canon(x[k]) for k in sorted(x,key=lambda v:v.encode('utf-16-be')))+'}'
 raise TypeError(type(x))
def pin(ctx):return hashlib.sha256(canon(ctx).encode()).hexdigest()
pp=sorted((ins/'fixtures/valid').glob('*.json'))[0];cp=ins/'fixtures/contexts'/pp.name
P=json.loads(pp.read_text());CTX=json.loads(cp.read_text());rp=sorted((ins/'fixtures/replies/valid').glob('*.json'))[0]
def put(name,x):p=data/name;p.write_text(json.dumps(x,ensure_ascii=False));return p
pfile=put('proposal.json',P);cfile=put('context.json',CTX)
pdup=data/'duplicate-proposal.json';pdup.write_text('{"ability_id":"independent-invalid-first",'+pfile.read_text()[1:])
cdup=data/'duplicate-context.json';cdup.write_text('{"synthetic":false,'+cfile.read_text()[1:])
rdup=data/'duplicate-reply.json';rdup.write_text('{"reason_code":"independent-invalid-first",'+rp.read_text()[1:])
ic=json.loads(cfile.read_text());ic['ability_registry']['entries'][-1]['param_schema']['properties']['World_ID___Proof']={'type':'string','maxLength':40};icfile=put('illegal-property-context.json',ic)
records=[]
env=os.environ.copy();env.update({'PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(O/'tmp'),'AWZ_OBSERVATION_PATH':str(src)})
def run(label,argv,source=src,timeout=150):
 e=env.copy();e['AWZ_OBSERVATION_PATH']=str(source);beg=time.monotonic();p=subprocess.run(argv,cwd=S,env=e,capture_output=True,text=True,timeout=timeout)
 (O/'logs'/f'{label}.stdout').write_text(p.stdout);(O/'logs'/f'{label}.stderr').write_text(p.stderr);(O/'logs'/f'{label}.rc').write_text(str(p.returncode)+'\n')
 try:obj=json.loads(p.stdout)
 except Exception:obj={}
 r={'label':label,'argv':list(map(str,argv)),'source':str(source),'rc':p.returncode,'seconds':round(time.monotonic()-beg,3),'stdout_sha256':h(O/'logs'/f'{label}.stdout'),'stderr_sha256':h(O/'logs'/f'{label}.stderr'),'decision':obj.get('decision'),'errors':obj.get('errors'),'world_side_log':obj.get('world_side_log'),'all_ok':obj.get('all_ok'),'traceback':'Traceback' in p.stderr+p.stdout};records.append(r)
 (O/'runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n');print(label,p.returncode,r['decision'],r['all_ok'],flush=True);return obj
base=[sys.executable,'-B',str(script),'--root',str(S)]
def gate(label,sp=script,proposal=pfile,context=cfile,ctx=CTX,source=src):return run(label,[sys.executable,'-B',str(sp),'--root',str(S),'gate','--proposal',str(proposal),'--context',str(context),'--expected-context-sha256',pin(ctx)],source)
# Independent positive and raw duplicate-key counterexamples, each with true accepted guard-off controls.
gate('baseline');gate('duplicate-proposal',proposal=pdup);gate('duplicate-proposal-guard-off',sp=strict,proposal=pdup)
gate('duplicate-context',context=cdup);gate('duplicate-context-guard-off',sp=strict,context=cdup)
for label,sp in [('duplicate-reply',script),('duplicate-reply-guard-off',strict)]:run(label,[sys.executable,'-B',str(sp),'--root',str(S),'reply','--reply',str(rdup)])
gate('illegal-property',context=icfile,ctx=ic);gate('illegal-property-guards-off',sp=props,context=icfile,ctx=ic)
for label,source in [('source-missing',data/'not-present.json'),('source-unreadable',bad),('source-drift',drift)]:
 gate(label,source=source);gate(label+'-guard-off',sp=nosrc,source=source)
# Static audit: default suite writes only its temporary directory; explicit output has no input/ancestor safety checks.
beforecopy=tree(S)
run('suite-default',base+['--suite']);afterdefault=tree(S)
(O/'default-zero-write.json').write_text(json.dumps({'before_files':len(beforecopy),'after_files':len(afterdefault),'added':sorted(set(afterdefault)-set(beforecopy)),'removed':sorted(set(beforecopy)-set(afterdefault)),'changed':[p for p in beforecopy if p in afterdefault and beforecopy[p]!=afterdefault[p]]},indent=2)+'\n')
# Reproduce destructive overwrite only on the isolated candidate input folder; no real inputs touched.
target=ins;pre={n:h(target/n) for n in ['check_result.json','SHA256SUMS.txt']}
run('suite-output-equals-input',base+['--suite','--output-dir',str(target)])
post={n:h(target/n) for n in pre}
(O/'output-overwrite.json').write_text(json.dumps({'output_dir':str(target),'before':pre,'after':post,'changed':[n for n in pre if pre[n]!=post[n]],'parent_directory_risk_static':'same unguarded Path(output_dir).resolve()/mkdir/write path also permits ancestors; no extra parent-run after confirmed failure'},indent=2)+'\n')
bad.chmod(0o600)
after={'candidate':tree(C),'r4':tree(R/'reports/V9-B1',('r5-candidate',)),'old_B8':tree(R/'reports/V-V9-B1/r5-independent'),'contracts':tree(R/'contracts/v9'),'docs':tree(R/'docs/v9')}
(O/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
summary={k:{'count':len(protected[k]),'unchanged':protected[k]==after[k]} for k in protected}
(O/'preservation.json').write_text(json.dumps(summary,indent=2)+'\n')
(O/'input-identities.json').write_text(json.dumps({'candidate_script':{'path':str(C/'check_skill_proposal.py'),'sha256':h(C/'check_skill_proposal.py')},'isolated_script_sha256':h(script),'r4_script_sha256':h(R/'reports/V9-B1/check_skill_proposal.py'),'awz_original_sha256':h(awz),'awz_isolated_sha256':h(src),'uid':os.geteuid(),'mutants':{p.name:h(p) for p in mut.glob('*.py')}},indent=2)+'\n')
print('PRESERVATION',summary,flush=True)
