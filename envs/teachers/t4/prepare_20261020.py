from pathlib import Path
import json, subprocess, hashlib, shutil, time, sys
from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename, canonicalize_name
from packaging.version import Version
ROOT=Path('/Users/mac/AinerWorkFlow/AinerZero')
REPORT=Path((ROOT/'reports/teachers-install-download-20261020/CURRENT_PATH.txt').read_text().strip())
JOURNAL=REPORT/'network-live.jsonl'
BUDGET=2_000_000_000

def spent():
 total=0
 for p in REPORT.glob('network-ledger-*.json'):
  total+=sum(int(x['response_body_bytes'] or 0) for x in json.loads(p.read_text()))
 if JOURNAL.exists():
  total+=sum(json.loads(x)['bytes'] for x in JOURNAL.read_text().splitlines())
 return total

def fetch(url,dest,category,expected=None):
 dest=Path(dest)
 assert not dest.exists(),dest
 assert shutil.disk_usage(ROOT).free>=50*1024**3,'disk guard'
 if expected is not None: assert spent()+expected<=BUDGET,'budget guard'
 argv=['curl','--fail','--location','--silent','--show-error','--max-time','90','--limit-rate','2M','--max-filesize',str(min(BUDGET-spent(),expected if expected is not None else 10_000_000)),'-o',str(dest),'-w','%{size_download}',url]
 start=time.time();r=subprocess.run(argv,capture_output=True,text=True)
 n=int(r.stdout or 0)
 item={'url':url,'path':str(dest),'category':category,'bytes':n,'returncode':r.returncode,'stderr':r.stderr,'elapsed_s':time.time()-start,'argv':argv}
 with JOURNAL.open('a') as f:f.write(json.dumps(item)+'\n');f.flush()
 assert r.returncode==0,item
 assert n==dest.stat().st_size
 if expected is not None:assert n==expected,(n,expected)
 assert spent()<=BUDGET
 return dest

def metadata(name,version=None):
 key='pypi-'+canonicalize_name(name)+(('-'+version) if version else '')
 dest=REPORT/(key+'.json')
 if not dest.exists():fetch('https://pypi.org/pypi/'+name+(('/'+version) if version else '')+'/json',dest,'software-metadata')
 return json.loads(dest.read_text())

def resolve():
 tags=list(sys_tags());ranks={t:i for i,t in enumerate(tags)}
 requirements={}; chosen={};queue=['mlx>=0.30','mlx-arsenal','numpy','huggingface-hub','safetensors','opencv-python','imageio','imageio-ffmpeg','coremltools','hatchling']
 while queue:
  req=Requirement(queue.pop(0))
  if req.marker and not req.marker.evaluate({'extra':''}):continue
  name=canonicalize_name(req.name)
  assert name not in ('torch','torchvision','torchaudio','jax','jaxlib'),name
  requirements.setdefault(name,[]).append(str(req.specifier))
  d=metadata(name)
  def usable(d):
   ver=Version(d['info']['version'])
   if any(not Requirement(name+s).specifier.contains(ver,prereleases=False) for s in requirements[name]):return []
   choices=[]
   for w in d['urls']:
    if w['packagetype']!='bdist_wheel' or w.get('yanked'):continue
    if w.get('requires_python') and not Requirement('python'+w['requires_python']).specifier.contains(Version('.'.join(map(str,sys.version_info[:3])))):continue
    _,_,_,wt=parse_wheel_filename(w['filename']);rank=min((ranks[t] for t in wt if t in ranks),default=10**8)
    if rank<10**8:choices.append((rank,w))
   return choices
  choices=usable(d)
  if not choices:
   for v in sorted(d['releases'],key=Version,reverse=True):
    if Version(v).is_prerelease:continue
    if not all(Requirement(name+s).specifier.contains(v) for s in requirements[name]):continue
    if not any(x['packagetype']=='bdist_wheel' for x in d['releases'][v]):continue
    dd=metadata(name,v);choices=usable(dd)
    if choices:d=dd;break
  assert choices,('no compatible wheel',name,requirements[name])
  w=min(choices,key=lambda x:x[0])[1]
  if name in chosen:
   assert chosen[name]['version']==d['info']['version'],('resolver version conflict',name)
   continue
  chosen[name]={'name':name,'version':d['info']['version'],'filename':w['filename'],'url':w['url'],'size':w['size'],'sha256':w['digests']['sha256'],'requires_dist':d['info']['requires_dist'] or []}
  print(name,d['info']['version'],w['size'],flush=True)
  queue+=d['info']['requires_dist'] or []
 assert spent()+sum(x['size'] for x in chosen.values())+1_459_675_816+5_000_000<=BUDGET,'projected budget'
 (REPORT/'software-plan.json').write_text(json.dumps(list(chosen.values()),indent=2))
 print('SOFTWARE',sum(x['size'] for x in chosen.values()),'SPENT',spent(),flush=True)
if __name__=='__main__':resolve()
