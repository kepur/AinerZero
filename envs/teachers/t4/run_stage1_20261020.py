from pathlib import Path
import json,sys,subprocess,hashlib,shutil,time,importlib.util,os
ROOT=Path('/Users/mac/AinerWorkFlow/AinerZero')
s=importlib.util.spec_from_file_location('prep',ROOT/'envs/teachers/t4/prepare_20261020.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
p=m.REPORT

def command(name,argv,env=None):
 start=time.time();r=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,env=env)
 (p/(name+'.json')).write_text(json.dumps({'argv':argv,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'elapsed_s':time.time()-start},indent=2))
 print(name,r.returncode,flush=True)
 assert r.returncode==0,(name,r.stderr)
 return r

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
 return h.hexdigest()

assert not (p/'stage1-started.json').exists(),'No repeat automatic execution'
(p/'stage1-started.json').write_text(json.dumps({'at':time.time(),'pid':os.getpid(),'payload_budget':m.BUDGET,'download_streams':1,'rate_bytes_s':2097152}))
try:
 plan=json.loads((p/'software-plan.json').read_text())
 assert m.spent()+sum(x['size'] for x in plan)+1_459_675_816 < m.BUDGET
 wheels=ROOT/'envs/teachers/t4/wheelhouse-20261020';wheels.mkdir(exist_ok=False)
 for item in plan:
  dest=m.fetch(item['url'],wheels/item['filename'],'software',item['size']);assert sha(dest)==item['sha256'];print('wheel',item['name'],item['size'],flush=True)
 venv=ROOT/'envs/teachers/.venv-t4';assert not venv.exists()
 env=os.environ.copy();env.update({'UV_CACHE_DIR':str(ROOT/'envs/teachers/t4/uv-cache'),'UV_OFFLINE':'1','UV_PYTHON_DOWNLOADS':'never','HF_HOME':str(ROOT/'artifacts/teachers/hf-cache'),'PIP_NO_INDEX':'1','PYTHONNOUSERSITE':'1'})
 command('venv-create',['uv','venv',str(venv),'--python',sys.executable,'--no-python-downloads','--offline'],env)
 command('software-install',['uv','pip','install','--python',str(venv/'bin/python'),'--offline','--no-deps',*[str(wheels/x['filename']) for x in plan]],env)
 command('core-editable-install',['uv','pip','install','--python',str(venv/'bin/python'),'--offline','--no-deps','--no-build-isolation','-e',str(ROOT/'envs/teachers/src/vjepa2-mlx/packages/vjepa2-core-mlx')],env)
 freeze=command('environment-freeze',['uv','pip','freeze','--python',str(venv/'bin/python'),'--offline'],env)
 (p/'env.lock.txt').write_text(freeze.stdout)
 check=command('dependency-check',['uv','pip','check','--python',str(venv/'bin/python'),'--offline'],env)
 assert not any(x.split('==')[0].lower() in ('torch','torchvision','torchaudio','jax','jaxlib') for x in freeze.stdout.splitlines())
 selected=[]
 repos=[('vjepa-hf','dgrauet/vjepa-2.1-vitl-mlx'),('da2-hf','apple/coreml-depth-anything-v2-small')]
 base=ROOT/'artifacts/teachers/t4-approved';base.mkdir(parents=True,exist_ok=True)
 for key,repo in repos:
  d=json.loads((p/(key+'.json')).read_text());revision=d['sha'];target=base/revision;target.mkdir(exist_ok=False)
  for f in d['siblings']:
   rel=f['rfilename']
   allowed=(rel in ('README.md','config.json','split_model.json','encoder.safetensors','predictor.safetensors')) if key=='vjepa-hf' else (rel=='README.md' or rel.startswith(('DepthAnythingV2SmallF16.mlpackage/','DepthAnythingV2SmallF32.mlpackage/')))
   if not allowed:continue
   dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True);partial=dest.with_name(dest.name+'.part')
   assert m.spent()+f['size']<=m.BUDGET
   assert shutil.disk_usage(ROOT).free>=50*1024**3
   url=f'https://huggingface.co/{repo}/resolve/{revision}/{rel}'
   argv=['curl','--fail','--location','--silent','--show-error','--max-time','1800','--limit-rate','2M','--max-filesize',str(f['size']),'-o',str(partial),'-w','%{size_download}',url]
   start=time.time();r=subprocess.run(argv,capture_output=True,text=True);n=int(r.stdout or 0)
   row={'url':url,'path':str(partial),'category':'weights-and-model-metadata','bytes':n,'returncode':r.returncode,'stderr':r.stderr,'elapsed_s':time.time()-start,'argv':argv}
   with m.JOURNAL.open('a') as log:log.write(json.dumps(row)+'\n');log.flush()
   assert r.returncode==0,row
   assert n==f['size']==partial.stat().st_size
   digest=sha(partial)
   if f.get('lfs'):assert digest==f['lfs']['sha256']
   else:
    data=partial.read_bytes();assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==f['blobId']
   partial.rename(dest)
   selected.append({'repository':repo,'revision':revision,'file':rel,'path':str(dest),'bytes':n,'sha256':digest,'expected_lfs_sha256':f.get('lfs',{}).get('sha256')})
   (p/'downloads-progress.json').write_text(json.dumps(selected,indent=2))
   print('model file',rel,n,'total transferred',m.spent(),flush=True)
 (p/'downloads.json').write_text(json.dumps(selected,indent=2))
 (p/'stage1-complete.json').write_text(json.dumps({'at':time.time(),'payload_bytes':m.spent(),'free_bytes':shutil.disk_usage(ROOT).free,'models_loaded':0,'inference_calls':0,'training_updates':0},indent=2))
 print('COMPLETE',m.spent(),flush=True)
except BaseException as e:
 (p/'stage1-failure.json').write_text(json.dumps({'at':time.time(),'exception':repr(e),'transferred_payload_bytes':m.spent(),'free_bytes':shutil.disk_usage(ROOT).free},indent=2))
 raise
