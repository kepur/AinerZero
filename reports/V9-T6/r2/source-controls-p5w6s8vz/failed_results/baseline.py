"""T6 measurement helpers. Standalone inspection never starts model inference.
Actual runs require a registered project CLI/RunStore worker and explicit budget.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
from pathlib import Path
import statistics
import time

HERE = Path(__file__).resolve().parent

def _pipeline():
    spec = importlib.util.spec_from_file_location('t6_pipeline', HERE / 'pipeline.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_results(numerical, controls):
    if not isinstance(numerical, dict) or not numerical:
        raise ValueError('numerical results missing')
    if any(not isinstance(v, dict) or v.get('passed') is not True for v in numerical.values()):
        raise ValueError('numerical checks failed or unverified')
    if not isinstance(controls, list) or not controls:
        raise ValueError('negative controls missing')
    for row in controls:
        if (not isinstance(row.get('clean_returncode'), int) or isinstance(row.get('clean_returncode'), bool)
                or row['clean_returncode'] != 0 or not isinstance(row.get('bad_returncode'), int)
                or isinstance(row.get('bad_returncode'), bool) or row['bad_returncode'] <= 0
                or row.get('observed_error') != row.get('expected_error') or not row.get('expected_error')):
            raise ValueError('control lacks real clean/bad exit and matching fault evidence')
    return True


def measure_teacher_instance(teacher, images, timestamps, world_key, synchronize, *, iterations=5):
    """Measure an ALREADY owned adapter. Caller owns run budget/resource guard.

    No model factory, loader, default fixture or permission bypass is supplied.
    Sample means a frame throughout; sequence statistics are separate.
    """
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 3 or not images:
        raise ValueError('at least 3 repeats and nonempty images required')
    synchronize()
    t = time.perf_counter()
    teacher.process_keyframes(images[:1], timestamps_s=timestamps[:1], world_key=world_key)
    synchronize()
    first = time.perf_counter()-t
    latencies, result = [], None
    for _ in range(iterations):
        synchronize(); t = time.perf_counter()
        result = teacher.process_keyframes(images, timestamps_s=timestamps, world_key=world_key)
        synchronize(); elapsed = time.perf_counter()-t
        if not math.isfinite(elapsed) or elapsed <= 0:
            raise ValueError('invalid observed elapsed time')
        latencies.append(elapsed)
    median = statistics.median(latencies)
    byte_count = sum(result[k].nbytes for k in ('pose_3x4', 'intrinsics', 'depth', 'confidence'))
    return {'sample_unit': 'frame', 'frames_per_sequence': len(images), 'repeats': iterations,
            'first_frame_latency_s': first, 'sequence_latencies_s': latencies,
            'median_sequence_latency_s': median, 'sequence_latency_range_s': [min(latencies), max(latencies)],
            'steady_state_frames_per_second': len(images)/median,
            'time_per_1000_frames_s_extrapolated': median*1000/len(images),
            'tensor_bytes_per_sequence': byte_count, 'tensor_bytes_per_frame': byte_count/len(images),
            'load_time_s': None, 'peak_rss_bytes': None, 'peak_mps_bytes': None,
            'unverified': ['load and lifetime RSS/GPU peaks must come from the registered worker receipt'],
            'admission': 'measurement_only_not_capability_or_noise_registration'}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['inspect', 'run'], default='inspect')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.mode == 'run':
        print(json.dumps({'status': 'blocked', 'models_loaded': 0,
            'reason': 'T6 project CLI/central RunStore binding, remaining budget and calibration inputs must be registered by the coordinator. Standalone model runs are refused.'}))
        return 3
    module = _pipeline()
    result = {'status': 'inspection_only', 'models_loaded': 0,
              'models': [module.inspect_weights(v) for v in module.APPROVED],
              'real_execution': 'not_authorized_by_this_command'}
    if args.output:
        with args.output.open('x') as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
