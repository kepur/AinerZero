"""Independent T7 CPU audit. Never imports torch/DA3 or executes author mains.

Author methods are extracted from AST and exercised with explicitly fake model
objects for boundary tests only. Those tests are not DA3 inference evidence.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import types
import urllib.request

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
BASE = Path(__file__).resolve().parent
SOURCE = ROOT / 'envs/teachers/t6'
CASES = ['positive_pipeline', 'positive_metrics', 'missing_weights',
         'disallowed_variant', 'state_dict_mismatch', 'timestamp_length',
         'missing_geometry', 'cache_key_identity', 'empty_depth_calibration',
         'invented_calibration_population', 'failed_checks_success_exit']


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def write(p, value):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def extracted(path, names, namespace):
    tree = ast.parse(Path(path).read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    return namespace


def case(name, evidence):
    import numpy as np
    from PIL import Image
    real_model_modules_at_start = [k for k in sys.modules if k == 'torch' or k.startswith('depth_anything_3') or k.startswith('mlx')]
    assert not real_model_modules_at_start, real_model_modules_at_start
    folder = evidence / 'fixtures' / name
    folder.mkdir(parents=True, exist_ok=True)
    calls = []

    class FakeNetwork:
        mismatch = False
        def load_state_dict(self, state, strict=True):
            calls.append({'load_state_dict_strict': strict, 'state_keys': list(state)})
            if strict and self.mismatch:
                raise RuntimeError('fixture state dict mismatch')
            return types.SimpleNamespace(missing_keys=['expected.weight'] if self.mismatch else [], unexpected_keys=['wrong.weight'] if self.mismatch else [])

    class FakeModel:
        def __init__(self, model_name=None):
            self.model = FakeNetwork()
            self.missing = False
            calls.append({'fake_model_architecture': model_name})
        def to(self, device):
            return self
        def eval(self):
            return self
        def inference(self, images, process_res=4, **kw):
            n = len(images)
            pose = np.repeat(np.eye(4, dtype=np.float32)[None], n, axis=0)[:, :3]
            return types.SimpleNamespace(depth=np.ones((n, process_res, process_res), dtype=np.float32),
                conf=None if self.missing else np.ones((n, process_res, process_res), dtype=np.float32),
                extrinsics=None if self.missing else pose,
                intrinsics=None if self.missing else np.repeat(np.eye(3, dtype=np.float32)[None], n, axis=0))

    torch_stub = types.SimpleNamespace(dtype=object, float32='float32',
        device=lambda d: types.SimpleNamespace(type=d),
        inference_mode=lambda: (lambda f: f),
        backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False)),
        __version__='T7_CPU_FIXTURE_NO_TORCH')
    tensor_stub = types.ModuleType('safetensors.torch')
    tensor_stub.load_file = lambda path: {'wrong.weight' if name == 'state_dict_mismatch' else 'expected.weight': np.ones(1)}
    sys.modules['safetensors.torch'] = tensor_stub
    ns = {'np': np, 'Image': Image, 'torch': torch_stub, 'Path': Path, 'Any': object,
          'Sequence': list, 'DepthAnything3': FakeModel, 'hashlib': hashlib,
          'json': json, 'time': time, 'os': os, 'REPO_ROOT': ROOT,
          'st_np': types.SimpleNamespace(save_file=lambda *a: (_ for _ in ()).throw(AssertionError('unexpected tensor output')))}
    extracted(SOURCE / 'pipeline.py', ['DA3GeometryTeacher'], ns)
    Teacher = ns['DA3GeometryTeacher']
    if name != 'missing_weights':
        (folder / 'model.safetensors').write_bytes(b'T7_SENTINEL_NOT_MODEL_WEIGHTS')
    if name == 'state_dict_mismatch':
        original_init = FakeModel.__init__
        def mismatch_init(self, model_name=None):
            original_init(self, model_name)
            self.model.mismatch = True
        FakeModel.__init__ = mismatch_init

    def make(variant='DA3-SMALL'):
        return Teacher(variant=variant, device='cpu', weights_dir=folder)

    frames = [np.zeros((4, 4, 3), dtype=np.uint8), np.ones((4, 4, 3), dtype=np.uint8)]
    def process(t, timestamps=None):
        return t.process_keyframes(frames, timestamps_s=timestamps or [0., .5], process_res=4)

    observation = {'case': name, 'backend': 'explicit_FAKE_CPU_boundary_fixture', 'real_models_loaded': 0}
    if name in ['missing_weights', 'disallowed_variant', 'state_dict_mismatch']:
        try:
            t = make('DA3-GIANT' if name == 'disallowed_variant' else 'DA3-SMALL')
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            print(json.dumps({**observation, 'rejected': type(exc).__name__, 'calls': calls})); return
        print(json.dumps({**observation, 'accepted': True, 'architecture': t.model_name,
                          'weights_file_present': t.safetensors_path.exists(), 'calls': calls}))
        raise AssertionError('bad loading input accepted by unchanged author method')
    if name in ['positive_pipeline', 'timestamp_length', 'missing_geometry', 'cache_key_identity']:
        t = make()
        if name == 'missing_geometry':
            t.model.missing = True
        try:
            result = process(t, [0.] if name == 'timestamp_length' else None)
        except (ValueError, RuntimeError) as exc:
            if name in ['timestamp_length', 'missing_geometry']:
                print(json.dumps({**observation, 'rejected': type(exc).__name__})); return
            raise
        entry = result['cache_entry']
        if name == 'positive_pipeline':
            assert result['pose_3x4'].shape == (2, 3, 4)
            assert len(entry['key_material']['input']['timestamps_s']) == 2
            print(json.dumps({**observation, 'supported_fixture_interface_checks': 'passed'})); return
        if name == 'timestamp_length':
            print(json.dumps({**observation, 'frames': 2, 'timestamps': entry['key_material']['input']['timestamps_s']}))
            assert len(entry['key_material']['input']['timestamps_s']) == 2, 'mismatched time identity accepted'
        elif name == 'missing_geometry':
            print(json.dumps({**observation, 'missing_predictions': True, 'fabricated_pose': result['extrinsics'].tolist(),
                              'fabricated_intrinsics': result['intrinsics'].tolist(), 'confidence_unique': np.unique(result['confidence']).tolist()}))
            raise AssertionError('missing geometry silently replaced by identity pose/intrinsics and unit confidence')
        else:
            canonical = hashlib.sha256(json.dumps(entry['key_material'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            print(json.dumps({**observation, 'reported_cache_key': entry['cache_key'], 'canonical_key_material_sha': canonical}))
            assert entry['cache_key'] == canonical, 'cache rejects producer key: key != canonical key_material SHA'
        return

    metric_ns = {'np': np, 'Path': Path, 'json': json, 'REPORTS_DIR': folder}
    extracted(SOURCE / 'noise_calibration.py', ['compute_rotation_error_degrees', 'compute_translation_rel_error',
              'compute_depth_metrics', 'run_synthetic_calibration_suite'], metric_ns)
    if name == 'positive_metrics':
        assert metric_ns['compute_rotation_error_degrees'](np.eye(3), np.eye(3)) == 0
        assert metric_ns['compute_translation_rel_error'](np.ones(3), np.ones(3)) == 0
        m = metric_ns['compute_depth_metrics'](np.ones((2, 2)), np.ones((2, 2)))
        assert m['abs_rel'] == 0 and m['delta1'] == 1 and m['valid_pixels'] == 4
        print(json.dumps({**observation, 'analytic_metric_controls': 'passed'})); return
    if name == 'empty_depth_calibration':
        m = metric_ns['compute_depth_metrics'](np.zeros((2, 2)), np.zeros((2, 2)))
        print(json.dumps({**observation, 'metrics': m}))
        assert not (m['valid_pixels'] == 0 and m['abs_rel'] == 0 and m['delta1'] == 1), 'empty sample receives perfect scores'
        return
    if name == 'invented_calibration_population':
        record = metric_ns['run_synthetic_calibration_suite']()
        tree = ast.parse((SOURCE / 'noise_calibration.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_synthetic_calibration_suite')
        n_views = next(n.value.value for n in fn.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'n_views' for t in n.targets))
        print(json.dumps({**observation, 'generated_views': n_views, 'declared_data': record['data'],
                          'declared_validation': record['validation'], 'status': record['status'], 'teacher_calls': 0}))
        assert record['data']['n_worlds'] <= n_views, 'declares 32 worlds/840 samples despite only 8 artificial views and zero teacher calls'
        return
    if name == 'failed_checks_success_exit':
        bench_ns = {'REPORTS_DIR': folder, 'json': json,
            'run_benchmark_for_variant': lambda *a, **k: {'fixture': True},
            'run_numerical_consistency_checks': lambda: {'mps_vs_cpu': {'passed': False}},
            'run_negative_controls': lambda: {'controls': [], 'all_passed': False}}
        extracted(SOURCE / 'benchmark_suite.py', ['main'], bench_ns)
        bench_ns['main']()
        print(json.dumps({**observation, 'author_main_returned_normally_despite_parity_and_controls_false': True}))
        raise AssertionError('failed numerical checks/negative controls do not fail author main')
    raise ValueError(name)


def gather(evidence):
    started = time.time()
    evidence.mkdir(parents=True, exist_ok=False)
    paths = sorted(set(list((SOURCE).glob('*.py')) + list((ROOT / 'reports/V9-T6').rglob('*')) +
        list((ROOT / 'artifacts/teachers/da3').rglob('*')) +
        [ROOT / 'src/ainerzero/v9/teachers/cache.py', ROOT / 'envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/api.py']))
    paths = [p for p in paths if p.is_file() and '__pycache__' not in p.parts]
    before = {str(p.relative_to(ROOT)): {'size': p.stat().st_size, 'sha256': sha(p)} for p in paths}
    write(evidence / 'source-and-artifacts-before.json', before)
    for p in paths:
        if p.suffix in ('.py', '.json', '.txt', '.md') and p.stat().st_size < 2_000_000:
            dest = evidence / 'frozen-inputs' / p.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(p.read_bytes())
    versions = {}
    for name in ['torch', 'torchvision', 'numpy', 'safetensors', 'depth-anything-3', 'psutil']:
        try: versions[name] = md.version(name)
        except md.PackageNotFoundError: versions[name] = None
    write(evidence / 'environment.json', {'executable': sys.executable, 'version': sys.version,
        'isolated': sys.flags.isolated, 'package_metadata_only': versions})
    downloads = json.loads((ROOT / 'reports/V9-T6/downloads.json').read_text())
    weight_checks = []
    for r in downloads['records']:
        actual = before[r['file']]
        weight_checks.append({'path': r['file'], 'size_matches': actual['size'] == r['size_bytes'],
            'sha_matches': actual['sha256'] == r['sha256'], **actual})
    write(evidence / 'download-identity-checks.json', weight_checks)
    # Metadata only; never request resolve/model.safetensors or model payloads.
    metadata = []
    for label, repo, rev in [('small', 'depth-anything/DA3-SMALL', 'e08cab65ca0ec38e7826075418411ab90cab4da3'),
                            ('base', 'depth-anything/DA3-BASE', 'f4a6c9b3c95e41c82048423d3493a81ec3fa810e')]:
        url = f'https://huggingface.co/api/models/{repo}/revision/{rev}?blobs=true'
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                raw = response.read(2_000_001)
                assert len(raw) <= 2_000_000, 'metadata cap exceeded'
                (evidence / f'hf-{label}-api.json').write_bytes(raw)
                obj = json.loads(raw)
                metadata.append({'repo': repo, 'url': url, 'resolved_sha': obj.get('sha'),
                    'license': obj.get('cardData', {}).get('license'), 'siblings': obj.get('siblings', [])})
        except Exception as exc:
            metadata.append({'repo': repo, 'url': url, 'error': repr(exc), 'status': 'UNVERIFIED'})
    write(evidence / 'hf-metadata-summary.json', metadata)
    result = []
    for name in CASES:
        argv = [sys.executable, '-I', str(Path(__file__).resolve()), '--case', name, '--evidence', str(evidence)]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')
        t = time.time()
        try:
            proc = subprocess.run(argv, cwd=BASE, env=env, capture_output=True, timeout=45)
            (evidence / f'{name}.stdout').write_bytes(proc.stdout)
            (evidence / f'{name}.stderr').write_bytes(proc.stderr)
            result.append({'case': name, 'argv': argv, 'rc': proc.returncode, 'wall_seconds': time.time()-t,
                'kind': 'positive_control' if name.startswith('positive') else 'adverse_contract_test',
                'meaning': 'RC1 is an actual unmet contract assertion, not a model-run failure'})
        except subprocess.TimeoutExpired as exc:
            result.append({'case': name, 'argv': argv, 'status': 'TIMED_OUT', 'error': repr(exc)})
    write(evidence / 'case-results.json', result)
    after = {str(p.relative_to(ROOT)): {'size': p.stat().st_size, 'sha256': sha(p)} for p in paths}
    write(evidence / 'source-and-artifacts-after.json', after)
    summary = {'status': 'independent_CPU_evidence_collected', 'recommendation': 'REJECT_T6',
        'positive_rc0': sum(r.get('rc') == 0 for r in result if r['case'].startswith('positive')),
        'adverse_real_nonzero': sum(r.get('rc') not in (None, 0) for r in result if not r['case'].startswith('positive')),
        'source_and_originals_unchanged': before == after,
        'weights_checks': weight_checks, 'new_real_model_runs': 0, 'new_gpu_runs': 0,
        'actual_source_mutations': 0, 'fake_CPU_fixtures_not_model_evidence': True,
        'wall_seconds': time.time()-started, 'audit_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    write(evidence / 'summary.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    if '--case' in sys.argv:
        case(sys.argv[sys.argv.index('--case')+1], Path(sys.argv[sys.argv.index('--evidence')+1]))
    else:
        gather(BASE / 'evidence')
