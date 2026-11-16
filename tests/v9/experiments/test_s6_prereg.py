"""P261 + P264: SYNTHETIC complete evidence, real builder/helper/analysis, no worlds/MLX.

P264 (DESIGN-r3 §7.5): the synthetic repository has two commits, the probe's (the real a33d34b runner) and HEAD
(the frozen runner with the three registered constants, plus the builder, its helpers and DESIGN-r3). The probe
report is anchored by its SHA; by default ``invoke`` anchors the report as it stands, so the deeper checks run.

The only behavior mock is the third-party version query. Paths point at a
fresh synthetic repository with its own committed source fixture, never the
working repository's Git index, evidence, ledger or output.
"""
import hashlib
import importlib.util
import json
import os
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
PI = B.PI
AN = B.AN
VERSIONS = {'numpy': np.__version__, 'mlx': 'unknown'}       # the probe-time semantics (runner a33d34b)
PROBE_COMMIT = 'a33d34b5cb8d06800f584a0abcfd788d16f80fcb'
GIT = Path(os.environ.get('S6_PREREG_GIT_REPO', REPO))      # git history (an isolated mutation copy has none)
FRESH = ['reports/V9-S6-PHASE1/make_prereg.py', 'reports/V9-S6-PHASE1/prereg_evidence.py', 'reports/V9-S6-PHASE1/prereg_identity.py']


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True))


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.STDOUT).decode().strip()


@pytest.fixture(scope='session')
def synthetic_base(tmp_path_factory):
    root = tmp_path_factory.mktemp('SYNTHETIC-s6-prereg')
    # Commit A: the probe's code, exported from the real a33d34b.
    with PI.probe_tree(GIT, PROBE_COMMIT) as (probe_root, code, _):
        for rel in code:
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(probe_root / rel, dest)
    git(root, 'init', '-q')
    git(root, 'add', 'src', 'reports')
    git(root, '-c', 'user.name=SYNTHETIC CPU fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic probe code')
    head = git(root, 'rev-parse', 'HEAD')
    sets = PE.source_sets(root)
    # Commit B (HEAD): the frozen code as in the working repository (runner with the r3 constants), builder, helpers, design.
    for rel in [*code, *FRESH, 'reports/V9-S6-DESIGN/DESIGN-r3.md']:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, dest)
    git(root, 'add', 'src', 'reports')
    git(root, '-c', 'user.name=SYNTHETIC CPU fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic frozen code (r3)')
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


def report_sha(root):
    return hashlib.sha256(report_path(root).read_bytes()).hexdigest()


@pytest.fixture
def case(synthetic_base, tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    shutil.copytree(synthetic_base, root)
    here = root / 'reports/V9-S6-PHASE1'
    for name, value in {'REPO': root, 'HERE': here, 'RUNNER': here / 'run_s6p1.py', 'VERIFY': here / 'verify_s6p1.py', '__file__': str(here / 'make_prereg.py')}.items():
        monkeypatch.setattr(B, name, value)
    monkeypatch.setattr(PE, '__file__', str(here / 'prereg_evidence.py'))
    monkeypatch.setattr(PI, '__file__', str(here / 'prereg_identity.py'))
    monkeypatch.setattr(PE, 'cpu_versions', lambda repo: VERSIONS)
    # Synthetic ledger times are small numbers (1970); the real installation dates the MLX inference against them.
    real = PI.distributions()
    monkeypatch.setattr(PI, 'distributions', lambda: {k: {**v, 'dist_info_mtime': 0.0} for k, v in real.items()})
    return root


def report_path(root):
    return root / 'reports/V9-S6-PHASE1/probe/EVAL-probe.json'


def invoke(root, monkeypatch, anchor=None):
    """Run the real builder. ``anchor``: the recorded report SHA; by default the report as it stands, so that the
    deeper checks are exercised (the anchor itself is tested separately)."""
    out = root / 'candidate.json'
    monkeypatch.setattr(B, 'PROBE_REPORT_SHA256', anchor or report_sha(root))
    monkeypatch.setattr(sys, 'argv', ['make_prereg.py', '--design', str(root / 'reports/V9-S6-DESIGN/DESIGN-r3.md'), '--probe', str(report_path(root)), '--out', str(out)])
    B.main()
    return json.loads(out.read_text())


def refuse(root, monkeypatch, match, anchor=None):
    before = tree_hashes(root)
    with pytest.raises((ValueError, SystemExit), match=match):
        invoke(root, monkeypatch, anchor)
    assert not (root / 'candidate.json').exists()
    assert tree_hashes(root) == before


def commit(root, message):
    git(root, 'add', '-A', 'src', 'reports/V9-S6-PHASE1')
    git(root, '-c', 'user.name=SYNTHETIC', '-c', 'user.email=s@example.invalid', 'commit', '-qm', message)


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
    assert doc['budget']['train_cap_s'] == 19800 and doc['budget']['eval_limit_s'] == 5400
    assert doc['sets']['final']['train_cap_s'] == 19800 and doc['sets']['final']['eval_limit_s'] == 5400
    for rel in FRESH + ['reports/V9-S6-DESIGN/DESIGN-r3.md']:
        assert doc['manifest'][rel] == B.GD.sha256_file(case / rel)
    assert len(doc['probe_evidence']['files_sha256']) == 84
    assert not any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules)
    # two identities, the difference proof, the post-r3 version record
    probe_commit = git(case, 'rev-list', '--max-parents=0', 'HEAD')
    assert doc['probe_identity']['commit'] == probe_commit and doc['git_head'] == git(case, 'rev-parse', 'HEAD')
    assert doc['probe_identity']['code_manifest_sha256'] != doc['code_manifest_sha256']
    assert doc['probe_identity']['report_sha256'] == report_sha(case)
    assert doc['runner_difference']['changed_files'] == ['reports/V9-S6-PHASE1/run_s6p1.py']
    assert doc['runner_difference']['new'] == {'train_cap_s': 19800, 'eval_limit_s': 5400, 'third_party': ['numpy', 'mlx.core']}
    assert doc['third_party'] == {'numpy': np.__version__, 'mlx.core': PI.final_versions()['mlx.core']}
    assert 'unknown' not in doc['third_party'].values() and set(doc['distributions']) == {'mlx', 'mlx-metal', 'numpy'}
    assert doc['mlx_environment'] == {}
    code = B.GD.build_manifest(case, [case / 'reports/V9-S6-PHASE1/run_s6p1.py'], src_root=case / 'src',
                               extra=[case / 'reports/V9-S6-PHASE1/verify_s6p1.py'])
    assert doc['code_manifest_sha256'] == PE.manifest_sha(code) and all(doc['manifest'][k] == v for k, v in code.items())


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


@pytest.mark.parametrize('which', ['train-just-under', 'train-over', 'eval-just-under', 'eval-over'])
def test_budget_boundaries_real_builder(case, monkeypatch, which):
    """Through the real builder, just under and just over the r3 caps (19800 s, 5400 s)."""
    if which.startswith('train'):
        sec = (19800 / 1.15 - 450) / 28
        change_training_time(case, sec + (1e-6 if which.endswith('over') else -1e-6))
    else:
        verify = 5400 / (1.30 * (28 / 6)) - 4 * 100
        verify += 1e-6 if which.endswith('over') else -1e-6
        update_report(case, lambda p: p.update(verify_seconds=verify, elapsed_s=verify + 101))
    if which.endswith('over'):
        refuse(case, monkeypatch, '预计超出上限')
    else:
        doc = invoke(case, monkeypatch)
        assert doc['budget']['estimated_' + ('train_s' if which.startswith('train') else 'eval_s')] == (19800 if which.startswith('train') else 5400)


@pytest.mark.parametrize('side', ['train', 'eval'])
def test_budget_cap_is_inclusive_at_exact_equality(side):
    """S2: an estimate exactly equal to its cap is accepted; one ulp above is refused."""
    import math
    pr = {'train_seconds': {a + '-r0': 500. for a in AN.ARMS}, 'verify_seconds': 100., 'eval_seconds': 100.,
          'config': {'worlds': [50, 25]}}
    final = {'cand_ns': 'x', 'test_ns': 'y', 'sizes': {}, 'reps': {**{a: 5 for a in AN.GATE_ARMS}, 'G': 3},
             'worlds': [200, 100], 'train_cap_s': 1e9, 'eval_limit_s': 1e9}
    est_train, est_eval = PE.estimate_budget(pr, final)
    exact = {**final, ('train_cap_s' if side == 'train' else 'eval_limit_s'): est_train if side == 'train' else est_eval}
    assert PE.estimate_budget(pr, exact) == (est_train, est_eval)
    key = 'train_cap_s' if side == 'train' else 'eval_limit_s'
    below = {**exact, key: math.nextafter(exact[key], 0)}
    with pytest.raises(ValueError, match='预计超出上限'):
        PE.estimate_budget(pr, below)


def test_existing_output_is_never_overwritten(case, monkeypatch):
    (case / 'candidate.json').write_text('preserve')
    with pytest.raises(SystemExit):
        invoke(case, monkeypatch)
    assert (case / 'candidate.json').read_text() == 'preserve'


def test_cpu_version_query_never_imports_mlx():
    assert PE.cpu_versions(REPO) == VERSIONS
    assert not any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules)


@pytest.mark.parametrize('field', ['train', 'verify_seconds', 'eval_seconds'])
@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), -float('inf'), True, '100'])
def test_every_duration_rejects_invalid_types_and_values(case, monkeypatch, field, value):
    def damage(pr):
        if field == 'train':
            pr['train_seconds']['R-r0'] = value
        else:
            pr[field] = value
    update_report(case, damage)
    before = tree_hashes(case)
    with pytest.raises(ValueError):
        invoke(case, monkeypatch)
    assert tree_hashes(case) == before


def test_incomplete_live_style_report_refused(case, monkeypatch):
    update_report(case, lambda pr: pr.pop('result'))
    before = tree_hashes(case)
    with pytest.raises(ValueError, match='incomplete'):
        invoke(case, monkeypatch)
    assert tree_hashes(case) == before



# --- P264: the report anchor (P262 review R1) -------------------------------------------------------------------------
@pytest.mark.parametrize('change', [
    lambda p: p.__setitem__('verify_seconds', 50.),
    lambda p: p.update(verify_seconds=40., elapsed_s=150.),
    lambda p: p.__setitem__('eval_seconds', 1.),
])
def test_a_report_differing_from_the_recorded_anchor_is_refused(case, monkeypatch, change):
    anchor = report_sha(case)                 # recorded when the probe finished
    update_report(case, change)               # a later edit, however self-consistent
    refuse(case, monkeypatch, 'probe report SHA differs from the recorded anchor', anchor=anchor)


def test_the_anchor_is_checked_before_reading_the_report(case, monkeypatch):
    p = report_path(case)
    anchor = report_sha(case)
    p.write_text('{"git_head": "' + 'f' * 40 + '", "schema": 1')        # not even JSON
    refuse(case, monkeypatch, 'probe report SHA differs', anchor=anchor)


# --- P264: reviewer cases that the author tests missed (P262 review S1) ---------------------------------------------------
def rebind_selection(root):
    picks = {a: json.loads((root / RAW / f'cells/{a}-r0/cell.json').read_text())['tracks'][0]['picks'] for a in AN.ARMS}
    sel = {f'{a}-r0': [len(set(x) & set(y)) / max(len(x), 1) for x, y in zip(picks[a][1:], picks['E'][1:])]
           for a in ('R', 'Z', 'T', 'G')}
    update_report(root, lambda p: p.__setitem__('selection', sel))


def change_picks(root, cell, change):
    def edit(rec):
        tr = rec['tracks'][0]
        change(tr['picks'])
        tr['revealed'] = [i for ids in tr['picks'] for i in ids]
        tr['reveal_log'] = [{'call': r, 'ids': ids} for r, ids in enumerate(tr['picks'])]
    rewrite(root, RAW + f'cells/{cell}/cell.json', edit)
    bind_cell(root, cell)
    rebind_selection(root)


def test_ledger_total_over_the_probe_cap(case, monkeypatch):
    rewrite(case, RAW + 'train-ledger.json', lambda v: v.append({**v[0], 'start': 10000., 'last_beat': 16000., 'cells': []}))
    refuse(case, monkeypatch, 'actual probe training exceeded cap')


def test_t_picks_must_equal_r_picks(case, monkeypatch):
    change_picks(case, 'T-r0', lambda picks: picks.__setitem__(3, list(range(20000, 23000))))
    refuse(case, monkeypatch, 'T/R selections')


def test_picks_outside_the_pool_are_refused(case, monkeypatch):
    change_picks(case, 'E-r0', lambda picks: picks[3].__setitem__(0, 60000))
    refuse(case, monkeypatch, 'pick IDs')


def test_replay_first_ok_false_is_refused(case, monkeypatch):
    p = case / RAW / 'eval-s6p1-probe/verify.json'
    v = json.loads(p.read_text())
    v['replay']['Z-r0']['first_ok'] = False
    p.write_text(json.dumps(v, sort_keys=True))
    bind_eval(case, 'verify.json')
    update_report(case, lambda pr: pr.__setitem__('verify', v))
    refuse(case, monkeypatch, 'first picks replay')


def test_resumed_training_with_two_closed_ledger_rows_is_accepted(case, monkeypatch):
    def split(rows):
        r = rows[0]
        rows[:] = [{**r, 'start': 1000., 'last_beat': 2600., 'cells': r['cells'][:3]},
                   {**r, 'start': 5000., 'last_beat': 6600., 'cells': r['cells'][3:]}]
    rewrite(case, RAW + 'train-ledger.json', split)
    assert invoke(case, monkeypatch)['probe_evidence']['training_ledger_seconds'] == 3200.


def test_a_ledger_commit_must_hold_the_probe_code(case, monkeypatch):
    probe_commit = git(case, 'rev-list', '--max-parents=0', 'HEAD')
    rewrite(case, RAW + 'train-ledger.json', lambda v: v[0].__setitem__('git_head', probe_commit))
    assert invoke(case, monkeypatch)['probe_evidence']['probe_commit'] == probe_commit
    (case / 'candidate.json').unlink()
    head = git(case, 'rev-parse', 'HEAD')                    # the r3 code, not the probe's
    rewrite(case, RAW + 'train-ledger.json', lambda v: v[0].__setitem__('git_head', head))
    refuse(case, monkeypatch, 'code differs at the ledger commit')


# --- P264: the frozen runner (DESIGN-r3 §7.5) ---------------------------------------------------------------------------
def edit_runner(root, old, new):
    p = root / 'reports/V9-S6-PHASE1/run_s6p1.py'
    src = p.read_text()
    assert src.count(old) == 1
    p.write_text(src.replace(old, new))
    commit(root, 'runner edit')


@pytest.mark.parametrize('old,new,match', [
    ('"train_cap_s": 19800, "eval_limit_s": 5400}', '"train_cap_s": 43200, "eval_limit_s": 5400}', 'frozen runner train_cap_s'),
    ('"train_cap_s": 19800, "eval_limit_s": 5400}', '"train_cap_s": 19800, "eval_limit_s": 9999}', 'frozen runner eval_limit_s'),
    ('"train_cap_s": 19800, "eval_limit_s": 5400}', '"train_cap_s": 5.5 * 3600, "eval_limit_s": 5400}', 'plain numeric literal'),
    ('THIRD_PARTY = ("numpy", "mlx.core")', 'THIRD_PARTY = ("numpy", "mlx")', 'THIRD_PARTY differs'),
    ('DANGLING_CHARGE_S = 900', 'DANGLING_CHARGE_S = 60', 'beyond the three'),
])
def test_the_frozen_runner_may_differ_only_in_the_registered_constants(case, monkeypatch, old, new, match):
    edit_runner(case, old, new)
    refuse(case, monkeypatch, match)


def test_other_frozen_files_must_equal_the_probe_code(case, monkeypatch):
    p = case / 'src/ainerzero/v9/experiments/s6/analysis.py'
    p.write_text(p.read_text() + '\n# drift\n')
    commit(case, 'analysis drift')
    refuse(case, monkeypatch, 'other than the runner')


def test_mlx_environment_variables_refuse(case, monkeypatch):
    monkeypatch.setenv('MLX_METAL_FAST_SYNCH', '1')
    refuse(case, monkeypatch, 'MLX_')


def test_the_design_must_be_r3(case, monkeypatch):
    out = case / 'candidate.json'
    monkeypatch.setattr(B, 'PROBE_REPORT_SHA256', report_sha(case))
    shutil.copyfile(case / 'reports/V9-S6-DESIGN/DESIGN-r3.md', case / 'reports/V9-S6-DESIGN/DESIGN-r2.md')
    monkeypatch.setattr(sys, 'argv', ['make_prereg.py', '--design', str(case / 'reports/V9-S6-DESIGN/DESIGN-r2.md'), '--probe', str(report_path(case)), '--out', str(out)])
    with pytest.raises(ValueError, match='DESIGN-r3'):
        B.main()
    assert not out.exists()


# --- P264: source_sets evaluates only whitelisted configuration (P262 review S3) -------------------------------------------
@pytest.mark.parametrize('expr', ['().__class__.__base__.__subclasses__()', 'C._private', 'C.Sizes.__globals__', 'open("x")', 'os.getpid()'])
def test_source_sets_refuses_anything_but_the_configuration(case, expr):
    p = case / 'reports/V9-S6-PHASE1/run_s6p1.py'
    src = p.read_text()
    old = '"worlds": (3, 2), "train_cap_s": 1800,'
    assert src.count(old) == 1
    p.write_text(src.replace(old, f'"worlds": (3, 2), "extra": {expr}, "train_cap_s": 1800,'))
    with pytest.raises(ValueError, match='configuration'):
        PE.source_sets(case, final_caps=PE.NEW_CAPS)


def test_an_mlx_installed_after_the_probe_refuses(case, monkeypatch):
    real = PI.distributions()
    monkeypatch.setattr(PI, 'distributions', lambda: {k: {**v, 'dist_info_mtime': 5000.0} for k, v in real.items()})
    refuse(case, monkeypatch, 'newer than the probe')
