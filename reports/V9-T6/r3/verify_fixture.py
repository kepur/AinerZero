from pathlib import Path
import hashlib, importlib.util,json,tempfile
import numpy as np
R=Path('/Users/mac/AinerWorkFlow/AinerZero');D=R/'reports/V9-T6/r2-calib-fixtures';O=R/'reports/V9-T6/r3'
M=json.loads((D/'manifest.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert M['views']==len(M['rows'])==18 and M['worlds']==6
fit={r['world_key'] for r in M['rows'] if r['split']=='fit'};hold={r['world_key'] for r in M['rows'] if r['split']=='holdout'}
assert len(fit)==len(hold)==3 and not fit&hold
for p,v in M['files'].items():assert sha(D/p)==v['sha256'] and (D/p).stat().st_size==v['bytes']
max_surface_error=0.;inverse_error=0.
for row in M['rows']:
 d=D/row['directory'];depth=np.load(d/'depth_camera_z.npy',allow_pickle=False);c2w=np.load(d/'camera_to_world.npy',allow_pickle=False);w2c=np.load(d/'world_to_camera.npy',allow_pickle=False);k=np.load(d/'intrinsics.npy',allow_pickle=False)
 assert row['partition']=='development' and np.isfinite(depth).all() and (depth>0).all()
 assert np.allclose(c2w[:3,:3].T@c2w[:3,:3],np.eye(3),atol=1e-12) and np.linalg.det(c2w[:3,:3])>0
 inverse_error=max(inverse_error,float(np.max(np.abs(c2w@w2c-np.eye(4)))))
 y,x=np.indices(depth.shape);pixels=np.stack([x,y,np.ones_like(x)],-1)
 camera_points=(pixels@np.linalg.inv(k).T)*depth[...,None]
 pts=camera_points@c2w[:3,:3].T+c2w[:3,3]
 world=int(row['world_key'].split('-')[-1]);bounds=[([-4.,0.,-4.5],[4.,3.5,6.]),([-1.5+.12*world,0.,1.8],[-.45+.12*world,1.1+.03*world,3.0]),([.4,0.,3.3-.08*world],[1.5,1.6,4.2-.08*world]),([-2.5,0.,4.3],[-1.7,2.,5.1])]
 surface=np.full(depth.shape,np.inf)
 for lo,hi in bounds:
  lo=np.asarray(lo);hi=np.asarray(hi);inside=((pts>=lo-1e-5)&(pts<=hi+1e-5)).all(-1)
  distance=np.minimum(np.abs(pts-lo),np.abs(pts-hi)).min(-1)
  surface=np.minimum(surface,np.where(inside,distance,np.inf))
 assert np.isfinite(surface).all() and surface.max()<1e-4
 max_surface_error=max(max_surface_error,float(surface.max()))
# Replay original deterministic generator into a unique retained directory.
spec=importlib.util.spec_from_file_location('fixture_generator',R/'envs/teachers/t6/prepare_calibration_fixtures.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
parent=Path(tempfile.mkdtemp(prefix='fixture-replay-',dir=O));replay=parent/'fixtures';g.generate(replay)
assert (replay/'manifest.json').read_bytes()==(D/'manifest.json').read_bytes()
for rel in M['files']:assert (D/rel).read_bytes()==(replay/rel).read_bytes()
result={'status':'cpu_fixture_only','views':18,'worlds':6,'fit_worlds':sorted(fit),'holdout_worlds':sorted(hold),'file_count':len(M['files']),'manifest_sha256':sha(D/'manifest.json'),'generator_sha256':sha(R/'envs/teachers/t6/prepare_calibration_fixtures.py'),'manifest_byte_identical_on_replay':True,'replay_files_byte_identical':True,'max_surface_reprojection_error_metres':max_surface_error,'max_pose_inverse_error':inverse_error,'replay_root':str(replay),'real_model_runs':0,'render_kind':'analytical CPU geometry, not Blender','noise_registered':False}
(O/'fixture-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
