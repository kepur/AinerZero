"""P207 一级独立复核：不 import cues/store，从原始步字段重算严格命中的 precision@1 与候选池召回率。"""
import sys,collections,json
import numpy as np
sys.path.insert(0,'src')
from ainerzero.v9.experiments.s3 import data as D,spec
NS=spec.NAMESPACE_PROBE; LAM=float(sys.argv[1]); N=int(sys.argv[2])
def terr(o,h):
    v=np.asarray(o)[:189].reshape(3,3,21)[:,:,:4].argmax(-1); return np.rot90(v,k=(-int(h))%4)
tot=collections.Counter();hit=collections.Counter();loose=collections.Counter()
for w in range(N):
    ep=D.generate_episode(D.derive_seed(NS,'world',w),D.derive_seed(NS,'ep',w,0))
    S=ep['steps'];xy=[(s['truth']['x'],s['truth']['y']) for s in S]
    T=[terr(s['obs'],s['est_pose'][2]) for s in S];E=np.array([s['est_pose'][:2] for s in S],dtype=float)
    for e in ep['events']:
        if e['bucket']!='long': continue
        q=e['t'];idx=np.arange(0,max(0,q-5+1))          # r.t <= q-5
        if idx.size==0: continue
        pv=e['prev_visit_t'];c=tuple(e['cell']);a=pv
        while a>0 and xy[a-1]==c: a-=1
        dd=np.abs(E[idx]-E[q]).sum(1); sim=np.array([np.mean(T[r]==T[q]) for r in idx]); tb=1e-6*idx
        both=sim*49.0*LAM-dd+tb; pose=-dd+tb; view=sim+tb
        def top(s,k=1): return [int(idx[i]) for i in np.argsort(-s,kind='stable')[:k]]
        kinds=['all']+(['swapped'] if e['swapped'] else [])
        pool=set(top(both,4)+top(pose,4)+top(view,4)); assert len(pool)<=12
        for K in kinds:
            tot[K]+=1
            for nm,s in (('both',both),('pose',pose),('view',view)):
                r=top(s)[0]
                hit[K,nm]+=(a<=r<=pv); loose[K,nm]+=(xy[r]==c)
            hit[K,'pool']+=any(a<=r<=pv for r in pool)
for K in ('all','swapped'):
    print(K,'n',tot[K],{nm:round(hit[K,nm]/tot[K],4) for nm in ('both','pose','view','pool')},'loose_both',round(loose[K,'both']/tot[K],4))
