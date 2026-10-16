"""Real nonzero child controls. Corrupt one operation at a time in memory."""
import importlib.abc
import json
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT / 'src'))


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'mlx', 'torch', 'tensorflow', 'onnxruntime'}:
            raise AssertionError('forbidden model runtime')


sys.meta_path.insert(0, NoModels())


def child(case):
    import numpy as np

    from ainerzero.v9.geometry import SE2, SE3, GravityFrame, ObservabilityError, solve_pose_graph

    def close(a, b):
        assert np.max(np.abs(a - b)) <= 1e-9, 'mathematical property must detect corrupt ' + case

    if case == 'gravity_validation':
        GravityFrame.__post_init__ = lambda self: None
        rejected = False
        try:
            GravityFrame([0, 0, 9.81], [0, 0, 1], [1, 0, 0])
        except ValueError:
            rejected = True
        assert rejected, 'wrong declared gravity/up must be rejected'
        return
    if case == 'gauge_validation':
        rejected = False
        solve_pose_graph = lambda *args, **kwargs: None
        try:
            solve_pose_graph(SE2, [SE2.identity()] * 2, [])
        except ObservabilityError:
            rejected = True
        assert rejected, 'no anchor must report unobservable'
        return
    name, operation = case.split('_')
    g = SE2 if name == 'SE2' else SE3
    x = np.arange(1, g.dof + 1) / 7
    y = -np.arange(g.dof) / 11
    a, b = g.exp(x), g.exp(y)
    if operation == 'compose':
        g.compose = classmethod(lambda cls, a, b: a.copy())
        close(g.compose(a, b), a @ b)
    elif operation == 'inverse':
        g.inverse = classmethod(lambda cls, a: a.copy())
        close(a @ g.inverse(a), g.identity())
    elif operation == 'exp':
        g.exp = staticmethod(lambda xi: g.identity())
        close(g.exp(x), a)
    elif operation == 'log':
        g.log = staticmethod(lambda t: np.zeros(g.dof))
        close(g.exp(g.log(a)), a)
    elif operation == 'adjoint':
        g.adjoint = staticmethod(lambda t: np.eye(g.dof))
        close(g.exp(g.adjoint(a) @ y), a @ b @ g.inverse(a))
    assert not any(k.split('.')[0] in {'mlx', 'torch', 'tensorflow', 'onnxruntime'} for k in sys.modules)


if len(sys.argv) == 3 and sys.argv[1] == '--child':
    child(sys.argv[2])
else:
    cases = [g + '_' + op for g in ['SE2', 'SE3'] for op in ['compose', 'inverse', 'exp', 'log', 'adjoint']]
    cases += ['gravity_validation', 'gauge_validation']
    target = OUT / 'mutation-results-r1.json'
    assert not target.exists(), 'preserve previous mutation evidence'
    records = []
    for case in cases:
        argv = [sys.executable, '-B', str(Path(__file__).resolve()), '--child', case]
        process = subprocess.run(argv, capture_output=True, text=True)
        log = OUT / ('mutation-' + case + '.log')
        assert not log.exists()
        log.write_text(process.stdout + process.stderr)
        records.append({'case': case, 'argv': argv, 'returncode': process.returncode, 'log': str(log)})
        assert process.returncode == 1, 'corrupt operation must really fail: ' + case
        assert 'AssertionError:' in process.stderr, 'must fail by tested property, not unrelated crash'
    target.write_text(json.dumps(records, indent=2) + '\n')
    print('12/12 deliberate corruptions failed with real child exit 1 and AssertionError')
