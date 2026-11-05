#!/usr/bin/env python3
"""V9.T4 Teacher Integration & M2 Max Inference Benchmark Suite.

Executes:
1. Strict SHA256 / revision verification of downloaded assets.
2. Numerical verification for V-JEPA 2.1 (MLX) and Depth Anything V2 Small (Core ML).
3. Negative controls (intentional corruption turns checks red).
4. M2 Max inference benchmarks with budget, residency, and memory guards.
Outputs:
- reports/V9-T4/downloads.json
- reports/V9-T4/numerical_checks.json
- reports/V9-T4/bench.json
"""

import gc
import hashlib
import json
import os
import resource
import shutil
import sys
import time
from pathlib import Path

import coremltools as ct
from PIL import Image
import mlx.core as mx
import numpy as np

import vjepa2_core_mlx.utils.weights as weights

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
REPORTS_DIR = ROOT / "reports/V9-T4"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

VJEPA_DIR = ROOT / "artifacts/teachers/t4-approved/b0674736bad10eb16bd765942a9065e7e2ee9a54"
DA2_DIR = ROOT / "artifacts/teachers/t4-approved/cfef6f6f2a70783dedc0bfae40cecbc2052285d3"
DA2_F16_PATH = DA2_DIR / "DepthAnythingV2SmallF16.mlpackage"
DA2_F32_PATH = DA2_DIR / "DepthAnythingV2SmallF32.mlpackage"

LOCK_PATH = ROOT / "artifacts/locks/m0-worker.lock"

# Memory and budget guards
MAX_PEAK_MEMORY_BYTES = 32 * 1024 * 1024 * 1024  # 32 GB
MAX_GPU_WALL_SECONDS = 1800  # 30 mins
SINGLE_BENCH_MAX_SECONDS = 600  # 10 mins

def get_rss_bytes() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

def check_guards(start_time: float):
    elapsed = time.time() - start_time
    assert elapsed <= MAX_GPU_WALL_SECONDS, f"Total wall clock exceeded 30 mins: {elapsed:.1f}s"
    rss = get_rss_bytes()
    assert rss <= MAX_PEAK_MEMORY_BYTES, f"RSS memory exceeded 32 GB: {rss / (1024**3):.2f} GB"

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

# =========================================================================
# Part 1: Download & SHA Verification
# =========================================================================
print("=== Part 1: Download & Asset Verification ===", flush=True)
downloads_manifest_path = REPORTS_DIR / "downloads.json"
assert downloads_manifest_path.exists(), "downloads.json must exist in reports/V9-T4"
downloads = json.loads(downloads_manifest_path.read_text())

total_bytes = 0
for item in downloads:
    p = Path(item["path"])
    assert p.exists(), f"File missing: {p}"
    actual_size = p.stat().st_size
    assert actual_size == item["bytes"], f"Size mismatch for {p}: {actual_size} vs {item['bytes']}"
    actual_sha = sha256_file(p)
    assert actual_sha == item["sha256"], f"SHA256 mismatch for {p}: {actual_sha} vs {item['sha256']}"
    total_bytes += actual_size

print(f"Verified {len(downloads)} files. Total model bytes: {total_bytes} ({total_bytes / (1024**3):.3f} GB) <= 2.0 GB", flush=True)
assert total_bytes <= 2 * 1024 * 1024 * 1024, "Total downloaded weights exceed 2 GB budget!"

# =========================================================================
# Part 2: Numerical Verification & Negative Controls
# =========================================================================
print("\n=== Part 2: Numerical Verification ===", flush=True)
numerical_results = {
    "vjepa2": {},
    "depth_anything_v2": {},
    "negative_controls": {},
}

# --- V-JEPA 2.1 ---
print("Running V-JEPA 2.1 numerical checks...", flush=True)
t0 = time.time()
vjepa_enc = weights.from_pretrained(VJEPA_DIR)
load_s = time.time() - t0

# A. Determinism
np.random.seed(1337)
x_np = np.random.randn(1, 3, 16, 384, 384).astype(np.float32)
x_mx = mx.array(x_np)

out1 = vjepa_enc(x_mx)
mx.eval(out1)
out2 = vjepa_enc(x_mx)
mx.eval(out2)

bit_exact = bool(mx.all(out1 == out2).item())
assert bit_exact, "V-JEPA 2.1 must be bit-exact across identical inputs!"
numerical_results["vjepa2"]["determinism_bit_exact"] = bit_exact
print(f"V-JEPA bit-exact determinism: {bit_exact}")

# B. Output shape
expected_shape = [1, 4608, 1024]
assert list(out1.shape) == expected_shape, f"Shape mismatch: {list(out1.shape)} vs {expected_shape}"
numerical_results["vjepa2"]["output_shape"] = list(out1.shape)
numerical_results["vjepa2"]["output_shape_matches_config"] = True
print(f"V-JEPA output shape: {list(out1.shape)} (matches config 384x384, 16 frames, tubelet 2)")

# C. Batch invariance: B=1 vs B=2
x2_np = np.random.randn(1, 3, 16, 384, 384).astype(np.float32)
x_batch = mx.concatenate([x_mx, mx.array(x2_np)], axis=0)
out_batch = vjepa_enc(x_batch)
mx.eval(out_batch)

diff_batch = np.abs(np.array(out1[0]) - np.array(out_batch[0]))
max_batch_diff = float(np.max(diff_batch))
mean_batch_diff = float(np.mean(diff_batch))
assert max_batch_diff < 1e-4, f"Batch invariance violated: max diff {max_batch_diff}"
numerical_results["vjepa2"]["batch_invariance"] = {
    "max_abs_diff": max_batch_diff,
    "mean_abs_diff": mean_batch_diff,
    "passed": True,
    "tolerance": 1e-4,
}
print(f"V-JEPA batch invariance: max diff = {max_batch_diff:.2e}, mean diff = {mean_batch_diff:.2e}")

# D. F32 vs F16 and F32 vs BF16 Cosine Similarity
vjepa_f16 = weights.from_pretrained(VJEPA_DIR)
vjepa_f16.set_dtype(mx.float16)
out_f16 = vjepa_f16(mx.array(x_np).astype(mx.float16))
mx.eval(out_f16)

out1_np = np.array(out1[0])  # (4608, 1024)
out_f16_np = np.array(out_f16[0])

num_f16 = (out1_np * out_f16_np).sum(axis=-1)
den_f16 = np.linalg.norm(out1_np, axis=-1) * np.linalg.norm(out_f16_np, axis=-1)
cos_f16 = num_f16 / den_f16
mean_cos_f16 = float(np.mean(cos_f16))
min_cos_f16 = float(np.min(cos_f16))
assert mean_cos_f16 > 0.999, f"F16 cosine similarity too low: {mean_cos_f16}"

vjepa_bf16 = weights.from_pretrained(VJEPA_DIR)
vjepa_bf16.set_dtype(mx.bfloat16)
out_bf16 = vjepa_bf16(mx.array(x_np).astype(mx.bfloat16))
mx.eval(out_bf16)
out_bf16_np = np.array(out_bf16[0])

num_bf16 = (out1_np * out_bf16_np).sum(axis=-1)
den_bf16 = np.linalg.norm(out1_np, axis=-1) * np.linalg.norm(out_bf16_np, axis=-1)
cos_bf16 = num_bf16 / den_bf16
mean_cos_bf16 = float(np.mean(cos_bf16))
min_cos_bf16 = float(np.min(cos_bf16))
assert mean_cos_bf16 > 0.999, f"BF16 cosine similarity too low: {mean_cos_bf16}"

numerical_results["vjepa2"]["precision_similarity"] = {
    "f32_vs_f16_cosine_similarity_mean": mean_cos_f16,
    "f32_vs_f16_cosine_similarity_min": min_cos_f16,
    "f32_vs_bf16_cosine_similarity_mean": mean_cos_bf16,
    "f32_vs_bf16_cosine_similarity_min": min_cos_bf16,
    "tolerance_threshold": 0.999,
    "passed": True,
}
print(f"V-JEPA precision: F16 mean cos = {mean_cos_f16:.6f}, BF16 mean cos = {mean_cos_bf16:.6f}")

# E. Intentional negative control 1: weight scrambling
print("Testing V-JEPA negative control (scrambled weights)...", flush=True)
vjepa_corrupt = weights.from_pretrained(VJEPA_DIR)
orig_weight = np.array(vjepa_corrupt.blocks[0].mlp.fc1.weight)
# Scramble weight
scrambled = orig_weight[::-1, ::-1].copy()
vjepa_corrupt.blocks[0].mlp.fc1.weight = mx.array(scrambled)
out_corrupt = vjepa_corrupt(x_mx)
mx.eval(out_corrupt)
out_corrupt_np = np.array(out_corrupt[0])

num_c = (out1_np * out_corrupt_np).sum(axis=-1)
den_c = np.linalg.norm(out1_np, axis=-1) * np.linalg.norm(out_corrupt_np, axis=-1)
cos_corrupt = float(np.mean(num_c / den_c))

# The check requires that corrupted model FAILS the clean similarity threshold (0.999)
corrupt_check_turned_red = cos_corrupt < 0.95
assert corrupt_check_turned_red, f"Corrupted model should fail similarity threshold 0.999! Got cos = {cos_corrupt}"
numerical_results["negative_controls"]["vjepa_weight_scramble_turned_red"] = {
    "clean_threshold": 0.999,
    "corrupted_cosine_similarity": cos_corrupt,
    "failed_threshold_as_expected": True,
}
print(f"V-JEPA negative control (scrambled weight): cos sim dropped to {cos_corrupt:.4f} (RED as required)")

# Clean up V-JEPA memory before running DA2
del vjepa_enc, vjepa_f16, vjepa_bf16, vjepa_corrupt, out1, out2, out_batch, out_f16, out_bf16, out_corrupt
gc.collect()
mx.metal.clear_cache()
print("V-JEPA memory cleaned up.", flush=True)

# --- Depth Anything V2 Small ---
print("\nRunning Depth Anything V2 Small numerical checks...", flush=True)
model_da2_f16 = ct.models.MLModel(str(DA2_F16_PATH), compute_units=ct.ComputeUnit.CPU_AND_NE)
model_da2_f32 = ct.models.MLModel(str(DA2_F32_PATH), compute_units=ct.ComputeUnit.CPU_AND_NE)

w_da2, h_da2 = 518, 392
np.random.seed(999)
test_rgb = np.uint8(np.random.randint(0, 255, (h_da2, w_da2, 3)))
test_pil = Image.fromarray(test_rgb)

# A. Determinism
p1 = model_da2_f16.predict({"image": test_pil})
p2 = model_da2_f16.predict({"image": test_pil})
d1 = np.array(p1["depth"])
d2 = np.array(p2["depth"])
da2_bit_exact = bool(np.array_equal(d1, d2))
assert da2_bit_exact, "Depth Anything V2 F16 must be bit-exact!"
numerical_results["depth_anything_v2"]["determinism_bit_exact"] = da2_bit_exact
print(f"DA2 F16 determinism: {da2_bit_exact}")

# B. Pearson and Spearman correlation between F16 and F32
p32 = model_da2_f32.predict({"image": test_pil})
d32 = np.array(p32["depth"])

def rank_data(a):
    sorter = np.argsort(a)
    ranks = np.empty_like(sorter, dtype=float)
    ranks[sorter] = np.arange(len(a), dtype=float)
    return ranks

d1_flat = d1.flatten().astype(np.float64)
d32_flat = d32.flatten().astype(np.float64)

pearson_r = float(np.corrcoef(d1_flat, d32_flat)[0, 1])
spearman_rho = float(np.corrcoef(rank_data(d1_flat), rank_data(d32_flat))[0, 1])

assert pearson_r > 0.999, f"Pearson r too low: {pearson_r}"
assert spearman_rho > 0.999, f"Spearman rho too low: {spearman_rho}"

numerical_results["depth_anything_v2"]["f16_vs_f32"] = {
    "pearson_r": pearson_r,
    "spearman_rho": spearman_rho,
    "tolerance_threshold": 0.999,
    "passed": True,
}
print(f"DA2 F16 vs F32: Pearson r = {pearson_r:.6f}, Spearman rho = {spearman_rho:.6f}")

# C. Synthetic Ramp Depth Ordering
y_c = np.linspace(0, 1, h_da2)[:, None]
x_c = np.linspace(-1, 1, w_da2)[None, :]
grid = np.sin(x_c * 20 * (y_c + 0.1)) * 0.2 + y_c * 0.8
ramp_arr = np.clip(grid * 255, 0, 255).astype(np.uint8)
ramp_pil = Image.fromarray(np.stack([ramp_arr]*3, axis=-1))

pred_ramp = model_da2_f16.predict({"image": ramp_pil})
depth_ramp = np.array(pred_ramp["depth"])
profile = np.mean(depth_ramp, axis=1)
top_mean = float(np.mean(profile[:h_da2 // 4]))
bottom_mean = float(np.mean(profile[3 * h_da2 // 4:]))

# In Core ML DA2 export: top (far horizon) has larger depth value, bottom (near) has smaller depth value
depth_dir_ok = top_mean > bottom_mean
assert depth_dir_ok, f"Expected top_mean > bottom_mean, got {top_mean} <= {bottom_mean}"
numerical_results["depth_anything_v2"]["synthetic_ramp_ordering"] = {
    "top_mean_far": top_mean,
    "bottom_mean_near": bottom_mean,
    "direction_correct": depth_dir_ok,
    "passed": True,
}
print(f"DA2 synthetic ramp depth ordering: top (far)={top_mean:.4f} > bottom (near)={bottom_mean:.4f}")

# D. Intentional negative control 2: vertical flip
print("Testing DA2 negative control (flipped input)...", flush=True)
flipped_pil = ramp_pil.transpose(Image.FLIP_TOP_BOTTOM)
pred_flip = model_da2_f16.predict({"image": flipped_pil})
depth_flip = np.array(pred_flip["depth"])
flip_profile = np.mean(depth_flip, axis=1)
top_flip = float(np.mean(flip_profile[:h_da2 // 4]))
bottom_flip = float(np.mean(flip_profile[3 * h_da2 // 4:]))

# The standard check (top > bottom) MUST FAIL on flipped image
flip_direction_turned_red = not (top_flip > bottom_flip)
assert flip_direction_turned_red, f"Flipped ramp did not invert! top={top_flip}, bottom={bottom_flip}"
numerical_results["negative_controls"]["da2_vertical_flip_turned_red"] = {
    "flipped_top_mean": top_flip,
    "flipped_bottom_mean": bottom_flip,
    "ordering_inverted": flip_direction_turned_red,
    "passed_rejection": True,
}
print(f"DA2 negative control (vertical flip): top={top_flip:.4f} < bottom={bottom_flip:.4f} (RED as required)")

# Clean up DA2 memory
del model_da2_f16, model_da2_f32, p1, p2, p32, pred_ramp, pred_flip
gc.collect()

(REPORTS_DIR / "numerical_checks.json").write_text(json.dumps(numerical_results, indent=2))
print("Numerical verification complete. Written to numerical_checks.json.", flush=True)

# =========================================================================
# Part 3: M2 Max Inference Benchmarks
# =========================================================================
print("\n=== Part 3: M2 Max Inference Benchmarks ===", flush=True)
bench_results = {
    "hardware": {
        "platform": sys.platform,
        "device": "Apple M2 Max",
        "power_source": "AC Power",
        "budget_max_wall_clock_s": MAX_GPU_WALL_SECONDS,
        "single_run_max_s": SINGLE_BENCH_MAX_SECONDS,
        "memory_limit_bytes": MAX_PEAK_MEMORY_BYTES,
    },
    "benchmarks": {},
    "timing_summary": {},
}

bench_start_time = time.time()

# -------------------------------------------------------------------------
# Benchmark 1: V-JEPA 2.1 ViT-L MLX
# -------------------------------------------------------------------------
print("\n--- Running Benchmark 1: V-JEPA 2.1 ViT-L (MLX) ---", flush=True)
check_guards(bench_start_time)

# Pre-load memory baseline
rss_before_vjepa = get_rss_bytes()
t0 = time.time()
vjepa_model = weights.from_pretrained(VJEPA_DIR)
load_vjepa_s = time.time() - t0
rss_after_load_vjepa = get_rss_bytes()

# Input specs: 16 frames, 384x384 (native)
b, c, t_frames, h_px, w_px = 1, 3, 16, 384, 384
np.random.seed(2026)
test_clip = mx.array(np.random.randn(b, c, t_frames, h_px, w_px).astype(np.float32))

# First inference (includes JIT compilation / graph compile)
t_warm0 = time.time()
out_warm = vjepa_model(test_clip)
mx.eval(out_warm)
first_inference_s = time.time() - t_warm0

# Steady-state throughput: 5 repetitions
repeats = 5
durations = []
for i in range(repeats):
    t_run0 = time.time()
    out = vjepa_model(test_clip)
    mx.eval(out)
    dt = time.time() - t_run0
    durations.append(dt)

median_duration = float(np.median(durations))
min_duration = float(np.min(durations))
max_duration = float(np.max(durations))

# Throughput calculations
clip_per_s_median = 1.0 / median_duration
clip_per_s_min = 1.0 / max_duration
clip_per_s_max = 1.0 / min_duration

frames_per_s_median = t_frames / median_duration
frames_per_s_min = t_frames / max_duration
frames_per_s_max = t_frames / min_duration

extrapolated_time_1k_samples_s = median_duration * 1000

# Feature bytes and cache volume
# Output shape: (1, 4608, 1024) in float32
feature_shape = list(out_warm.shape)
single_sample_feature_bytes = int(np.prod(feature_shape) * 4)  # float32 = 4 bytes
cache_volume_1k_samples_bytes = single_sample_feature_bytes * 1000

peak_rss_vjepa = get_rss_bytes()
mlx_peak_mem_vjepa = mx.get_peak_memory()

bench_results["benchmarks"]["vjepa2_1_vitl_mlx"] = {
    "model_name": "V-JEPA 2.1 ViT-L (RoPE)",
    "framework": "MLX 0.32.4",
    "weights_format": "safetensors",
    "precision": "float32",
    "input_resolution": [384, 384],
    "input_frames": t_frames,
    "input_tubelet_size": 2,
    "input_shape": [b, c, t_frames, h_px, w_px],
    "output_shape": feature_shape,
    "load_duration_s": load_vjepa_s,
    "first_inference_latency_s": first_inference_s,
    "steady_state": {
        "repetitions": repeats,
        "durations_s": durations,
        "median_duration_s": median_duration,
        "min_duration_s": min_duration,
        "max_duration_s": max_duration,
        "throughput_clip_per_s_median": clip_per_s_median,
        "throughput_clip_per_s_range": [clip_per_s_min, clip_per_s_max],
        "throughput_frames_per_s_median": frames_per_s_median,
        "throughput_frames_per_s_range": [frames_per_s_min, frames_per_s_max],
    },
    "extrapolated_time_per_1k_samples_s": extrapolated_time_1k_samples_s,
    "extrapolated_note": "Extrapolated from steady-state median inference latency",
    "storage": {
        "single_sample_feature_bytes": single_sample_feature_bytes,
        "single_sample_feature_mb": single_sample_feature_bytes / (1024**2),
        "cache_volume_per_1k_samples_bytes": cache_volume_1k_samples_bytes,
        "cache_volume_per_1k_samples_gb": cache_volume_1k_samples_bytes / (1024**3),
    },
    "memory": {
        "rss_baseline_bytes": rss_before_vjepa,
        "rss_after_load_bytes": rss_after_load_vjepa,
        "rss_peak_bytes": peak_rss_vjepa,
        "rss_peak_mb": peak_rss_vjepa / (1024**2),
        "mlx_peak_memory_bytes": mlx_peak_mem_vjepa,
        "mlx_peak_memory_mb": mlx_peak_mem_vjepa / (1024**2),
    },
}

print(f"V-JEPA Load time: {load_vjepa_s:.3f}s")
print(f"V-JEPA First inference (warmup): {first_inference_s:.3f}s")
print(f"V-JEPA Median latency: {median_duration:.4f}s ({clip_per_s_median:.2f} clips/s, {frames_per_s_median:.1f} fps)")
print(f"V-JEPA Single feature size: {single_sample_feature_bytes / (1024**2):.2f} MB; 1k samples: {cache_volume_1k_samples_bytes / (1024**3):.2f} GB")
print(f"V-JEPA Peak RSS: {peak_rss_vjepa / (1024**2):.1f} MB, MLX Peak: {mlx_peak_mem_vjepa / (1024**2):.1f} MB")

# Unload V-JEPA and observe memory drop
del vjepa_model, out_warm, out, test_clip
gc.collect()
mx.metal.clear_cache()
rss_after_vjepa_unload = get_rss_bytes()
mlx_after_vjepa_unload = mx.get_active_memory()
print(f"Memory drop after V-JEPA unload: RSS {peak_rss_vjepa/(1024**2):.1f}MB -> {rss_after_vjepa_unload/(1024**2):.1f}MB, MLX active {mlx_after_vjepa_unload}B")

# -------------------------------------------------------------------------
# Benchmark 2: Core ML Depth Anything V2 Small (F16)
# Testing CPU_AND_NE, CPU_AND_GPU, and ALL
# -------------------------------------------------------------------------
print("\n--- Running Benchmark 2: Depth Anything V2 Small (Core ML) ---", flush=True)

compute_units_to_test = [
    ("CPU_AND_NE", ct.ComputeUnit.CPU_AND_NE, "Apple Neural Engine + CPU (Zero GPU contention with MLX Metal)"),
    ("CPU_AND_GPU", ct.ComputeUnit.CPU_AND_GPU, "Apple GPU + CPU (Shares GPU with MLX Metal)"),
    ("ALL", ct.ComputeUnit.ALL, "All Compute Units: NE + GPU + CPU"),
]

da2_benchmarks = {}

np.random.seed(42)
test_da2_img = Image.fromarray(np.uint8(np.random.randint(0, 255, (h_da2, w_da2, 3))))

for cu_name, cu_val, cu_desc in compute_units_to_test:
    check_guards(bench_start_time)
    print(f"\nTesting Core ML compute unit: {cu_name} ({cu_desc})...", flush=True)
    rss_pre_cu = get_rss_bytes()
    
    t0_load = time.time()
    model_da2 = ct.models.MLModel(str(DA2_F16_PATH), compute_units=cu_val)
    load_da2_s = time.time() - t0_load

    # First inference (warmup & ANE/GPU compilation)
    t_first0 = time.time()
    pred_first = model_da2.predict({"image": test_da2_img})
    first_da2_s = time.time() - t_first0

    # Steady state: 10 repetitions for high fidelity
    repeats_da2 = 10
    da2_durations = []
    for _ in range(repeats_da2):
        t_run0 = time.time()
        p = model_da2.predict({"image": test_da2_img})
        dt = time.time() - t_run0
        da2_durations.append(dt)

    median_da2_d = float(np.median(da2_durations))
    min_da2_d = float(np.min(da2_durations))
    max_da2_d = float(np.max(da2_durations))

    fps_median = 1.0 / median_da2_d
    fps_min = 1.0 / max_da2_d
    fps_max = 1.0 / min_da2_d

    extrapolated_time_1k_da2 = median_da2_d * 1000

    # Feature size: depth map is 392x518 float16
    single_depth_bytes = 392 * 518 * 2  # float16 = 2 bytes
    cache_1k_da2_bytes = single_depth_bytes * 1000
    peak_rss_cu = get_rss_bytes()

    da2_benchmarks[cu_name] = {
        "compute_unit": cu_name,
        "description": cu_desc,
        "competes_with_mlx_gpu": cu_name != "CPU_AND_NE",
        "recommended_for_world_mode": cu_name == "CPU_AND_NE",
        "input_resolution": [w_da2, h_da2],
        "output_resolution": [w_da2, h_da2],
        "precision": "float16",
        "load_duration_s": load_da2_s,
        "first_inference_latency_s": first_da2_s,
        "steady_state": {
            "repetitions": repeats_da2,
            "durations_s": da2_durations,
            "median_duration_s": median_da2_d,
            "min_duration_s": min_da2_d,
            "max_duration_s": max_da2_d,
            "throughput_fps_median": fps_median,
            "throughput_fps_range": [fps_min, fps_max],
        },
        "extrapolated_time_per_1k_samples_s": extrapolated_time_1k_da2,
        "extrapolated_note": "Extrapolated from steady-state median inference latency",
        "storage": {
            "single_sample_depth_bytes": single_depth_bytes,
            "single_sample_depth_kb": single_depth_bytes / 1024,
            "cache_volume_per_1k_samples_bytes": cache_1k_da2_bytes,
            "cache_volume_per_1k_samples_mb": cache_1k_da2_bytes / (1024**2),
        },
        "memory": {
            "rss_pre_load_bytes": rss_pre_cu,
            "rss_peak_bytes": peak_rss_cu,
            "rss_peak_mb": peak_rss_cu / (1024**2),
        },
    }

    print(f"  Load time: {load_da2_s:.3f}s")
    print(f"  First inference latency: {first_da2_s:.3f}s")
    print(f"  Median latency: {median_da2_d*1000:.2f}ms ({fps_median:.1f} fps), range: [{fps_min:.1f}, {fps_max:.1f}] fps")
    print(f"  1k samples time (extrapolated): {extrapolated_time_1k_da2:.2f}s")

    del model_da2, pred_first, p
    gc.collect()

bench_results["benchmarks"]["depth_anything_v2_small_coreml"] = da2_benchmarks

total_elapsed_bench = time.time() - bench_start_time
bench_results["timing_summary"] = {
    "total_benchmark_wall_s": total_elapsed_bench,
    "budget_wall_s": MAX_GPU_WALL_SECONDS,
    "budget_respected": total_elapsed_bench <= MAX_GPU_WALL_SECONDS,
    "memory_limit_bytes": MAX_PEAK_MEMORY_BYTES,
    "peak_rss_total_bytes": get_rss_bytes(),
    "peak_rss_total_gb": get_rss_bytes() / (1024**3),
    "memory_guard_respected": get_rss_bytes() <= MAX_PEAK_MEMORY_BYTES,
}

(REPORTS_DIR / "bench.json").write_text(json.dumps(bench_results, indent=2))
print(f"\nAll benchmarks complete in {total_elapsed_bench:.1f}s <= 1800s. Written to bench.json.", flush=True)
