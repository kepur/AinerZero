"""CPU residual summaries from supplied paired predictions, never a teacher simulator.
Outputs are unregistered candidates. Real input/receipt approval is external.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np


def _rotation(value):
    r = np.asarray(value, dtype=np.float64)
    if r.shape != (3, 3) or not np.isfinite(r).all():
        raise ValueError('rotation must be finite 3x3')
    if not np.allclose(r.T @ r, np.eye(3), atol=1e-5, rtol=0) or not np.isclose(np.linalg.det(r), 1, atol=1e-5):
        raise ValueError('rotation is not SO(3); no silent repair')
    return r


def compute_rotation_error_degrees(r_pred, r_gt):
    delta = _rotation(r_pred).T @ _rotation(r_gt)
    return float(np.degrees(np.arccos(np.clip((np.trace(delta)-1)/2, -1, 1))))


def compute_translation_rel_error(t_pred, t_gt, scale=1.):
    p, g = np.asarray(t_pred, dtype=float), np.asarray(t_gt, dtype=float)
    if p.shape != (3,) or g.shape != (3,) or not np.isfinite(p).all() or not np.isfinite(g).all():
        raise ValueError('translations must be finite 3-vectors')
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('explicit positive finite alignment scale required')
    denom = float(np.linalg.norm(g))
    if denom == 0:
        raise ValueError('relative translation error undefined at zero ground-truth norm')
    return float(np.linalg.norm(p*scale-g)/denom)


def compute_depth_metrics(d_pred, d_gt, valid_mask=None):
    p, g = np.asarray(d_pred, dtype=float), np.asarray(d_gt, dtype=float)
    if p.shape != g.shape or p.ndim < 2:
        raise ValueError('paired depth shapes must agree')
    mask = np.isfinite(p) & np.isfinite(g) & (p > 0) & (g > 0)
    if valid_mask is not None:
        supplied = np.asarray(valid_mask)
        if supplied.shape != p.shape or supplied.dtype != np.bool_:
            raise ValueError('depth mask must be boolean and match image shape')
        mask &= supplied
    if not mask.any():
        raise ValueError('zero valid depth pixels; no perfect-score substitute')
    pred, truth = p[mask], g[mask]
    scale = float(np.median(truth)/np.median(pred))
    aligned = pred*scale
    ratio = np.maximum(aligned/truth, truth/aligned)
    return {'abs_rel': float(np.mean(np.abs(aligned-truth)/truth)),
            'delta1': float(np.mean(ratio < 1.25)), 'valid_pixels': int(mask.sum()),
            'total_pixels': int(mask.size), 'median_alignment_scale': scale,
            'alignment': 'per_view_median_relative_depth_diagnostic'}


def calibrate_paired_predictions(records, scene_layer):
    if not records or not isinstance(scene_layer, dict) or not scene_layer:
        raise ValueError('explicit nonempty paired records and scene stratum required')
    ids, worlds, receipts, metrics = set(), set(), set(), []
    fit_worlds, holdout_worlds = set(), set()
    teacher_identity = None
    for row in records:
        if row.get('partition') != 'development':
            raise ValueError('calibration accepts development pairs only; never final')
        for key in ('record_id', 'world_key', 'source_receipt_id', 'teacher_identity'):
            if not row.get(key):
                raise ValueError(f'missing supplied provenance: {key}')
        if row['record_id'] in ids:
            raise ValueError('duplicate paired sample identity')
        if row.get('scene_layer') != scene_layer:
            raise ValueError('scene strata must not be silently pooled')
        if row.get('alignment', {}).get('kind') != 'prealigned' or not row['alignment'].get('evidence_ref'):
            raise ValueError('explicit prealignment evidence required; no invented Sim3 fit')
        if row.get('pose_convention') != 'camera_to_world':
            raise ValueError('paired poses must declare camera_to_world convention')
        split = row.get('split')
        if split not in ('fit', 'holdout'):
            raise ValueError('explicit fit/holdout world split required')
        (fit_worlds if split == 'fit' else holdout_worlds).add(row['world_key'])
        if teacher_identity is None:
            teacher_identity = row['teacher_identity']
        elif teacher_identity != row['teacher_identity']:
            raise ValueError('cannot pool model/weight/preprocess identities')
        ids.add(row['record_id']); worlds.add(row['world_key']); receipts.add(row['source_receipt_id'])
        depth = compute_depth_metrics(row['predicted_depth'], row['truth_depth'])
        metrics.append({'record_id': row['record_id'], 'world_key': row['world_key'], 'split': split,
            'rotation_error_deg': compute_rotation_error_degrees(row['predicted_rotation'], row['truth_rotation']),
            'translation_rel_error': compute_translation_rel_error(row['predicted_translation'], row['truth_translation']),
            'depth': depth})
    if fit_worlds & holdout_worlds:
        raise ValueError('fit and holdout worlds overlap')
    if not fit_worlds or not holdout_worlds:
        raise ValueError('both explicit disjoint world sets are required')
    material = {'teacher_identity': teacher_identity, 'scene_layer': scene_layer,
                'sample_ids': sorted(ids), 'source_receipt_ids': sorted(receipts)}
    key = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {'record_type': 'teacher_calibration_candidate', 'calibration_id': key,
            'status': 'candidate_unregistered', 'source_authentication': 'UNVERIFIED_by_this_CPU_summary',
            'data': {'partition': 'development', 'n_worlds': len(worlds), 'n_samples': len(records),
                     'world_keys': sorted(worlds), 'source_receipt_ids': sorted(receipts)},
            'validation': {'fit_worlds': sorted(fit_worlds), 'holdout_worlds': sorted(holdout_worlds),
                'n_holdout_worlds': len(holdout_worlds), 'nees_coverage_95': None,
                'noise_covariance': None, 'status': 'not_registered; covariance/NEES require preregistered method and actual controlled teacher pairs'},
            'scene_layer': scene_layer, 'teacher_identity': teacher_identity,
            'per_sample_metrics': metrics,
            'note': 'No noise is generated here. This is not a registered sensor-noise model or training admission.'}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--pairs', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    data = json.loads(args.pairs.read_text())
    result = calibrate_paired_predictions(data['records'], data['scene_layer'])
    with args.output.open('x') as f:
        json.dump(result, f, indent=2, allow_nan=False)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
