#!/usr/bin/env python3
"""P28 read-only, one-shot batch-1 timing. CPU modes never import MLX.

Arm1 is identity-only/N/A under task answer #425. No C0 batch is opened.
The three measured primitives are partial evaluation costs, not capability.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATASET_DIGEST = "8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
DATASET = ROOT / "artifacts/v9/s1/datasets" / DATASET_DIGEST
P18 = ROOT / "reports/V9-P18/r4/products/metrics.json"
N = 12
WARMUP = 3
MIN_SAMPLES = 30
BOOT_EPOCH = 1792678827
TASK = "ainerzero.V9.P28"
ARMS = ("arm2", "arm3", "arm4")
ONCE = HERE / "REAL_ATTEMPT_ONCE.json"
FORBIDDEN = frozenset(("make_optimizer", "init_optimizer", "value_and_grad", "optimizer_update",
                       "sync_parameters", "save_params", "load_params", "window_probe", "clip_grad_norm"))
sys.path.insert(0, str(ROOT / "src"))


class BoundaryViolation(RuntimeError):
    pass


def safe_path(value):
    path = Path(value)
    if "final" in os.fspath(path).lower() or "final" in str(path.resolve()).lower():
        raise BoundaryViolation(f"sealed path refused before opening: {path}")
    return path.resolve()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(path):
    return hashlib.sha256(safe_path(path).read_bytes()).hexdigest()


def install_io_guard(output):
    output = safe_path(output)
    lock = ROOT / "artifacts/locks/m0-worker.lock"

    def audit(event, args):
        if event == "sqlite3.connect":
            raise BoundaryViolation("P28 must not open any RunStore or ledger")
        if event in ("os.rename", "os.remove", "os.rmdir", "os.mkdir", "os.link"):
            paths = args[:2] if event in ("os.rename", "os.link") else args[:1]
            for value in paths:
                if isinstance(value, (str, bytes, os.PathLike)):
                    path = safe_path(os.fsdecode(value))
                    once_link = event == "os.link" and path == ONCE and safe_path(args[0]) == output / "attempt.json"
                    if not path.is_relative_to(output) and not once_link:
                        raise BoundaryViolation(f"filesystem mutation outside run output refused: {path}")
        if event not in ("open", "os.listdir", "os.scandir") or not args:
            return
        if isinstance(args[0], int) or args[0] is None:
            return
        path = safe_path(os.fsdecode(args[0]))
        if event == "open":
            mode, flags = args[1:3]
            writing = bool((isinstance(mode, str) and any(c in mode for c in "wax+")) or
                           (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            if writing and not path.is_relative_to(output) and path not in (lock, Path(os.devnull)):
                raise BoundaryViolation(f"write outside this run output refused: {path}")
    sys.addaudithook(audit)


def write_json(path, value):
    path = safe_path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def source_files():
    sources = sorted((ROOT / "src/ainerzero/v9/experiments/s1").glob("*.py"))
    sources += [ROOT / name for name in ("src/ainerzero/learning/pilot_model.py", "src/ainerzero/cli.py",
                "src/ainerzero/runtime/checkpoints.py", "reports/V9-B3-mlx-unitcost/measure_unit_cost.py",
                "reports/V9-B3-mlx-unitcost/test_measure_unit_cost.py")]
    sources += [DATASET / "dataset_manifest.json", DATASET / "packets/development.jsonl", P18]
    return {str(path.relative_to(ROOT)): sha(path) for path in sources}


def load_inputs():
    from ainerzero.v9.experiments.s1 import data

    manifest = json.loads(safe_path(DATASET / "dataset_manifest.json").read_text())
    body = {"plan": {**manifest["plan"], "partitions": list(manifest["plan"].get("partitions", data.PARTITIONS))},
            "source_identity": manifest["source_identity"], "counts": manifest["counts"], "episodes": manifest["episodes"]}
    digest = hashlib.sha256(data.canonical_bytes(body)).hexdigest()
    if digest != DATASET_DIGEST or manifest["dataset_digest"] != digest:
        raise BoundaryViolation("development dataset identity differs from registration")
    packets = DATASET / "packets/development.jsonl"
    if sha(packets) != manifest["files"]["packets/development.jsonl"]["sha256"]:
        raise BoundaryViolation("development packet bytes differ from manifest")
    # Do not call verify_dataset: it also opens train and truth files.
    episodes = {episode.episode_id: episode for episode in data.load_training_episodes(safe_path(DATASET), "development")}
    selected = sorted((row for row in manifest["episodes"] if row["partition"] == "development"),
                      key=lambda row: (row["scene_id"], row["episode_id"]))[:N]
    if len(selected) != N:
        raise BoundaryViolation("not enough registered development episodes")
    sequences = [data.build_episode_sequence(episodes[row["episode_id"]]) for row in selected]
    sample = {"dataset_digest": digest, "partition": "development", "N": N, "ordering": "scene_id, episode_id",
              "episodes": selected, "total_frames": sum(len(s["obs"]) for s in sequences),
              "total_transitions": sum(len(s["obs"]) - 1 for s in sequences),
              "family_caveat": "first 12 sorted scenes are all e3_identity; no cross-family representativeness"}
    sample["manifest_sha256"] = hashlib.sha256(canonical(sample)).hexdigest()
    return sequences, sample


def command_output(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=10).stdout.strip()


def resource_sample(*, mx=None):
    import psutil
    from ainerzero.v9.experiments.s1 import resource_gate, spec

    boot = int(psutil.boot_time())
    # zero is the registered same-boot baseline; never reset to current swap.
    probe = (lambda: {"available": False, "active_bytes": 0.0, "peak_bytes": 0.0}) if mx is None else (
        lambda: {"available": True, "active_bytes": float(mx.get_active_memory()), "peak_bytes": float(mx.get_peak_memory())})
    snapshot = resource_gate.collect(root=HERE, swap_baseline_bytes=0.0, mlx_probe=probe)
    reasons = resource_gate.evaluate(snapshot, spec.RESOURCE_LIMITS)
    if boot != BOOT_EPOCH:
        reasons.append(f"boot differs from registered 2026-10-22 17:20: {boot}")
    row = snapshot.to_dict() | {"boot_epoch": boot, "reasons": reasons,
            "swap_baseline_bytes": 0, "mlx_measurement": "not imported" if mx is None else "actual allocator"}
    return row


def assert_resources(*, mx=None):
    sample = resource_sample(mx=mx)
    if sample["reasons"]:
        raise BoundaryViolation("resource gate refused: " + "; ".join(sample["reasons"]))
    return sample


def environment():
    return {"python": sys.version, "platform": platform.platform(), "macos": platform.mac_ver()[0],
            "chip": command_output("/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"),
            "kern.boottime": command_output("/usr/sbin/sysctl", "-n", "kern.boottime"),
            "vm.swapusage": command_output("/usr/sbin/sysctl", "-n", "vm.swapusage"),
            "mlx_installed_version": importlib.metadata.version("mlx"),
            "mlx_imported": any(name == "mlx" or name.startswith("mlx.") for name in sys.modules)}


class ReadOnlyBackend:
    def __init__(self, backend):
        self.backend = backend

    def __getattr__(self, name):
        if name in FORBIDDEN:
            raise BoundaryViolation(f"training/checkpoint method is forbidden: {name}")
        if name not in ("eval", "encode", "probe_graph"):
            raise BoundaryViolation(f"unregistered backend operation: {name}")
        return getattr(self.backend, name)


class FakeArm:
    def __init__(self, arm_id):
        self.arm_id = arm_id
        self.calls = 0

    def forward_terms(self, batch, *, burn_in, memory, pose):
        import numpy as np
        assert batch["obs"].shape[0] == 1 and batch["obs"].shape[1] == 2 and burn_in == 0
        self.calls += 1
        return np.float32(0), {"position": np.float32(0)}, pose.copy(), None, {"steps": (memory or {}).get("steps", 0) + 1}


class FakeBackend:
    def eval(self, *values):
        return None

    def encode(self, model, row):
        import numpy as np
        return np.asarray(row[:8]).copy()

    def probe_graph(self, model, memory, pose=None):
        return {"fake": True, "memory_steps": memory["steps"]}


def summarize_times(warmup, measured):
    import numpy as np
    if len(warmup) != WARMUP or len(measured) < MIN_SAMPLES:
        raise BoundaryViolation("insufficient warmup or measured samples")
    values = [row["seconds"] for row in measured]
    if not all(np.isfinite(x) and x >= 0 for x in values):
        raise BoundaryViolation("invalid timer result")
    return {"first_call_seconds": warmup[0]["seconds"], "warmup": warmup, "measured": measured,
            "samples": len(values), "median_seconds": float(np.median(values)),
            "p90_seconds": float(np.percentile(values, 90)), "max_seconds": max(values),
            "first_call_caveat": "first call includes compilation/warmup work; compiler time is not separately isolated"}


def measure_arm(arm_id, model, backend, sequences, output, *, check=lambda: None, clock=time.perf_counter):
    import numpy as np
    from ainerzero.v9.experiments.s1 import data

    raw = output / (arm_id + "-raw.jsonl")
    def timed(operation, invoke, metadata):
        check()
        start = clock()
        result = invoke()
        elapsed = clock() - start
        row = {"operation": operation, "seconds": elapsed, **metadata}
        with raw.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
        check()
        return result, row

    def forward(sequence, step, memory, pose):
        batch = data.sequence_batch(sequence, step, step + 2)
        def invoke():
            terms = model.forward_terms(batch, burn_in=0, memory=memory, pose=pose)
            backend.eval(terms[0], *terms[1].values())
            return terms
        return invoke

    warm = []
    memory, pose = None, np.zeros((1, 4), dtype=np.float32)
    for i in range(WARMUP):
        sequence = sequences[0]
        terms, row = timed("forward-warmup", forward(sequence, i % (len(sequence["obs"]) - 1), memory, pose), {"index": i})
        memory, pose = terms[4], terms[2]
        warm.append(row)
    measured, states = [], []
    for sequence in sequences:
        memory, pose = None, np.zeros((1, 4), dtype=np.float32)
        for step in range(len(sequence["obs"]) - 1):
            terms, row = timed("forward", forward(sequence, step, memory, pose),
                               {"episode_id": sequence["episode_id"], "frame": step + 1, "batch_size": 1})
            memory, pose = terms[4], np.asarray(terms[2]).copy()
            measured.append(row)
        states.append((memory, pose, sequence["episode_id"]))
    results = {"arm_id": arm_id, "status": "partial", "batch_size": 1, "seed": 0,
               "forward": summarize_times(warm, measured)}
    write_json(output / (arm_id + ".json"), results)
    rows = [(sequence["episode_id"], i, row) for sequence in sequences for i, row in enumerate(sequence["obs"])]
    warm, measured = [], []
    for i in range(WARMUP + len(rows)):
        episode, frame, obs = rows[0] if i < WARMUP else rows[i - WARMUP]
        _, row = timed("encode-warmup" if i < WARMUP else "encode", lambda: backend.encode(model, obs),
                       {"episode_id": episode, "frame": frame, "batch_size": 1})
        (warm if i < WARMUP else measured).append(row)
    results["encode"] = summarize_times(warm, measured)
    write_json(output / (arm_id + ".json"), results)
    warm, measured = [], []
    count = ((MIN_SAMPLES + len(states) - 1) // len(states)) * len(states)
    for i in range(WARMUP + count):
        memory, pose, episode = states[0] if i < WARMUP else states[(i - WARMUP) % len(states)]
        _, row = timed("probe_graph-warmup" if i < WARMUP else "probe_graph",
                       lambda: backend.probe_graph(model, memory, pose=pose),
                       {"episode_id": episode, "memory_source": "completed measured forward sequence", "batch_size": 1})
        (warm if i < WARMUP else measured).append(row)
    results["probe_graph"] = summarize_times(warm, measured)
    results["status"] = "completed"
    write_json(output / (arm_id + ".json"), results)
    return results


def extrapolate(results):
    source = json.loads(safe_path(P18).read_text())
    calls = source["d3_call_counts"]["per_arm_seed_eval"]["repaired_k1_measured_non_author"]
    binding = source["d3_call_counts"]["binding"]
    if binding["dataset_digest"] != DATASET_DIGEST or calls != {"encode_calls": 3500, "probe_graph_calls": 800,
          "provenance": "measured_non_author (P19)", "single_step_forwards": 1492, "step_sequence_calls": 611,
          "window_forward_loss_calls": 175}:
        raise BoundaryViolation("P18 call accounting differs from frozen source")
    per_arm = {}
    for arm_id, result in results.items():
        if result.get("status") != "completed":
            continue
        row = {"arm_id": arm_id}
        for field in ("median_seconds", "p90_seconds"):
            seconds = (calls["single_step_forwards"] * result["forward"][field] +
                       calls["encode_calls"] * result["encode"][field] +
                       calls["probe_graph_calls"] * result["probe_graph"][field])
            row[field] = seconds
            row[field + "_fraction_of_1200"] = seconds / 1200
            row["mean_step_sequence_" + field] = calls["single_step_forwards"] / calls["step_sequence_calls"] * result["forward"][field]
        per_arm[arm_id] = row
    phase = {field: 3 * sum(row[field] for row in per_arm.values()) for field in ("median_seconds", "p90_seconds")}
    return {"source": str(P18), "source_sha256": sha(P18), "calls_per_arm_seed": calls, "per_arm_seed": per_arm,
            "nine_eval_invocations_arithmetic": phase, "phase_cap_seconds": 14400,
            "phase_fraction_median": phase["median_seconds"] / 14400,
            "phase_fraction_p90": phase["p90_seconds"] / 14400,
            "assumptions": ["1492 forwards already include the 611 sequence calls; no double multiplication",
                "per-arm seed0 untrained structures reused arithmetically for three seeds; no trained-checkpoint cost claim",
                "median-to-p90 weighted sums are scenario arithmetic, not confidence bounds or a joint p90",
                "only first 12 sorted development scenes, all e3_identity, with sparse untrained memories"],
            "unmeasured": ["175 separate checkpoint window-forward_loss batches", "C0 D real forward and its 2-second deadline",
                "checkpoint reload, model I/O, sequence slicing, output serialization, full Python bookkeeping",
                "trained-memory population and other scene families, training time, full end-to-end phase wall"],
            "budget_verdict": "partial primitive arithmetic only; cannot certify 20-minute or four-hour end-to-end fit"}


def validate_freeze(path, inputs):
    freeze = json.loads(safe_path(path).read_text())
    if freeze.get("task") != TASK or "冻结通过" not in freeze.get("message", ""):
        raise BoundaryViolation("level-1 freeze reply is required before real mode")
    if freeze.get("source_files") != inputs or freeze.get("argv") != [sys.executable, *sys.argv]:
        raise BoundaryViolation("frozen sources or exact Python argv differ")
    return freeze


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry", "preflight", "real"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args(argv)
    output = safe_path(args.output)
    if not output.is_relative_to(HERE) or output == HERE:
        raise BoundaryViolation("output must be a fresh child of this report directory")
    output.mkdir(parents=True, exist_ok=False)
    sys.dont_write_bytecode = True
    install_io_guard(output)
    inputs = source_files()
    report = {"task": TASK, "mode": args.mode, "status": "started", "real_model_runs": 0,
              "source_files": inputs, "N": N, "warmup_per_primitive": WARMUP, "minimum_samples": MIN_SAMPLES,
              "arms": {}, "arm1_policy": "level-1 answer #425: identity only; all three primitives N/A"}
    write_json(output / "run.json", report)
    try:
        sequences, samples = load_inputs()
        write_json(output / "samples.json", samples)
        report["sample_manifest_sha256"] = samples["manifest_sha256"]
        from ainerzero.v9.experiments.s1 import identity
        report["arm1_identity"] = identity.verify_d_candidate_identity(ROOT)
        report["arms"]["arm1"] = {"status": "not_applicable", "forward": "not_applicable", "encode": "not_applicable",
                                   "probe_graph": "not_applicable", "reason": "incomparable S1 input layout; no forward_terms"}
        write_json(output / "arm1.json", report["arms"]["arm1"])
        env = environment()
        (output / "env.txt").write_text(json.dumps(env, ensure_ascii=False, indent=2) + "\n")
        if args.mode == "preflight":
            report["resources"] = resource_sample()
            report["status"] = "preflight_only"
            return 0
        if args.mode == "dry":
            backend = ReadOnlyBackend(FakeBackend())
            for arm_id in ARMS:
                report["arms"][arm_id] = measure_arm(arm_id, FakeArm(arm_id), backend, sequences, output)
                write_json(output / "run.json", report)
            report["status"] = "cpu_dryrun_completed_not_model_timing"
            report["mlx_imported"] = any(name == "mlx" or name.startswith("mlx.") for name in sys.modules)
            if report["mlx_imported"]:
                raise BoundaryViolation("CPU dryrun imported MLX")
            return 0
        if args.freeze is None:
            raise BoundaryViolation("real mode requires the level-1 freeze file")
        freeze = validate_freeze(args.freeze, inputs)
        # Attempt marker may only be created once, before any real MLX import.
        # Its parent is HERE, so create through this run's output via an exclusive hard link.
        marker = output / "attempt.json"
        write_json(marker, {"freeze_message_id": freeze["message_id"], "started_unix": time.time(), "output": str(output)})
        os.link(marker, safe_path(ONCE))  # EEXIST is a refusal, never a second run.
        report["resources_before_mlx"] = assert_resources()
        from ainerzero.cli import worker_lock
        from ainerzero.v9.experiments.s1 import spec
        lock_path = Path(spec.host_anchor()["lock"])
        if not lock_path.is_file():
            raise BoundaryViolation("registered shared lock file is missing; will not create a new lock")
        with worker_lock(lock_path):
            report["resources_after_lock"] = assert_resources()
            import mlx.core as mx
            from ainerzero.v9.experiments.s1 import arms, runtime
            report["real_model_runs"] = 1
            report["mlx_default_device"] = str(mx.default_device())
            report["backend_name"] = runtime.MlxBackend.name
            backend = ReadOnlyBackend(runtime.MlxBackend())
            resource_rows = []
            def check():
                row = resource_sample(mx=mx)
                resource_rows.append(row)
                peak_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * (1 if sys.platform == "darwin" else 1024)
                write_json(output / "resources-latest.json", {"last_sample": row,
                    "process_peak_rss_bytes": peak_rss, "mlx_peak_bytes": int(mx.get_peak_memory())})
                if row["reasons"]:
                    raise BoundaryViolation("resource gate refused: " + "; ".join(row["reasons"]))
            check()
            for arm_id in ARMS:
                check()
                begin = time.perf_counter()
                model = arms.build_trainable_arm(arm_id, seed=0)
                model.eval()
                before = arms.parameter_sha256(model)
                init_seconds = time.perf_counter() - begin
                result = measure_arm(arm_id, model, backend, sequences, output, check=check)
                after = arms.parameter_sha256(model)
                if after != before:
                    raise BoundaryViolation(f"parameters changed without authorization: {arm_id}")
                result.update(parameter_sha256_before=before, parameter_sha256_after=after,
                              parameter_count=arms.count_parameters(model), initialization_and_identity_seconds=init_seconds)
                report["arms"][arm_id] = result
                report["resource_samples"] = resource_rows
                write_json(output / (arm_id + ".json"), result)
                write_json(output / "run.json", report)
                del model
            check()
            report["mlx_peak_bytes"] = int(mx.get_peak_memory())
            report["process_peak_rss_bytes"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * (1 if sys.platform == "darwin" else 1024)
            report["resource_samples"] = resource_rows
            report["extrapolation"] = extrapolate(report["arms"])
        report["status"] = "measurement_completed_not_capability"
        return 0
    except BaseException as exc:
        report["status"] = "failed_or_refused_no_retry"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["source_identity_unchanged"] = source_files() == inputs
        write_json(output / "run.json", report)


if __name__ == "__main__":
    raise SystemExit(main())
