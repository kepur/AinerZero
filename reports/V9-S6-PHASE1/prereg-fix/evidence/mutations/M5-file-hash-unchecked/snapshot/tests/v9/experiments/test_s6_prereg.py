"""P261: SYNTHETIC complete evidence, real builder/helper/analysis, no worlds/MLX.

The only behavior mock is the third-party version query. Paths point at a
fresh synthetic repository with its own committed source fixture, never the
working repository's Git index, evidence, ledger or output.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
HERE = REPO / 'reports/V9-S6-PHASE1'
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('s6_prereg_builder_test', HERE / 'make_prereg.py')
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)
PE = B.PE
AN = B.AN
VERSIONS = {'numpy': np.__version__, 'mlx': 'unknown'}


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True))


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.STDOUT).decode().strip()


@pytest.fixture(scope='session')
def synthetic_base(tmp_path_factory):
    root = tmp_path_factory.mktemp('SYNTHETIC-s6-prereg')
    code = B.GD.build_manifest(REPO, [HERE / 'run_s6p1.py'], src_root=REPO / 'src', extra=[HERE / 'verify_s6p1.py'])
    for rel in [*code, 'reports/V9-S6-PHASE1/make_prereg.py', 'reports/V9-S6-PHASE1/prereg_evidence.py']:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, dest)
    design = root / 'reports/V9-S6-DESIGN/DESIGN-r2.md'
    design.parent.mkdir(parents=True)
    shutil.copyfile(REPO / design.relative_to(root), design)
    git(root, 'init', '-q')
    git(root, 'add', 'src', 'reports')
    git(root, '-c', 'user.name=SYNTHETIC CPU fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic test source identity')
    head = git(root, 'rev-parse', 'HEAD')
    sets = PE.source_sets(root)
    cfg = sets['probe']
    raw = root / 'artifacts/v9/s6/phase1/probe'
    out = raw / 'eval-s6p1-probe'
    pools = {'0': 'a' * 64}
    write(raw / 'pools.json', pools)
    recs, secs, hashes = {}, {}, {}
    for arm in AN.ARMS:
        cell = arm + '-r0'
        d = raw / 'cells' / cell
        d.mkdir(parents=True)
        weights = {}
        for r in range(4):
            for j in range(3):
                name = f'r{r}-n{j}.safetensors'
                # Byte blobs are deliberately NOT model weights. Validator hashes
                # them, and never calls safetensors/model loaders.
                (d / name).write_bytes(f'SYNTHETIC {cell} {r} {j}'.encode())
                weights[name] = B.GD.sha256_file(d / name)
        tracks = []
        for _ in range(3 if arm == 'P' else 1):
            picks = [list(range(r * 3000, (r + 1) * 3000)) for r in range(4)]
            tracks.append({'picks': picks, 'revealed': sum(picks, []),
                           'score_sha256': [None] + [None if arm in ('R', 'T', 'G') else 'b' * 64] * 3,
                           'reveal_log': [{'call': r, 'ids': ids} for r, ids in enumerate(picks)]})
        rec = {'schema': 's6.phase1.cell.v1', 'arm': arm, 'replicate': 0, 'cand_ns': cfg['cand_ns'],
               'sizes': cfg['sizes'], 'net_seeds': [1, 2, 3], 'first_seed': PE.seed(cfg['cand_ns'], 's6-first', 0),
               'pool_seed': PE.seed(cfg['cand_ns'], 's6-pool', 0),
               'pick_seed': PE.seed(cfg['cand_ns'], 's6-pick', 'R' if arm == 'T' else arm, 0),
               'pool_sha256': pools['0'], 'tracks': tracks, 'seconds': 500.,
               'timings': [{'round': r, 'train_s': 100., 'select_s': 0.} for r in range(4)], 'files_sha256': weights}
        write(d / 'cell.json', rec)
        recs[cell], secs[cell], hashes[cell] = rec, rec['seconds'], B.GD.sha256_file(d / 'cell.json')
    write(raw / 'train-ledger.json', [{'start': 1000., 'last_beat': 4100., 'closed': True,
          'cells': [{'arm': a, 'replicate': 0, 'seconds': 500.} for a in AN.ARMS], 'prereg_sha256': None,
          'code_manifest_sha256': PE.manifest_sha(code), 'git_head': None, 'third_party': VERSIONS}])
    verify = {'passed': True, 'pools_ok': {'0': True}, 'replay': {},
              'retrain': {f'{a}-r0-n0': {'seed': 1, 'rounds_identical': [True] * 4, 'passed': True} for a in ('E', 'P')}}
    for cell, rec in recs.items():
        nt = len(rec['tracks'])
        verify['replay'][cell] = {'passed': True, 'first_ok': True, 'rounds_ok': [True] * (3 * nt), 'contact_share': [[.1] * 4 for _ in range(nt)]}
    write(out / 'verify.json', verify)
    write(out / 'worlds.json', {'main6': [[w, 6] for w in range(50)], 'extrap10': [[1000 + w, 10] for w in range(25)]})
    arrays = {}
    # All arms are equal: several scientific gates FAIL, yet this is complete.
    for t, nw in zip(AN.TEST_SETS, (50, 25)):
        arrays[t + '/counts'] = np.full((nw, 4), 10, dtype=np.int64)
        arrays[t + '/eb'] = np.full(nw, 20.)
        for a in AN.ARMS:
            arrays[t + '/sums/' + a] = np.full((1, 3, 4, nw, 4), 5.)
    np.savez(out / 'errors.npz', **arrays)
    pr = {'schema': 's6.phase1.eval.v1', 'set': 'probe', 'config': cfg, 'sets': sets,
          'prereg_sha256': None, 'git_head': head, 'code_manifest_sha256': PE.manifest_sha(code),
          'code_dirty': [], 'third_party': VERSIONS, 'cells_sha256': hashes, 'train_seconds': secs,
          'verify': verify, 'verify_seconds': 100., 'eval_seconds': 100., 'elapsed_s': 201.,
          'files_sha256': {p.name: B.GD.sha256_file(p) for p in out.iterdir()},
          'result': AN.decide(PE.analysis_input(arrays, 3)),
          'descriptive': {f'round{r}': AN.describe(PE.analysis_input(arrays, r)) for r in range(4)},
          'selection': {f'{a}-r0': [1.] * 3 for a in ('R', 'Z', 'T', 'G')}}
    write(root / 'reports/V9-S6-PHASE1/probe/EVAL-probe.json', pr)
    (root / 'SYNTHETIC.txt').write_text('CPU integrity fixture. No worlds or real weights. No scientific evidence.\n')
    return root


@pytest.fixture
def case(synthetic_base, tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    shutil.copytree(synthetic_base, root)
    here = root / 'reports/V9-S6-PHASE1'
    for name, value in {'REPO': root, 'HERE': here, 'RUNNER': here / 'run_s6p1.py', 'VERIFY': here / 'verify_s6p1.py', '__file__': str(here / 'make_prereg.py')}.items():
        monkeypatch.setattr(B, name, value)
    monkeypatch.setattr(PE, '__file__', str(here / 'prereg_evidence.py'))
    monkeypatch.setattr(PE, 'cpu_versions', lambda repo: VERSIONS)
    return root


def report_path(root):
    return root / 'reports/V9-S6-PHASE1/probe/EVAL-probe.json'


def invoke(root, monkeypatch):
    out = root / 'candidate.json'
    monkeypatch.setattr(sys, 'argv', ['make_prereg.py', '--design', str(root / 'reports/V9-S6-DESIGN/DESIGN-r2.md'), '--probe', str(report_path(root)), '--out', str(out)])
    B.main()
    return json.loads(out.read_text())


def rewrite(root, relative, change):
    p = root / relative
    value = json.loads(p.read_text())
    change(value)
    write(p, value)


def update_report(root, change):
    rewrite(root, report_path(root).relative_to(root), change)


def bind_cell(root, cell='R-r0'):
    update_report(root, lambda p: p['cells_sha256'].__setitem__(cell, B.GD.sha256_file(root / f'artifacts/v9/s6/phase1/probe/cells/{cell}/cell.json')))


def bind_eval(root, name):
    update_report(root, lambda p: p['files_sha256'].__setitem__(name, B.GD.sha256_file(root / f'artifacts/v9/s6/phase1/probe/eval-s6p1-probe/{name}')))


def test_complete_probe_with_failed_science_accepted(case, monkeypatch):
    doc = invoke(case, monkeypatch)
    assert doc['probe_evidence']['science_all_pass'] is False
    assert doc['budget']['estimated_train_s'] == 16618
    assert doc['budget']['estimated_eval_s'] == 3033
    assert sum(doc['sets']['final']['reps'].values()) == 28
    assert doc['budget']['train_cap_s'] == 21600 and doc['budget']['eval_limit_s'] == 3600
    assert 'reports/V9-S6-PHASE1/make_prereg.py' in doc['manifest']
    assert 'reports/V9-S6-PHASE1/prereg_evidence.py' in doc['manifest']
    assert len(doc['probe_evidence']['files_sha256']) == 84
    assert not any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules)


REPORT_CASES = {
    'empty-gates': lambda p: p['result'].__setitem__('gates', {}),
    'gate-value': lambda p: p['result']['gates']['GS'].__setitem__('point', 999.),
    'replicate-float': lambda p: p['result'].__setitem__('replicates', 1.0),
    'gate-bool': lambda p: p['result']['gates']['GS'].__setitem__('passed', 'false'),
    'summary-verify': lambda p: p.__setitem__('verify', {'passed': True}),
    'truthy-verify': lambda p: p['verify'].__setitem__('passed', 'false'),
    'schema': lambda p: p.__setitem__('schema', 'bad'),
    'set': lambda p: p.__setitem__('set', 'final'),
    'code-sha': lambda p: p.__setitem__('code_manifest_sha256', '0' * 64),
    'git-head': lambda p: p.__setitem__('git_head', '0' * 40),
    'dirty': lambda p: p.__setitem__('code_dirty', [' M x']),
    'version': lambda p: p['third_party'].__setitem__('mlx', 'forged'),
    'config': lambda p: p['config'].__setitem__('cand_ns', 'wrong'),
    'extra-set': lambda p: p['sets'].__setitem__('forged', {}),
    'final-cap': lambda p: p['sets']['final'].__setitem__('train_cap_s', 999999),
    'final-reps': lambda p: p['sets']['final']['reps'].__setitem__('G', 5),
    'bool-world': lambda p: p['sets']['final'].__setitem__('worlds', [True, 100]),
    'missing-cell': lambda p: p['cells_sha256'].pop('G-r0'),
    'extra-cell': lambda p: p['train_seconds'].__setitem__('E-r999', 0),
    'missing-time': lambda p: p['train_seconds'].pop('G-r0'),
    'negative-time': lambda p: p['train_seconds'].__setitem__('R-r0', -1),
    'zero-time': lambda p: p['train_seconds'].__setitem__('R-r0', 0),
    'nan-time': lambda p: p['train_seconds'].__setitem__('R-r0', float('nan')),
    'inf-time': lambda p: p.__setitem__('eval_seconds', float('inf')),
    'bool-time': lambda p: p.__setitem__('verify_seconds', True),
    'zero-eval': lambda p: p.__setitem__('eval_seconds', 0),
    'negative-verify': lambda p: p.__setitem__('verify_seconds', -1),
    'nan-verify': lambda p: p.__setitem__('verify_seconds', float('nan')),
    'clock': lambda p: p.__setitem__('elapsed_s', 1),
    'time-disagrees': lambda p: p['train_seconds'].__setitem__('R-r0', 499),
    'train-over-budget': lambda p: None,  # special coordinated mutation below
    'eval-over-budget': lambda p: p.update(verify_seconds=1000., elapsed_s=1101.),
    'description': lambda p: p['descriptive'].pop('round0'),
    'selection': lambda p: p['selection']['R-r0'].__setitem__(0, 0),
    'extra-file': lambda p: p['files_sha256'].__setitem__('fake.json', '0' * 64),
}


def change_training_time(root, sec):
    for a in AN.ARMS:
        cell = a + '-r0'
        rewrite(root, f'artifacts/v9/s6/phase1/probe/cells/{cell}/cell.json', lambda r: r.__setitem__('seconds', sec))
        bind_cell(root, cell)
    update_report(root, lambda p: p.__setitem__('train_seconds', {a + '-r0': sec for a in AN.ARMS}))
    def ledger(rows):
        for c in rows[0]['cells']:
            c['seconds'] = sec
        rows[0]['last_beat'] = rows[0]['start'] + sec * 6 + 1
    rewrite(root, 'artifacts/v9/s6/phase1/probe/train-ledger.json', ledger)


@pytest.mark.parametrize('damage', REPORT_CASES)
def test_report_damage_refuses_without_writes(case, monkeypatch, damage):
    if damage == 'train-over-budget':
        change_training_time(case, 700.)
    else:
        update_report(case, REPORT_CASES[damage])
    before = tree_hashes(case)
    with pytest.raises((ValueError, KeyError, OSError, SystemExit)):
        invoke(case, monkeypatch)
    assert not (case / 'candidate.json').exists()
    assert tree_hashes(case) == before


RAW = 'artifacts/v9/s6/phase1/probe/'
RAW_CASES = {
    'open-ledger': (RAW + 'train-ledger.json', lambda v: v[0].__setitem__('closed', False)),
    'truthy-closed': (RAW + 'train-ledger.json', lambda v: v[0].__setitem__('closed', 'true')),
    'training-code': (RAW + 'train-ledger.json', lambda v: v[0].__setitem__('code_manifest_sha256', 'old')),
    'training-version': (RAW + 'train-ledger.json', lambda v: v[0]['third_party'].__setitem__('numpy', 'old')),
    'ledger-time': (RAW + 'train-ledger.json', lambda v: v[0]['cells'][0].__setitem__('seconds', 499)),
    'ledger-window': (RAW + 'train-ledger.json', lambda v: v[0].__setitem__('last_beat', 1001)),
    'ledger-missing': (RAW + 'train-ledger.json', lambda v: v[0]['cells'].pop()),
    'ledger-duplicate': (RAW + 'train-ledger.json', lambda v: v[0]['cells'].append(v[0]['cells'][0])),
    'pool': (RAW + 'pools.json', lambda v: v.__setitem__('0', '0' * 64)),
    'picks-round': (RAW + 'cells/R-r0/cell.json', lambda v: v['tracks'][0]['picks'].pop()),
    'reveal': (RAW + 'cells/R-r0/cell.json', lambda v: v['tracks'][0]['reveal_log'][0]['ids'].__setitem__(0, 59999)),
    'picks-type': (RAW + 'cells/R-r0/cell.json', lambda v: v['tracks'][0]['picks'][0].__setitem__(0, True)),
    'repeated-pick': (RAW + 'cells/R-r0/cell.json', lambda v: v['tracks'][0]['picks'][1].__setitem__(0, 0)),
    'timing-round': (RAW + 'cells/R-r0/cell.json', lambda v: v['timings'].pop()),
    'timing-round-zero': (RAW + 'cells/R-r0/cell.json', lambda v: v['timings'][0].__setitem__('train_s', 0)),
    'timing-round-big': (RAW + 'cells/R-r0/cell.json', lambda v: v['timings'][0].__setitem__('train_s', 900)),
    'seed': (RAW + 'cells/R-r0/cell.json', lambda v: v.__setitem__('net_seeds', [2, 3, 4])),
    'replicate-float': (RAW + 'cells/R-r0/cell.json', lambda v: v.__setitem__('replicate', 0.0)),
    'scores': (RAW + 'cells/R-r0/cell.json', lambda v: v['tracks'][0]['score_sha256'].pop()),
    'weight-set': (RAW + 'cells/R-r0/cell.json', lambda v: v['files_sha256'].pop('r0-n0.safetensors')),
    'replay-false': (RAW + 'eval-s6p1-probe/verify.json', lambda v: v['replay']['E-r0'].__setitem__('passed', False)),
    'replay-truthy': (RAW + 'eval-s6p1-probe/verify.json', lambda v: v['replay']['E-r0']['rounds_ok'].__setitem__(0, 1)),
    'replay-missing': (RAW + 'eval-s6p1-probe/verify.json', lambda v: v['replay'].pop('G-r0')),
    'retrain-missing': (RAW + 'eval-s6p1-probe/verify.json', lambda v: v['retrain'].pop('P-r0-n0')),
    'retrain-false': (RAW + 'eval-s6p1-probe/verify.json', lambda v: v['retrain']['P-r0-n0']['rounds_identical'].__setitem__(3, False)),
    'pool-truthy': (RAW + 'eval-s6p1-probe/verify.json', lambda v: v['pools_ok'].__setitem__('0', 'true')),
    'worlds': (RAW + 'eval-s6p1-probe/worlds.json', lambda v: v['main6'][0].__setitem__(0, 99)),
}


@pytest.mark.parametrize('damage', RAW_CASES)
def test_raw_damage_even_rehashed_refuses(case, monkeypatch, damage):
    rel, change = RAW_CASES[damage]
    rewrite(case, rel, change)
    if '/cells/' in rel:
        bind_cell(case)
    if 'eval-s6p1-probe/' in rel:
        name = Path(rel).name
        bind_eval(case, name)
        if name == 'verify.json':
            update_report(case, lambda p: p.__setitem__('verify', json.loads((case / rel).read_text())))
    before = tree_hashes(case)
    with pytest.raises((ValueError, KeyError, OSError, SystemExit)):
        invoke(case, monkeypatch)
    assert tree_hashes(case) == before


def tree_hashes(root):
    return {str(p.relative_to(root)): B.GD.sha256_file(p) for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('kind', ['weights', 'cell-hash', 'eval-hash', 'missing-file', 'extra-cell-dir', 'dirty-source', 'duplicate-json', 'errors-shape', 'errors-nan', 'errors-extra', 'errors-values'])
def test_file_corruption(case, monkeypatch, kind):
    raw = case / RAW
    if kind == 'weights':
        (raw / 'cells/R-r0/r0-n0.safetensors').write_bytes(b'changed')
    elif kind == 'cell-hash':
        rewrite(case, RAW + 'cells/R-r0/cell.json', lambda v: v.__setitem__('seconds', 501))
    elif kind == 'eval-hash':
        (raw / 'eval-s6p1-probe/worlds.json').write_text('{}')
    elif kind == 'missing-file':
        (raw / 'eval-s6p1-probe/errors.npz').unlink()
    elif kind == 'extra-cell-dir':
        (raw / 'cells/R-r999').mkdir()
    elif kind == 'dirty-source':
        with (case / 'reports/V9-S6-PHASE1/run_s6p1.py').open('a') as fh:
            fh.write('\n# SYNTHETIC source tamper\n')
    elif kind == 'duplicate-json':
        p = report_path(case)
        p.write_text(p.read_text()[:-1] + ', "schema": "s6.phase1.eval.v1"}')
    else:
        p = raw / 'eval-s6p1-probe/errors.npz'
        with np.load(p) as data:
            arr = {k: data[k] for k in data.files}
        if kind == 'errors-shape':
            arr['main6/sums/R'] = arr['main6/sums/R'][:, :, :3]
        elif kind == 'errors-nan':
            arr['main6/sums/R'][0, 0, 0, 0, 0] = np.nan
        elif kind == 'errors-extra':
            arr['forged'] = np.zeros(1)
        else:
            arr['main6/sums/E'][0, 0, 3, 0, 0] += 1
        np.savez(p, **arr)
        bind_eval(case, 'errors.npz')
    before = tree_hashes(case)
    with pytest.raises((ValueError, KeyError, OSError, SystemExit)):
        invoke(case, monkeypatch)
    assert tree_hashes(case) == before


@pytest.mark.parametrize('which', ['train-equal', 'train-over', 'eval-equal', 'eval-over'])
def test_budget_boundaries_real_builder(case, monkeypatch, which):
    if which.startswith('train'):
        sec = (21600 / 1.15 - 450) / 28
        change_training_time(case, sec + (1e-6 if which.endswith('over') else 0))
    else:
        verify = 3600 / (1.30 * (28 / 6)) - 4 * 100
        if which.endswith('over'):
            verify += 1e-6
        update_report(case, lambda p: p.update(verify_seconds=verify, elapsed_s=verify + 101))
    if which.endswith('over'):
        with pytest.raises(ValueError, match='预计超出上限'):
            invoke(case, monkeypatch)
        assert not (case / 'candidate.json').exists()
    else:
        doc = invoke(case, monkeypatch)
        assert doc['budget']['estimated_' + ('train_s' if which.startswith('train') else 'eval_s')] == (21600 if which.startswith('train') else 3600)


def test_existing_output_is_never_overwritten(case, monkeypatch):
    (case / 'candidate.json').write_text('preserve')
    with pytest.raises(SystemExit):
        invoke(case, monkeypatch)
    assert (case / 'candidate.json').read_text() == 'preserve'


def test_cpu_version_query_never_imports_mlx():
    assert PE.cpu_versions(REPO) == VERSIONS
    assert not any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules)
