"""DA3 prediction library; execution belongs to a registered project worker.
Import/inspect are CPU-only. This library grants no model execution budget.
"""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[3]
APPROVED = {
    'DA3-SMALL': {'model_name': 'da3-small', 'revision': 'e08cab65ca0ec38e7826075418411ab90cab4da3',
        'model.safetensors': (137248940, '364492e38a3a06d221ac75da7f6621ada3f2361cd24fde11ba79091e9f40efcf'),
        'config.json': (1202, 'a486e29e82b7ab4a7d4cefc1ea4526cfe2ae438a572c8ca98917cfbcde7447d2')},
    'DA3-BASE': {'model_name': 'da3-base', 'revision': 'f4a6c9b3c95e41c82048423d3493a81ec3fa810e',
        'model.safetensors': (541518028, 'e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5'),
        'config.json': (1205, '5e34115ebc17bd2d8d43033c5f72e9446ac8833fd61d3fa160b7e67e0bb5b7b5')},
}

def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()

def source_identity():
    upstream = ROOT / 'envs/teachers/t6/Depth-Anything-3/src'
    if not upstream.is_dir():
        raise ValueError('upstream source tree is missing')
    files = {}
    for path in sorted(upstream.rglob('*')):
        if path.is_file() and path.suffix in ('.py', '.yaml', '.json'):
            if path.is_symlink():
                raise ValueError('upstream source symlinks are not accepted')
            files[str(path.relative_to(upstream))] = digest(path)
    if not files:
        raise ValueError('upstream source identity is empty')
    versions = {}
    for name in ('torch', 'numpy', 'safetensors'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {'upstream_files_sha256': hashlib.sha256(canonical(files)).hexdigest(),
            'upstream_files': files, 'package_versions': versions}

def inspect_weights(variant: str, directory: Path | None = None) -> dict:
    if variant not in APPROVED:
        raise ValueError('only exact DA3-SMALL and DA3-BASE variants are approved')
    spec = APPROVED[variant]
    directory = Path(directory) if directory is not None else ROOT / 'artifacts/teachers/da3' / variant
    rows = []
    for filename in ('config.json', 'model.safetensors'):
        p = directory / filename
        if not p.is_file() or p.is_symlink():
            raise ValueError(f'missing or symlink model artifact: {p}')
        size, expected = spec[filename]
        if p.stat().st_size != size:
            raise ValueError(f'artifact size mismatch: {filename}')
        actual = digest(p)
        if actual != expected:
            raise ValueError(f'artifact SHA256 mismatch: {filename}')
        rows.append({'name': filename, 'sha256': actual, 'bytes': size})
    cfg = json.loads((directory / 'config.json').read_text())
    if cfg.get('model_name') != spec['model_name']:
        raise ValueError('config model identity mismatch')
    return {'variant': variant, 'model_name': spec['model_name'], 'revision': spec['revision'],
            'license': 'Apache-2.0', 'files': rows, 'directory': str(directory), 'models_loaded': 0}

def validate_timestamps(values, count: int) -> list[float]:
    if False:
        raise ValueError('one explicit timestamp per frame is required')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('timestamps must be finite nonnegative numbers')
    result = [float(v) for v in values]
    if any(b <= a for a, b in zip(result, result[1:])):
        raise ValueError('timestamps must be strictly increasing')
    return result

def checked_predictions(prediction, count: int):
    import numpy as np
    arrays = {}
    for field in ('depth', 'conf', 'extrinsics', 'intrinsics'):
        value = getattr(prediction, field, None)
        if value is None:
            raise ValueError(f'required prediction missing: {field}; no synthetic substitute')
        array = np.asarray(value)
        if not np.issubdtype(array.dtype, np.floating) or not np.isfinite(array).all():
            raise ValueError(f'prediction must be finite floating point: {field}')
        arrays[field] = array.astype(np.float32)
    depth, conf, pose, intrinsics = (arrays[k] for k in ('depth', 'conf', 'extrinsics', 'intrinsics'))
    if depth.ndim != 3 or depth.shape[0] != count or depth.shape != conf.shape:
        raise ValueError('depth/confidence shape mismatch')
    if not (depth > 0).any() or (conf < 0).any():
        raise ValueError('no valid depth or negative confidence')
    if pose.shape not in ((count, 3, 4), (count, 4, 4)) or intrinsics.shape != (count, 3, 3):
        raise ValueError('camera prediction shape mismatch')
    if (intrinsics[:, 0, 0] <= 0).any() or (intrinsics[:, 1, 1] <= 0).any():
        raise ValueError('nonpositive focal length')
    return arrays

def validate_real_checkpoint_load(model, state):
    """Checkpoint addresses the outer API wrapper including model.* keys."""
    result = model.load_state_dict(state, strict=True)
    if getattr(result, 'missing_keys', ()) or getattr(result, 'unexpected_keys', ()):
        raise ValueError('checkpoint load returned unmatched keys')
    return result

class DA3GeometryTeacher:
    """Prediction library owned/unloaded by an approved project worker only."""
    def __init__(self, variant='DA3-SMALL', device='mps', weights_dir=None, dtype='float32'):
        manifest = inspect_weights(variant, weights_dir)
        if device not in ('cpu', 'mps'):
            raise ValueError('unsupported device; no silent fallback')
        precision = str(dtype).removeprefix('torch.')
        if precision not in ('float32', 'float16'):
            raise ValueError('unsupported compute precision')
        self._manifest_bytes = canonical(manifest)
        self._source_bytes = canonical(source_identity())
        self._variant, self._device, self._dtype = variant, device, precision
        self._load_model()

    @property
    def manifest(self):
        return json.loads(self._manifest_bytes)

    @property
    def variant(self):
        return self._variant

    @property
    def model_name(self):
        return self.manifest['model_name']

    @property
    def device(self):
        return self._device

    @property
    def dtype(self):
        return self._dtype

    @property
    def weights_dir(self):
        return Path(self.manifest['directory'])

    def _load_model(self):
        import torch
        from safetensors.torch import load_file
        upstream = ROOT / 'envs/teachers/t6/Depth-Anything-3/src'
        if str(upstream) not in sys.path:
            sys.path.insert(0, str(upstream))
        from depth_anything_3.api import DepthAnything3
        if self.device == 'mps' and not torch.backends.mps.is_available():
            raise RuntimeError('MPS unavailable; refusing CPU substitution')
        precision = torch.float32 if self.dtype == 'float32' else torch.float16
        class ExplicitPrecisionDA3(DepthAnything3):
            @torch.inference_mode()
            def forward(inner, image, extrinsics=None, intrinsics=None, export_feat_layers=None,
                        infer_gs=False, use_ray_pose=False, ref_view_strategy='saddle_balanced'):
                # Upstream selects AMP internally; bypass that one seam so the
                # requested precision describes actual network arithmetic.
                with torch.autocast(device_type=image.device.type, enabled=False):
                    image = image.to(dtype=precision)
                    extrinsics = extrinsics.to(dtype=precision) if extrinsics is not None else None
                    intrinsics = intrinsics.to(dtype=precision) if intrinsics is not None else None
                    return inner.model(image, extrinsics, intrinsics, export_feat_layers or [],
                                       infer_gs, use_ray_pose, ref_view_strategy)
        model = ExplicitPrecisionDA3(model_name=self.model_name)
        # Upstream checkpoint has nn.Identity in levels 1..3 of output_conv2_aux
        nn_module = getattr(torch, "nn", None)
        if nn_module is not None and hasattr(model, "model") and hasattr(getattr(model, "model", None), "head"):
            scratch = getattr(model.model.head, "scratch", None)
            if scratch is not None and hasattr(scratch, "output_conv2_aux"):
                for i in range(1, len(scratch.output_conv2_aux)):
                    scratch.output_conv2_aux[i][2] = nn_module.Identity()
        state = load_file(str(self.weights_dir / 'model.safetensors'), device='cpu')
        validate_real_checkpoint_load(model, state)
        del state
        model.to(device=torch.device(self.device), dtype=precision)
        model.eval()
        self.model = model

    def close(self):
        """Release owned references; worker must measure real RSS recovery."""
        import gc
        import torch
        if hasattr(self, 'model'):
            del self.model
        gc.collect()
        if self.device == 'mps':
            torch.mps.synchronize()
            torch.mps.empty_cache()

    def process_keyframes(self, images: Sequence, timestamps_s=None, world_key=None,
                          partition='development', output_dir=None, process_res=504):
        import numpy as np
        from PIL import Image
        if partition not in ('train', 'development'):
            raise ValueError('final/unknown partitions unavailable through this adapter')
        if not isinstance(world_key, str) or not world_key.strip():
            raise ValueError('explicit world/source identity required')
        if not images or not isinstance(process_res, int) or isinstance(process_res, bool) or process_res <= 0:
            raise ValueError('nonempty images and positive resolution required')
        if output_dir is not None and Path(output_dir).exists():
            raise ValueError('output already exists; refusing before model work')
        timestamps = validate_timestamps(timestamps_s, len(images))
        frames, identities = [], []
        for image in images:
            if isinstance(image, str):
                with Image.open(image) as opened:
                    frame = opened.convert('RGB')
            elif isinstance(image, np.ndarray):
                if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
                    raise ValueError('array inputs must be RGB uint8; no implicit range conversion')
                frame = Image.fromarray(image)
            elif isinstance(image, Image.Image):
                frame = image.convert('RGB')
            else:
                raise ValueError('unsupported image input')
            frames.append(frame)
            identities.append({'width': frame.width, 'height': frame.height,
                               'rgb_sha256': hashlib.sha256(frame.tobytes()).hexdigest()})
        prediction = self.model.inference(frames, process_res=process_res, export_format='mini_npz')
        arrays = checked_predictions(prediction, len(frames))
        key_material = {
            'teacher': {'teacher_id': self.model_name, 'variant': self.variant,
                        'revision': self.manifest['revision'], 'weights': self.manifest['files'],
                        'adapter_sha256': digest(Path(__file__)),
                        'upstream_files_sha256': json.loads(self._source_bytes)['upstream_files_sha256'],
                        'package_versions': json.loads(self._source_bytes)['package_versions'],
                        'runtime': {'device': self.device, 'compute_dtype': self.dtype}},
            'preprocess': {'resolution': process_res, 'frames': len(frames),
                           'normalization': 'upstream_input_processor'},
            'input': {'media_type': 'image/raw-rgb8', 'frames': identities, 'timestamps_s': timestamps},
        }
        key = hashlib.sha256(canonical(key_material)).hexdigest()
        receipt = {'record_type': 'teacher_prediction_candidate', 'cache_key': key,
                   'key_material': key_material, 'world_key': world_key, 'partition': partition,
                   'source_type': 'teacher_feature', 'registered_cache_entry': False,
                   'coordinate_frame': {'camera_convention': 'opencv', 'extrinsics': 'world_to_camera',
                                        'scale': 'up_to_scale', 'to_world': None},
                   'reproducibility': 'unverified', 'files': [],
                   'note': 'Not an admitted cache v2/v2.1 entry; source binding/admission belong to the project cache gateway.'}
        if output_dir is not None:
            dest = Path(output_dir)
            if dest.exists():
                raise ValueError('output must be a new directory; never overwrite prior evidence')
            dest.mkdir(parents=True)
            from safetensors.numpy import save_file
            tensors = {'camera_pose': arrays['extrinsics'][:, :3, :4], 'intrinsics': arrays['intrinsics'],
                       'depth': arrays['depth'], 'confidence': arrays['conf']}
            tensor_file = dest / 'prediction.safetensors'
            save_file(tensors, str(tensor_file))
            receipt['files'] = [{'name': tensor_file.name, 'sha256': digest(tensor_file), 'bytes': tensor_file.stat().st_size}]
            (dest / 'candidate.json').write_bytes(canonical(receipt) + b'\n')
        return {'depth': arrays['depth'], 'confidence': arrays['conf'],
                'extrinsics': arrays['extrinsics'], 'pose_3x4': arrays['extrinsics'][:, :3, :4],
                'intrinsics': arrays['intrinsics'], 'cache_key': key, 'key_material': key_material,
                'prediction_record': receipt}

if __name__ == '__main__':
    raise SystemExit('Library only; real inference requires the approved project CLI worker.')
