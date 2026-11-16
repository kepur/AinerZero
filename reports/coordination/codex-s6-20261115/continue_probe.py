"""Supervise the already-authorized S6 probe continuation; never train or read final.
Run through relay submit-run on coordinator P258. No MLX import here: the original runner owns its lock.
"""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path('/Users/mac/AinerWorkFlow/AinerZero')
os.chdir(ROOT)
record=ROOT/'reports/coordination/codex-s6-20261115/evidence'
ledger=ROOT/'artifacts/v9/s6/phase1/probe/train-ledger.json'
log=ROOT/'reports/V9-S6-PHASE1/probe/train-probe.log'
expected=json.loads((record/'code-before-eval.json').read_text())
def code_check():
 for name,h in expected['manifest'].items():
  # run_guard manifest values are SHA strings.
  if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h:raise RuntimeError('code changed: '+name)
def main():
 code_check()
 end=time.monotonic()+9000
 last=''
 while time.monotonic()<end:
  rows=json.loads(ledger.read_text())
  tail=log.read_text().splitlines()[-1]
  if tail!=last: print('train:',tail,flush=True);last=tail
  done=len(rows[-1].get('cells',[]))==6 and rows[-1].get('closed') is True and 'training complete' in tail
  if done:break
  time.sleep(15)
 else:raise RuntimeError('existing probe did not complete; no eval launched')
 code_check()
 report=ROOT/'reports/V9-S6-PHASE1/probe/EVAL-probe.json'
 out=ROOT/'artifacts/v9/s6/phase1/probe/eval-s6p1-probe'
 if report.exists() or out.exists():raise RuntimeError('eval already exists; refuse duplicate')
 cache=Path('/tmp')/('s6-probe-eval-codex-'+str(os.getpid())+'-'+str(time.time_ns()))
 cmd=[str(ROOT/'.venv/bin/python'),'-I','-X','pycache_prefix='+str(cache),str(ROOT/'reports/V9-S6-PHASE1/run_s6p1.py'),'eval','--set','probe','--report',str(report)]
 (record/'eval-command.json').write_text(json.dumps({'argv':cmd,'time':time.time(),'training_ledger':rows,'code_sha':expected['digest']},indent=2))
 print('probe training complete; launch original eval runner (own shared lock)',flush=True)
 with (record/'eval-probe.log').open('x') as fh:
  res=subprocess.run(cmd,stdout=fh,stderr=subprocess.STDOUT)
 if res.returncode:raise RuntimeError('probe eval failed; see evidence/eval-probe.log; rc='+str(res.returncode))
 r=json.loads(report.read_text())
 print('probe eval complete:',json.dumps({'report':str(report),'verify_passed':r.get('verify',{}).get('passed'),'result_valid':r.get('result',{}).get('valid'),'eval_seconds':r.get('eval_seconds'),'verify_seconds':r.get('verify_seconds')},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
