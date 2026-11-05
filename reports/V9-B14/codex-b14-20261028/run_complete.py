import os,sys,tempfile,pathlib,shutil,subprocess,hashlib,json,importlib.util
R=pathlib.Path.cwd(); O=R/'reports/V9-B14/codex-b14-20261028'; E=O/'evidence'/'complete-input-rerun'; E.mkdir()
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
inputs=list((R/'src').rglob('*.py'))+list((R/'tests/v9/contracts').rglob('*.py'))+list((R/'reports/V9-B12').rglob('*'))+list((R/'reports/V9-B13').rglob('*'))+[R.parent/'AnimeWorldZero/docs/adr/ADR-0014-constrained-mechanism-formation.md']
inputs=[p for p in inputs if p.is_file() and '__pycache__' not in str(p)]
before={str(p):sha(p) for p in inputs}; (E/'source-before.json').write_text(json.dumps(before,indent=2))
subprocess.run(['git','status','--short'],stdout=(E/'git-status-before.txt').open('w'))
spec=importlib.util.spec_from_file_location('guards',R/'reports/V9-B12/guard_removal.py'); g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
g.MUTANTS.append(dict(mid='G16',file='interfaces/spatial_memory.py',anchor='        require_slow_eligible_origin(evidence.origin_category)   # V9.B13 K3：起源轴；LLM/教师起源不能靠换 producer 晋升\n',node='tests/v9/contracts/test_spatial_memory.py::test_llm_or_teacher_origin_cannot_reach_slow_even_with_a_legitimate_producer'))
results={}
with tempfile.TemporaryDirectory(prefix='b14-independent-') as t:
    T=pathlib.Path(t); shutil.copytree(R/'src',T/'src',ignore=shutil.ignore_patterns('__pycache__')); shutil.copytree(R/'tests/v9/contracts',T/'tests/v9/contracts'); shutil.copy2(R/'pyproject.toml',T/'pyproject.toml')
    (T/'reports/V9-B12').mkdir(parents=True); shutil.copy2(R/'reports/V9-B12/cmfl_registration.json',T/'reports/V9-B12/cmfl_registration.json')
    (T/'sitecustomize.py').write_text("import sys\nclass Block:\n def find_spec(self,fullname,path=None,target=None):\n  if fullname.split('.')[0] in ('mlx','torch'): raise RuntimeError('B14 prohibited model import: '+fullname)\nsys.meta_path.insert(0,Block())\n")
    env=dict(os.environ,PYTHONPATH=str(T)+os.pathsep+str(T/'src'),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    def run(name,args):
        cmd=[str(R/'.venv/bin/python'),*args]; p=subprocess.run(cmd,cwd=T,env=env,capture_output=True,text=True,timeout=120)
        (E/(name+'.txt')).write_text(json.dumps(dict(argv=cmd,cwd=str(T),PYTHONPATH=env['PYTHONPATH'],returncode=p.returncode))+'\n'+p.stdout+p.stderr)
        results[name]=p.returncode; return p
    run('contracts',['-m','pytest','tests/v9/contracts','-q','-p','no:cacheprovider','--junitxml='+str(E/'contracts.xml')])
    run('independent',[str(O/'probe.py')])
    controls=[]
    for m in g.MUTANTS:
        node=m['node']; base=run(m['mid']+'-baseline',['-m','pytest',node,'-q','-p','no:cacheprovider'])
        target=T/'src/ainerzero/v9'/m['file']; original=target.read_text(); assert original.count(m['anchor'])==1
        target.write_text(original.replace(m['anchor'],'        # B14 isolated guard removal\n'))
        mutant=run(m['mid']+'-removed',['-m','pytest',node,'-q','-p','no:cacheprovider'])
        if m['mid']=='G16': run('independent-origin-gate-removed',[str(O/'probe.py')])
        target.write_text(original)
        controls.append(dict(id=m['mid'],baseline_rc=base.returncode,removed_rc=mutant.returncode,load_bearing=base.returncode==0 and mutant.returncode==1))
    (E/'guards.json').write_text(json.dumps(controls,indent=2))
after={str(p):sha(p) for p in inputs}; (E/'source-after.json').write_text(json.dumps(after,indent=2)); (E/'execution.json').write_text(json.dumps(dict(results=results,changed_inputs=[p for p in before if before[p]!=after[p]]),indent=2))
print(json.dumps(dict(results=results,changed_inputs=[p for p in before if before[p]!=after[p]])))
