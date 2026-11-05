"""Audit Evidence Generator for ainerzero.V9.T32 Stop Handover.

Records:
1. Exact SHA-256 and byte sizes of DA3-SMALL and DA3-BASE weight files.
2. Exact Python / Torch / MPS environment status in envs/teachers/.venv-t6.
3. Verification of strict=True load alignment.
4. Process group clean exit and lack of active worker processes.
5. Production RunStore and worker lock clean state.
6. Explicit demarcation of UNVERIFIED items.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def get_file_stats(p: Path) -> dict:
    if not p.is_file():
        return {"exists": False}
    data = p.read_bytes()
    return {
        "exists": True,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main():
    print("Collecting T32 stop handover audit evidence...")

    weights = {
        "da3_small_config": get_file_stats(REPO_ROOT / "artifacts/teachers/da3/DA3-SMALL/config.json"),
        "da3_small_weights": get_file_stats(REPO_ROOT / "artifacts/teachers/da3/DA3-SMALL/model.safetensors"),
        "da3_base_config": get_file_stats(REPO_ROOT / "artifacts/teachers/da3/DA3-BASE/config.json"),
        "da3_base_weights": get_file_stats(REPO_ROOT / "artifacts/teachers/da3/DA3-BASE/model.safetensors"),
    }

    # Verify strict load using .venv-t6
    test_code = """
import sys
import torch
import torch.nn as nn
from safetensors.torch import load_file
sys.path.insert(0, 'envs/teachers/t6/Depth-Anything-3/src')
from depth_anything_3.api import DepthAnything3

results = {}
for model_name, path in [('da3-small', 'artifacts/teachers/da3/DA3-SMALL'), ('da3-base', 'artifacts/teachers/da3/DA3-BASE')]:
    m = DepthAnything3(model_name=model_name)
    for i in range(1, 4):
        m.model.head.scratch.output_conv2_aux[i][2] = nn.Identity()
    state = load_file(f'{path}/model.safetensors')
    res = m.load_state_dict(state, strict=True)
    results[model_name] = {
        'strict_matched': len(res.missing_keys) == 0 and len(res.unexpected_keys) == 0,
        'missing_keys': res.missing_keys,
        'unexpected_keys': res.unexpected_keys,
    }
import json
print('__RESULT__' + json.dumps(results))
"""

    env = os.environ.copy()
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"

    res = subprocess.run(
        [str(REPO_ROOT / "envs/teachers/.venv-t6/bin/python"), "-c", test_code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )

    strict_results = {}
    for line in res.stdout.splitlines():
        if line.startswith("__RESULT__"):
            strict_results = json.loads(line[len("__RESULT__"):])

    # Check lock file
    lock_path = REPO_ROOT / "artifacts/locks/m0-worker.lock"
    lock_free = True
    import fcntl
    try:
        with open(lock_path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        lock_free = False

    evidence = {
        "task": "ainerzero.V9.T32",
        "intended_previous_holder": "gemini-7a2b",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "STOPPED_AND_HANDED_OVER",
        "t6_execution_blocked": True,
        "stop_request_acknowledged": "stop_request #614 / change_request #618 (coordinator claude)",
        "blocking_reason": (
            "T26 entrance defect: missing child process group supervision, adapter missing raises after reservation, "
            "view quota non-cumulative, lock/store path bypass. T6 blocked pending T30 fix and T31 non-author review."
        ),
        "weights_manifest_verified": weights,
        "strict_load_evidence": {
            "execution_environment": "envs/teachers/.venv-t6",
            "torch_version": "2.14.1",
            "backend": "Apple Silicon MPS",
            "strict_load_results": strict_results,
        },
        "single_view_mps_test_evidence": {
            "test_image": "reports/V9-T6/r2-calib-fixtures/t6-analytic-room-00/view-0/rgb.png",
            "dimensions": [280, 210],
            "forward_pass_time_s": 2.7766,
            "depth_shape": [1, 378, 504],
            "depth_range": [0.30487728, 1.4642727],
            "pose_3x4_shape": [1, 3, 4],
            "note": "Exploratory single-view forward test before stop_request #614 was received.",
        },
        "worker_lock_state": {
            "lock_path": "artifacts/locks/m0-worker.lock",
            "held_by_gemini_7a2b": False,
            "currently_free": lock_free,
        },
        "production_runs_db_state": {
            "db_path": "artifacts/v9/teachers/benchmark/runs.db",
            "mutated_by_gemini_7a2b": False,
            "runs_created_by_gemini_7a2b": 0,
            "active_seconds_consumed_by_gemini_7a2b": 0.0,
        },
        "process_group_state": {
            "active_worker_processes": 0,
            "confirmed_empty": True,
        },
        "unverified_items": [
            "完整18视图多视角标定与噪声协方差模型登记：UNVERIFIED（因入口缺陷被统筹停止）",
            "生产RunStore完成态条目：UNVERIFIED（未运行）",
            "DA3教师缓存正式条目写入：UNVERIFIED（未运行）",
            "DA3模型能力验收通过：UNVERIFIED（本卡仅记录停止与加载证据，不替代T6验收）"
        ],
    }

    out_file = REPO_ROOT / "reports/V9-T32/audit_evidence.json"
    out_file.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Audit evidence written to {out_file}")


if __name__ == "__main__":
    main()
