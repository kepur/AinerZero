"""一级核查（纯 CPU、纯内存）：S2 run_episode 的寻路方向缺陷对动作分布与寻路成功率的影响。"""
import collections,random,statistics as st,sys
from ainerzero.v9.experiments.s2 import world as W,data as D
assert 'mlx' not in sys.modules
exec(open('reports/V9-S3-DESIGN/tier1-probe/tour_probe_fixed.py',encoding='utf8').read().split('def tour(')[0].split('BUCKETS=')[0]) if False else None
def to_goal(L,g):
    dist={};q=collections.deque()
    for h in range(4): dist[(g[0],g[1],h)]=0;q.append((g[0],g[1],h))
    while q:
        x,y,h=q.popleft();d=dist[(x,y,h)]
        for ph in ((h+1)%4,(h-1)%4):
            if (x,y,ph) not in dist: dist[(x,y,ph)]=d+1;q.append((x,y,ph))
        dx,dy=W.DELTA[h];px,py=x-dx,y-dy
        if 0<=px<W.SIZE and 0<=py<W.SIZE and L.terrain[py][px]==W.FREE and (px,py,h) not in dist: dist[(px,py,h)]=d+1;q.append((px,py,h))
    return dist
act=collections.Counter();per=collections.defaultdict(collections.Counter)
for sd in range(40):
    L=W.make_layout(9000+sd);ep=D.run_episode(L,random.Random(77+sd))
    for s in ep['steps']:
        act[s['action']]+=s['dt'];per[s['segment_kind']][s['action']]+=s['dt']
names={0:'FORWARD',1:'LEFT',2:'RIGHT',3:'WAIT'}
tot=sum(act.values());print('全部动作占比',{names[k]:round(v/tot,3) for k,v in sorted(act.items())})
for k,c in per.items():
    t=sum(c.values());print(' ',k,{names[a]:round(v/t,3) for a,v in sorted(c.items())},'env_steps',t)
# 同一起终点：现有贪心 vs 正确反向距离的到达率
res=collections.Counter();N=0
for sd in range(40):
    L=W.make_layout(9000+sd);rng=random.Random(5+sd)
    for _ in range(5):
        s,g,_a,_b=W.sample_start_goal_pair(L,rng,kind='long');N+=1
        f=W.compute_pose_bfs_distances(L,g)
        t=s
        for i in range(200):
            if (t.x,t.y)==(g.x,g.y): res['existing']+=1;break
            a=D._find_path_step(L,t,g,dist_from_goal=f)
            if a==W.ACTION_WAIT: res['existing_stuck_wait']+=1;break
            t=W.step(L,t,a,1)
        d=to_goal(L,(g.x,g.y));t=s;ok=False
        for i in range(200):
            if (t.x,t.y)==(g.x,g.y): res['fixed']+=1;ok=True;break
            bd=d.get((t.x,t.y,t.heading),10**9);b=W.ACTION_WAIT
            for a in W.PATH_ACTIONS:
                n=W.step(L,t,a,1);x=d.get((n.x,n.y,n.heading),10**9)
                if x<bd: bd=x;b=a
            if b==W.ACTION_WAIT: break
            t=W.step(L,t,b,1)
print('长目标寻路（无噪声，200 步内到达）：',dict(res),'共',N)
