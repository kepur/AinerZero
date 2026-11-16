"""CPU numerical controls for the independent reviewer; creates no worlds."""
import json
import runpy
from pathlib import Path
import sys
import numpy as np

here=Path(__file__).resolve().parent
m=runpy.run_path(str(here/'recompute.py'))
arrays={}
vals={'R':[2.,3.,4.,5.], 'E':[1.5,3.,3.5,5.2], 'T':[1.2,3.,4.,5.],
      'Z':[1.6,3.,4.,5.], 'P':[1.4,3.,4.,5.], 'G':[1.,3.,4.,5.]}
for t,w in [('main6',50),('extrap10',25)]:
    arrays[t+'/counts']=np.full((w,4),450)
    arrays[t+'/eb']=np.full(w,10.)
    for a,v in vals.items():
        arrays[t+'/sums/'+a]=np.tile(v,(1,3,4,w,1))
out=m['decide'](arrays)
expect={'GS':.05,'GT':.01,'GZ-D':.01,'GZ-W':.875,'GK-A':13.2/14,'GK-F':1.04,'GP':.06,'GX':.05}
for g,x in expect.items():
    r=out['gates'][g]
    assert abs(r['point']-x)<1e-12,(g,r,x)
    assert r['se_w']<1e-12
    assert np.allclose(r['bonferroni'],[x,x],atol=1e-12)
    assert r['passed'],g
assert out['all_pass']
arrays['main6/sums/E'][...,3]=6.
bad=m['decide'](arrays)
assert not bad['gates']['GK-F']['point_ok'] and not bad['gates']['GK-F']['passed']
tampered=json.loads(json.dumps(out))
tampered['gates']['GS']['bonferroni'][0]+=.01
tampered['gates']['GX']['passed']=False
tampered['gates']['GP']['point']+=.02
diff=m['compare'](out,tampered)
fail=[x['path'] for x in diff if not x['ok']]
assert fail==['/gates/GP/point','/gates/GS/bonferroni/0','/gates/GX/passed'],fail
# Nonconstant CPU numerical control: known world-sampling variance of a mean.
vary=np.linspace(1.,1.5,50)
arrays['main6/sums/E'][...,0]=vary[None,None,None,:]
arrays['main6/sums/E'][...,3]=5.2
variable=m['decide'](arrays)
expected_se=float(np.std(vary,ddof=0)/np.sqrt(50)/10)
observed_se=variable['gates']['GS']['se_w']
assert abs(observed_se/expected_se-1)<.025,(expected_se,observed_se)
g=variable['gates']['GS']
assert np.allclose(g['bonferroni'],[g['point']-g['q']*g['se'],g['point']+g['q']*g['se']],atol=1e-14)
result=dict(status='reviewer_numerical_controls_passed',hand_calculated_points=expect,
            constant_world_intervals_checked=8,free_cost_negative_control_rejected=True,
            nonconstant_world_variance=dict(analytic_se=expected_se,bootstrap_se=observed_se,relative_tolerance=.025),
            field_tampers_detected=fail,no_world_generation=True,forbidden_modules_loaded=[x for x in sys.modules if x.split('.')[0] in ('mlx','ainerzero')])
print(json.dumps(result,indent=2))
