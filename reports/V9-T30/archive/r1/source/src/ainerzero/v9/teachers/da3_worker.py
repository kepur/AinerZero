"""Standalone worker script for T6 DA3 teacher benchmark execution.

Executed as a supervised child process group by `da3_controlled.py`.
Supports:
- Safe mock/simulation actions for CPU testing
- Process group memory allocation (for RSS limit testing)
- Long sleep (for timeout testing)
- Grandchild process spawning (for orphan/leak cleanup testing)
- Output reporting via structured JSON file
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T6 DA3 benchmark worker process")
    parser.add_argument("--spec-file", type=Path, required=True, help="Path to DA3 run spec JSON")
    parser.add_argument("--output-file", type=Path, required=True, help="Path to output JSON")
    parser.add_argument(
        "--action",
        choices=(
            "mock_run",
            "simulate_timeout",
            "simulate_high_rss",
            "simulate_grandchild_leak",
            "real_pipeline",
        ),
        default="mock_run",
        help="Worker execution action",
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    
    # Read spec
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

    # Handle actions
    if args.action == "simulate_grandchild_leak":
        # Spawn grandchild process in the same process group that sleeps forever
        grandchild = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            # Do NOT create new session; stay in the current process group
        )
        # Record grandchild PID into output file before exiting early
        result = {
            "status": "leaked_grandchild_spawned",
            "worker_pid": pid,
            "worker_pgid": pgid,
            "grandchild_pid": grandchild.pid,
        }
        args.output_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        # Exit immediately while grandchild stays alive!
        return 0

    if args.action == "simulate_timeout":
        sleep_dur = args.simulate_sleep_seconds or 10.0
        time.sleep(sleep_dur)
        return 0

    if args.action == "simulate_high_rss":
        target_mib = args.simulate_rss_mib or 100
        # Allocate bytes in chunks and touch memory
        chunk_size = 1024 * 1024
        chunks = []
        for _ in range(target_mib):
            b = bytearray(chunk_size)
            for i in range(0, chunk_size, 4096):
                b[i] = 1
            chunks.append(b)
        # Sleep to allow supervisor to observe RSS
        time.sleep(args.simulate_sleep_seconds or 5.0)
        return 0

    if args.action == "real_pipeline":
        # Check if real execution is authorized
        sys.stderr.write(
            "Real DA3 pipeline execution is not authorized in pure-CPU mode. "
            "Coordinator release authorization required.\n"
        )
        return 2

    # Default action: mock_run
    # If sleep requested:
    if args.simulate_sleep_seconds > 0:
        time.sleep(args.simulate_sleep_seconds)

    # If memory requested:
    chunks = []
    if args.simulate_rss_mib > 0:
        chunk_size = 1024 * 1024
        for _ in range(args.simulate_rss_mib):
            b = bytearray(chunk_size)
            b[0] = 1
            chunks.append(b)

    # Spawn grandchildren if requested (clean background helper)
    grandchild_pids = []
    for _ in range(args.spawn_grandchild_count):
        sub = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.01)"]
        )
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
        "prediction_record": {
            "record_type": "teacher_prediction_candidate",
            "registered_cache_entry": False,
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
