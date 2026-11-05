from pathlib import Path
import json,hashlib,subprocess,sys
ROOT=Path('/Users/mac/AinerWorkFlow/AinerZero')
p=Path(sys.argv[1])
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
 return h.hexdigest()
complete=json.loads((p/'stage1-complete.json').read_text());assert complete['models_loaded']==0
manifest=Path(sys.argv[2]) if len(sys.argv)>2 else p/'downloads.json'
files=json.loads(manifest.read_text());assert len(files)==12
for item in files:
 path=Path(item['path']);assert path.is_file() and path.stat().st_size==item['bytes'];assert sha(path)==item['sha256']
 repo=item['repository'];f=item['file']
 assert (repo=='dgrauet/vjepa-2.1-vitl-mlx' and f in ('encoder.safetensors','predictor.safetensors','config.json','split_model.json','README.md')) or (repo=='apple/coreml-depth-anything-v2-small' and (f=='README.md' or f.startswith(('DepthAnythingV2SmallF16.mlpackage/','DepthAnythingV2SmallF32.mlpackage/'))))
 assert item['revision'] in item['path']
actual=sum(int(x['response_body_bytes'] or 0) for q in p.glob('network-ledger-*.json') for x in json.loads(q.read_text()))+sum(json.loads(x)['bytes'] for x in (p/'network-live.jsonl').read_text().splitlines())
assert actual==complete['payload_bytes']<=2_000_000_000
for before in p.glob('main-*-before.txt'):
 name=before.name[len('main-'):-len('-before.txt')];r=subprocess.run(['uv','pip','freeze','--python',str(ROOT/name/'bin/python'),'--offline'],capture_output=True,text=True);assert r.returncode==0;assert (r.stdout+r.stderr)==before.read_text(),name
for rel,expected in json.loads((p/'source-file-shas.json').read_text()).items():assert sha(ROOT/'envs/teachers/src/vjepa2-mlx'/rel)==expected
assert json.loads((p/'dependency-check.json').read_text())['returncode']==0
print(json.dumps({'assertions':'passed','model_files':len(files),'transferred_payload_bytes':actual,'no_model_execution_by_script':True,'main_freezes_unchanged':True,'source_files_unchanged':True},indent=2))
