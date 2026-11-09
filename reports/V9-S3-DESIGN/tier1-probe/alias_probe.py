"""一级设计期探针（纯 CPU、纯内存、不写实验目录）：巡游生成器的返回事件，与手工线索检索精度。"""
import collections, random, statistics as st, sys, time
import numpy as np
from ainerzero.v9.experiments.s2 import world as W, data as D
assert 'mlx' not in sys.modules
BUCKETS=[('short',8,29),('mid',30,79),('long',80,10**6)]
def bucket(l):
    for n,a,b in BUCKETS:
        if a<=l<=b: return n
    return None
def comp_cells(L):
    free=[(x,y) for y in range(W.SIZE) for x in range(W.SIZE) if L.terrain[y][x]==W.FREE]
    seen=set();best=[]
    for c in free:
        if c in seen: continue
        q=[c];seen.add(c);comp=[c]
        while q:
            x,y=q.pop()
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                n=(x+dx,y+dy)
                if n in seen or not(0<=n[0]<W.SIZE and 0<=n[1]<W.SIZE) or L.terrain[n[1]][n[0]]!=W.FREE: continue
                seen.add(n);q.append(n);comp.append(n)
        if len(comp)>len(best): best=comp
    return best

def to_goal_dist(L,g):
    """位姿图反向多源 BFS：dist[pose] = 从 pose 走到目标格（任意朝向）的最少动作数。"""
    dist={};q=collections.deque()
    for h in range(4): dist[(g[0],g[1],h)]=0;q.append((g[0],g[1],h))
    while q:
        x,y,h=q.popleft();d=dist[(x,y,h)]
        for ph in ((h+1)%4,(h-1)%4):          # 上一步是转向
            if (x,y,ph) not in dist: dist[(x,y,ph)]=d+1;q.append((x,y,ph))
        dx,dy=W.DELTA[h];px,py=x-dx,y-dy      # 上一步是前进
        if 0<=px<W.SIZE and 0<=py<W.SIZE and L.terrain[py][px]==W.FREE and (px,py,h) not in dist:
            dist[(px,py,h)]=d+1;q.append((px,py,h))
    return dist
def step_to(L,s,dist):
    best=W.ACTION_WAIT;bd=dist.get((s.x,s.y,s.heading),10**9)
    for a in W.PATH_ACTIONS:
        n=W.step(L,s,a,1);d=dist.get((n.x,n.y,n.heading),10**9)
        if d<bd: bd=d;best=a
    return best
def tour(L,rng,T,M,p_slip,noise=0.1):
    cells=comp_cells(L); rng.shuffle(cells)
    targets=cells[:M]
    s=W.State(x=targets[0][0],y=targets[0][1],heading=rng.randrange(4))
    due=[];queue=list(targets[1:]);visited=collections.defaultdict(list)
    recs=[];t=0
    est=[float(s.x),float(s.y)]
    def rec():
        v=np.array(W.compute_ego_view(L,s.x,s.y,s.heading),dtype=np.int8)
        recs.append(dict(t=t,x=s.x,y=s.y,h=s.heading,ex=est[0],ey=est[1],v=v))
    rec()
    while t<T:
        # 选下一个目标：到期的返回优先，否则走新点，否则随机回访
        due.sort()
        if due and due[0][0]<=t:
            _,g=due.pop(0)
        elif queue:
            g=queue.pop(0)
        elif visited:
            g=rng.choice(list(visited))
        else: break
        dist=to_goal_dist(L,g)
        guard=0
        while t<T and (s.x,s.y)!=g and guard<200:
            guard+=1
            a=rng.choice(W.ACTIONS) if rng.random()<noise else step_to(L,s,dist)
            prev=s; bumps=s.wall_bumps
            slip=(a==W.ACTION_FORWARD and rng.random()<p_slip)
            if not slip: s=W.step(L,s,a,1)
            bumped=s.wall_bumps>bumps
            if a==W.ACTION_FORWARD and not bumped:   # 里程计：只知道自己下了前进且没撞墙
                dx,dy=W.DELTA[prev.heading]; est[0]+=dx; est[1]+=dy
            t+=1; rec()
        if (s.x,s.y)==g:
            visited[g].append(t)
            n=len(visited[g])
            if n<=3:
                name,a_,b_=rng.choice(BUCKETS); hi=min(b_,160)
                due.append((t+rng.randint(a_,hi),g))
    return recs,visited
def rot(v,h,k):
    return np.rot90(v,k=(k*h)%4)
def detect_k(L):
    cs=comp_cells(L)
    for k in (1,-1):
        ok=True
        for (x,y) in cs[:40]:
            base=np.array(W.compute_ego_view(L,x,y,0))
            for h in (1,2,3):
                if not np.array_equal(rot(np.array(W.compute_ego_view(L,x,y,h)),h,k),base): ok=False;break
            if not ok: break
        if ok: return k
    return 0
RADIUS=3
def crop(v):
    c=3;r=RADIUS
    return v[c-r:c+r+1,c-r:c+r+1]
def retrieve(recs,q_i,mode,k,gap=5,lam=0.5):
    q=recs[q_i]; pool=recs[:max(0,q_i-gap)]
    if not pool: return None
    qv=crop(rot(q['v'],q['h'],k))
    best=None;bs=-1e18
    for r in pool:
        d=abs(r['ex']-q['ex'])+abs(r['ey']-q['ey'])
        sim=float(np.mean(crop(rot(r['v'],r['h'],k))==qv))
        s={'pose':-d,'view':sim,'both':sim*49*lam-d}[mode]+1e-6*r['t']
        if s>bs: bs=s;best=r
    return best
def run(N,T,M,p):
    out=collections.defaultdict(lambda:[0,0]); nret=[];uniq=[];top=[];perbk=collections.Counter(); drift=collections.defaultdict(list)
    k=None
    for sd in range(N):
        L=W.make_layout(5000+sd); rng=random.Random(31+sd)
        if k is None: k=detect_k(L)
        recs,vis=tour(L,rng,T,M,p)
        c=collections.Counter((r['x'],r['y']) for r in recs); uniq.append(len(c)); top.append(c.most_common(1)[0][1]/len(recs))
        n=0; byb=collections.Counter()
        for g,ts in vis.items():
            for a,b in zip(ts,ts[1:]):
                lag=b-a; bk=bucket(lag)
                if not bk: continue
                n+=1;byb[bk]+=1
                qi=b
                drift[bk].append(abs(recs[qi]['ex']-recs[qi]['x'])+abs(recs[qi]['ey']-recs[qi]['y'])-abs(recs[a]['ex']-recs[a]['x'])-abs(recs[a]['ey']-recs[a]['y']))
                for m in ('pose','view','both'):
                    r=retrieve(recs,qi,m,k); out[(bk,m)][1]+=1
                    if r and (r['x'],r['y'])==(recs[qi]['x'],recs[qi]['y']): out[(bk,m)][0]+=1
        nret.append(n)
        for b_,_,_ in BUCKETS: perbk[b_]+=(byb[b_]>0)
    print(f"T={T} M={M} slip={p}: k={k} uniq_med={st.median(uniq)} top_med={st.median(top):.3f} top_max={max(top):.3f} returns/ep med={st.median(nret)} min={min(nret)} | episodes having short/mid/long={perbk['short']}/{perbk['mid']}/{perbk['long']} of {N}")
    for b_,_,_ in BUCKETS:
        row=' '.join(f"{m}={out[(b_,m)][0]/max(1,out[(b_,m)][1]):.2f}" for m in ('pose','view','both'))
        print(f"   {b_:5} n={out[(b_,'pose')][1]:4d} {row}")
for RADIUS in (3,2,1):
    print('--- view radius',RADIUS)
    for T,M,p in [(360,8,0.0),(360,8,0.05)]:
        run(16,T,M,p)
