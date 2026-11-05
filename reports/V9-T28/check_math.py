"""Proposal arithmetic examples and refusal controls, NOT model observations."""
from pathlib import Path
import hashlib,json,math,subprocess,sys
import numpy as np
O=Path(__file__).resolve().parent

def rot_z(t):
 c,s=math.cos(t),math.sin(t);return np.array([[c,-s,0],[s,c,0],[0,0,1.]])
def validate(p):
 b=p['budget']
 assert p['status']=='proposal_unapproved' and p['execution_permitted'] is False,'unapproved proposal may not permit execution'
 assert not(set(p['split']['fit_worlds'])&set(p['split']['holdout_worlds'])),'fit/holdout overlap'
 assert p['estimation']['nees'] is None and p['estimation']['coverage_95'] is None,'unjustified NEES/coverage'
 views=sum(s['calls']*s['frames_per_call'] for m in b['models'] for s in m['stages'])
 assert views==b['total_planned_forward_views'] and views<=64,'forward view budget'
 assert b['cumulative_wall_seconds_max']<=1200 and b['single_run_wall_seconds_max']<=1200,'wall budget'
 assert p['alignment']['forbid_centre_only_sim3'] is True,'degenerate centre-only alignment'
 assert p['estimation']['regularization']=='none; no inverse or pseudoinverse','unregistered regularization'
 return views

def pose_residual(gt,pred):
 # Inputs here are explicit C2W toy matrices, never teacher predictions.
 for c in gt+pred:
  assert c.shape==(4,4) and np.isfinite(c).all() and np.allclose(c[3],[0,0,0,1])
  assert np.allclose(c[:3,:3].T@c[:3,:3],np.eye(3),atol=1e-10) and np.linalg.det(c[:3,:3])>0
 def rel(seq,i):
  a=seq[0];c=seq[i]
  return a[:3,:3].T@c[:3,:3], a[:3,:3].T@(c[:3,3]-a[:3,3])
 rg,ug=rel(gt,1);rp,up=rel(pred,1);_,g2=rel(gt,2);_,p2=rel(pred,2)
 bg,bp=np.linalg.norm(g2),np.linalg.norm(p2)
 assert bg>1e-6 and bp>1e-12,'zero anchor baseline'
 delta=rg.T@rp;skew=np.array([delta[2,1]-delta[1,2],delta[0,2]-delta[2,0],delta[1,0]-delta[0,1]])/2
 sin=float(np.linalg.norm(skew));cos=float(np.clip((np.trace(delta)-1)/2,-1,1));angle=math.atan2(sin,cos)
 assert math.pi-angle>1e-6,'ambiguous pi branch'
 rv=skew if angle<1e-8 else skew*(angle/sin)
 return np.concatenate([rv,((bg/bp)*up-ug)/bg])
def example():
 gt=[]
 for x in (0.,.35,.7):
  c=np.eye(4);c[:3,3]=[x,1.4,-3.2];gt.append(c)
 q=rot_z(.7);shift=np.array([7.,-4.,2.]);scale=3.25;pred=[]
 for c in gt:
  z=np.eye(4);z[:3,:3]=q@c[:3,:3];z[:3,3]=scale*q@c[:3,3]+shift;pred.append(z)
 e=pose_residual(gt,pred);assert np.max(np.abs(e))<1e-12,'global gauge invariance'
 damaged=[v.copy() for v in pred];damaged[1][:3,:3]=damaged[1][:3,:3]@rot_z(.1)
 angle=np.linalg.norm(pose_residual(gt,damaged)[:3]);assert abs(angle-.1)<1e-12
 bad_convention=[np.linalg.inv(x) for x in pred]
 assert np.linalg.norm(pose_residual(gt,bad_convention))>.1,'W2C mislabeled C2W must not look gauge-correct'
 # Three deliberately supplied toy vectors demonstrate covariance rank only.
 x=np.array([[0,1,2,3,4,5,6],[1,0,3,5,2,6,4],[3,2,0,1,6,3,5]],dtype=float)
 centered=x-x.mean(0);cov=centered.T@centered/(len(x)-1);rank=int(np.linalg.matrix_rank(cov,tol=1e-10));assert rank<=2
 return {'global_gauge_residual_max':float(abs(e).max()),'known_rotation_error_rad':angle,'toy_full_covariance_dimension':7,'toy_fit_worlds':3,'toy_covariance_rank':rank,'real_models_loaded':0,'observed_teacher_metrics':None}

def main():
 p=json.loads((O/'proposal.json').read_text())
 if '--bad' in sys.argv:
  fault=sys.argv[-1]
  if fault=='split':p['split']['holdout_worlds'].append(p['split']['fit_worlds'][0])
  elif fault=='views':p['budget']['models'][0]['stages'][1]['calls']+=1
  elif fault=='alignment':p['alignment']['forbid_centre_only_sim3']=False
  elif fault=='approval':p['execution_permitted']=True
  elif fault=='nees':p['estimation']['nees']=.95
  else:raise ValueError(fault)
  validate(p);print('accepted');return
 views=validate(p);results=example();records=[]
 for fault in ('split','views','alignment','approval','nees'):
  argv=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'--bad',fault];q=subprocess.run(argv,capture_output=True,timeout=15)
  (O/(fault+'.stdout')).write_bytes(q.stdout);(O/(fault+'.stderr')).write_bytes(q.stderr)
  assert q.returncode==1 and b'AssertionError' in q.stderr,(fault,q.returncode)
  records.append({'fault':fault,'argv':argv,'returncode':q.returncode,'expected_failure':'AssertionError','kind':'proposal-field corruption, NOT product source mutation or model negative control'})
 results.update({'proposal_sha256':hashlib.sha256((O/'proposal.json').read_bytes()).hexdigest(),'planned_forward_views':views,'planned_forward_calls':22,'planned_model_loads':6,'bad_proposal_controls':records,'status':'author_CPU_math_examples_only','models_loaded':0})
 (O/'math-evidence.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results))
if __name__=='__main__':main()
