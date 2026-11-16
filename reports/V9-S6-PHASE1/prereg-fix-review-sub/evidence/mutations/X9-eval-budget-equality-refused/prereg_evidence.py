"""Read-only CPU evidence closure for the S6 preregistration builder.

Never imports the runner, cells or MLX. This verifies integrity and internal
consistency, not cryptographic provenance against a malicious evidence author.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import io
import json
import math
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ainerzero.v9.experiments.s3 import run_guard as GD
from ainerzero.v9.experiments.s6 import analysis as AN


class EvidenceError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise EvidenceError(message)


def keys(obj, expected, label):
    require(type(obj) is dict and set(obj) == set(expected), f"{label}: incorrect key set")


def number(value, label, *, zero=False):
    require(type(value) in (int, float) and math.isfinite(value)
            and (value >= 0 if zero else value > 0), f"{label}: expected finite {'nonnegative' if zero else 'positive'} number")
    return value


def same(actual, expected, label):
    """Typed structural equality; recomputed undefined science statistics may be NaN."""
    if type(expected) is dict:
        keys(actual, expected, label)
        for k in expected:
            same(actual[k], expected[k], f"{label}/{k}")
    elif type(expected) is list:
        require(type(actual) is list and len(actual) == len(expected), f"{label}: list length/type")
        for i, (a, e) in enumerate(zip(actual, expected)):
            same(a, e, f"{label}/{i}")
    elif type(expected) in (float, int):
        require(type(actual) is int if type(expected) is int else type(actual) in (float, int), f"{label}: numeric type")
        require((math.isnan(expected) and math.isnan(actual)) or actual == expected,
                f"{label}: value differs")
    else:
        require(type(actual) is type(expected) and actual == expected, f"{label}: value/type differs")


def manifest_sha(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def cpu_versions(repo):
    """Match the runner's version semantics without importing MLX.

    MLX is a namespace package on the supported installation: its top-level
    module has no __version__, and the runner records 'unknown'. Refuse other
    layouts instead of guessing. NumPy is already loaded for CPU analysis.
    """
    spec = importlib.machinery.PathFinder.find_spec("mlx", sys.path)
    require(spec is not None and spec.origin is None and spec.submodule_search_locations,
            "MLX must be the installed namespace package (no import performed)")
    prefix = Path(sys.prefix).resolve()
    for p in [Path(np.__file__), *(Path(p) for p in spec.submodule_search_locations)]:
        p = p.resolve()
        require(not p.is_relative_to(repo.resolve()) or p.is_relative_to(prefix), "third-party library shadowed by repository")
    return {"numpy": str(np.__version__), "mlx": "unknown"}


def source_sets(repo):
    """Read configuration expressions only, never execute module bodies/imports."""
    cell = ast.parse((repo / 'src/ainerzero/v9/experiments/s6/cells.py').read_text())
    values = {}
    for node in cell.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('ARMS', 'REPLICATES', 'N_LEARNERS'):
                values[name] = ast.literal_eval(node.value)
        if isinstance(node, ast.ClassDef) and node.name == 'Sizes':
            values['FULL'] = {n.target.id: ast.literal_eval(n.value) for n in node.body if isinstance(n, ast.AnnAssign)}
    require(values['N_LEARNERS'] == 3 and tuple(values['ARMS']) == AN.ARMS, 'learner/arm definitions changed')
    # Only these literal configuration expressions are evaluated, in an import-free
    # namespace. Unexpected syntax fails before evaluation.
    C = SimpleNamespace(**values, Sizes=lambda **kw: {**values['FULL'], **kw})
    env = {'__builtins__': {}, 'dict': dict, 'C': C}
    allowed = (ast.Expression, ast.Dict, ast.Constant, ast.Name, ast.Load, ast.Attribute,
               ast.Call, ast.keyword, ast.Tuple, ast.List, ast.BinOp, ast.Mult,
               ast.DictComp, ast.comprehension, ast.Store)
    tree = ast.parse((repo / 'reports/V9-S6-PHASE1/run_s6p1.py').read_text())
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name in ('SMOKE_SIZES', 'SETS'):
            expression = ast.Expression(node.value)
            require(all(isinstance(n, allowed) for n in ast.walk(expression)), 'unsupported configuration expression')
            env[name] = eval(compile(expression, '<S6 config only>', 'eval'), env)
    sets = json.loads(json.dumps(env['SETS']))
    expected_sizes = dict(per=3000, rounds=4, steps=2500, pool=60000, cand_worlds=240)
    for name in ('probe', 'final'):
        same(sets[name]['sizes'], expected_sizes, name + ' sizes')
    same(sets['probe']['reps'], {a: 1 for a in AN.ARMS}, 'probe replicates')
    same(sets['final']['reps'], {**{a: 5 for a in AN.GATE_ARMS}, 'G': 3}, 'final replicates')
    same(sets['probe']['worlds'], [50, 25], 'probe worlds')
    same(sets['final']['worlds'], [200, 100], 'final worlds')
    same(sets['final']['train_cap_s'], 21600.0, 'final training cap')
    same(sets['final']['eval_limit_s'], 3600, 'final eval cap')
    require(sets['probe']['cand_ns'] == 's6p1-pcand' and sets['probe']['test_ns'] == 's6p1-probe'
            and sets['final']['cand_ns'] == 's6p1-cand' and sets['final']['test_ns'] == 's6p1-final', 'partition names')
    return sets


def committed_identity(repo, code, report_head):
    # --no-optional-locks keeps read-only status from refreshing .git/index.
    def git(*args):
        r = subprocess.run(['git', '--no-optional-locks', *args], cwd=repo, capture_output=True, text=True)
        require(r.returncode == 0, 'cannot read committed source identity')
        return r.stdout.strip()
    head = git('rev-parse', 'HEAD')
    require(not git('status', '--porcelain', '--', *code), 'numerical source files are not committed')
    require(type(report_head) is str and len(report_head) == 40
            and all(c in '0123456789abcdef' for c in report_head), 'invalid report git_head')
    for commit in {head, report_head}:
        run = subprocess.run(['git', 'archive', commit, *code], cwd=repo, capture_output=True)
        require(run.returncode == 0, f'cannot read committed source tree {commit}')
        with tarfile.open(fileobj=io.BytesIO(run.stdout), mode='r:') as archive:
            files = {m.name: m for m in archive.getmembers() if m.isfile()}
            keys(files, code, 'committed code files')
            for rel, digest in code.items():
                require(hashlib.sha256(archive.extractfile(files[rel]).read()).hexdigest() == digest,
                        f'code differs at committed identity {commit}: {rel}')
    return head


def seed(namespace, *parts):
    raw = f"{namespace}:" + ':'.join(str(p) for p in parts)
    return int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16) & 0x7fffffff


class Closure:
    def __init__(self, repo):
        self.repo, self.files = repo.resolve(), {}

    def read(self, path):
        path = path.resolve()
        require(path.is_relative_to(self.repo), f'evidence outside repository: {path}')
        data = path.read_bytes()
        rel, digest = str(path.relative_to(self.repo)), hashlib.sha256(data).hexdigest()
        require(rel not in self.files or self.files[rel] == digest, f'evidence changed while reading: {rel}')
        self.files[rel] = digest
        return data

    def json(self, path):
        def unique(pairs):
            out = {}
            for k, v in pairs:
                require(k not in out, f'duplicate JSON key {k}: {path}')
                out[k] = v
            return out
        return json.loads(self.read(path), object_pairs_hook=unique)

    def hashed(self, directory, hashes, expected):
        keys(hashes, expected, str(directory))
        for name, want in hashes.items():
            require(type(want) is str and len(want) == 64 and all(c in '0123456789abcdef' for c in want), f'invalid SHA: {name}')
            actual = hashlib.sha256(self.read(directory / name)).hexdigest()
            require(actual == want, f'hash differs: {directory / name}')

    def unchanged(self):
        require(not GD.check_manifest(self.repo, self.files), 'evidence changed during validation')


def check_cell(rec, arm, cfg, pools, directory, closure):
    same(rec['schema'], 's6.phase1.cell.v1', 'cell schema')
    same(rec['arm'], arm, 'cell arm')
    same(rec['replicate'], 0, 'cell replicate')
    same(rec['cand_ns'], cfg['cand_ns'], 'candidate namespace')
    same(rec['sizes'], cfg['sizes'], 'cell sizes')
    same(rec['net_seeds'], [1, 2, 3], 'network seeds')
    for key, parts in {'first_seed': ('s6-first', 0), 'pool_seed': ('s6-pool', 0),
                       'pick_seed': ('s6-pick', 'R' if arm == 'T' else arm, 0)}.items():
        same(rec[key], seed(cfg['cand_ns'], *parts), key)
    same(rec['pool_sha256'], pools['0'], 'cell pool SHA')
    per, rounds, pool = (cfg['sizes'][k] for k in ('per', 'rounds', 'pool'))
    require(type(rec['tracks']) is list and len(rec['tracks']) == (3 if arm == 'P' else 1), 'track count')
    for track in rec['tracks']:
        keys(track, ('picks', 'reveal_log', 'revealed', 'score_sha256'), 'track')
        picks = track['picks']
        require(type(picks) is list and len(picks) == rounds, 'pick rounds')
        for ids in picks:
            require(type(ids) is list and len(ids) == per and all(type(i) is int and 0 <= i < pool for i in ids), 'pick IDs')
        flat = [i for ids in picks for i in ids]
        require(len(set(flat)) == len(flat), 'duplicate picks')
        same(track['revealed'], flat, 'revealed IDs')
        same(track['reveal_log'], [{'call': r, 'ids': ids} for r, ids in enumerate(picks)], 'reveal log')
        scores = track['score_sha256']
        require(type(scores) is list and len(scores) == rounds and scores[0] is None, 'score digest rounds')
        for s in scores[1:]:
            require((s is None if arm in ('R', 'T', 'G') else type(s) is str and len(s) == 64
                     and all(c in '0123456789abcdef' for c in s)), 'score digest')
    seconds = number(rec['seconds'], 'cell seconds')
    require(type(rec['timings']) is list and len(rec['timings']) == rounds, 'timing rounds')
    total = 0
    for r, timing in enumerate(rec['timings']):
        keys(timing, ('round', 'train_s', 'select_s'), 'round timing')
        same(timing['round'], r, 'timing round index')
        total += number(timing['train_s'], 'round training') + number(timing['select_s'], 'round selection', zero=True)
    require(total <= seconds + .15, 'round timings exceed cell seconds (rounding allowance .15s)')
    names = {f'r{r}-n{j}.safetensors' for r in range(rounds) for j in range(3)}
    require({p.name for p in directory.iterdir()} == names | {'cell.json'}, 'cell directory file set')
    closure.hashed(directory, rec['files_sha256'], names)


def check_verify(v, recs):
    keys(v, ('replay', 'retrain', 'pools_ok', 'passed'), 'verify')
    same(v['passed'], True, 'verify passed')
    same(v['pools_ok'], {'0': True}, 'pool verification')
    keys(v['replay'], recs, 'replay cells')
    for cell, rec in recs.items():
        row = v['replay'][cell]
        keys(row, ('first_ok', 'rounds_ok', 'contact_share', 'passed'), 'replay record')
        same(row['first_ok'], True, 'first picks replay')
        same(row['passed'], True, 'replay passed')
        same(row['rounds_ok'], [True] * (3 * len(rec['tracks'])), 'replayed selection rounds')
        require(type(row['contact_share']) is list and len(row['contact_share']) == len(rec['tracks']), 'contact tracks')
        for track in row['contact_share']:
            require(type(track) is list and len(track) == 4, 'contact rounds')
            for share in track:
                require(number(share, 'contact share', zero=True) <= 1, 'contact share > 1')
    keys(v['retrain'], ('E-r0-n0', 'P-r0-n0'), 'retraining cells')
    for row in v['retrain'].values():
        same(row, {'seed': 1, 'rounds_identical': [True] * 4, 'passed': True}, 'retraining record')


def analysis_input(arrays, rnd):
    return {t: {'sums': {a: arrays[f'{t}/sums/{a}'][:, :, rnd] for a in AN.ARMS},
                'counts': arrays[f'{t}/counts'], 'eb': arrays[f'{t}/eb']} for t in AN.TEST_SETS}


def validate_probe(repo, probe, code, versions):
    """Read actual runner paths; do not follow input-provided artifact paths."""
    closure = Closure(repo)
    pr = closure.json(probe)
    required = {'schema', 'set', 'sets', 'config', 'third_party', 'prereg_sha256', 'code_dirty',
                'code_manifest_sha256', 'git_head', 'cells_sha256', 'train_seconds',
                'files_sha256', 'verify', 'result', 'descriptive', 'selection',
                'verify_seconds', 'eval_seconds', 'elapsed_s'}
    require(type(pr) is dict and required <= set(pr), 'probe eval report is incomplete')
    same(pr['schema'], 's6.phase1.eval.v1', 'report schema')
    same(pr['set'], 'probe', 'report set')
    sets = source_sets(repo)
    same(pr['sets'], sets, 'report sets')
    same(pr['config'], sets['probe'], 'probe configuration')
    cfg = sets['probe']
    same(pr['third_party'], versions, 'report third-party versions')
    same(pr['prereg_sha256'], None, 'probe prereg identity')
    same(pr['code_dirty'], [], 'report code dirty')
    code_sha = manifest_sha(code)
    same(pr['code_manifest_sha256'], code_sha, 'report code SHA')
    head = committed_identity(repo, code, pr['git_head'])
    root = repo / 'artifacts/v9/s6/phase1/probe'
    out = root / ('eval-' + cfg['test_ns'])
    cells = {f'{a}-r0' for a in AN.ARMS}
    keys(pr['cells_sha256'], cells, 'report cells')
    keys(pr['train_seconds'], cells, 'training times')
    require({p.name for p in (root / 'cells').iterdir()} == cells, 'raw cell directory set')
    pools = closure.json(root / 'pools.json')
    keys(pools, ('0',), 'candidate pools')
    require(type(pools['0']) is str and len(pools['0']) == 64 and all(c in '0123456789abcdef' for c in pools['0']), 'pool digest')
    recs = {}
    for arm in AN.ARMS:
        cell = arm + '-r0'
        d = root / 'cells' / cell
        rec = closure.json(d / 'cell.json')
        require(hashlib.sha256((d / 'cell.json').read_bytes()).hexdigest() == pr['cells_sha256'][cell], 'cell record SHA')
        check_cell(rec, arm, cfg, pools, d, closure)
        same(number(pr['train_seconds'][cell], 'report training seconds'), rec['seconds'], 'cell/report time')
        recs[cell] = rec
    # Non-P tracks have a common first reveal; T and R share every selection.
    first = recs['R-r0']['tracks'][0]['picks'][0]
    for rec in recs.values():
        for tr in rec['tracks']:
            same(tr['picks'][0], first, 'shared first picks')
    same(recs['T-r0']['tracks'][0]['picks'], recs['R-r0']['tracks'][0]['picks'], 'T/R selections')
    ledger = closure.json(root / 'train-ledger.json')
    require(type(ledger) is list and ledger, 'empty training ledger')
    recorded, ledger_seconds = {}, 0
    for row in ledger:
        keys(row, ('start', 'last_beat', 'closed', 'cells', 'prereg_sha256', 'code_manifest_sha256', 'git_head', 'third_party'), 'ledger row')
        same(row['closed'], True, 'training ledger must be closed')
        same(row['prereg_sha256'], None, 'ledger prereg identity')
        same(row['code_manifest_sha256'], code_sha, 'training/evaluation/current code identity')
        same(row['third_party'], versions, 'training versions')
        # The original probe startup returns head=None. Never invent that evidence.
        if row['git_head'] is not None:
            committed_identity(repo, code, row['git_head'])
        start = number(row['start'], 'ledger start')
        elapsed = number(row['last_beat'], 'ledger last heartbeat') - start
        require(elapsed > 0, 'nonpositive ledger duration')
        ledger_seconds += elapsed
        require(type(row['cells']) is list, 'ledger cells type')
        row_seconds = 0
        for item in row['cells']:
            keys(item, ('arm', 'replicate', 'seconds'), 'ledger cell')
            same(item['replicate'], 0, 'ledger replicate')
            cell = str(item['arm']) + '-r0'
            require(cell in cells and cell not in recorded, 'extra/duplicate ledger cell')
            same(number(item['seconds'], 'ledger cell seconds'), recs[cell]['seconds'], 'ledger/cell time')
            recorded[cell] = item['seconds']
            row_seconds += item['seconds']
        require(row_seconds <= elapsed + .1 * len(row['cells']), 'cell timings exceed ledger interval')
    keys(recorded, cells, 'ledger completed cells')
    require(ledger_seconds <= cfg['train_cap_s'], 'actual probe training exceeded cap')
    require({p.name for p in out.iterdir()} == {'verify.json', 'errors.npz', 'worlds.json'}, 'eval directory file set')
    closure.hashed(out, pr['files_sha256'], ('verify.json', 'errors.npz', 'worlds.json'))
    v = closure.json(out / 'verify.json')
    same(pr['verify'], v, 'report/raw verification')
    check_verify(v, recs)
    worlds = closure.json(out / 'worlds.json')
    same(worlds, {'main6': [[w, 6] for w in range(50)], 'extrap10': [[1000 + w, 10] for w in range(25)]}, 'test world identities')
    with np.load(out / 'errors.npz', allow_pickle=False) as data:
        expected = {f'{t}/{key}' for t in AN.TEST_SETS for key in ('counts', 'eb', *(f'sums/{a}' for a in AN.ARMS))}
        require(len(data.files) == len(expected) and set(data.files) == expected, 'error array key set')
        arrays = {k: data[k] for k in data.files}
    for t, nw in zip(AN.TEST_SETS, cfg['worlds']):
        for key, shape in [('counts', (nw, 4)), ('eb', (nw,)), *((f'sums/{a}', (1, 3, 4, nw, 4)) for a in AN.ARMS)]:
            arr = arrays[f'{t}/{key}']
            require(arr.shape == shape and arr.dtype.kind in ('iu' if key == 'counts' else 'f')
                    and np.isfinite(arr).all() and (arr >= 0).all(), f'{t}/{key}: array shape/type/range')
    # These are the existing scientific calculations with their original defaults.
    # Failing/undefined gates are valid evidence when they match the raw arrays.
    same(pr['result'], AN.decide(analysis_input(arrays, 3)), 'recomputed gates')
    same(pr['descriptive'], {f'round{r}': AN.describe(analysis_input(arrays, r)) for r in range(4)}, 'round descriptions')
    e = recs['E-r0']['tracks'][0]['picks']
    selection = {f'{a}-r0': [len(set(x) & set(y)) / max(len(x), 1) for x, y in zip(recs[f'{a}-r0']['tracks'][0]['picks'][1:], e[1:])]
                 for a in ('R', 'Z', 'T', 'G')}
    same(pr['selection'], selection, 'selection statistics')
    verify_s = number(pr['verify_seconds'], 'verification seconds')
    eval_s = number(pr['eval_seconds'], 'evaluation seconds')
    elapsed = number(pr['elapsed_s'], 'report elapsed seconds')
    require(verify_s + eval_s <= elapsed + .15 and elapsed <= cfg['eval_limit_s'], 'inconsistent/excessive eval wall clock')
    closure.unchanged()
    return pr, {'files_sha256': closure.files, 'current_git_head': head,
                'training_ledger_seconds': ledger_seconds, 'science_all_pass': pr['result']['all_pass']}


def estimate_budget(pr):
    # validate_probe is mandatory before this calculation at the public entry.
    final = pr['sets']['final']
    n_final = sum(final['reps'].values())
    est_train = 1.15 * (sum(pr['train_seconds'][a + '-r0'] * k for a, k in final['reps'].items()) + 5 * 90)
    est_eval = 1.30 * (pr['verify_seconds'] * n_final / 6
                       + pr['eval_seconds'] * n_final / 6 * sum(final['worlds']) / sum(pr['config']['worlds']))
    require(math.isfinite(est_train) and math.isfinite(est_eval)
            and est_train <= final['train_cap_s'] and est_eval < final['eval_limit_s'],
            f'预计超出上限：训练 {est_train:.6f} 秒（上限 {final["train_cap_s"]}），评测 {est_eval:.6f} 秒（上限 {final["eval_limit_s"]}）')
    return est_train, est_eval
