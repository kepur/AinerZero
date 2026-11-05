"""CPU-only T6 implementation tests, not DA3 numerical/capability evidence."""
from __future__ import annotations
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy as np

SRC = Path(__file__).resolve().parents[1]
ROOT = SRC.parents[2]
REPORT = ROOT / 'reports/V9-T6/r2'
REPORT.mkdir(parents=True, exist_ok=True)

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

p = load('t6_r2_pipeline', SRC/'pipeline.py')
n = load('t6_r2_calibration', SRC/'noise_calibration.py')
b = load('t6_r2_benchmark', SRC/'benchmark_suite.py')

class FakeModel:
    def __init__(self):
        self.calls = 0
        self.missing = None
    def inference(self, images, process_res=4, **kw):
        self.calls += 1
        count = len(images)
        values = dict(depth=np.ones((count, 4, 4), dtype=np.float32),
            conf=np.ones((count, 4, 4), dtype=np.float32),
            extrinsics=np.repeat(np.eye(4, dtype=np.float32)[None], count, axis=0)[:, :3],
            intrinsics=np.repeat(np.eye(3, dtype=np.float32)[None], count, axis=0))
        if self.missing:
            values[self.missing] = None
        return types.SimpleNamespace(**values)

def teacher(dtype='float32'):
    manifest = {'model_name': 'da3-small', 'revision': p.APPROVED['DA3-SMALL']['revision'],
        'directory': '/CPU_TEST_FIXTURE_ONLY', 'files': [{'name': 'fixture', 'sha256': 'a'*64, 'bytes': 1}]}
    with patch.object(p, 'inspect_weights', return_value=manifest), patch.object(p.DA3GeometryTeacher, '_load_model', lambda self: None):
        obj = p.DA3GeometryTeacher(device='cpu', dtype=dtype)
    obj.model = FakeModel()
    return obj

def frames():
    return [np.zeros((4,4,3), dtype=np.uint8), np.ones((4,4,3), dtype=np.uint8)]

def run(t, **kw):
    args = dict(timestamps_s=[0., .5], world_key='CPU_FIXTURE:world', process_res=4)
    args.update(kw)
    return t.process_keyframes(frames(), **args)

def fixture_dir():
    return Path(tempfile.mkdtemp(prefix='cpu-fixture-', dir=REPORT))

def paired(record_id, world, split):
    return {'record_id': record_id, 'world_key': world, 'source_receipt_id': 'TEST_ONLY_RECEIPT',
        'teacher_identity': {'teacher_id': 'CPU_TEST_FIXTURE'}, 'partition': 'development',
        'scene_layer': {'setting': 'CPU_TEST'}, 'alignment': {'kind':'prealigned','evidence_ref':'TEST_ONLY'},
        'pose_convention':'camera_to_world','split':split,
        'predicted_rotation':np.eye(3).tolist(),'truth_rotation':np.eye(3).tolist(),
        'predicted_translation':[1.,0.,0.],'truth_translation':[1.,0.,0.],
        'predicted_depth':[[1.,1.],[1.,1.]],'truth_depth':[[1.,1.],[1.,1.]]}

class CPURevisionTests(unittest.TestCase):
    def test_00_t33_remainder_binding_matches_supervised_count(self):
        binding = p.load_remainder_binding(
            ROOT / 'reports/V9-T33/remainder_protocol.json', 10, 'ainerzero.V9.T33'
        )
        self.assertEqual(len(binding['rows']), 10)
        self.assertEqual(len({row['world_key'] for row in binding['rows']}), 6)
        self.assertEqual(sum(row['split'] == 'fit' for row in binding['rows']), 5)
        self.assertEqual(sum(row['split'] == 'holdout' for row in binding['rows']), 5)
        self.assertFalse(binding['protocol']['full_calibration_completed'])

    def test_00b_t33_remainder_binding_rejects_undercount_and_bad_identity(self):
        path = ROOT / 'reports/V9-T33/remainder_protocol.json'
        for views, task in [(9, 'ainerzero.V9.T33'), (10, 'ainerzero.V9.T6')]:
            with self.subTest(views=views, task=task), self.assertRaises(ValueError):
                p.load_remainder_binding(path, views, task)

    def test_00c_t33_remainder_binding_rejects_duplicate_or_unknown_records(self):
        original = json.loads((ROOT / 'reports/V9-T33/remainder_protocol.json').read_text())
        cases = []
        duplicate = json.loads(json.dumps(original))
        duplicate['selected_record_ids'][-1] = duplicate['selected_record_ids'][0]
        cases.append(duplicate)
        unknown = json.loads(json.dumps(original))
        unknown['selected_record_ids'][-1] = 'not-in-frozen-manifest'
        cases.append(unknown)
        for protocol in cases:
            target = fixture_dir() / 'bad-remainder.json'
            target.write_text(json.dumps(protocol))
            # The repository-containment guard is also part of the contract, so
            # use a temporary path under reports rather than a system temp path.
            with self.assertRaises(ValueError):
                p.load_remainder_binding(target, 10, 'ainerzero.V9.T33')

    def test_00d_supervised_worker_receives_the_same_remainder_count(self):
        spec_path = fixture_dir() / 'spec.json'
        spec_path.write_text(json.dumps({'task': 'ainerzero.V9.T33', 'views': 10}))
        remainder = ROOT / 'reports/V9-T33/remainder_protocol.json'
        if hasattr(p.inspect_weights, '_ran'):
            delattr(p.inspect_weights, '_ran')
        with patch.dict('os.environ', {
            'T6_RUN_REAL_CALIBRATION': '1',
            'DA3_TASK_ID': 'ainerzero.V9.T33',
            'T6_REMAINDER_PROTOCOL': str(remainder),
        }, clear=False), patch.object(sys, 'argv', [
            'worker', '--spec-file', str(spec_path), '--allow-model-execution'
        ]), patch('subprocess.run', return_value=types.SimpleNamespace(returncode=0)) as run_mock:
            p.inspect_weights('DA3-SMALL')
        command = run_mock.call_args.args[0]
        self.assertEqual(command[command.index('--expected-views') + 1], '10')
        self.assertEqual(command[command.index('--run-task') + 1], 'ainerzero.V9.T33')
        self.assertEqual(Path(command[command.index('--remainder-protocol') + 1]), remainder)
        delattr(p.inspect_weights, '_ran')

    def test_01_real_weight_inspection_does_not_import_models(self):
        self.assertNotIn('torch', sys.modules)
        for name in p.APPROVED:
            result = p.inspect_weights(name)
            self.assertEqual(len(result['files']), 2)
            self.assertEqual(result['models_loaded'], 0)
        self.assertNotIn('torch', sys.modules)

    def test_02_exact_variant_whitelist(self):
        for name in ['DA3-GIANT', 'da3-small', 'SMALL', 'DA3-SMALL-malformed']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                p.inspect_weights(name)

    def test_03_missing_weights_refused(self):
        with self.assertRaises(ValueError):
            p.inspect_weights('DA3-SMALL', fixture_dir())

    def test_04_hash_and_config_identity_guards(self):
        d=fixture_dir();cfg=json.dumps({'model_name':'da3-small'}).encode();weight=b'CPU_FIXTURE_WEIGHTS'
        (d/'config.json').write_bytes(cfg);(d/'model.safetensors').write_bytes(weight)
        spec={'model_name':'da3-small','revision':'TEST_ONLY',
              'config.json':(len(cfg),hashlib.sha256(cfg).hexdigest()),
              'model.safetensors':(len(weight),hashlib.sha256(weight).hexdigest())}
        with patch.dict(p.APPROVED, {'DA3-SMALL':spec}):
            p.inspect_weights('DA3-SMALL',d)
            (d/'model.safetensors').write_bytes(b'X'+weight[1:])
            with self.assertRaises(ValueError):p.inspect_weights('DA3-SMALL',d)
            (d/'model.safetensors').write_bytes(weight)
            wrong=json.dumps({'model_name':'da3-base'}).encode();(d/'config.json').write_bytes(wrong)
            spec['config.json']=(len(wrong),hashlib.sha256(wrong).hexdigest())
            with self.assertRaises(ValueError):p.inspect_weights('DA3-SMALL',d)

    def test_05_strict_load_checks_returned_mismatches(self):
        calls=[]
        class Wrapper:
            def load_state_dict(self,state,strict=True):
                calls.append(strict);return types.SimpleNamespace(missing_keys=[],unexpected_keys=[])
        p.validate_real_checkpoint_load(Wrapper(), {'model.weight':np.ones(1)})
        self.assertEqual(calls,[True])
        class Broken(Wrapper):
            def load_state_dict(self,state,strict=True):
                return types.SimpleNamespace(missing_keys=['a'],unexpected_keys=[])
        with self.assertRaises(ValueError):p.validate_real_checkpoint_load(Broken(),{})

    def test_06_actual_loader_targets_outer_wrapper_and_explicit_precision(self):
        calls=[]
        class Tensor:
            device=types.SimpleNamespace(type='cpu')
            def to(self,**kw):calls.append(('tensor_to',kw));return self
        class Inner:
            def __call__(self,*a):calls.append(('inner_forward',));return {'fixture':True}
            def load_state_dict(self,*a,**kw):raise AssertionError('WRONG INNER LOAD TARGET')
        class API:
            def __init__(self,model_name):self.model=Inner();calls.append(('init',model_name))
            def load_state_dict(self,state,strict):
                self.assert_state=state;calls.append(('outer_load',strict));return types.SimpleNamespace(missing_keys=[],unexpected_keys=[])
            def to(self,**kw):calls.append(('model_to',kw));return self
            def eval(self):return self
        torch=types.ModuleType('torch');torch.float32='FP32';torch.float16='FP16'
        torch.device=lambda s:types.SimpleNamespace(type=s)
        torch.backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda:False))
        torch.inference_mode=lambda:(lambda f:f)
        def autocast(**kw):calls.append(('autocast',kw));return contextlib.nullcontext()
        torch.autocast=autocast
        tensors=types.ModuleType('safetensors.torch');tensors.load_file=lambda *a,**kw:{'model.weight':np.ones(1)}
        api=types.ModuleType('depth_anything_3.api');api.DepthAnything3=API
        package=types.ModuleType('depth_anything_3');package.__path__=[]
        stub={'torch':torch,'safetensors.torch':tensors,'depth_anything_3':package,'depth_anything_3.api':api}
        obj=teacher(dtype='float16')
        with patch.dict(sys.modules,stub):
            obj._load_model();obj.model.forward(Tensor())
        self.assertIn(('outer_load',True),calls)
        self.assertIn(('autocast',{'device_type':'cpu','enabled':False}),calls)
        self.assertIn(('tensor_to',{'dtype':'FP16'}),calls)
        self.assertNotIn('torch',sys.modules)

    def test_07_mps_unavailable_never_silently_uses_cpu(self):
        obj=teacher();obj._device='mps'
        torch=types.ModuleType('torch');torch.backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda:False))
        tensors=types.ModuleType('safetensors.torch');tensors.load_file=lambda *a,**k: self.fail('must not read tensors')
        api=types.ModuleType('depth_anything_3.api');api.DepthAnything3=object
        package=types.ModuleType('depth_anything_3');package.__path__=[]
        with patch.dict(sys.modules,{'torch':torch,'safetensors.torch':tensors,'depth_anything_3':package,'depth_anything_3.api':api}):
            with self.assertRaises(RuntimeError):obj._load_model()

    def test_08_bad_timestamps_rejected_before_inference(self):
        for ts in [None,[0.],[0.,0.],[1.,0.],[-1.,0.],[0.,float('nan')],[0.,float('inf')],[False,.5]]:
            t=teacher()
            with self.subTest(ts=ts),self.assertRaises(ValueError):run(t,timestamps_s=ts)
            self.assertEqual(t.model.calls,0)

    def test_09_missing_predictions_never_fabricated(self):
        for field in ['depth','conf','extrinsics','intrinsics']:
            t=teacher();t.model.missing=field
            with self.subTest(field=field),self.assertRaises(ValueError):run(t)

    def test_10_prediction_shape_finite_and_focal_guards(self):
        base=FakeModel().inference(frames())
        for field,value in [('intrinsics',np.zeros((2,3,3),np.float32)),('depth',np.full((2,4,4),np.nan,np.float32)),
                            ('conf',-np.ones((2,4,4),np.float32)),('extrinsics',np.eye(4,dtype=np.float32))]:
            altered=types.SimpleNamespace(**vars(base));setattr(altered,field,value)
            with self.subTest(field=field),self.assertRaises(ValueError):p.checked_predictions(altered,2)

    def test_11_canonical_key_and_clock_precision_identity(self):
        t=teacher();a=run(t)
        expected=hashlib.sha256(json.dumps(a['key_material'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(a['cache_key'],expected)
        self.assertNotEqual(a['cache_key'],run(t,timestamps_s=[0.,1.])['cache_key'])
        self.assertNotEqual(a['cache_key'],run(teacher('float16'))['cache_key'])
        self.assertFalse(a['prediction_record']['registered_cache_entry'])
        self.assertEqual(a['prediction_record']['reproducibility'],'unverified')

    def test_12_runtime_identity_is_readonly_and_manifest_copy_is_defensive(self):
        t=teacher()
        with self.assertRaises(AttributeError):t.dtype='float16'
        m=t.manifest;m['files'].clear()
        self.assertEqual(len(t.manifest['files']),1)

    def test_13_final_unknown_world_and_output_reuse_refused_before_inference(self):
        for kw in [{'partition':'final'},{'world_key':''},{'output_dir':fixture_dir()}]:
            t=teacher()
            with self.subTest(kw=kw),self.assertRaises(ValueError):run(t,**kw)
            self.assertEqual(t.model.calls,0)

    def test_14_written_candidate_has_all_four_actual_fixture_tensors(self):
        d=fixture_dir()/'new-output';r=run(teacher(),output_dir=d)
        with (d/'prediction.safetensors').open('rb') as f:
            size=struct.unpack('<Q',f.read(8))[0];header=json.loads(f.read(size))
        self.assertEqual(set(header)-{'__metadata__'},{'camera_pose','intrinsics','depth','confidence'})
        self.assertEqual(r['prediction_record']['files'][0]['sha256'],p.digest(d/'prediction.safetensors'))

    def test_15_depth_empty_and_bad_mask_rejected(self):
        with self.assertRaises(ValueError):n.compute_depth_metrics(np.zeros((2,2)),np.zeros((2,2)))
        with self.assertRaises(ValueError):n.compute_depth_metrics(np.ones((2,2)),np.ones((2,2)),np.ones((2,2)))
        result=n.compute_depth_metrics(np.ones((2,2))*2,np.ones((2,2)))
        self.assertEqual(result['valid_pixels'],4);self.assertEqual(result['abs_rel'],0)
        self.assertEqual(result['median_alignment_scale'],.5)

    def test_16_paired_data_counts_are_real_not_constants(self):
        rows=[paired('a','fit-world','fit'),paired('b','holdout-world','holdout')]
        result=n.calibrate_paired_predictions(rows,{'setting':'CPU_TEST'})
        self.assertEqual(result['data']['n_worlds'],2);self.assertEqual(result['data']['n_samples'],2)
        self.assertEqual(result['validation']['n_holdout_worlds'],1)
        self.assertIsNone(result['validation']['nees_coverage_95'])
        self.assertEqual(result['status'],'candidate_unregistered')

    def test_17_no_final_duplicate_overlap_or_missing_receipt(self):
        good=[paired('a','fit-world','fit'),paired('b','holdout-world','holdout')]
        cases=[]
        for key,value in [('partition','final'),('source_receipt_id',''),('world_key','fit-world')]:
            rows=json.loads(json.dumps(good));rows[1][key]=value;cases.append(rows)
        cases.append([good[0],good[0]])
        for rows in cases:
            with self.subTest(rows=rows),self.assertRaises(ValueError):n.calibrate_paired_predictions(rows,{'setting':'CPU_TEST'})

    def test_18_no_invented_alignment_or_mixed_teacher(self):
        for key,value in [('alignment',{'kind':'sim3'}),('teacher_identity',{'teacher_id':'OTHER'}),('scene_layer',{'setting':'OTHER'})]:
            rows=[paired('a','fit-world','fit'),paired('b','holdout-world','holdout')];rows[1][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):n.calibrate_paired_predictions(rows,{'setting':'CPU_TEST'})

    def test_19_rotation_and_translation_domain_guards(self):
        self.assertEqual(n.compute_rotation_error_degrees(np.eye(3),np.eye(3)),0)
        with self.assertRaises(ValueError):n.compute_rotation_error_degrees(np.eye(3)*2,np.eye(3))
        with self.assertRaises(ValueError):n.compute_translation_rel_error([0,0,0],[0,0,0])

    def test_20_failed_or_unverified_results_refused(self):
        control={'clean_returncode':0,'bad_returncode':1,'expected_error':'BAD','observed_error':'BAD'}
        self.assertTrue(b.validate_results({'parity':{'passed':True}},[control]))
        for value in [False,'true',None]:
            with self.subTest(value=value),self.assertRaises(ValueError):b.validate_results({'parity':{'passed':value}},[control])
        for key,value in [('bad_returncode',0),('bad_returncode',-9),('bad_returncode',True),('clean_returncode',False),('observed_error','WRONG')]:
            bad=dict(control);bad[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):b.validate_results({'parity':{'passed':True}},[bad])

    def test_21_measurement_units_and_registered_run_refusal(self):
        result=b.measure_teacher_instance(teacher(),frames(),[0.,.5],'CPU_FIXTURE:world',lambda:None,iterations=3)
        self.assertEqual(result['sample_unit'],'frame');self.assertEqual(result['frames_per_sequence'],2)
        self.assertEqual(result['tensor_bytes_per_frame']*2,result['tensor_bytes_per_sequence'])
        self.assertIsNone(result['peak_mps_bytes'])
        self.assertEqual(b.main(['--mode','run']),3)
        self.assertNotIn('torch',sys.modules)

if __name__=='__main__':
    unittest.main(verbosity=2)
