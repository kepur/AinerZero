"""Registered CPU-only analytical references; no model or simulation launch."""
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

reg = json.loads((OUT / 'cpu_registration.json').read_text())
for path, sha in reg['source_sha256'].items():
    p = Path(path) if Path(path).is_absolute() else ROOT / path
    assert hashlib.sha256(p.read_bytes()).hexdigest() == sha, 'registered source changed: ' + path


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
          'registration_sha256': hashlib.sha256((OUT / 'cpu_registration.json').read_bytes()).hexdigest(),
          'references': results, 'limitations': ['bounded commuting translations only for pathwise upper bounds',
                                                'no arbitrary-Gaussian or nonlinear filter guarantee',
                                                'no rendered-room or visual perception acceptance'],
          'forbidden_model_imports': []}
target = OUT / 'reference-results-r1.json'
assert not target.exists(), 'preserve prior results; choose new revision'
target.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'references': [{'name': r['name'], 'steps': len(r['filter']),
                                 'max_filter_error': max(h['updated_error'] for h in r['filter']),
                                 'max_filter_bound': max(h['updated_bound'] for h in r['filter']),
                                 'pose_graph': r['pose_graph']} for r in results]}, indent=2))
