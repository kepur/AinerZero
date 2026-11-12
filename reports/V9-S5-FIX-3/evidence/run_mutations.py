"""P241 源码坏对照验证脚本。

严格遵守规约：
1. 先断言目标目录不是实盘仓库 (/Users/mac/AinerWorkFlow/AinerZero)；
2. 副本通过 `git archive HEAD` 导出到临时目录，再覆盖当前待测的 P241 改动文件；
3. 逐条注入源码突变，运行对应的生产测试，确认全部被测试杀死（returncode != 0）。
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

LIVE_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PYTHON_BIN = LIVE_REPO / ".venv/bin/python"
HOLD_LOCK = LIVE_REPO / "reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py"
LOCK_PATH = LIVE_REPO / "artifacts/locks/m0-worker.lock"

MODIFIED_FILES = [
    "src/ainerzero/v9/experiments/s5/tokens.py",
    "src/ainerzero/v9/experiments/s5/student.py",
    "src/ainerzero/v9/experiments/s5/data.py",
    "src/ainerzero/v9/experiments/s5/train.py",
    "tests/v9/experiments/test_s5_tokens.py",
    "tests/v9/experiments/test_s5_student_mlx.py",
    "tests/v9/experiments/test_s5_data.py",
    "tests/v9/experiments/test_s5_train_mlx.py",
]

MUTATIONS = [
    {
        "id": "M1_rlt_keep_fast_l1_instead_of_linf",
        "file": "src/ainerzero/v9/experiments/s5/tokens.py",
        "old": "diff_max = np.max(np.abs(arr[:, 1:] - arr[:, :-1]), axis=-1)",
        "new": "diff_max = np.mean(np.abs(arr[:, 1:] - arr[:, :-1]), axis=-1)",
        "test": "tests/v9/experiments/test_s5_tokens.py::test_rlt_keep_fast_matches_rlt_keep_elementwise",
        "native_mlx": False,
    },
    {
        "id": "M2_rlt_keep_fast_run_len_always_one",
        "file": "src/ainerzero/v9/experiments/s5/tokens.py",
        "old": "run_len = np.where(keep, next_kept - t_idx, 0)",
        "new": "run_len = np.where(keep, 1, 0)",
        "test": "tests/v9/experiments/test_s5_tokens.py::test_rlt_keep_fast_matches_rlt_keep_elementwise",
        "native_mlx": False,
    },
    {
        "id": "M3_student_sparse_sort_key_inverted",
        "file": "src/ainerzero/v9/experiments/s5/student.py",
        "old": "sort_key = (1 - mask_int) * self.num_tokens + idx_range",
        "new": "sort_key = mask_int * self.num_tokens + idx_range",
        "test": "tests/v9/experiments/test_s5_student_mlx.py::test_vectorized_sparse_branch_matches_legacy_reference_elementwise",
        "native_mlx": True,
    },
    {
        "id": "M4_student_sparse_attn_mask_unmasked_padding",
        "file": "src/ainerzero/v9/experiments/s5/student.py",
        "old": "mx.array(-1e9, dtype=x.dtype),",
        "new": "mx.array(0.0, dtype=x.dtype),",
        "test": "tests/v9/experiments/test_s5_student_mlx.py::test_vectorized_sparse_branch_matches_legacy_reference_elementwise",
        "native_mlx": True,
    },
    {
        "id": "M5_student_sparse_ungather_dropped_to_zero_index",
        "file": "src/ainerzero/v9/experiments/s5/student.py",
        "old": "mx.cumsum(mask_int, axis=1) - 1,\n            k_max,",
        "new": "mx.cumsum(mask_int, axis=1) - 1,\n            0,",
        "test": "tests/v9/experiments/test_s5_student_mlx.py::test_vectorized_sparse_branch_matches_legacy_reference_elementwise",
        "native_mlx": True,
    },
    {
        "id": "M6_student_sparse_layer_features_wrong_layer",
        "file": "src/ainerzero/v9/experiments/s5/student.py",
        "old": "self._layer_features.append(\n                mx.take_along_axis(padded_layer, ungather_idx, axis=1)\n            )",
        "new": "self._layer_features.append(x)",
        "test": "tests/v9/experiments/test_s5_student_mlx.py::test_vectorized_sparse_branch_matches_legacy_reference_elementwise",
        "native_mlx": True,
    },
    {
        "id": "M7_data_rlt_cache_key_missing_tau",
        "file": "src/ainerzero/v9/experiments/s5/data.py",
        "old": 'rlt_key = f"rlt:{clip_file.resolve()}:tau={tau_val!r}"',
        "new": 'rlt_key = f"rlt:{clip_file.resolve()}"',
        "test": "tests/v9/experiments/test_s5_data.py::test_rlt_keep_cached_by_clip_and_tau",
        "native_mlx": False,
    },
    {
        "id": "M8_data_rlt_cache_put_disabled",
        "file": "src/ainerzero/v9/experiments/s5/data.py",
        "old": "cache.put(rlt_key, cached_rlt, int(keep.nbytes + run_len.nbytes))",
        "new": "pass",
        "test": "tests/v9/experiments/test_s5_data.py::test_rlt_keep_cached_by_clip_and_tau",
        "native_mlx": False,
    },
    {
        "id": "M9_train_distill_recomputes_rlt_every_step",
        "file": "src/ainerzero/v9/experiments/s5/train.py",
        "old": 'keep_list.append(s_item["keep"])',
        "new": 'keep_list.append(rlt_keep_fast(s_item["patches"], cfg.tau)[0])',
        "test": "tests/v9/experiments/test_s5_train_mlx.py::test_train_and_predict_cache_rlt_keep_by_tau",
        "native_mlx": True,
    },
    {
        "id": "M10_train_supervised_bypasses_active_cache",
        "file": "src/ainerzero/v9/experiments/s5/train.py",
        "old": "                    teachers=teachers if cfg.eta is not None else None,\n                    tau=cfg.tau,\n                    cache=active_cache,",
        "new": "                    teachers=teachers if cfg.eta is not None else None,\n                    tau=cfg.tau,\n                    cache=None,",
        "test": "tests/v9/experiments/test_s5_train_mlx.py::test_train_and_predict_cache_rlt_keep_by_tau",
        "native_mlx": True,
    },
]


def export_repo_copy(dst_dir: Path) -> None:
    dst_resolved = dst_dir.resolve()
    assert dst_resolved != LIVE_REPO, f"Refusing to mutate live repo: {dst_resolved}"
    assert not str(dst_resolved).startswith(str(LIVE_REPO) + "/"), (
        f"Target copy must be outside live repo: {dst_resolved}"
    )
    dst_dir.mkdir(parents=True, exist_ok=True)
    p_arc = subprocess.Popen(
        ["git", "archive", "HEAD"],
        cwd=str(LIVE_REPO),
        stdout=subprocess.PIPE,
    )
    subprocess.run(["tar", "-x", "-C", str(dst_dir)], stdin=p_arc.stdout, check=True)
    assert p_arc.wait() == 0

    for rel in MODIFIED_FILES:
        src_file = LIVE_REPO / rel
        dst_file = dst_dir / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)


def run_pytest(copy_dir: Path, test_spec: str, native_mlx: bool) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin",
        "PYTHONPATH": str(copy_dir / "src"),
        "HOME": str(Path.home()),
    }
    cmd = [
        str(PYTHON_BIN),
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    if native_mlx:
        cmd.append("--native-mlx")
    cmd.append(test_spec)
    return subprocess.run(cmd, cwd=str(copy_dir), env=env, capture_output=True, text=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="p241_mutations_") as tmp:
        copy_dir = Path(tmp) / "repo_copy"
        assert copy_dir.resolve() != LIVE_REPO
        export_repo_copy(copy_dir)

        results = []
        for mut in MUTATIONS:
            target_file = copy_dir / mut["file"]
            assert target_file.resolve().parent != (LIVE_REPO / mut["file"]).resolve().parent
            orig_text = target_file.read_text(encoding="utf-8")
            assert orig_text.count(mut["old"]) == 1, (
                f"{mut['id']}: expected 1 occurrence of {mut['old']!r}, got {orig_text.count(mut['old'])}"
            )
            try:
                target_file.write_text(orig_text.replace(mut["old"], mut["new"], 1), encoding="utf-8")
                res = run_pytest(copy_dir, mut["test"], mut["native_mlx"])
                killed = res.returncode != 0
                print(f"[{mut['id']}] rc={res.returncode} killed={killed}")
                results.append(
                    {
                        "id": mut["id"],
                        "file": mut["file"],
                        "test": mut["test"],
                        "native_mlx": mut["native_mlx"],
                        "returncode": res.returncode,
                        "killed": killed,
                        "tail": (res.stdout + "\n" + res.stderr).strip()[-400:],
                    }
                )
                assert killed, f"Mutation {mut['id']} was NOT killed!"
            finally:
                target_file.write_text(orig_text, encoding="utf-8")

        out_path = LIVE_REPO / "reports/V9-S5-FIX-3/evidence/mutations_results.json"
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"ALL {len(results)} MUTATIONS KILLED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
