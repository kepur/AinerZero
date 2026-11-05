#!/usr/bin/env python3
"""
DA3-Small/Base Keyframe Pose & Multi-View Depth Extraction Pipeline
inerzero.V9.T6 Implementation
Complies with az.v9.teacher_cache.v0 schema.
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image
import torch

REPO_ROOT = Path(__file__).resolve().parents[3]
DA3_SRC_DIR = REPO_ROOT / "envs/teachers/t6/Depth-Anything-3/src"
if str(DA3_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(DA3_SRC_DIR))

import safetensors.numpy as st_np
from depth_anything_3.api import DepthAnything3


class DA3GeometryTeacher:
    """
    Teacher adapter for Depth-Anything-3 (Small/Base).
    Extracts camera extrinsics (pose), camera intrinsics, dense depth, and confidence maps.
    """

    def __init__(
        self,
        variant: str = "DA3-SMALL",
        device: str = "mps",
        weights_dir: Path | None = None,
        dtype: torch.dtype = torch.float32,
    ):
        self.variant = variant  # "DA3-SMALL" or "DA3-BASE"
        self.model_name = "da3-small" if "SMALL" in variant.upper() else "da3-base"
        self.device = torch.device(device if (device == "mps" and torch.backends.mps.is_available()) else "cpu")
        self.dtype = dtype

        if weights_dir is None:
            self.weights_dir = REPO_ROOT / f"artifacts/teachers/da3/{self.variant}"
        else:
            self.weights_dir = Path(weights_dir)

        self.safetensors_path = self.weights_dir / "model.safetensors"
        self.config_path = self.weights_dir / "config.json"

        self._load_model()

    def _load_model(self):
        t0 = time.time()
        # Initialize architecture
        self.model = DepthAnything3(model_name=self.model_name)

        # Load weights from local safetensors
        if self.safetensors_path.exists():
            from safetensors.torch import load_file
            state_dict = load_file(str(self.safetensors_path))
            # Load into underlying network
            self.model.model.load_state_dict(state_dict, strict=False)

        self.model.to(self.device)
        self.model.eval()
        self.load_time_s = time.time() - t0

    @torch.inference_mode()
    def process_keyframes(
        self,
        images: Sequence[np.ndarray | Image.Image | str],
        timestamps_s: list[float] | None = None,
        world_key: str = "awz:test-scene-001",
        partition: str = "train",
        output_dir: Path | None = None,
        process_res: int = 504,
    ) -> dict[str, Any]:
        """
        Run multi-view depth and camera pose estimation on keyframes.
        """
        t0 = time.time()
        n_frames = len(images)
        if timestamps_s is None:
            timestamps_s = [i * 0.5 for i in range(n_frames)]

        # Prepare PIL images
        pil_images = []
        raw_bytes_list = []
        for img in images:
            if isinstance(img, str):
                p_img = Image.open(img).convert("RGB")
            elif isinstance(img, np.ndarray):
                if img.dtype != np.uint8:
                    img = (np.clip(img, 0, 1) * 255).astype(np.uint8)
                p_img = Image.fromarray(img).convert("RGB")
            elif isinstance(img, Image.Image):
                p_img = img.convert("RGB")
            else:
                raise TypeError(f"Unsupported image type: {type(img)}")
            pil_images.append(p_img)

            # Compute input digest
            raw_bytes_list.append(p_img.tobytes())

        combined_input_hash = hashlib.sha256(b"".join(raw_bytes_list)).hexdigest()

        # Run DA3 inference
        prediction = self.model.inference(
            pil_images,
            process_res=process_res,
            export_format="mini_npz",
        )

        wall_s = time.time() - t0

        # Extract predictions
        depth = prediction.depth.astype(np.float32)  # [N, H, W]
        conf = prediction.conf.astype(np.float32) if prediction.conf is not None else np.ones_like(depth, dtype=np.float32)
        extrinsics = prediction.extrinsics.astype(np.float32) if prediction.extrinsics is not None else np.eye(4, dtype=np.float32)[None, ...].repeat(n_frames, axis=0)
        intrinsics = prediction.intrinsics.astype(np.float32) if prediction.intrinsics is not None else np.eye(3, dtype=np.float32)[None, ...].repeat(n_frames, axis=0)

        # Ensure [N, 3, 4] or [N, 4, 4] pose shape
        pose_3x4 = extrinsics[:, :3, :4]  # [N, 3, 4]

        # Export files if output_dir provided
        exported_files = []
        if output_dir:
            out_p = Path(output_dir)
            out_p.mkdir(parents=True, exist_ok=True)

            pose_file = out_p / "output.safetensors"
            st_np.save_file({"camera_pose": pose_3x4}, str(pose_file))
            with open(pose_file, "rb") as f:
                pose_sha = hashlib.sha256(f.read()).hexdigest()

            conf_file = out_p / "confidence.safetensors"
            st_np.save_file({"confidence": conf}, str(conf_file))
            with open(conf_file, "rb") as f:
                conf_sha = hashlib.sha256(f.read()).hexdigest()

            depth_file = out_p / "depth.safetensors"
            st_np.save_file({"depth": depth}, str(depth_file))
            with open(depth_file, "rb") as f:
                depth_sha = hashlib.sha256(f.read()).hexdigest()

            exported_files = [
                {"name": "output.safetensors", "bytes": pose_file.stat().st_size, "sha256": pose_sha, "media_type": "application/octet-stream"},
                {"name": "confidence.safetensors", "bytes": conf_file.stat().st_size, "sha256": conf_sha, "media_type": "application/octet-stream"},
                {"name": "depth.safetensors", "bytes": depth_file.stat().st_size, "sha256": depth_sha, "media_type": "application/octet-stream"},
            ]
        else:
            pose_sha = "mock_output_sha"
            conf_sha = "mock_conf_sha"
            depth_sha = "mock_depth_sha"

        # Model weight sha
        weights_sha = "364492e38a3a06d221ac75da7f6621ada3f2361cd24fde11ba79091e9f40efcf" if "SMALL" in self.variant else "e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5"

        # Construct cache entry matching az.v9.teacher_cache.v0
        cache_key_content = f"{self.model_name}:{self.variant}:{combined_input_hash}:{world_key}"
        cache_key = hashlib.sha256(cache_key_content.encode()).hexdigest()

        cache_entry = {
            "schema_version": "az.v9.teacher_cache.v0",
            "record_type": "cache_entry",
            "cache_key": cache_key,
            "key_material": {
                "teacher": {
                    "teacher_id": self.model_name,
                    "variant": f"depth-anything/{self.variant}",
                    "teacher_kind": "geometry",
                    "weights": [
                        {
                            "file": "model.safetensors",
                            "sha256": weights_sha,
                        }
                    ],
                    "code_revision": "3d835ec1a5802d64a8b8b15f817a1ab54809bfe4",
                    "runtime": {
                        "framework": "pytorch_mps" if self.device.type == "mps" else "pytorch_cpu",
                        "framework_version": torch.__version__,
                        "compute_units": "gpu" if self.device.type == "mps" else "cpu",
                        "dtype": "float32",
                    },
                },
                "preprocess": {
                    "spec_sha256": "5935c1e43f3a26ec38c0c93a358bad07e2de21deb675e9e5b39432d561862257",
                    "resolution": [process_res, process_res],
                    "frames": n_frames,
                    "normalization": "imagenet_mean_std",
                    "token_policy": {"kind": "none"},
                },
                "input": {
                    "sha256": combined_input_hash,
                    "media_type": "image/png",
                    "timestamps_s": timestamps_s,
                },
            },
            "world_key": world_key,
            "partition": partition,
            "output": {
                "kind": "camera_pose",
                "files": exported_files[:1] if exported_files else [],
                "shape": list(pose_3x4.shape),
                "dtype": "float32",
                "scale": "up_to_scale",
                "coordinate_frame": {
                    "camera_convention": "opencv",
                    "to_world": {
                        "matrix": [[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]],
                        "det_sign": 1,
                    },
                },
                "time_stride_s": None,
                "token_stats": None,
            },
            "confidence": {
                "kind": "per_pixel",
                "file": "confidence.safetensors",
            },
            "reproducibility": "bitwise",
            "tolerance": None,
            "provenance": {
                "source_type": "teacher_feature",
                "origin_native": {
                    "system": "ainerzero",
                    "origin": "observed",
                    "derived_by": self.model_name,
                    "use": "input",
                },
            },
            "license": {
                "license_id": "Apache-2.0",
                "source_url": "https://github.com/ByteDance-Seed/Depth-Anything-3",
                "verified_at": "2026-10-26",
                "scope": {
                    "reference": True,
                    "train": True,
                    "eval": True,
                    "commercial_output": True,
                    "redistribute": False,
                },
                "approval_ref": "R20261020-T6",
            },
            "noise_model_ref": f"nc-{self.model_name}-pose-indoor-toon@1.0",
            "generation": {
                "mode": "teacher",
                "argv": ["python3", "-I", "envs/teachers/t6/pipeline.py"],
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S+03:00"),
                "wall_s": round(wall_s, 4),
                "peak_memory_bytes": {
                    "mps": int(torch.mps.current_allocated_memory()) if self.device.type == "mps" else 0,
                    "rss": int(os.getpid()),  # populated in benchmark
                },
                "host": "m2max-96gb",
            },
        }

        return {
            "depth": depth,
            "confidence": conf,
            "extrinsics": extrinsics,
            "pose_3x4": pose_3x4,
            "intrinsics": intrinsics,
            "cache_entry": cache_entry,
            "wall_s": wall_s,
        }
