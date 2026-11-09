import random,statistics as st,collections,json,sys,time
from ainerzero.v9.experiments.s2 import world,data
assert 'mlx' not in sys.modules
def cell_of(s):
    t=s.get('truth') or s.get('truth_after') or s
    if isinstance(t,dict) and 'x' in t: return (t['x'],t['y'])
    if isinstance(t,dict) and 'pose' in t: return tuple(t['pose'][:2])
    raise KeyError(list(s.keys()))
def measure(ep):
    cells=[cell_of(s) for s in ep['steps']]
    c=collections.Counter(cells); n=len(cells)
    last={};lags=[]
    prev=None
    for i,x in enumerate(cells):
        if x!=prev:                       # 只算离开后再回来
            if x in last: lags.append(i-last[x])
        last[x]=i; prev=x
    return dict(n=n,uniq=len(c),top=c.most_common(1)[0][1]/n,rev5=sum(l>=5 for l in lags),rev20=sum(l>=20 for l in lags),rev60=sum(l>=60 for l in lags))
def run(fn,N=40):
    R=[]
    for sd in range(N):
        L=world.make_layout(9000+sd); R.append(measure(fn(L,random.Random(77+sd))))
    keys=R[0].keys()
    return {k:(round(st.median(r[k] for r in R),3),round(min(r[k] for r in R),3),round(max(r[k] for r in R),3)) for k in keys}
L=world.make_layout(9000); ep=data.run_episode(L,random.Random(77)); print('step keys',list(ep['steps'][0].keys())[:12]); print('free cells in layout',sum(v==world.FREE for row in L.terrain for v in row))
t=time.time()
print('default mix   (med,min,max)',run(lambda L,r:data.run_episode(L,r)))
print('bfs_only      (med,min,max)',run(lambda L,r:data.run_episode(L,r,force_bfs_only=True)))
print('bfs_only k=1  (med,min,max)',run(lambda L,r:data.run_episode(L,r,force_bfs_only=True,force_k1=True)))
print('sec',round(time.time()-t,1))
