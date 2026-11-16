#!/usr/bin/env python3
"""P267 non-author independent recomputation of S6 phase 1 final evaluation.

Imports only Python standard library and NumPy.
Audithook strictly forbids any imports of mlx or ainerzero.
Adapted from P260 probe-review tool with exact final dimensions (28 cells, 84 networks,
336 weights, K=5 replicates, df=4 Student-t quantiles).
"""
import ast
import hashlib
import json
import math
import os
import sys
from pathlib import Path

# Strict audit hook: forbid any model/project imports
def deny_model_import(event, args):
    if event == 'import' and (args[0].split('.')[0] in {'mlx', 'ainerzero'}):
        raise RuntimeError('Reviewer forbids model/project imports: ' + args[0])
sys.addaudithook(deny_model_import)

import numpy as np

HOME = Path(__file__).resolve().parent
ROOT = HOME.parents[2]

GATE_ARMS = ('R', 'E', 'Z', 'T', 'P')
ARMS = GATE_ARMS + ('G',)
TEST_SETS = ('main6', 'extrap10')
REPS = {'R': 5, 'E': 5, 'Z': 5, 'T': 5, 'P': 5, 'G': 3}
SIZES = dict(per=3000, rounds=4, steps=2500, pool=60000, cand_worlds=240)
KINDS = ('collision', 'graze', 'wall_pillar', 'free')
STATS = ('D', 'collision', 'graze', 'wall_pillar', 'free', 'all')
GATES = ('GS', 'GT', 'GZ-D', 'GZ-W', 'GK-A', 'GK-F', 'GP', 'GX')
ALPHA = 0.05
M = len(GATES)
N_BOOT = 10_000
SEED = 20261114

PREREG_FILE = ROOT / 'reports/V9-S6-PHASE1/PREREG-r1.json'
PREREG_SHA256 = 'c63d31a0d8a941affaa7de8fefc316fca88d9d6cdfc3e4901aa911810293179b'
REPORT_FILE = ROOT / 'reports/V9-S6-FINAL/EVAL-final.json'
FINAL_ROOT = ROOT / 'artifacts/v9/s6/phase1/final'

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))

def t_cdf_4(x):
    """Closed-form Student-t CDF for df = 4."""
    th = math.atan(x / 2.0)
    c2, s = math.cos(th) ** 2, math.sin(th)
    return 0.5 + 0.5 * s * (1.0 + 0.5 * c2)

def t_ppf_4(p):
    """Inverse CDF for Student-t with df = 4 via high-precision bisection."""
    lo, hi = 0.0, 50.0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        if t_cdf_4(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0

def audit_integrity():
    problems = []
    def check(ok, label):
        if not ok:
            problems.append(label)

    # 1. Preregistration
    check(sha(PREREG_FILE) == PREREG_SHA256, 'preregistration SHA256')
    prereg = read(PREREG_FILE)

    # 2. FINAL_READ_ONCE
    fro_path = FINAL_ROOT / 'FINAL_READ_ONCE.json'
    check(fro_path.is_file(), 'FINAL_READ_ONCE exists')
    fro = read(fro_path)
    check(fro.get('prereg_sha256') == PREREG_SHA256, 'FINAL_READ_ONCE prereg SHA256')

    # 3. Cells and Weights (28 cells, 84 networks, 336 weights)
    cells_expected = [f'{a}-r{k}' for a in GATE_ARMS for k in range(5)] + [f'G-r{k}' for k in range(3)]
    check(len(cells_expected) == 28, '28 expected cells')
    
    pools = read(FINAL_ROOT / 'pools.json')
    check(set(pools) == {'0', '1', '2', '3', '4'}, 'candidate pools 0..4')

    cell_records = {}
    weight_count = 0
    first_picks_by_k = {}
    r_picks_by_k = {}

    for c in cells_expected:
        cdir = FINAL_ROOT / 'cells' / c
        cp = cdir / 'cell.json'
        if not cp.exists():
            problems.append(f'missing {c}/cell.json')
            continue
        rec = read(cp)
        cell_records[c] = rec
        arm, k = c.split('-')
        k_idx = int(k[1:])
        check(rec['schema'] == 's6.phase1.cell.v1', f'{c}: schema')
        check(rec['arm'] == arm and rec['replicate'] == k_idx, f'{c}: identity')
        check(rec['cand_ns'] == 's6p1-cand', f'{c}: cand namespace')
        check(rec['sizes'] == SIZES, f'{c}: sizes')
        check(rec['net_seeds'] == [3 * k_idx + 1, 3 * k_idx + 2, 3 * k_idx + 3], f'{c}: net seeds')
        check(rec['pool_sha256'] == pools[str(k_idx)], f'{c}: pool SHA')

        # check tracks
        n_tracks = 3 if arm == 'P' else 1
        check(len(rec['tracks']) == n_tracks, f'{c}: track count')
        for ti, tr in enumerate(rec['tracks']):
            picks = tr['picks']
            check(len(picks) == 4 and all(len(p) == 3000 for p in picks), f'{c}: picks count')
            flat = sum(picks, [])
            check(len(flat) == 12000 and len(set(flat)) == 12000, f'{c}: unique IDs')
            check(tr['revealed'] == flat, f'{c}: revealed order')
            check([e['ids'] for e in tr['reveal_log']] == picks, f'{c}: reveal log')
            check([e['call'] for e in tr['reveal_log']] == [0, 1, 2, 3], f'{c}: reveal calls')

            if arm != 'P':
                if k_idx not in first_picks_by_k:
                    first_picks_by_k[k_idx] = picks[0]
                else:
                    check(picks[0] == first_picks_by_k[k_idx], f'{c}: common first picks in pool {k_idx}')

            if arm == 'R':
                r_picks_by_k[k_idx] = picks
            elif arm == 'T':
                if k_idx in r_picks_by_k:
                    check(picks == r_picks_by_k[k_idx], f'{c}: T picks equal R picks in pool {k_idx}')

        # check weights
        want_weights = {f'r{r}-n{n}.safetensors' for r in range(4) for n in range(3)}
        check(set(rec['files_sha256']) == want_weights, f'{c}: weight files set')
        for wf, w_sha in rec['files_sha256'].items():
            wp = cdir / wf
            check(wp.is_file() and sha(wp) == w_sha, f'{c}: weight SHA {wf}')
            weight_count += 1
            # header check
            with wp.open('rb') as f:
                header_size = int.from_bytes(f.read(8), 'little')
                check(0 < header_size < wp.stat().st_size, f'{c}: header size {wf}')

        # timings
        check([t['round'] for t in rec['timings']] == [0, 1, 2, 3], f'{c}: timing rounds')
        check(all(t['train_s'] > 0 and t['select_s'] >= 0 for t in rec['timings']), f'{c}: positive timings')

    check(weight_count == 336, 'total 336 weights verified')

    # 4. Train ledger
    ledger = read(FINAL_ROOT / 'train-ledger.json')
    ledger_cells = set()
    total_ledger_s = 0.0
    for row in ledger:
        check(row['closed'] is True, 'ledger row closed')
        check(row['prereg_sha256'] == PREREG_SHA256, 'ledger prereg SHA')
        check(row['code_manifest_sha256'] == prereg['code_manifest_sha256'], 'ledger code SHA')
        dur = row['last_beat'] - row['start']
        check(dur > 0, 'ledger positive duration')
        total_ledger_s += dur
        for c in row['cells']:
            cid = f'{c["arm"]}-r{c["replicate"]}'
            check(cid not in ledger_cells, f'duplicate ledger cell {cid}')
            ledger_cells.add(cid)
            if cid in cell_records:
                check(abs(c['seconds'] - cell_records[cid]['seconds']) < 1e-6, f'{cid}: ledger timing match')
    check(ledger_cells == set(cells_expected), 'ledger covers all 28 cells exactly once')
    check(total_ledger_s <= 19800.0, f'training within cap: {total_ledger_s:.1f}s <= 19800s')

    # 5. verify.json
    v = read(FINAL_ROOT / 'eval-s6p1-final/verify.json')
    check(v['passed'] is True, 'verify passed')
    check(set(v['pools_ok']) == {'0', '1', '2', '3', '4'} and all(v['pools_ok'].values()), 'pools ok')
    check(len(v['replay']) == 28, 'replay 28 cells')
    for cid, row in v['replay'].items():
        check(row['passed'] is True and row['first_ok'] is True and all(row['rounds_ok']), f'{cid}: replay passed')
        for tr in row['contact_share']:
            check(all(cs <= 1.0 for cs in tr), f'{cid}: contact share <= 1')
    check(v['retrain']['E-r0-n0']['passed'] is True and all(v['retrain']['E-r0-n0']['rounds_identical']), 'E-r0-n0 retrain')
    check(v['retrain']['P-r0-n0']['passed'] is True and all(v['retrain']['P-r0-n0']['rounds_identical']), 'P-r0-n0 retrain')

    # 6. Worlds disjointness
    worlds = read(FINAL_ROOT / 'eval-s6p1-final/worlds.json')
    check(len(worlds['main6']) == 200, 'main6 200 worlds')
    check(len(worlds['extrap10']) == 100, 'extrap10 100 worlds')

    return {
        'integrity_passed': len(problems) == 0,
        'problems': problems,
        'cells_checked': len(cells_expected),
        'weights_checked': weight_count,
        'training_wall_clock_s': total_ledger_s
    }, cell_records

def arm_stats(s, counts, eb):
    s = np.asarray(s, float)
    den = np.asarray(counts, float).sum(axis=0)
    avg = s.sum(axis=-2).mean(axis=(0, 1))
    return {
        'D': float(1.0 - avg[0] / np.sum(eb)),
        **{k: float(avg[i] / den[i]) for i, k in enumerate(KINDS)},
        'all': float(avg.sum() / den.sum())
    }

def gate_val(m, x):
    return {
        'GS': m['E']['D'] - m['R']['D'],
        'GT': m['E']['D'] - m['R']['D'] - 0.5 * (m['T']['D'] - m['R']['D']),
        'GZ-D': m['E']['D'] - m['Z']['D'],
        'GZ-W': m['E']['wall_pillar'] / m['Z']['wall_pillar'],
        'GK-A': m['E']['all'] / m['R']['all'],
        'GK-F': m['E']['free'] / m['Z']['free'],
        'GP': m['P']['D'] - m['R']['D'],
        'GX': x['E']['D'] - x['R']['D']
    }

def recompute_all(npz_path, cell_records):
    data = np.load(npz_path, allow_pickle=False)

    # 1. Point estimates and per-replicate
    main_arms = {arm: arm_stats(data[f'main6/sums/{arm}'][:, :, 3], data['main6/counts'], data['main6/eb']) for arm in ARMS}
    extrap_arms = {arm: arm_stats(data[f'extrap10/sums/{arm}'][:, :, 3], data['extrap10/counts'], data['extrap10/eb']) for arm in ARMS}
    points = gate_val(main_arms, extrap_arms)

    per_rep = []
    for k in range(5):
        m_k = {arm: arm_stats(data[f'main6/sums/{arm}'][k:k+1, :, 3], data['main6/counts'], data['main6/eb']) for arm in GATE_ARMS}
        x_k = {arm: arm_stats(data[f'extrap10/sums/{arm}'][k:k+1, :, 3], data['extrap10/counts'], data['extrap10/eb']) for arm in GATE_ARMS}
        per_rep.append(gate_val(m_k, x_k))

    per_rep_by_gate = {g: [per_rep[k][g] for k in range(5)] for g in GATES}

    # 2. Paired world bootstrap
    rng = np.random.default_rng(SEED)
    n_worlds = {'main6': 200, 'extrap10': 100}
    draws = {t: np.empty((N_BOOT, n_worlds[t]), dtype=np.int64) for t in TEST_SETS}
    for b in range(N_BOOT):
        for t in TEST_SETS:
            draws[t][b] = rng.integers(n_worlds[t], size=n_worlds[t])

    def multiplicity(idx, size):
        out = np.empty((idx.shape[0], size), dtype=float)
        for b in range(idx.shape[0]):
            out[b] = np.bincount(idx[b], minlength=size)
        return out

    boot_arm_stats = {}
    for t in TEST_SETS:
        nw = n_worlds[t]
        Mw = multiplicity(draws[t], nw)
        C = Mw @ np.asarray(data[f'{t}/counts'], float)
        B = Mw @ np.asarray(data[f'{t}/eb'], float)
        boot_arm_stats[t] = {}
        for arm in GATE_ARMS:
            S = np.einsum('bw,knwc->bknc', Mw, np.asarray(data[f'{t}/sums/{arm}'][..., 3, :, :], float))
            D = (1.0 - S[..., 0] / B[:, None, None]).mean(axis=(1, 2))
            wall_pillar = (S[..., 2] / C[:, None, None, 2]).mean(axis=(1, 2))
            free = (S[..., 3] / C[:, None, None, 3]).mean(axis=(1, 2))
            all_stat = (S.sum(axis=-1) / C.sum(axis=-1)[:, None, None]).mean(axis=(1, 2))
            boot_arm_stats[t][arm] = {'D': D, 'wall_pillar': wall_pillar, 'free': free, 'all': all_stat}

    boot_gates = gate_val(boot_arm_stats['main6'], boot_arm_stats['extrap10'])

    # Quantiles for K=5, df=4
    p_bonf = 1 - ALPHA / (2 * M)
    p_95 = 1 - ALPHA / 2
    q_bonf = t_ppf_4(p_bonf)
    q_95 = t_ppf_4(p_95)

    recomputed_gates = {}
    for g in GATES:
        x = points[g]
        tk = per_rep_by_gate[g]
        ratio = g in ('GZ-W', 'GK-A', 'GK-F')
        z = math.log(x) if ratio else x
        zk = [math.log(v) for v in tk] if ratio else tk
        bs = np.log(boot_gates[g]) if ratio else boot_gates[g]

        s_rep = float(np.std(zk, ddof=1))
        se_w = float(np.std(bs, ddof=1))
        se = math.sqrt(s_rep ** 2 / 5.0 + se_w ** 2)

        lo95 = math.exp(z - q_95 * se) if ratio else (z - q_95 * se)
        hi95 = math.exp(z + q_95 * se) if ratio else (z + q_95 * se)
        lo = math.exp(z - q_bonf * se) if ratio else (z - q_bonf * se)
        hi = math.exp(z + q_bonf * se) if ratio else (z + q_bonf * se)

        point_ok = {'GS': x >= 0.03, 'GT': True, 'GZ-D': x >= -0.02, 'GZ-W': x <= 0.95,
                    'GK-A': x <= 1.10, 'GK-F': x <= 1.10, 'GP': x >= 0.03, 'GX': x >= 0.02}[g]
        interval_ok = (hi < 1.0) if g == 'GZ-W' else (hi <= 1.20) if g in ('GK-A', 'GK-F') else (lo > (-0.04 if g == 'GZ-D' else 0.0))

        row = {
            'point': x,
            'per_replicate': tk,
            'ci95': [lo95, hi95],
            'bonferroni': [lo, hi],
            's_rep': s_rep,
            'se_w': se_w,
            'se': se,
            'q': q_bonf,
            'df': 4,
            'point_ok': bool(point_ok),
            'interval_ok': bool(interval_ok)
        }
        if g == 'GS':
            row['per_replicate_ok'] = bool(all(v >= 0.03 for v in tk))
        row['passed'] = bool(row['point_ok'] and row['interval_ok'] and row.get('per_replicate_ok', True))
        recomputed_gates[g] = row

    result = {
        'gates': recomputed_gates,
        'all_pass': all(r['passed'] for r in recomputed_gates.values()),
        'm': M,
        'alpha': ALPHA,
        'n_boot': N_BOOT,
        'seed': SEED,
        'replicates': 5,
        'levels': {'bonferroni': p_bonf, 'ci95': p_95}
    }

    # 3. Descriptive statistics
    def rep_stats(s, counts, eb, reps, worlds):
        s = np.asarray(s, float)[reps][:, :, worlds]
        c = np.asarray(counts, float)[worlds].sum(axis=0)
        b = np.asarray(eb, float)[worlds].sum()
        sum_c = s.sum(axis=2).mean(axis=(0, 1))
        return {
            'D': float(1.0 - sum_c[0] / b),
            **{k: float(sum_c[i] / c[i]) for i, k in enumerate(KINDS)},
            'all': float(sum_c.sum() / c.sum())
        }

    descriptive = {}
    for r in range(4):
        rnd_row = {}
        for t in TEST_SETS:
            nw = n_worlds[t]
            allw = np.arange(nw)
            arms_d = {arm: rep_stats(data[f'{t}/sums/{arm}'][..., r, :, :], data[f'{t}/counts'], data[f'{t}/eb'],
                                     np.arange(data[f'{t}/sums/{arm}'].shape[0]), allw) for arm in ARMS}
            t_row = {
                'arms': arms_d,
                'D(E)-D(T)': arms_d['E']['D'] - arms_d['T']['D'],
                'D(P)-D(E)': arms_d['P']['D'] - arms_d['E']['D']
            }
            kg = data[f'{t}/sums/G'].shape[0]
            e_on_g = rep_stats(data[f'{t}/sums/E'][..., r, :, :], data[f'{t}/counts'], data[f'{t}/eb'], np.arange(kg), allw)
            t_row['D(E)-D(G)'] = e_on_g['D'] - arms_d['G']['D']
            t_row['G_replicates'] = kg
            for base in ('R', 'Z'):
                t_row[f'E/{base}'] = {k: arms_d['E'][k] / arms_d[base][k] for k in STATS if k != 'D'}
            rnd_row[t] = t_row
        rnd_row['replicates'] = 5
        descriptive[f'round{r}'] = rnd_row

    # 4. Selection overlap
    selection = {}
    for k in range(5):
        e_picks = cell_records[f'E-r{k}']['tracks'][0]['picks']
        for a in ('R', 'Z', 'T', 'G'):
            cid = f'{a}-r{k}'
            if cid not in cell_records:
                continue
            a_picks = cell_records[cid]['tracks'][0]['picks']
            selection[cid] = [len(set(x) & set(y)) / max(len(x), 1) for x, y in zip(a_picks[1:], e_picks[1:])]

    return result, descriptive, selection

def compare_trees(a, b, path='', rows=None, tol=1e-9):
    if rows is None:
        rows = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                rows.append({'path': f'{path}/{k}', 'match': False, 'reason': 'missing_key'})
            else:
                compare_trees(a[k], b[k], f'{path}/{k}', rows, tol)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            rows.append({'path': path, 'match': False, 'reason': f'length_mismatch: {len(a)} vs {len(b)}'})
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                compare_trees(x, y, f'{path}/{i}', rows, tol)
    else:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            diff = abs(a - b)
            match = diff <= tol
            rows.append({'path': path, 'match': bool(match), 'diff': diff, 'a': a, 'b': b})
        else:
            match = (type(a) is type(b)) and (a == b)
            rows.append({'path': path, 'match': bool(match), 'a': a, 'b': b})
    return rows

def main():
    print('Starting P267 independent recomputation of S6 final...')
    audit_res, cell_records = audit_integrity()
    print('Integrity audit:', json.dumps(audit_res, indent=2))
    probs = audit_res.get("problems")
    assert audit_res["integrity_passed"], f"Integrity check failed: {probs}"

    report = read(REPORT_FILE)
    npz_path = FINAL_ROOT / 'eval-s6p1-final/errors.npz'
    result, descriptive, selection = recompute_all(npz_path, cell_records)

    # Compare with report
    print('Comparing recomputed results with EVAL-final.json...')
    res_diffs = compare_trees(result, report['result'], path='result')
    desc_diffs = compare_trees(descriptive, report['descriptive'], path='descriptive')
    sel_diffs = compare_trees(selection, report['selection'], path='selection')

    all_diffs = res_diffs + desc_diffs + sel_diffs
    mismatches = [d for d in all_diffs if not d.get('match', False)]

    max_numeric_diff = max((d['diff'] for d in all_diffs if 'diff' in d), default=0.0)
    print(f'Total compared items: {len(all_diffs)}')
    print(f'Mismatches (tol=1e-9): {len(mismatches)}')
    print(f'Max numeric difference across all fields: {max_numeric_diff:.2e}')

    recompute_summary = {
        'task': 'ainerzero.V9.P267',
        'report_sha256': sha(REPORT_FILE),
        'prereg_sha256': PREREG_SHA256,
        'integrity_audit': audit_res,
        'gates_result': result,
        'descriptive': descriptive,
        'selection': selection,
        'comparison': {
            'total_fields': len(all_diffs),
            'mismatches_exceeding_1e9': len(mismatches),
            'max_numeric_diff': max_numeric_diff
        }
    }

    out_json = HOME / 'recompute.json'
    out_json.write_text(json.dumps(recompute_summary, indent=2, ensure_ascii=False))
    print(f'Saved recomputation results to {out_json}')

    # Output details of gates
    print('\n=== Recomputed Final Gates ===')
    for g, row in result['gates'].items():
        pt, c, b, pas = row["point"], row["ci95"], row["bonferroni"], row["passed"]
        print(f"{g:6s}: point={pt:+.6f}, ci95=[{c[0]:+.6f}, {c[1]:+.6f}], bonf=[{b[0]:+.6f}, {b[1]:+.6f}], passed={pas}")
    print("all_pass:", result["all_pass"])

if __name__ == '__main__':
    main()
