"""一级核查（只读）：S2 真实训练集的动作分布与覆盖。"""
import glob,gzip,json,os,collections,statistics as st
R='artifacts/v9/s2/phase1/datasets/train'
files=sorted(glob.glob(R+'/world_*/*'))
print('sample files',[os.path.basename(f) for f in files[:4]],'n',len(files))
def load(p):
    op=gzip.open if p.endswith('.gz') else open
    with op(p,'rt',encoding='utf8') as f: return json.load(f)
act=collections.Counter();per=collections.defaultdict(collections.Counter);U=[];T=[];R60=[];n=0
for p in files:
    if not (p.endswith('.json') or p.endswith('.json.gz')) or 'meta' in os.path.basename(p) or 'layout' in os.path.basename(p): continue
    d=load(p)
    if not isinstance(d,dict) or 'steps' not in d: continue
    n+=1
    cells=[]
    for s in d['steps']:
        act[s['action']]+=s['dt'];per[s.get('segment_kind')][s['action']]+=s['dt'];t=s['truth_after'];cells.append((t['x'],t['y']))
    c=collections.Counter(cells);U.append(len(c));T.append(c.most_common(1)[0][1]/len(cells))
    last={};prev=None;r=0
    for i,x in enumerate(cells):
        if x!=prev and x in last and i-last[x]>=60: r+=1
        last[x]=i;prev=x
    R60.append(r)
print('episodes',n)
if n:
    names={0:'FORWARD',1:'LEFT',2:'RIGHT',3:'WAIT'};t=sum(act.values())
    print('动作占比',{names[k]:round(v/t,3) for k,v in sorted(act.items())})
    for k,c in per.items():
        tt=sum(c.values());print(' ',k,{names[a]:round(v/tt,3) for a,v in sorted(c.items())})
    print('uniq cells med/min/max',st.median(U),min(U),max(U),'| top share med/max',round(st.median(T),3),round(max(T),3),'| 离开≥60步后返回 med/max',st.median(R60),max(R60))
