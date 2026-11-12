"""Adversarial mutation test harness for S5 Phase 1 P235 R3 review (P237).

Tests 4 new adversarial mutations against tests/v9/experiments/test_s5_train_mlx.py
in an isolated temporary directory. None of these mutations overlap with previous
mutations.py or mutations-r2.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
VENV_PY = ROOT / ".venv/bin/python"
LOCK_FILE = ROOT / "artifacts/locks/m0-worker.lock"
HOLD_LOCK = ROOT / "reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py"

mutations = {
    # 1. restore_runs 方向：下一个保留的 token 反向填充
    "J1_restore_backward_fill": {
        "file": "src/ainerzero/v9/experiments/s5/train.py",
        "target": """    out_list = [t_4d[:, 0]]
    curr = t_4d[:, 0]

    for t in range(1, 8):
        mask_t = k_3d[:, t, :, :, None]  # [B, 14, 14, 1]
        curr = mx.where(mask_t, t_4d[:, t], curr)
        out_list.append(curr)

    out = mx.stack(out_list, axis=1)  # [B, 8, 14, 14, d]""",
        "replace": """    out_list = [None] * 8
    curr = t_4d[:, 7]
    out_list[7] = curr

    for t in range(6, -1, -1):
        mask_t = k_3d[:, t, :, :, None]
        curr = mx.where(mask_t, t_4d[:, t], curr)
        out_list[t] = curr

    out = mx.stack(out_list, axis=1)""",
        "test": "tests/v9/experiments/test_s5_train_mlx.py -k test_predict_restores_dropped_positions_from_run_start",
        "desc": "restore_runs 用下一个保留的 token 反向填充而非上一个保留的 token（游程起点）",
    },
    # 2. predict 方向：R2/R3 使用错误的掩码 mask=None
    "J2_predict_r2_r3_mask_none": {
        "file": "src/ainerzero/v9/experiments/s5/train.py",
        "target": """        r2_logit = heads_container["r2"](tokens, mask=mask)
        r3_logit = heads_container["r3"](tokens, mask=mask)""",
        "replace": """        r2_logit = heads_container["r2"](tokens, mask=None)
        r3_logit = heads_container["r3"](tokens, mask=None)""",
        "test": "tests/v9/experiments/test_s5_train_mlx.py",
        "desc": "predict 中 R2、R3 读出头在 RLT 稀疏模式下未传入注意力掩码（mask=None），导致补零 token 参与池化",
    },
    # 3. train_heads 缓存方向：不带 keep 掩码
    "J3_train_heads_cache_no_keep": {
        "file": "src/ainerzero/v9/experiments/s5/train.py",
        "target": "cached_tokens.append((mx.stop_gradient(t_out[0]), mx.stop_gradient(m_out[0]), k_saved))",
        "replace": "cached_tokens.append((mx.stop_gradient(t_out[0]), mx.stop_gradient(m_out[0]), None))",
        "test": "tests/v9/experiments/test_s5_train_mlx.py -k test_train_heads_r1_ignores_dropped_token_values",
        "desc": "train_heads 前置抽取缓存 student token 时丢弃 keep 掩码 (k_saved=None)，导致读出头训练未真正还原",
    },
    # 4. predict 方向：R2 误传 r1_tokens（带还原的特征）而非原始 tokens
    "J4_predict_r2_uses_restored_tokens": {
        "file": "src/ainerzero/v9/experiments/s5/train.py",
        "target": 'r2_logit = heads_container["r2"](tokens, mask=mask)',
        "replace": 'r2_logit = heads_container["r2"](r1_tokens, mask=mask)',
        "test": "tests/v9/experiments/test_s5_train_mlx.py",
        "desc": "predict 中 R2 读出头误传入经 restore_runs 还原后的 r1_tokens 而非学生原始 tokens",
    },
}


def run_test(env_dir: Path, test_spec: str) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{env_dir / 'src'}:{env.get('PYTHONPATH', '')}"

    parts = test_spec.split()
    test_file = env_dir / parts[0]
    extra_args = parts[1:]

    cmd = [
        str(VENV_PY),
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--native-mlx",
        "-rf",
        *extra_args,
        str(test_file),
    ]

    lock_cmd = [str(VENV_PY), str(HOLD_LOCK), str(LOCK_FILE)] + cmd
    while True:
        proc = subprocess.run(lock_cmd, cwd=env_dir, env=env, capture_output=True, text=True)
        if proc.returncode == 75:
            print("Lock busy (75), waiting 5s...", flush=True)
            time.sleep(5)
            continue
        return proc.returncode, proc.stdout + "\n" + proc.stderr


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="p237_mut_") as tmp_str:
        tmp_root = Path(tmp_str)
        assert str(tmp_root) != str(ROOT), "refusing to mutate live repo"
        print(f"Setting up isolated copy at: {tmp_root}", flush=True)

        shutil.copytree(ROOT / "src", tmp_root / "src")
        shutil.copytree(ROOT / "tests", tmp_root / "tests")
        shutil.copy2(ROOT / "pyproject.toml", tmp_root / "pyproject.toml")

        explore_dir = tmp_root / "reports/V9-S5-DESIGN/tier1-explore"
        explore_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "reports/V9-S5-DESIGN/tier1-explore/render.py", explore_dir / "render.py")

        # Verify import isolation
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{tmp_root / 'src'}:{env.get('PYTHONPATH', '')}"
        chk = subprocess.run(
            [str(VENV_PY), "-c", "import ainerzero; print('Imports from:', ainerzero.__file__)"],
            cwd=tmp_root,
            env=env,
            capture_output=True,
            text=True,
        )
        print(chk.stdout.strip(), flush=True)
        assert str(tmp_root) in chk.stdout, "Not imported from isolated copy!"

        # Baseline
        print("\n=== BASELINE: Native MLX Tests (under lock) ===", flush=True)
        rc, out = run_test(tmp_root, "tests/v9/experiments/test_s5_train_mlx.py")
        print(f"test_s5_train_mlx.py baseline rc={rc}", flush=True)
        assert rc == 0, f"Baseline MLX failed: {out}"

        # Run mutations
        print("\n=== RUNNING MLX MUTATIONS (J1 - J4) ===", flush=True)
        results = {}
        for name, info in mutations.items():
            p = tmp_root / info["file"]
            orig = p.read_text(encoding="utf-8")
            assert info["target"] in orig, f"Target not found for {name}"
            p.write_text(orig.replace(info["target"], info["replace"]), encoding="utf-8")
            try:
                rc, out = run_test(tmp_root, info["test"])
                status = "KILLED" if rc != 0 else "SURVIVED"
                results[name] = (status, rc, info["desc"], out)
                first_fail = [l.strip() for l in out.splitlines() if "FAILED" in l or "passed" in l][-2:]
                print(f"[{status}] {name} (rc={rc}): {first_fail}", flush=True)
            finally:
                p.write_text(orig, encoding="utf-8")

        print("\n=== MUTATION TEST SUMMARY ===", flush=True)
        for name, (status, rc, desc, _) in results.items():
            print(f"  {name:35s}: {status} (rc={rc}) - {desc}")


if __name__ == "__main__":
    main()
