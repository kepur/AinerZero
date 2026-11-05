"""Standalone worker script for T6 DA3 teacher benchmark execution.

Executed as an isolated child process group by `da3_controlled.py`.
Features:
- Real pipeline integration routing to `envs/teachers/t6/pipeline.py` and `.venv-t6`
- Upstream source tree identity & weights verification
- Safe mock/simulation actions for CPU testing (always explicitly recording model_runs=0)
- Process group memory allocation (for RSS limit testing)
- Long sleep (for timeout testing)
- Grandchild process spawning (for orphan/leak cleanup testing)
- Structured JSON output reporting
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# V9.T42: 统一登记的标定视图口径常量。worker 与中央 execute_guarded 共用同一来源，避免写死魔数与口径错位。
# V9.T44 (N-1): 删除无人使用的别名 CALIBRATION_VIEWS_REQUIRED，只保留唯一来源 REGISTERED_CALIBRATION_VIEWS。
REGISTERED_CALIBRATION_VIEWS: int = 18



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T6 DA3 benchmark worker process")
    parser.add_argument("--spec-file", type=Path, required=True, help="Path to DA3 run spec JSON")
    parser.add_argument("--output-file", type=Path, required=True, help="Path to output JSON")
    parser.add_argument(
        "--action",
        choices=(
            "real_pipeline",
            "mock_run",
            "simulate_timeout",
            "simulate_high_rss",
            "simulate_grandchild_leak",
        ),
        default="real_pipeline",
        help="Worker execution action (default: real_pipeline)",
    )
    parser.add_argument(
        "--simulate-rss-mib",
        type=int,
        default=0,
        help="Amount of memory in MiB to allocate and hold",
    )
    parser.add_argument(
        "--simulate-sleep-seconds",
        type=float,
        default=0.0,
        help="Duration in seconds to sleep",
    )
    parser.add_argument(
        "--spawn-grandchild-count",
        type=int,
        default=0,
        help="Number of background grandchild processes to spawn",
    )
    parser.add_argument(
        "--allow-model-execution",
        action="store_true",
        default=False,
        help="Whether actual model execution on hardware is authorized (default: False)",
    )
    return parser.parse_args()


def load_t6_pipeline():
    """Dynamically import envs/teachers/t6/pipeline.py."""
    repo_root = Path(__file__).resolve().parents[4]
    pipeline_path = repo_root / "envs/teachers/t6/pipeline.py"
    if not pipeline_path.is_file():
        raise FileNotFoundError(f"T6 pipeline module not found at {pipeline_path}")

    spec = importlib.util.spec_from_file_location("t6_pipeline", str(pipeline_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {pipeline_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    args = parse_args()

    if not args.spec_file.is_file():
        sys.stderr.write(f"Spec file not found: {args.spec_file}\n")
        return 1

    try:
        spec_data = json.loads(args.spec_file.read_text(encoding="utf-8"))
    except Exception as exc:
        sys.stderr.write(f"Failed to read spec JSON: {exc}\n")
        return 1

    pid = os.getpid()
    try:
        pgid = os.getpgid(0)
    except Exception:
        pgid = pid

    # Action 1: simulate_grandchild_leak
    if args.action == "simulate_grandchild_leak":
        grandchild = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            # Stays in same process group
        )
        result = {
            "status": "leaked_grandchild_spawned",
            "worker_pid": pid,
            "worker_pgid": pgid,
            "grandchild_pid": grandchild.pid,
            "model_runs": 0,
            "is_mock": True,
        }
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        args.output_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0

    # Action 2: simulate_timeout
    if args.action == "simulate_timeout":
        sleep_dur = args.simulate_sleep_seconds or 10.0
        time.sleep(sleep_dur)
        result = {
            "status": "timeout_sleep_finished",
            "worker_pid": pid,
            "worker_pgid": pgid,
            "model_runs": 0,
            "is_mock": True,
        }
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        args.output_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0

    # Action 3: simulate_high_rss
    if args.action == "simulate_high_rss":
        target_mib = args.simulate_rss_mib or 100
        chunk_size = 1024 * 1024
        chunks = []
        for _ in range(target_mib):
            b = bytearray(chunk_size)
            for i in range(0, chunk_size, 4096):
                b[i] = 1
            chunks.append(b)
        time.sleep(args.simulate_sleep_seconds or 5.0)
        result = {
            "status": "high_rss_finished",
            "worker_pid": pid,
            "worker_pgid": pgid,
            "model_runs": 0,
            "is_mock": True,
        }
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        args.output_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0

    # Action 4: real_pipeline
    if args.action == "real_pipeline":
        repo_root = Path(__file__).resolve().parents[4]
        venv_python = repo_root / "envs/teachers/.venv-t6/bin/python"

        # Verify .venv-t6 interpreter
        if not venv_python.is_file():
            sys.stderr.write(f".venv-t6 python interpreter not found at {venv_python}\n")
            return 2

        # Route through official pipeline library to verify upstream source identity & weights
        try:
            pipeline_mod = load_t6_pipeline()
            source_id = pipeline_mod.source_identity()
            variant_key = "DA3-SMALL" if "small" in str(spec_data.get("model", "")).lower() else "DA3-BASE"
            weights_info = pipeline_mod.inspect_weights(variant_key)
        except Exception as exc:
            sys.stderr.write(f"T6 pipeline verification failed: {exc}\n")
            return 2

        # If real model forward pass is not authorized, refuse execution
        if not args.allow_model_execution:
            result = {
                "status": "blocked",
                "mode": "real_pipeline",
                "task": spec_data.get("task", "ainerzero.V9.T6"),
                "worker_pid": pid,
                "worker_pgid": pgid,
                "model_runs": 0,
                "is_mock": False,
                "pipeline_verified": True,
                "source_identity_sha256": source_id.get("upstream_files_sha256"),
                "weights_inspection": weights_info,
                "reason": "Real DA3 forward pass is blocked: coordinator execution authorization not granted in pure-CPU mode.",
            }
            args.output_file.parent.mkdir(parents=True, exist_ok=True)
            args.output_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
            sys.stderr.write("Real DA3 execution is blocked: coordinator governance authorization required.\n")
            return 3

        # When authorized: real model execution via real_da3_worker / pipeline / calibration runner
        views = spec_data.get("views", 0)
        task_id = os.environ.get("DA3_TASK_ID", spec_data.get("task", "ainerzero.V9.T35"))

        runner_executed = False
        if views == REGISTERED_CALIBRATION_VIEWS and args.allow_model_execution:
            runner_script = repo_root / "src/ainerzero/v9/teachers/da3_calibration_runner.py"
            # 每次运行一个新目录：管线拒绝已存在的输出目录，而已交付的 reports/V9-T35/ 证据不得被覆盖或占用。
            run_stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-pid{pid}"
            run_root = repo_root / "reports/V9-T6/calibration-runs" / run_stamp
            out_ev = os.environ.get("T6_EVIDENCE_FILE", str(run_root / "calibration_evidence.json"))
            pred_dir = os.environ.get("T6_PREDICTIONS_DIR", str(run_root / "predictions"))

            env = dict(os.environ, KMP_DUPLICATE_LIB_OK="TRUE")
            env.pop("PYTHONPATH", None)

            cmd = [
                str(venv_python),
                str(runner_script),
                "--output",
                str(out_ev),
                "--predictions-dir",
                str(pred_dir),
                "--task",
                str(task_id),
            ]
            runner_proc = subprocess.run(cmd, env=env)
            runner_executed = True
            if runner_proc.returncode != 0:
                sys.stderr.write(f"Real DA3 calibration runner failed with exit code {runner_proc.returncode}\n")
                return runner_proc.returncode

        if not runner_executed:
            # 已授权真实执行、中央账本多半已按 spec.views 预扣，但标定 runner 一次都没启动：必须大声拒绝，
            # 不能返回 completed。T37 只把 model_runs 改成了如实的 0，仍会出现"预扣视图、零前向、rc=0"的陷阱（T38 §3.2）。
            refusal = {
                "status": "refused_no_calibration",
                "mode": "real_pipeline",
                "task": task_id,
                "worker_pid": pid,
                "worker_pgid": pgid,
                "model_runs": 0,
                "real_forward_executed": False,
                "is_mock": False,
                "requested_views": views,
                "reason": (f"authorized to execute, but no calibration was run: the calibration runner only starts for views == {REGISTERED_CALIBRATION_VIEWS}. "
                           "Nothing was executed and nothing should be counted as a run."),
            }
            args.output_file.parent.mkdir(parents=True, exist_ok=True)
            args.output_file.write_text(json.dumps(refusal, indent=2), encoding="utf-8")
            sys.stderr.write(f"Real DA3 execution refused: no calibration was run for views={views} (runner requires views == {REGISTERED_CALIBRATION_VIEWS}).\n")
            return 4

        result = {
            "status": "completed",
            "mode": "real_pipeline",
            "task": task_id,
            "worker_pid": pid,
            "worker_pgid": pgid,
            "model_runs": 1 if runner_executed else 0,
            "real_forward_executed": runner_executed,
            "note": None if runner_executed else f"no real calibration executed: the runner only runs for views == {REGISTERED_CALIBRATION_VIEWS}",
            "is_mock": False,
            "pipeline_verified": True,
            "source_identity_sha256": source_id.get("upstream_files_sha256"),
            "weights_inspection": weights_info,
            "coordinator_released": True,
        }
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        args.output_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0

    # Action 5: mock_run (Test substitute)
    if args.simulate_sleep_seconds > 0:
        time.sleep(args.simulate_sleep_seconds)

    chunks = []
    if args.simulate_rss_mib > 0:
        chunk_size = 1024 * 1024
        for _ in range(args.simulate_rss_mib):
            b = bytearray(chunk_size)
            b[0] = 1
            chunks.append(b)

    grandchild_pids = []
    for _ in range(args.spawn_grandchild_count):
        sub = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.01)"])
        grandchild_pids.append(sub.pid)
        sub.wait()

    result = {
        "status": "completed",
        "worker_pid": pid,
        "worker_pgid": pgid,
        "task": spec_data.get("task", "ainerzero.V9.T6"),
        "model": spec_data.get("model"),
        "views": spec_data.get("views"),
        "wall_budget_seconds": spec_data.get("wall_budget_seconds"),
        "grandchild_pids": grandchild_pids,
        "model_runs": 0,  # Explicitly declare 0 real model runs for mock
        "is_mock": True,
        "prediction_record": {
            "record_type": "teacher_prediction_candidate",
            "registered_cache_entry": False,
            "model_runs": 0,
        },
    }

    try:
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        args.output_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception as exc:
        sys.stderr.write(f"Failed to write output JSON: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
