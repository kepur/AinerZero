"""生成 teacher_cache.v0 的正反例（ainerzero.V9.T1）。

用法：python3 -I reports/V9-T1/make_examples.py <repo_root>
只写 contracts/v9/examples/teacher_cache/{valid,invalid}/。示例里的哈希是确定性的占位值，
不对应任何真实文件；cache_key 按 §2.1 由 key_material 的规范 JSON 算出。
"""
import copy
import hashlib
import json
import sys
from pathlib import Path


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def h(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def cache_key(km):
    return hashlib.sha256(canon(km)).hexdigest()


LIC_VJEPA = {
    "license_id": "MIT",
    "source_url": "https://huggingface.co/dgrauet/vjepa-2.1-vitl-mlx",
    "verified_at": "2026-10-16",
    "scope": {"reference": True, "train": True, "eval": True, "commercial_output": True, "redistribute": False},
    "approval_ref": "R20261016-T4",
}
LIC_DA3 = {
    "license_id": "Apache-2.0",
    "source_url": "https://github.com/ByteDance-Seed/Depth-Anything-3",
    "verified_at": "2026-10-16",
    "scope": {"reference": True, "train": True, "eval": True, "commercial_output": True, "redistribute": False},
    "approval_ref": "R20261016-T6-placeholder",
}

KM_VJEPA = {
    "teacher": {
        "teacher_id": "vjepa2.1-vitl",
        "variant": "dgrauet/vjepa-2.1-vitl-mlx",
        "teacher_kind": "feature",
        "weights": [
            {"file": "encoder.safetensors", "sha256": h("example:encoder")},
            {"file": "predictor.safetensors", "sha256": h("example:predictor")},
        ],
        "code_revision": "0000000example",
        "runtime": {"framework": "mlx", "framework_version": "0.32.4", "compute_units": "gpu", "dtype": "float32"},
    },
    "preprocess": {
        "spec_sha256": h("example:vjepa-preprocess"),
        "resolution": [384, 384],
        "frames": 16,
        "normalization": "imagenet_mean_std",
        "token_policy": {"kind": "none"},
    },
    "input": {
        "sha256": h("example:clip-0001"),
        "media_type": "video/x-raw-rgb24",
        "timestamps_s": [round(i / 24, 6) for i in range(16)],
    },
}


def gen(mode="teacher"):
    return {
        "mode": mode,
        "argv": ["python3", "-I", "envs/teachers/t4/extract.py", "--example"],
        "started_at": "2026-10-16T03:00:00+03:00",
        "wall_s": 1.25,
        "peak_memory_bytes": {"mlx": 4_000_000_000, "rss": 6_000_000_000},
        "host": "m2max-96gb",
    }


def vjepa_entry(km=None):
    km = copy.deepcopy(km or KM_VJEPA)
    rlt = km["preprocess"]["token_policy"]["kind"] == "rlt"
    return {
        "schema_version": "az.v9.teacher_cache.v0",
        "record_type": "cache_entry",
        "cache_key": cache_key(km),
        "key_material": km,
        "world_key": "synthetic:seed-0001",
        "partition": "development",
        "output": {
            "kind": "video_latent",
            "files": [{"name": "output.safetensors", "bytes": 8_388_608, "sha256": h("example:vjepa-out"),
                       "media_type": "application/octet-stream"}],
            "shape": [8, 576, 1024],
            "dtype": "float16",
            "scale": "not_applicable",
            "coordinate_frame": {"camera_convention": "none", "to_world": None},
            "time_stride_s": round(2 / 24, 6),
            "token_stats": {"kept": 2304, "total": 4608, "run_length_hist": {"1": 1800, "2": 504}} if rlt else None,
        },
        "confidence": {"kind": "none", "file": None},
        "reproducibility": "numeric",
        "tolerance": {"metric": "cosine_min", "value": 0.9999},
        "provenance": {"source_type": "teacher_feature",
                       "origin_native": {"system": "ainerzero", "origin": "observed",
                                         "derived_by": km["teacher"]["teacher_id"], "use": "input"}},
        "license": copy.deepcopy(LIC_VJEPA),
        "noise_model_ref": None,
        "generation": gen(),
    }


def da3_entry():
    km = {
        "teacher": {
            "teacher_id": "da3-small",
            "variant": "depth-anything/DA3-SMALL",
            "teacher_kind": "geometry",
            "weights": [{"file": "model.safetensors", "sha256": h("example:da3-small")}],
            "code_revision": "0000000example",
            "runtime": {"framework": "pytorch_mps", "framework_version": "example", "compute_units": "gpu", "dtype": "float32"},
        },
        "preprocess": {"spec_sha256": h("example:da3-preprocess"), "resolution": [504, 504], "frames": 4,
                       "normalization": "imagenet_mean_std", "token_policy": {"kind": "none"}},
        "input": {"sha256": h("example:keyframes-0001"), "media_type": "image/png", "timestamps_s": [0.0, 0.5, 1.0, 1.5]},
    }
    return {
        "schema_version": "az.v9.teacher_cache.v0",
        "record_type": "cache_entry",
        "cache_key": cache_key(km),
        "key_material": km,
        "world_key": "awz:b5-world-0007",
        "partition": "train",
        "output": {
            "kind": "camera_pose",
            "files": [{"name": "output.safetensors", "bytes": 2048, "sha256": h("example:da3-out"),
                       "media_type": "application/octet-stream"}],
            "shape": [4, 3, 4],
            "dtype": "float32",
            "scale": "up_to_scale",
            "coordinate_frame": {"camera_convention": "opencv",
                                 "to_world": {"matrix": [[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]], "det_sign": 1}},
            "time_stride_s": None,
            "token_stats": None,
        },
        "confidence": {"kind": "per_pixel", "file": "confidence.safetensors"},
        "reproducibility": "bitwise",
        "tolerance": None,
        "provenance": {"source_type": "teacher_feature",
                       "origin_native": {"system": "ainerzero", "origin": "observed", "derived_by": "da3-small", "use": "input"}},
        "license": copy.deepcopy(LIC_DA3),
        "noise_model_ref": "nc-da3-small-pose-indoor-toon@1.0",
        "generation": gen(),
    }


def nc_pose():
    return {
        "schema_version": "az.v9.teacher_cache.v0",
        "record_type": "noise_calibration",
        "calibration_id": "nc-da3-small-pose-indoor-toon",
        "version": "1.0",
        "teacher_family": {"teacher_id": "da3-small", "weights_sha256": [h("example:da3-small")],
                           "preprocess_spec_sha256": h("example:da3-preprocess")},
        "quantity": "camera_pose",
        "scene_layer": {"setting": "indoor", "lighting": "key_fill", "shading": "toon", "camera_motion": "moving",
                        "held_frame_ratio_bin": "0.0-0.5", "occlusion_bin": "low"},
        "data": {"partition": "development", "world_list_sha256": h("example:world-list"), "n_worlds": 32, "n_samples": 840},
        "alignment": {"kind": "sim3", "params_recorded": True},
        "model": {"family": "gaussian", "dim": 6, "bias": [0, 0, 0, 0, 0, 0],
                  "cov": [[1e-4 if i == j else 0.0 for j in range(6)] for i in range(6)], "dof": None, "table_ref": None},
        "validation": {"nees_coverage_95": 0.94, "n_holdout_worlds": 8},
        "status": "registered",
    }


def nc_mask():
    return {
        "schema_version": "az.v9.teacher_cache.v0",
        "record_type": "noise_calibration",
        "calibration_id": "nc-sam2-1-mask-outdoor-toon",
        "version": "0.1",
        "teacher_family": {"teacher_id": "sam2.1-small", "weights_sha256": [h("example:sam2")],
                           "preprocess_spec_sha256": h("example:sam2-preprocess")},
        "quantity": "object_mask",
        "scene_layer": {"setting": "outdoor", "lighting": "sun", "shading": "toon", "camera_motion": "static",
                        "held_frame_ratio_bin": "0.5-1.0", "occlusion_bin": "high"},
        "data": {"partition": "development", "world_list_sha256": h("example:world-list-2"), "n_worlds": 12, "n_samples": 300},
        "alignment": {"kind": "none", "params_recorded": True},
        "model": {"family": "association_stats", "dim": 1, "bias": None, "cov": None, "dof": None,
                  "table_ref": "reports/V9-T10/association_stats.json"},
        "validation": {"nees_coverage_95": None, "n_holdout_worlds": 0},
        "status": "insufficient",
    }


def set_path(obj, path, value):
    cur = obj
    for k in path[:-1]:
        cur = cur[k]
    if value is DELETE:
        del cur[path[-1]]
    else:
        cur[path[-1]] = value


DELETE = object()

# (文件名, 基础记录构造, [(路径, 新值)], 期望违反的 schema 关键字, 期望错误路径片段)
INVALID = [
    ("final_partition", vjepa_entry, [(["partition"], "final")], "enum", "partition"),
    ("frame_index_instead_of_time", vjepa_entry,
     [(["key_material", "input", "timestamps_s"], DELETE), (["key_material", "input", "frame_indices"], [0, 1, 2])],
     "required", "input"),
    ("empty_weights", vjepa_entry, [(["key_material", "teacher", "weights"], [])], "minItems", "weights"),
    ("teacher_claim_source", vjepa_entry, [(["provenance", "source_type"], "teacher_claim")], "const", "source_type"),
    ("feature_with_metric_scale", vjepa_entry, [(["output", "scale"], "metric")], "const", "scale"),
    ("geometry_scale_not_applicable", da3_entry, [(["output", "scale"], "not_applicable")], "enum", "scale"),
    ("rlt_without_tau", vjepa_entry,
     [(["key_material", "preprocess", "token_policy"], {"kind": "rlt", "norm": "linf", "patch": 16})], "oneOf", "token_policy"),
    ("rlt_without_token_stats", vjepa_entry,
     [(["key_material", "preprocess", "token_policy"], {"kind": "rlt", "tau": 0.02, "norm": "linf", "patch": 16})],
     "type", "token_stats"),
    ("numeric_without_tolerance", vjepa_entry, [(["tolerance"], None)], "type", "tolerance"),
    ("feature_with_noise_model", vjepa_entry, [(["noise_model_ref"], "nc-x@1.0")], "type", "noise_model_ref"),
    ("det_sign_zero", da3_entry, [(["output", "coordinate_frame", "to_world", "det_sign"], 0)], "enum", "det_sign"),
    ("license_plain_http", vjepa_entry, [(["license", "source_url"], "http://example.org")], "pattern", "source_url"),
    ("uppercase_sha", vjepa_entry, [(["cache_key"], "A" * 64)], "pattern", "cache_key"),
    ("license_scope_missing_item", vjepa_entry, [(["license", "scope", "redistribute"], DELETE)], "required", "scope"),
    ("calibration_final_partition", nc_pose, [(["data", "partition"], "final")], "const", "partition"),
    ("calibration_registered_low_coverage", nc_pose, [(["validation", "nees_coverage_95"], 0.80)], "minimum", "nees_coverage_95"),
    ("calibration_registered_few_worlds", nc_pose, [(["data", "n_worlds"], 10)], "minimum", "n_worlds"),
    ("calibration_mask_as_gaussian", nc_mask, [(["model", "family"], "gaussian"), (["model", "cov"], [[1.0]])], "const", "family"),
    ("calibration_student_t_without_dof", nc_pose, [(["model", "family"], "student_t")], "type", "dof"),
]

# 结构合法、但跨字段语义错误：由读写代码（T2）拒绝，checker 用同样规则核对
SEMANTIC = [
    ("semantic_wrong_cache_key", vjepa_entry, [(["key_material", "preprocess", "frames"], 8)], "cache_key_mismatch"),
    ("semantic_derived_by_mismatch", vjepa_entry, [(["provenance", "origin_native", "derived_by"], "other-teacher")], "derived_by_mismatch"),
    ("semantic_unapproved_teacher", vjepa_entry, [(["license", "approval_ref"], None)], "unapproved"),
    ("semantic_timestamps_decreasing", vjepa_entry, [(["key_material", "input", "timestamps_s"], [0.5, 0.25] + [1.0] * 14)],
     "timestamps_not_monotonic"),
]


def main(root):
    base = Path(root) / "contracts/v9/examples/teacher_cache"
    valid = {
        "vjepa21_cache_entry": vjepa_entry(),
        "vjepa21_rlt_cache_entry": vjepa_entry({**copy.deepcopy(KM_VJEPA), "preprocess": {
            **copy.deepcopy(KM_VJEPA["preprocess"]), "token_policy": {"kind": "rlt", "tau": 0.02, "norm": "linf", "patch": 16}}}),
        "da3_small_pose_cache_entry": da3_entry(),
        "nc_da3_small_pose_registered": nc_pose(),
        "nc_sam2_mask_insufficient": nc_mask(),
    }
    manifest = {"valid": [], "invalid": [], "semantic": []}
    for name, rec in valid.items():
        (base / "valid" / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["valid"].append(name)
    for name, make, edits, keyword, path_part in INVALID:
        rec = make()
        for p, v in edits:
            set_path(rec, p, v)
        (base / "invalid" / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["invalid"].append({"name": name, "keyword": keyword, "path_part": path_part})
    for name, make, edits, reason in SEMANTIC:
        rec = make()
        for p, v in edits:
            set_path(rec, p, v)
        (base / "invalid" / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["semantic"].append({"name": name, "reason": reason})
    (base / "EXPECTATIONS.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"valid={len(manifest['valid'])} invalid={len(manifest['invalid'])} semantic={len(manifest['semantic'])}")


if __name__ == "__main__":
    main(sys.argv[1])
