from pathlib import Path
import hashlib, importlib.util, json, subprocess, sys
R=Path('/Users/mac/AinerWorkFlow/AinerZero'); O=R/'reports/V9-T6/r2'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
spec=importlib.util.spec_from_file_location('t6',R/'envs/teachers/t6/pipeline.py'); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
archive=json.loads((R/'reports/V9-T6/r1-archive-codex-20261026/snapshot.json').read_text())
checks=[]
for row in archive['files']:
 p=R/row['archive']; assert sha(p)==row['sha256'],str(p)
 unchanged=not row['source'].startswith('envs/teachers/t6/')
 if unchanged:assert sha(R/row['source'])==row['sha256'],row['source']
 checks.append({'source':row['source'],'archive_sha256':row['sha256'],'archive_matches':True,'current_original_report_checked_unchanged':unchanged})
cmd=[sys.executable,'-I','-B',str(R/'envs/teachers/t6/benchmark_suite.py'),'--mode','run']
p=subprocess.run(cmd,capture_output=True,timeout=10)
(O/'standalone-run.stdout').write_bytes(p.stdout);(O/'standalone-run.stderr').write_bytes(p.stderr)
assert p.returncode==3 and json.loads(p.stdout)['models_loaded']==0 and not p.stderr
paths=['envs/teachers/t6/pipeline.py','envs/teachers/t6/noise_calibration.py','envs/teachers/t6/benchmark_suite.py','envs/teachers/t6/tests/test_r2.py','envs/teachers/t6/tests/run_mutations_r2.py','reports/V9-T6/r2/collect_closeout.py']
result={'models_loaded':0,'model_execution_budget_reserved':0,'model_execution_budget_actual':0,'no_gpu_call':True,
 'archive_checks':checks,'approved_artifacts':[m.inspect_weights(v) for v in m.APPROVED],
 'source_identity':m.source_identity(),'sources':{x:sha(R/x) for x in paths},
 'standalone_run_refusal':{'argv':cmd,'returncode':p.returncode,'expected_returncode':3,'response':json.loads(p.stdout)},
 'cpu_imports':{'torch': 'torch' in sys.modules,'depth_anything_3':'depth_anything_3' in sys.modules,'mlx':'mlx' in sys.modules}}
assert not any(result['cpu_imports'].values())
(O/'closeout-evidence.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'archive_files_verified':len(checks),'weights_verified':4,'model_runs':0,'standalone_run_rc':3,'closeout':str(O/'closeout-evidence.json')}))
