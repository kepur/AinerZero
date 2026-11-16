#!/usr/bin/env python3
"""Read-only S6 probe review. Imports only stdlib and NumPy; never project/model code.

Outputs must be new subdirectories of this script's directory. --report is an
explicit tier1-release gate: do not supply until tier1 says that report is ready.
"""
import argparse
import ast
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
from pathlib import Path

def deny_model_import(event, args):
    if event == 'import' and (args[0].split('.')[0] in {'mlx', 'ainerzero'}):
        raise RuntimeError('Reviewer forbids model/project imports: ' + args[0])
sys.addaudithook(deny_model_import)
import numpy as np

HOME = Path(__file__).resolve().parent
ROOT = HOME.parents[2]
ARMS = ('R', 'E', 'Z', 'T', 'P', 'G')
REPS = {'R': 5, 'E': 5, 'Z': 5, 'T': 5, 'P': 5, 'G': 3}
SIZES = dict(per=3000, rounds=4, steps=2500, pool=60000, cand_worlds=240)
KINDS = ('collision', 'graze', 'wall_pillar', 'free')
GATES = ('GS', 'GT', 'GZ-D', 'GZ-W', 'GK-A', 'GK-F', 'GP', 'GX')

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read(p):
    return json.loads(Path(p).read_text())

def write(p, obj):
    with Path(p).open('x') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')

def source_manifest(root):
    """AST-only closure, independently resolved without executing any source."""
    src = root / 'src'
    pending = [root / 'reports/V9-S6-PHASE1/run_s6p1.py']
    seen = set()
    while pending:
        p = pending.pop().resolve()
        if p in seen:
            continue
        seen.add(p)
        inside = p.is_relative_to(src)
        names = []
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Import):
                names += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ''
                if n.level:
                    if not inside:
                        continue
                    parts = list(p.relative_to(src).with_suffix('').parts)
                    pkg = parts[-1] == '__init__'
                    if pkg:
                        parts.pop()
                    drop = n.level - 1 if pkg else n.level
                    if drop:
                        parts = parts[:-drop]
                    base = '.'.join(parts + ([base] if base else []))
                names += [base] + [base + '.' + a.name for a in n.names if a.name != '*']
        for name in names:
            if not inside:
                sibling = p.parent / (name.split('.')[0] + '.py')
                if sibling.is_file():
                    pending.append(sibling)
            if name == 'ainerzero' or name.startswith('ainerzero.'):
                bits = name.split('.')
                for j in range(1, len(bits) + 1):
                    q = src.joinpath(*bits[:j])
                    if (q / '__init__.py').is_file():
                        pending.append(q / '__init__.py')
                    elif q.with_suffix('.py').is_file():
                        pending.append(q.with_suffix('.py'))
    seen.add(root / 'reports/V9-S6-PHASE1/verify_s6p1.py')
    return {str(p.relative_to(root)): sha(p) for p in sorted(seen)}

def audit_cells(root):
    base = root / 'artifacts/v9/s6/phase1/probe'
    problems, missing, rows, inputs = [], [], {}, {}
    pools = read(base / 'pools.json')
    ledger = read(base / 'train-ledger.json')
    for p in (base / 'pools.json', base / 'train-ledger.json'):
        inputs[str(p.relative_to(root))] = sha(p)
    def check(ok, label):
        if not ok:
            problems.append(label)
    first = None
    records = {}
    for arm in ARMS:
        cell = base / 'cells' / (arm + '-r0')
        p = cell / 'cell.json'
        if not p.exists():
            missing.append(arm + '-r0')
            continue
        rec = read(p)
        records[arm] = rec
        inputs[str(p.relative_to(root))] = sha(p)
        check(rec['schema'] == 's6.phase1.cell.v1', arm + ':schema')
        check(rec['arm'] == arm and rec['replicate'] == 0, arm + ':identity')
        check(rec['sizes'] == SIZES, arm + ':sizes')
        check(rec['cand_ns'] == 's6p1-pcand', arm + ':namespace')
        check(rec['net_seeds'] == [1, 2, 3], arm + ':seeds')
        def seed(*keys):
            raw='s6p1-pcand:'+':'.join(str(k) for k in keys)
            return int(hashlib.sha256(raw.encode()).hexdigest()[:16],16)&0x7fffffff
        check(rec['first_seed']==seed('s6-first',0), arm+':first seed derivation')
        check(rec['pool_seed']==seed('s6-pool',0), arm+':pool seed derivation')
        check(rec['pick_seed']==seed('s6-pick','R' if arm=='T' else arm,0), arm+':pick seed derivation')
        check(rec['pool_sha256'] == pools['0'], arm + ':pool SHA reference')
        tracks = rec['tracks']
        check(len(tracks) == (3 if arm == 'P' else 1), arm + ':track count')
        track_rows = []
        for ti, tr in enumerate(tracks):
            picks = tr['picks']
            check(len(picks) == 4 and all(len(p) == 3000 for p in picks), arm + ':pick budgets')
            flat = sum(picks, [])
            check(all(type(i) == int and 0 <= i < 60000 for i in flat), arm + ':ID range')
            check(len(set(flat)) == 12000, arm + ':unique labels per learner')
            check(tr['revealed'] == flat, arm + ':revealed order')
            check([e['ids'] for e in tr['reveal_log']] == picks, arm + ':reveal matches picks')
            check([e['call'] for e in tr['reveal_log']] == [0, 1, 2, 3], arm + ':reveal calls')
            if first is None:
                first = picks[0]
            check(picks[0] == first, arm + ':common first round')
            expected_first=np.random.default_rng(seed('s6-first',0)).choice(np.arange(60000),3000,replace=False).tolist()
            check(picks[0]==expected_first,arm+':independent first draw')
            if arm in ('R','T'):
                rand=np.random.default_rng(seed('s6-pick','R',0))
                taken=set(picks[0])
                for rr in range(1,4):
                    rem=np.array(sorted(set(range(60000))-taken))
                    expected=rand.choice(rem,3000,replace=False).tolist()
                    check(picks[rr]==expected,arm+':independent random round '+str(rr))
                    taken.update(picks[rr])
            ds = tr['score_sha256']
            check(len(ds) == 4 and ds[0] is None, arm + ':score digest count')
            check(all((isinstance(d, str) and len(d) == 64) if arm in ('E', 'Z', 'P') else d is None for d in ds[1:]), arm + ':score digest format')
            track_rows.append(dict(track=ti, labels=len(flat), picks_sha256=hashlib.sha256(json.dumps(picks, separators=(',', ':')).encode()).hexdigest()))
        want = {f'r{r}-n{j}.safetensors' for r in range(4) for j in range(3)}
        check(set(rec['files_sha256']) == want, arm + ':weight manifest membership')
        check({p.name for p in cell.glob('*.safetensors')} == want, arm + ':weight files membership')
        for name, digest in rec['files_sha256'].items():
            p = cell / name
            check(p.is_file() and sha(p) == digest, arm + ':weight SHA ' + name)
            if p.is_file():
                inputs[str(p.relative_to(root))] = sha(p)
                # Safetensors header parse only; no deserialization or model inference.
                with p.open('rb') as f:
                    n = int.from_bytes(f.read(8), 'little')
                    check(0 < n < min(p.stat().st_size, 10_000_000), arm + ':weight header size')
                    header = json.loads(f.read(n))
                intervals = sorted(v['data_offsets'] for k,v in header.items() if k != '__metadata__')
                check(bool(intervals) and intervals[0][0] == 0 and intervals[-1][1] == p.stat().st_size - 8 - n and all(a[1] == b[0] for a,b in zip(intervals, intervals[1:])), arm + ':weight buffer coverage')
        check([t['round'] for t in rec['timings']] == [0,1,2,3], arm + ':timing rounds')
        check(all(t['train_s'] > 0 and t['select_s'] >= 0 for t in rec['timings']), arm + ':positive timing')
        check(abs(sum(t['train_s'] + t['select_s'] for t in rec['timings']) - rec['seconds']) < 2, arm + ':timing total')
        rows[arm] = dict(seconds=rec['seconds'], weights=len(want), tracks=track_rows, timings=rec['timings'])
    if 'R' in records and 'T' in records:
        check(records['R']['tracks'][0]['picks'] == records['T']['tracks'][0]['picks'], 'R/T all picks equal')
        check(records['R']['pick_seed'] == records['T']['pick_seed'], 'R/T random seed')
    charges = []
    for row in ledger:
        check(row['last_beat'] >= row['start'], 'ledger monotonic')
        charges.append(row['last_beat'] - row['start'] + (0 if row['closed'] else 900))
        for c in row['cells']:
            check(c['replicate'] == 0 and c['arm'] in ARMS, 'ledger cell identity')
            if c['arm'] in rows:
                check(c['seconds'] == rows[c['arm']]['seconds'], 'ledger timing ' + c['arm'])
    complete = not missing and all(r['closed'] for r in ledger)
    totals = [c['arm'] for row in ledger for c in row['cells']]
    if complete:
        check(sorted(totals) == sorted(ARMS), 'ledger six cells exactly once')
    return dict(stage='complete' if complete else 'in_progress', problems=problems, missing=missing,
                cells=rows, ledger_charged_s=sum(charges), ledger_closed=all(r['closed'] for r in ledger)), inputs, records

def arm_stats(s, counts, eb):
    # Collapse numerator first: algebraically independent ratio-of-pooled-sums form.
    s = np.asarray(s, float)
    den = np.asarray(counts, float).sum(axis=0)
    avg = s.sum(axis=(-2,)).mean(axis=(0, 1))
    return {'D': float(1 - avg[0] / np.sum(eb)), **{k: float(avg[i] / den[i]) for i,k in enumerate(KINDS)}, 'all': float(avg.sum() / den.sum())}

def gate_values(a, x):
    return {'GS': a['E']['D']-a['R']['D'], 'GT': a['E']['D']-(a['T']['D']+a['R']['D'])/2,
            'GZ-D': a['E']['D']-a['Z']['D'], 'GZ-W': a['E']['wall_pillar']/a['Z']['wall_pillar'],
            'GK-A': a['E']['all']/a['R']['all'], 'GK-F': a['E']['free']/a['Z']['free'],
            'GP': a['P']['D']-a['R']['D'], 'GX': x['E']['D']-x['R']['D']}

def describe(arrays, rnd):
    out = {}
    for t in ('main6','extrap10'):
        a = {arm: arm_stats(arrays[f'{t}/sums/{arm}'][:,:,rnd], arrays[t+'/counts'], arrays[t+'/eb']) for arm in ARMS}
        out[t] = {'arms': a, 'D(E)-D(T)': a['E']['D']-a['T']['D'], 'D(P)-D(E)': a['P']['D']-a['E']['D'],
                  'D(E)-D(G)': a['E']['D']-a['G']['D'], 'G_replicates': 1,
                  **{f'E/{b}': {k:a['E'][k]/a[b][k] for k in (*KINDS,'all')} for b in ('R','Z')}}
    out['replicates'] = 1
    return out

def decide(arrays):
    desc = describe(arrays, 3)
    points = gate_values(desc['main6']['arms'], desc['extrap10']['arms'])
    rng = np.random.default_rng(20261114)
    # Explicit independent paired resampling, main then extrap per draw; no einsum/multiplicity implementation.
    draws = {'main6': np.empty((10000,50), dtype=int), 'extrap10': np.empty((10000,25), dtype=int)}
    for b in range(10000):
        for t in draws:
            w = draws[t].shape[1]
            draws[t][b] = rng.integers(w, size=w)
    bs = {}
    for t, ix in draws.items():
        c = arrays[t+'/counts'][ix].sum(axis=1)
        eb = arrays[t+'/eb'][ix].sum(axis=1)
        bs[t] = {}
        for arm in ARMS[:5]:
            # Process each draw by direct indexed summation, retaining the pairing.
            src = arrays[f'{t}/sums/{arm}'][0,:,3]
            mean_sum = np.stack([src[:, idx].sum(axis=1).mean(axis=0) for idx in ix])
            bs[t][arm] = {'D': 1-mean_sum[:,0]/eb, 'wall_pillar': mean_sum[:,2]/c[:,2],
                           'free': mean_sum[:,3]/c[:,3], 'all': mean_sum.sum(axis=1)/c.sum(axis=1)}
    boot = gate_values(bs['main6'], bs['extrap10'])
    out = {}
    for g,x in points.items():
        ratio = g in ('GZ-W','GK-A','GK-F')
        z = math.log(x) if ratio else x
        se = float(np.std(np.log(boot[g]) if ratio else boot[g], ddof=1))
        q = statistics.NormalDist().inv_cdf(1-.05/16)
        q95 = statistics.NormalDist().inv_cdf(.975)
        trans = math.exp if ratio else float
        lo,hi = trans(z-q*se),trans(z+q*se)
        point = {'GS':x>=.03, 'GT':True, 'GZ-D':x>=-.02, 'GZ-W':x<=.95, 'GK-A':x<=1.10, 'GK-F':x<=1.10, 'GP':x>=.03, 'GX':x>=.02}[g]
        interval = hi < 1 if g=='GZ-W' else hi <= 1.20 if g in ('GK-A','GK-F') else lo > (-.04 if g=='GZ-D' else 0)
        row = dict(point=x, per_replicate=[x], ci95=[trans(z-q95*se),trans(z+q95*se)], bonferroni=[lo,hi],
                   s_rep=0.0, se_w=se, se=se, q=q, df=None, point_ok=bool(point), interval_ok=bool(interval))
        if g == 'GS':
            row['per_replicate_ok'] = bool(x>=.03)
        row['passed'] = bool(point and interval and row.get('per_replicate_ok',True))
        out[g] = row
    return dict(gates=out, all_pass=all(r['passed'] for r in out.values()), m=8, alpha=.05, n_boot=10000, seed=20261114,
                replicates=1, levels={'bonferroni':1-.05/16,'ci95':.975})

def compare(a,b,path='',rows=None):
    if rows is None:
        rows=[]
    if isinstance(a,dict) and isinstance(b,dict):
        for k in sorted(set(a)|set(b)):
            if k not in a or k not in b:
                rows.append(dict(path=path+'/'+k, ok=False, reason='missing key'))
            else:
                compare(a[k],b[k],path+'/'+k,rows)
    elif isinstance(a,list) and isinstance(b,list):
        if len(a)!=len(b):
            rows.append(dict(path=path,ok=False,reason='length'))
        else:
            for i,(x,y) in enumerate(zip(a,b)):
                compare(x,y,path+'/'+str(i),rows)
    else:
        numeric = type(a) in (int,float) and type(b) in (int,float)
        ok = math.isclose(a,b,rel_tol=2e-11,abs_tol=2e-12) if numeric else type(a)==type(b) and a==b
        rows.append(dict(path=path,ok=bool(ok),independent=a,reported=b))
    return rows

def budget(audit,report):
    seconds = {arm:r['seconds'] for arm,r in audit['cells'].items()}
    weighted = sum(seconds[a]*REPS[a] for a in ARMS)
    cell_sum = sum(seconds.values())
    # Separate documented conservative pool allowance and observed ledger overhead.
    overhead = audit['ledger_charged_s']-cell_sum
    train = 1.15*(weighted+5*90)
    verification = report['verify_seconds']*28/6
    evaluation = report['eval_seconds']*(28/6)*4
    ev = 1.3*(verification+evaluation)
    return dict(final_cells=28,final_networks=84,final_weight_files=336,per_arm_probe_s=seconds,
                weighted_training_s=weighted,probe_ledger_overhead_s=overhead,observed_overhead_x5_s=5*overhead,
                conservative_pool_allowance_s=450,estimated_train_s=train,train_cap_s=21600,train_fits=train<=21600,
                projected_verify_s=verification,projected_scoring_s=evaluation,estimated_eval_s=ev,eval_cap_s=3600,eval_fits=ev<=3600,
                assumptions='Same-size cells; final 28/probe 6 cells; final/probe 300/75 worlds; 15% train and 30% eval reserve. Timing projection is not a resource reservation.')

def selfcheck():
    # Independent closed-form fixture; no production module or fixture import.
    c=np.array([[1,2,3,4],[4,3,2,1]])
    eb=np.array([2.,8.])
    s=np.tile(np.array([[[[1.,2.,3.,4.],[3.,4.,5.,6.]]]]),(1,3,1,1))
    a=arm_stats(s,c,eb)
    assert abs(a['D']-.6)<1e-14 and abs(a['all']-1.4)<1e-14
    assert a['collision']==.8 and a['free']==2.
    assert not compare({'x':1.},{'x':1.1})[0]['ok']
    assert compare({'x':True},{'x':True})[0]['ok']
    assert not compare({'x':True},{'x':1})[0]['ok']
    try:
        __import__('mlx')
    except RuntimeError:
        pass
    else:
        raise AssertionError('MLX import barrier failed')
    return dict(closed_form_D=.6,closed_form_all=1.4,comparison_tamper_rejected=True,mlx_import_blocked=True)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--report',type=Path)
    a=ap.parse_args()
    out=a.out.resolve()
    if not out.is_relative_to(HOME) or out==HOME:
        raise SystemExit('Output must be a new child directory within the reviewer scope')
    out.mkdir(parents=True,exist_ok=False)
    write(out/'selfcheck.json',selfcheck())
    audit,inputs,records=audit_cells(ROOT)
    manifest=source_manifest(ROOT)
    digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    write(out/'source-manifest.json',dict(files=manifest,sha256=digest))
    write(out/'integrity.json',audit)
    result=dict(status='tools_ready_waiting_tier1_eval_release',integrity_stage=audit['stage'],problems=audit['problems'])
    if a.report:
        if audit['stage']!='complete':
            raise AssertionError('Training incomplete')
        p=a.report.resolve()
        report=read(p)
        inputs[str(p.relative_to(ROOT))]=sha(p)
        base=ROOT/'artifacts/v9/s6/phase1/probe/eval-s6p1-probe'
        checks=[]
        def check(ok,path):
            checks.append(dict(path=path,ok=bool(ok)))
        check(report['schema']=='s6.phase1.eval.v1' and report['set']=='probe','report identity')
        check(report['git_head'].startswith('a33d34b') and report['code_dirty']==[],'reviewed source revision')
        check(report['code_manifest_sha256']==digest,'eval code manifest digest')
        for row in read(ROOT/'artifacts/v9/s6/phase1/probe/train-ledger.json'):
            check(row['code_manifest_sha256']==digest,'train code manifest digest')
            check(row['third_party']==report['third_party'],'train/eval recorded third-party versions')
        check(report['prereg_sha256'] is None,'probe has no final prereg identity')
        cfg=report['config']
        check(cfg==report['sets']['probe'],'probe config reference')
        check(cfg==dict(cand_ns='s6p1-pcand',test_ns='s6p1-probe',sizes=SIZES,reps={a:1 for a in ARMS},worlds=[50,25],train_cap_s=9000.,eval_limit_s=3600),'probe fixed config')
        check(report['sets']['final']==dict(cand_ns='s6p1-cand',test_ns='s6p1-final',sizes=SIZES,reps=REPS,worlds=[200,100],train_cap_s=21600.,eval_limit_s=3600),'final fixed config')
        check(set(report['files_sha256'])=={'verify.json','errors.npz','worlds.json'},'eval manifest members')
        for name,dig in report['files_sha256'].items():
            f=base/name
            check(f.is_file() and sha(f)==dig,'eval file SHA '+name)
            inputs[str(f.relative_to(ROOT))]=sha(f)
        check(set(report['cells_sha256'])=={a+'-r0' for a in ARMS},'six cell report membership')
        for arm in ARMS:
            cp=ROOT/'artifacts/v9/s6/phase1/probe/cells'/(arm+'-r0')/'cell.json'
            check(report['cells_sha256'][arm+'-r0']==sha(cp),'cell record SHA '+arm)
            check(report['train_seconds'][arm+'-r0']==records[arm]['seconds'],'train seconds '+arm)
        verify=read(base/'verify.json')
        check(verify==report['verify'],'verify embedded record equality')
        check(verify['passed'] is True and verify['pools_ok']=={'0':True},'verify overall/pools')
        check(set(verify['replay'])=={a+'-r0' for a in ARMS},'replay six cells')
        for arm in ARMS:
            v=verify['replay'][arm+'-r0']
            check(v['passed'] is True and v['first_ok'] is True and v['rounds_ok']==[True]*(9 if arm=='P' else 3),'replay rounds '+arm)
            check(len(v['contact_share'])==(3 if arm=='P' else 1) and all(len(s)==4 and all(0<=q<=1 for q in s) for s in v['contact_share']),'contact shares '+arm)
        check(set(verify['retrain'])=={'E-r0-n0','P-r0-n0'},'preselected retrain cells')
        for k,v in verify['retrain'].items():
            check(v==dict(seed=1,rounds_identical=[True]*4,passed=True),'retrain four bitwise rounds '+k)
        worlds=read(base/'worlds.json')
        check(worlds=={'main6':[[i,6] for i in range(50)],'extrap10':[[1000+i,10] for i in range(25)]},'world identity 50+25')
        with np.load(base/'errors.npz',allow_pickle=False) as z:
            arrays={k:z[k] for k in z.files}
        want={t+'/'+key for t in ('main6','extrap10') for key in ('counts','eb',*('sums/'+a for a in ARMS))}
        check(set(arrays)==want,'errors array membership')
        for t,w,n in [('main6',50,6),('extrap10',25,10)]:
            c,b=arrays[t+'/counts'],arrays[t+'/eb']
            check(c.shape==(w,4) and np.issubdtype(c.dtype,np.integer) and np.all(c>=0),'counts shape/type '+t)
            # World stores states 0..299; next-state evaluation covers 299 transitions.
            check(np.all(c.sum(1)==299*n),'299 evaluated transitions per world '+t)
            check(b.shape==(w,) and np.isfinite(b).all() and np.all(b>=0) and b.sum()>0,'baseline finite/nonnegative '+t)
            for arm in ARMS:
                s=arrays[t+'/sums/'+arm]
                check(s.shape==(1,3,4,w,4) and np.isfinite(s).all() and np.all(s>=0),'errors shape/finite '+t+'/'+arm)
        recomputed=decide(arrays)
        descriptive={f'round{r}':describe(arrays,r) for r in range(4)}
        selections={arm+'-r0':[len(set(x)&set(y))/3000 for x,y in zip(records[arm]['tracks'][0]['picks'][1:],records['E']['tracks'][0]['picks'][1:])] for arm in ('R','Z','T','G')}
        checks+=compare(recomputed,report['result'],'result')
        checks+=compare(descriptive,report['descriptive'],'descriptive')
        checks+=compare(selections,report['selection'],'selection')
        write(out/'recomputed.json',dict(result=recomputed,descriptive=descriptive,selection=selections))
        write(out/'comparison.json',checks)
        projected=budget(audit,report)
        write(out/'budget.json',projected)
        bad=[r for r in checks if not r['ok']]
        result=dict(status='recommend_pass' if not bad and not audit['problems'] and projected['train_fits'] and projected['eval_fits'] else 'recommend_return',compared_fields=len(checks),mismatches=bad,integrity_problems=audit['problems'],budget_fits=projected['train_fits'] and projected['eval_fits'],recorded_third_party=report['third_party'],scientific_conclusion=False,
                    verification_limit='CPU verifies saved replay/retrain records and SHA identity; does not rerun model inference, worlds, labels, or training.')
    write(out/'inputs-sha256.json',inputs)
    write(out/'summary.json',result)
    write(out/'environment.json',dict(python=sys.version,numpy=np.__version__,platform=platform.platform(),argv=sys.argv,forbidden_modules_loaded=[n for n in sys.modules if n.split('.')[0] in ('mlx','ainerzero')]))
    print(json.dumps(result,ensure_ascii=False))
    if result.get('problems') or result['status']=='recommend_return':
        raise SystemExit(1)

if __name__=='__main__':
    main()
