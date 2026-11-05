"""Guarded Entry Runner for T6 DA3 Real Benchmark & Noise Calibration.

Binds:
- Central CLI / RunStore ledger (artifacts/v9/teachers/benchmark/runs.db under ainerzero.V9.T6)
- Cross-process exclusive worker_lock (artifacts/locks/m0-worker.lock)
- RESEARCH_LOG.md R20261026-T6 approval and reports/V9-T6/r2-calib-fixtures/statistical_protocol.json
- Parent supervision of child process group running under envs/teachers/.venv-t6
- Bounded resource enforcement: peak RSS <= 8.0 GiB, wall time <= 1200.0s, views <= 64
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil

# Ensure src is on path
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ainerzero.v9.teachers.benchmark_protocol import (
    DEFAULT_LOCK_PATH,
    DEFAULT_RESEARCH_LOG,
    DEFAULT_STORE_PATH,
    DEFAULT_T6_WEIGHTS_ROOT,
    T6_MAX_CUMULATIVE_WALL_SECONDS,
    T6_MAX_PER_RUN_WALL_SECONDS,
    T6_MAX_PROCESS_RSS_BYTES,
    T6_MAX_PROCESS_RSS_GIB,
    T6_MAX_VIEWS,
    T6_TASK_ID,
    DA3RunSpec,
)
from ainerzero.v9.teachers.da3_controlled import execute_guarded_da3_benchmark


from ainerzero.cli import worker_lock
from ainerzero.runtime.lifecycle import RunStore, BudgetExceeded
from ainerzero.v9.teachers.da3_controlled import (
    check_t6_resource_limits,
    check_t6_views_quota,
    check_da3_weights_manifest,
    verify_t6_approval_and_protocol,
    query_t6_ledger_read_only,
    normalize_da3_model_name,
)
from uuid import uuid4


class SubprocessDA3BenchmarkAdapter:
    """Supervised subprocess adapter executing real DA3 in envs/teachers/.venv-t6."""

    def __init__(self, python_bin: Path | None = None, script_path: Path | None = None):
        self.python_bin = python_bin or (REPO_ROOT / "envs/teachers/.venv-t6/bin/python")
        self.script_path = script_path or (REPO_ROOT / "envs/teachers/t6/real_da3_worker.py")
        self.peak_rss_bytes = 0

    def run_benchmark(self, spec: DA3RunSpec) -> dict[str, Any]:
        output_json = REPO_ROOT / "reports/V9-T6/r3/calibration_evidence.json"
        cmd = [
            str(self.python_bin),
            str(self.script_path),
            "--output",
            str(output_json),
        ]

        env = os.environ.copy()
        env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
        env["PYTHONUNBUFFERED"] = "1"

        print(f"[Parent Supervisor] Launching child process group: {' '.join(cmd)}")
        t_start = time.time()

        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,  # Isolate into own process group
        )

        child_pgid = os.getpgid(proc.pid)
        max_rss = 0

        # Non-blocking supervisor loop
        try:
            ps_proc = psutil.Process(proc.pid)
            while proc.poll() is None:
                try:
                    # Measure RSS of child and its children
                    mem_self = ps_proc.memory_info().rss
                    mem_children = sum(c.memory_info().rss for c in ps_proc.children(recursive=True))
                    tot_rss = mem_self + mem_children
                    if tot_rss > max_rss:
                        max_rss = tot_rss

                    if tot_rss > T6_MAX_PROCESS_RSS_BYTES:
                        print(
                            f"[Parent Supervisor] RSS breach! {tot_rss / (1024**3):.2f} GiB > {T6_MAX_PROCESS_RSS_GIB} GiB. Terminating group {child_pgid}."
                        )
                        os.killpg(child_pgid, signal.SIGTERM)
                        raise RuntimeError(
                            f"Process RSS breach: {tot_rss / (1024**3):.2f} GiB > {T6_MAX_PROCESS_RSS_GIB} GiB"
                        )

                    elapsed = time.time() - t_start
                    if elapsed > spec.wall_budget_seconds:
                        print(
                            f"[Parent Supervisor] Wall budget timeout! {elapsed:.1f}s > {spec.wall_budget_seconds:.1f}s. Terminating group {child_pgid}."
                        )
                        os.killpg(child_pgid, signal.SIGTERM)
                        raise TimeoutError(f"Wall budget exceeded: {elapsed:.1f}s")

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    break

                time.sleep(0.2)

            stdout_output, _ = proc.communicate(timeout=10)
            if proc.returncode != 0:
                print(f"[Child Output on Failure]\n{stdout_output}")
                raise RuntimeError(f"Child worker exited with code {proc.returncode}")

            print(f"[Parent Supervisor] Child process group finished cleanly with rc=0.")
            print(f"[Parent Supervisor] Peak monitored child RSS: {max_rss / (1024**2):.2f} MB ({max_rss / (1024**3):.4f} GiB).")
            self.peak_rss_bytes = max_rss

        except Exception:
            # Terminate child group on any parent exception
            try:
                os.killpg(child_pgid, signal.SIGTERM)
            except OSError:
                pass
            raise

        if not output_json.is_file():
            raise FileNotFoundError(f"Child did not produce expected evidence file: {output_json}")

        evidence = json.loads(output_json.read_text(encoding="utf-8"))
        evidence["supervisor_stats"] = {
            "peak_monitored_rss_bytes": max_rss,
            "peak_monitored_rss_gib": round(max_rss / (1024**3), 4),
            "wall_elapsed_s": round(time.time() - t_start, 2),
            "exit_code": proc.returncode,
        }
        return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="T6 Guarded Real DA3 Benchmark Entry")
    parser.add_argument("--wall-budget-seconds", type=float, default=600.0)
    parser.add_argument("--views", type=int, default=18)
    parser.add_argument("--model", choices=["da3-small", "da3-base", "da3-all"], default="da3-all")
    parser.add_argument(
        "--statistical-protocol",
        type=Path,
        default=REPO_ROOT / "reports/V9-T6/r2-calib-fixtures/statistical_protocol.json",
    )
    args = parser.parse_args()

    spec = DA3RunSpec(
        model=args.model,
        wall_budget_seconds=args.wall_budget_seconds,
        views=args.views,
        research_log_path=REPO_ROOT / DEFAULT_RESEARCH_LOG,
        store_path=REPO_ROOT / DEFAULT_STORE_PATH,
        lock_path=REPO_ROOT / DEFAULT_LOCK_PATH,
        weights_root=REPO_ROOT / DEFAULT_T6_WEIGHTS_ROOT,
        statistical_protocol_path=args.statistical_protocol,
        coordinator_release=True,
        allow_model_execution=True,
    )

    print("==========================================================================")
    print("Executing Guarded T6 DA3 Benchmark under Central RunStore & Worker Lock")
    print("==========================================================================")
    print(f"Task: {T6_TASK_ID}")
    print(f"Lock: {spec.lock_path}")
    print(f"Store: {spec.store_path}")
    print(f"Protocol: {spec.statistical_protocol_path}")
    print(f"Wall Budget: {spec.wall_budget_seconds}s")
    print(f"Views: {spec.views}")

    # 1. Gate checks
    approval = verify_t6_approval_and_protocol(spec.research_log_path, spec.statistical_protocol_path)
    if not approval["is_approved"]:
        raise RuntimeError(f"Approval gate failed: {approval.get('missing_items')}")

    model_norm = normalize_da3_model_name(spec.model)
    check_da3_weights_manifest(spec.weights_root, model_norm)
    check_t6_views_quota(spec.views)
    check_t6_resource_limits(max_rss_gib=T6_MAX_PROCESS_RSS_GIB, check_system_guards=True)

    # 2. Acquire lock & RunStore
    with worker_lock(spec.lock_path):
        spec.store_path.parent.mkdir(parents=True, exist_ok=True)
        with RunStore(spec.store_path) as store:
            cum_sec_locked, cum_views_locked = query_t6_ledger_read_only(spec.store_path)
            check_t6_views_quota(spec.views, cumulative_views=cum_views_locked)
            if cum_sec_locked + spec.wall_budget_seconds > T6_MAX_CUMULATIVE_WALL_SECONDS:
                raise RuntimeError(
                    f"Cumulative budget exceeded: {cum_sec_locked:.1f}s + {spec.wall_budget_seconds:.1f}s > {T6_MAX_CUMULATIVE_WALL_SECONDS:.1f}s"
                )

            run_id = uuid4().hex
            request_id = f"t6-da3-calibration-{run_id}"

            config_snapshot = {
                "task": T6_TASK_ID,
                "model": model_norm,
                "views": spec.views,
                "budget": {
                    "max_wall_seconds": T6_MAX_CUMULATIVE_WALL_SECONDS,
                    "max_environment_steps": 1000,
                    "max_optimizer_steps": 1000,
                    "max_daily_active_seconds": T6_MAX_CUMULATIVE_WALL_SECONDS,
                    "max_model_transitions": 0,
                    "timezone": "UTC",
                },
                "frozen_bindings": {
                    "research_log_sha256": approval.get("research_log_sha256"),
                    "statistical_protocol_sha256": approval.get("protocol_details", {}).get("sha256"),
                    "weights_root": str(spec.weights_root),
                },
            }

            store.create_run(config_snapshot, request_id=request_id, run_id=run_id)
            store.transition(run_id, "initializing", reason="Pre-work initialization")
            store.transition(run_id, "validating", reason="Pre-work budget reservation")
            store.consume(run_id, active_seconds=spec.wall_budget_seconds)

            # 3. Supervised execution of real DA3 worker in isolated child process group
            adapter = SubprocessDA3BenchmarkAdapter()
            try:
                evidence = adapter.run_benchmark(spec)
                store.transition(run_id, "completed", reason="Real DA3 benchmark and calibration completed")
            except Exception as exc:
                store.transition(run_id, "failed", reason=f"Execution error: {exc}")
                raise

    print("\n==========================================================================")
    print("GUARDED RUN COMPLETED SUCCESSFULLY!")
    print("==========================================================================")
    print(f"Run ID: {run_id}")
    print(f"Wall elapsed: {evidence.get('supervisor_stats', {}).get('wall_elapsed_s')}s")
    print(f"Peak RSS: {evidence.get('supervisor_stats', {}).get('peak_monitored_rss_gib')} GiB")

    # Save summary report in reports/V9-T6/r3/
    out_file = REPO_ROOT / "reports/V9-T6/r3/guarded_run_summary.json"
    evidence["run_id"] = run_id
    evidence["cumulative_reserved_seconds"] = cum_sec_locked + spec.wall_budget_seconds
    out_file.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Run report written to {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
