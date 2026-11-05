"""Deterministic CPU analytical indoor fixtures; no teacher or Blender execution.
All outputs are development-only. This is geometry truth, never model output.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import numpy as np
from PIL import Image

WIDTH, HEIGHT, FOCAL = 280, 210, 220.
SCENE_LAYER = {'family':'analytical_indoor_box_room','lighting':'fixed_diffuse_checker','dynamic':False}
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def camera(eye, target):
 eye=np.asarray(eye,dtype=np.float64);f=np.asarray(target)-eye;f/=np.linalg.norm(f)
 right=np.cross(f,[0.,1.,0.]);right/=np.linalg.norm(right);down=np.cross(f,right)
 rotation=np.column_stack([right,down,f]);assert np.allclose(rotation.T@rotation,np.eye(3),atol=1e-12) and np.linalg.det(rotation)>0
 pose=np.eye(4);pose[:3,:3]=rotation;pose[:3,3]=eye
 return pose

def cast_box(origin,rays,lower,upper,inside=False):
 with np.errstate(divide='ignore',invalid='ignore'):
  a=(np.asarray(lower)-origin)/rays;b=(np.asarray(upper)-origin)/rays
 near_axes=np.minimum(a,b);far_axes=np.maximum(a,b)
 near=near_axes.max(-1);far=far_axes.min(-1)
 distance=far if inside else near
 valid=(far>=near)&(distance>0)&np.isfinite(distance)
 axis=np.argmin(far_axes,axis=-1) if inside else np.argmax(near_axes,axis=-1)
 return np.where(valid,distance,np.inf),axis

def render(world,pose):
 yy,xx=np.indices((HEIGHT,WIDTH),dtype=np.float64)
 c=np.stack([(xx-(WIDTH-1)/2)/FOCAL,(yy-(HEIGHT-1)/2)/FOCAL,np.ones_like(xx)],-1)
 rays=c@pose[:3,:3].T;eye=pose[:3,3]
 depth,axis=cast_box(eye,rays,[-4.,0.,-4.5],[4.,3.5,6.],True)
 ids=np.zeros((HEIGHT,WIDTH),dtype=np.int32)
 boxes=[([-1.5+.12*world,0.,1.8],[-.45+.12*world,1.1+.03*world,3.0]),
        ([.4,0.,3.3-.08*world],[1.5,1.6,4.2-.08*world]),
        ([-2.5,0.,4.3],[-1.7,2.,5.1])]
 for i,(lo,hi) in enumerate(boxes,1):
  d,a=cast_box(eye,rays,lo,hi);mask=d<depth
  depth=np.where(mask,d,depth);axis=np.where(mask,a,axis);ids=np.where(mask,i,ids)
 assert np.isfinite(depth).all() and (depth>0).all()
 points=eye+depth[...,None]*rays
 palette=np.array([[166,176,189],[200,96,65],[71,159,127],[159,113,181]],dtype=float)
 checker=(np.floor(points[...,0]*3)+np.floor(points[...,1]*3)+np.floor(points[...,2]*3)).astype(int)%2
 shading=.68+.18*checker+.06*axis
 # World-coordinate texture is shared by all views, not independent image noise.
 detail=7*np.sin(points[...,0]*13+points[...,2]*4)*np.cos(points[...,1]*17)
 rgb=np.clip(palette[ids]*shading[...,None]+detail[...,None]+world*2,0,255).astype(np.uint8)
 assert np.allclose((points-eye)@pose[:3,:3][:,2],depth,atol=1e-10)
 return rgb,depth.astype('<f4')

def generate(out):
 out=Path(out)
 if out.exists():raise ValueError('fixture output already exists; no overwrite')
 out.mkdir(parents=True)
 k=np.array([[FOCAL,0,(WIDTH-1)/2],[0,FOCAL,(HEIGHT-1)/2],[0,0,1]],dtype='<f8')
 rows=[]
 for world in range(6):
  split='fit' if world<3 else 'holdout';key=f't6-analytic-room-{world:02d}'
  for view,offset in enumerate([-.35,0.,.35]):
   directory=out/key/f'view-{view}';directory.mkdir(parents=True)
   pose=camera([offset,1.45+.02*world,-3.2],[.05*world,.9,3.1])
   rgb,depth=render(world,pose)
   Image.fromarray(rgb).save(directory/'rgb.png',compress_level=9,optimize=False)
   for name,array in [('depth_camera_z',depth),('camera_to_world',pose.astype('<f8')),('world_to_camera',np.linalg.inv(pose).astype('<f8')),('intrinsics',k)]:
    np.save(directory/(name+'.npy'),array,allow_pickle=False)
   rows.append({'record_id':f'{key}/view-{view}','world_key':key,'partition':'development','split':split,
    'timestamp_s':view*.5,'scene_layer':SCENE_LAYER,'camera_convention':'opencv','depth_units':'metres_camera_z',
    'directory':str(directory.relative_to(out))})
 files={str(p.relative_to(out)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()}
 manifest={'schema':'t6.analytical_geometry_fixture.v1','generator_sha256':sha(Path(__file__)),
  'render_kind':'CPU analytical ray-box intersection; NOT Blender; no model prediction',
  'partition':'development','worlds':6,'views':len(rows),'fit_worlds':3,'holdout_worlds':3,
  'width':WIDTH,'height':HEIGHT,'focal_px':FOCAL,'source_authentication':'local_generated_geometry',
  'rows':rows,'files':files,'truth_checks':['SO(3) camera orientation','all positive finite depth','camera Z reprojection <=1e-10'],
  'calibration_admission':'fixture only; no covariance/NEES/model capability registration'}
 (out/'manifest.json').write_bytes(canonical(manifest)+b'\n')
 return manifest

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);args=p.parse_args()
 m=generate(args.output);print(json.dumps({'manifest':str(args.output/'manifest.json'),'views':m['views'],'worlds':m['worlds'],'models_loaded':0,'generator_sha256':m['generator_sha256']}))
if __name__=='__main__':main()
