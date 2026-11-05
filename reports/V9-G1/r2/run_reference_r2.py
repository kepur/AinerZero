"""r2 重登记后的 G1 参考重放：只改输入消费门，不豁免任何哈希。

r1 原件（reports/V9-G1/r1-codex-20261016/run_reference.py）原样保留。
本副本按 F3 的 r2 登记核对输入：
- 文档输入按 r2 登记的 new_sha256 强制核对（不豁免）；
- 代码输入按 r1 登记的哈希强制核对；
- fixture/参数仍读 r1 cpu_registration.json，不重登记、不改数值行为。
输出 reports/V9-G1/r2/reference-results-r2.json，并与 r1 的 reference-results-r1.json
逐字段比较 references（期望 0 差异，证明 r2 未改动登记的 G1 数值行为）。
"""
import hashlib
import importlib.abc
import importlib.util
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT / 'src'))


class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'mlx', 'torch', 'tensorflow', 'onnxruntime'}:
            raise AssertionError('forbidden model runtime import: ' + fullname)


sys.meta_path.insert(0, DenyModels())
import numpy as np

from ainerzero.environments.gridlab2d import Action, make_world
from ainerzero.v9.geometry import (
    SE2, GravityFrame, KnownRotationGaussian, RelativeFactor, TangentGaussian,
    bounded_translation_update, linear_translation_error_bound, solve_pose_graph,
)

R1_DIR = ROOT / 'reports' / 'V9-G1' / 'r1-codex-20261016'
reg = json.loads((R1_DIR / 'cpu_registration.json').read_text())
registration_r2 = json.loads((OUT / 'input_registration_r2.json').read_text())
# 文档输入：按 r2 的 new_sha256 强制核对（不允许豁免文档哈希）。
for entry in registration_r2['documents']:
    p = ROOT / entry['path']
    assert hashlib.sha256(p.read_bytes()).hexdigest() == entry['new_sha256'], (
        'r2 registered document input changed: ' + entry['path'])
# 代码输入：仍按 r1 登记的哈希强制核对。
for path, meta in registration_r2['code_inputs']['inputs'].items():
    p = Path(path) if Path(path).is_absolute() else ROOT / path
    assert hashlib.sha256(p.read_bytes()).hexdigest() == meta['sha256'], (
        'r1 registered code input changed: ' + path)


def gridlab_path():
    world = make_world(reg['gridlab_seed'])
    points = [list(world.agent)]
    for action in reg['gridlab_actions']:
        world.apply(Action(action))
        points.append(list(world.agent))
    return np.asarray(points, dtype=float), {'source': 'existing GridLab2D.apply', 'seed': world.seed,
                                           'world_id': str(world.world_id), 'layout_sha256_final': world.layout_sha256(),
                                           'actions': reg['gridlab_actions'], 'units': 'grid cell'}


def awz_path():
    path = Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/python/animeworld/kernel/motion.py')
    spec = importlib.util.spec_from_file_location('g1_readonly_awz_motion', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    trajectory = module.Trajectory2D(reg['awz_room_waypoints_xz'])
    xz = np.asarray([trajectory.eval_pos_and_tangent(s)[0]
                     for s in np.linspace(0, trajectory.total_length, 25)])
    # AWZ is Y-up. GravityFrame horizontal reference +X yields second planar axis -Z.
    frame = GravityFrame([0, -9.81, 0], [0, 1, 0], [1, 0, 0])
    points = xz * np.array([1, -1])
    for planar, world_xz in zip(points, xz):
        pose = SE2.identity()
        pose[:2, 2] = planar
        lifted = frame.lift(pose, 0)
        assert np.max(np.abs(lifted[:3, 3] - np.r_[world_xz[0], 0, world_xz[1]])) <= 1e-9
    return points, {'source': str(path), 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'path': reg['awz_room_waypoints_xz'], 'samples': len(points), 'units': 'meter',
                    'scope': 'existing AWZ analytical trajectory, no WorldKernel/rendering/sensor acceptance'}


def reference(name, truth, source):
    source['coordinate_scope'] = 'diagnostic known-motion reference only; no learner, no capability promotion'
    initial_error = np.asarray(reg['filter_initial_translation_error'])
    drift = np.asarray(reg['filter_odometry_bias_per_step'])
    obs_bias = np.asarray(reg['filter_measurement_bias'])
    initial = SE2.identity()
    initial[:2, 2] = truth[0] + initial_error
    belief = KnownRotationGaussian(SE2, initial, np.diag(reg['filter_covariance_diagonal'][:2]))
    no_noise = TangentGaussian(SE2, SE2.exp(np.r_[truth[0], 0]), np.diag(reg['filter_covariance_diagonal']))
    q = np.diag(reg['filter_process_covariance_rate_diagonal'])
    measurement_covariance = np.diag(reg['filter_measurement_covariance_diagonal'])
    bound = float(np.linalg.norm(initial_error))
    history = []
    for i, (prev, current) in enumerate(zip(truth, truth[1:]), 1):
        displacement = current - prev
        no_noise = no_noise.predict(np.r_[displacement, 0], 1., np.zeros((3, 3)))
        no_noise_error = float(np.linalg.norm(no_noise.mean[:2, 2] - current))
        assert no_noise_error <= reg['round_trip_atol']
        belief = belief.predict(displacement + drift, 1., q[:2, :2])
        predicted_error = float(np.linalg.norm(belief.mean[:2, 2] - current))
        belief, gain = belief.update_position(current + obs_bias, measurement_covariance)
        predicted_bound, bound = bounded_translation_update(bound, np.linalg.norm(drift), np.linalg.norm(obs_bias), gain[:2])
        actual = float(np.linalg.norm(belief.mean[:2, 2] - current))
        assert predicted_error <= predicted_bound + reg['numeric_slack'], {'step': i, 'prediction_error': predicted_error, 'translation_bound': predicted_bound, 'yaw': float(SE2.log(belief.mean)[2]), 'scope': 'fixed-heading premise violated if yaw changed'}
        assert actual <= bound + reg['numeric_slack']
        assert np.linalg.eigvalsh(belief.translation_covariance)[0] > 0
        assert np.array_equal(belief.mean[:2, :2], np.eye(2)), 'fixed-known-rotation premise'
        history.append({'step': i, 'noiseless_error': no_noise_error,
                        'prediction_error': predicted_error, 'prediction_bound': predicted_bound,
                        'updated_error': actual, 'updated_bound': bound})
    # Reduced-incidence translation graph, fixed rotations, explicit anchor at node0.
    centered = truth - truth[0]
    edges = [(i, i + 1) for i in range(len(truth) - 1)] + [(len(truth) - 1, 0)]
    factors, errors, rows = [], [], []
    for number, (i, j) in enumerate(edges):
        error = drift if number < len(edges) - 1 else np.zeros(2)
        measured = centered[j] - centered[i] + error
        factors.append(RelativeFactor(i, j, SE2.exp(np.r_[measured, 0]), np.eye(3)))
        errors.append(error)
        row = np.zeros(len(truth) - 1)
        if j: row[j - 1] += 1
        if i: row[i - 1] -= 1
        rows.append(row)
    dead_reckoning = [SE2.identity()]
    for factor in factors[:-1]:
        dead_reckoning.append(SE2.compose(dead_reckoning[-1], factor.measurement))
    before = float(np.linalg.norm(np.asarray([p[:2, 2] for p in dead_reckoning]) - centered))
    fit = solve_pose_graph(SE2, dead_reckoning, factors, anchor=0, fixed_rotations=True,
                          max_iterations=reg['graph_iterations'], step_tolerance=reg['graph_step_tolerance'],
                          jacobian_step=reg['graph_numeric_jacobian_step'])
    actual_graph = float(np.linalg.norm(np.asarray([p[:2, 2] for p in fit.poses]) - centered))
    analytic_graph_bound = linear_translation_error_bound(rows, np.ones(len(edges)), errors)
    exact_error = np.linalg.lstsq(np.asarray(rows), np.asarray(errors), rcond=None)[0]
    actual_error = np.asarray([p[:2, 2] for p in fit.poses[1:]]) - centered[1:]
    assert fit.converged
    assert actual_graph <= analytic_graph_bound + reg['numeric_slack']
    assert np.max(np.abs(actual_error - exact_error)) <= reg['round_trip_atol']
    assert actual_graph < before
    assert fit.rank == fit.free_dimensions
    return {'name': name, 'source': source, 'truth_points': truth.tolist(),
            'filter': history, 'pose_graph': {'anchor': 0, 'anchor_coordinates': [0, 0, 0],
             'gauge': fit.gauge, 'fixed_rotations': True, 'before_error_l2': before,
             'after_error_l2': actual_graph, 'analytic_error_bound_l2': analytic_graph_bound,
             'linear_exact_error_l2': float(np.linalg.norm(exact_error)),
             'converged': fit.converged, 'rank': fit.rank, 'free_dimensions': fit.free_dimensions,
             'residual_norm': fit.residual_norm, 'iterations': fit.iterations}}


results = [reference(name, *fn()) for name, fn in [('GridLab2D', gridlab_path), ('AWZ analytical small room', awz_path)]]
assert not any(k.split('.')[0] in {'mlx', 'torch', 'onnxruntime', 'tensorflow'} for k in sys.modules)
result = {'task': 'ainerzero.V9.G1', 'cpu_only': True, 'model_budget': 0,
          'filter_reference_class': 'KnownRotationGaussian; exact conditional translation KF, not general nonlinear IEKF pathwise bound',
          'r1_registration_sha256': hashlib.sha256(
              (R1_DIR / 'cpu_registration.json').read_bytes()).hexdigest(),
          'input_registration_r2_sha256': hashlib.sha256(
              (OUT / 'input_registration_r2.json').read_bytes()).hexdigest(),
          'registered_documents': [{'path': e['path'], 'sha256': e['new_sha256'],
                                    'policy': 'r2 new hash enforced (no exemption)'}
                                   for e in registration_r2['documents']],
          'registered_code_inputs': {path: meta['sha256']
                                     for path, meta in registration_r2['code_inputs']['inputs'].items()},
          'references': results, 'limitations': ['bounded commuting translations only for pathwise upper bounds',
                                                'no arbitrary-Gaussian or nonlinear filter guarantee',
                                                'no rendered-room or visual perception acceptance'],
          'forbidden_model_imports': []}
target = OUT / 'reference-results-r2.json'
if target.exists():
    assert json.loads(target.read_text()) == result, 'existing r2 results differ; keep both revisions'
else:
    target.write_text(json.dumps(result, indent=2) + '\n')
r1_result = json.loads((R1_DIR / 'reference-results-r1.json').read_text())
same = r1_result['references'] == result['references']
diff = {'task': 'ainerzero.V9.G5', 'r1_references_vs_r2_replay': 'identical' if same else 'different',
        'references_equal': same, 'compared_fields': ['references']}
(OUT / 'evidence' / 'replay-vs-r1-diff.json').write_text(json.dumps(diff, indent=2) + '\n')
assert same, 'r2 replay 与 r1 登记的 references 不一致（数值行为被改动）'
print(json.dumps({'replay': 'r2 gate passed', 'references_equal_r1': same,
                  'input_registration_r2_sha256': result['input_registration_r2_sha256'],
                  'r1_registration_sha256': result['r1_registration_sha256']}, indent=2))
print(json.dumps({'references': [{'name': r['name'], 'steps': len(r['filter']),
                                 'max_filter_error': max(h['updated_error'] for h in r['filter']),
                                 'max_filter_bound': max(h['updated_bound'] for h in r['filter']),
                                 'pose_graph': r['pose_graph']} for r in results]}, indent=2))
