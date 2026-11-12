"""Adversarial mutation test harness for S5 Phase 1 R3 review (P233).

Tests 6 new adversarial mutations against tests/v9/experiments/test_s5_labels.py,
test_s5_world.py, and test_s5_student_mlx.py in an isolated temporary directory.
None of these mutations overlap with previous mutations.py, mutations-materialize.py,
mutations-obj.py, or mutations-extra.py.
"""

from __future__ import annotations

import fcntl
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
    # 1. obj 定义与盲区核验 (addendum obj 补充)
    "K1_obj_excludes_non_wall": {
        "file": "src/ainerzero/v9/experiments/s5/labels.py",
        "target": "obj_arr[k, r, c] = float(np.sum(p_ids >= 0)) / (PATCH_SIZE * PATCH_SIZE)",
        "replace": "obj_arr[k, r, c] = float(np.sum(p_ids == 0)) / (PATCH_SIZE * PATCH_SIZE)",
        "test": "tests/v9/experiments/test_s5_labels.py",
        "is_mlx": False,
        "desc": "obj 统计仅包含墙体(0)，漏掉柱子(1..P)与圆盘(100+i)；验证 test_r1_object_share_geometry 的盲区",
    },
    # 2. disk_groups 遮挡比分母
    "K2_disk_groups_unoccluded_wrong_id": {
        "file": "src/ainerzero/v9/experiments/s5/labels.py",
        "target": "unoccluded_px = int(np.sum(single_ids == 100))",
        "replace": "unoccluded_px = int(np.sum(single_ids == disk_oid))",
        "test": "tests/v9/experiments/test_s5_labels.py",
        "is_mlx": False,
        "desc": "单独渲染单圆盘无遮挡像素时误用全局 disk_oid(100+i) 匹配单圆盘局部id(100)，导致 i>0 圆盘遮挡比全为0",
    },
    # 3. ordering_pairs 的 closer 判定
    "K3_ordering_pairs_closer_inverted": {
        "file": "src/ainerzero/v9/experiments/s5/labels.py",
        "target": 'closer = "a" if a["z_median"] < b["z_median"] else ("b" if b["z_median"] < a["z_median"] else "equal")',
        "replace": 'closer = "b" if a["z_median"] < b["z_median"] else ("a" if b["z_median"] < a["z_median"] else "equal")',
        "test": "tests/v9/experiments/test_s5_labels.py",
        "is_mlx": False,
        "desc": "颠倒 ordering_pairs 中谁更近的真值判定；检验生产代码是否真正被测试把关",
    },
    # 4. materialize.py 里 R3 的标签提取
    "K4_mat_r3_uses_r2": {
        "file": "src/ainerzero/v9/experiments/s5/materialize.py",
        "target": "lbl_r3 = r3(ep, c, precomputed_frame=r3_rendered)",
        "replace": "lbl_r3 = r2(ep, c, precomputed_frame=rendered_frames[15])",
        "test": "tests/v9/experiments/test_s5_world.py -k test_materialize_end_to_end_matches_direct_calls",
        "is_mlx": False,
        "desc": "物化时 R3 标签误用段末 R2 占据网格写入；检验物化端到端测试能否拦截",
    },
    # 5. Student 在部分保留时的紧凑表示聚合
    "K5_student_compact_gather_prefix": {
        "file": "src/ainerzero/v9/experiments/s5/student.py",
        "target": "compact_x[b, :k_counts[b]] = x[b, mx.array(indices_list[b])]",
        "replace": "compact_x[b, :k_counts[b]] = x[b, :k_counts[b]]",
        "test": "tests/v9/experiments/test_s5_student_mlx.py -k test_features_layer_index_with_partial_keep",
        "is_mlx": True,
        "desc": "Student 稀疏分支未按保留索引 gather，而是直接取前 k 个 token；破坏位置与时空对应关系",
    },
    # 6. align_loss 的 mask 传递
    "K6_align_loss_drops_mask": {
        "file": "src/ainerzero/v9/experiments/s5/losses.py",
        "target": "return cosine_distill_loss(student_proj, teacher_sg, mask=mask, eps=eps)",
        "replace": "return cosine_distill_loss(student_proj, teacher_sg, mask=None, eps=eps)",
        "test": "tests/v9/experiments/test_s5_student_mlx.py -k test_distill_losses_average_only_inside_the_mask",
        "is_mlx": True,
        "desc": "align_loss 内部调用底层余弦损失时丢弃了 mask 参数，导致无效 token 污染对齐损失",
    },
}


def run_test(env_dir: Path, test_spec: str, is_mlx: bool) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{env_dir / 'src'}:{env.get('PYTHONPATH', '')}"

    parts = test_spec.split()
    test_file = env_dir / parts[0]
    extra_args = parts[1:]

    cmd = [str(VENV_PY), "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if is_mlx:
        cmd.append("--native-mlx")
    cmd.extend(extra_args)
    cmd.append(str(test_file))

    if is_mlx:
        # Wrap with hold_lock.py or acquire lock via flock
        lock_cmd = [str(VENV_PY), str(HOLD_LOCK), str(LOCK_FILE)] + cmd
        # If lock busy, wait and retry
        while True:
            proc = subprocess.run(lock_cmd, cwd=env_dir, env=env, capture_output=True, text=True)
            if proc.returncode == 75:
                print("Lock busy (75), waiting 5s...", flush=True)
                time.sleep(5)
                continue
            return proc.returncode, proc.stdout + "\n" + proc.stderr
    else:
        proc = subprocess.run(cmd, cwd=env_dir, env=env, capture_output=True, text=True)
        return proc.returncode, proc.stdout + "\n" + proc.stderr


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="p233_mut_") as tmp_str:
        tmp_root = Path(tmp_str)
        print(f"Setting up isolated copy at: {tmp_root}", flush=True)
        shutil.copytree(ROOT / "src", tmp_root / "src")
        shutil.copy2(ROOT / "pyproject.toml", tmp_root / "pyproject.toml")

        (tmp_root / "tests").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "tests/conftest.py", tmp_root / "tests/conftest.py")
        if (ROOT / "tests/_hermetic_site").exists():
            shutil.copytree(ROOT / "tests/_hermetic_site", tmp_root / "tests/_hermetic_site")

        (tmp_root / "tests/v9/experiments").mkdir(parents=True, exist_ok=True)
        for tf in (ROOT / "tests/v9/experiments").glob("test_s5_*.py"):
            shutil.copy2(tf, tmp_root / "tests/v9/experiments" / tf.name)

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

        # Baseline CPU run
        print("\n=== BASELINE: CPU Tests ===", flush=True)
        rc, out = run_test(tmp_root, "tests/v9/experiments/test_s5_labels.py", is_mlx=False)
        print(f"test_s5_labels.py baseline rc={rc}")
        assert rc == 0, f"Baseline labels failed: {out}"

        # Run CPU mutations
        print("\n=== RUNNING CPU MUTATIONS (K1 - K4) ===", flush=True)
        results = {}
        for name, info in mutations.items():
            if info["is_mlx"]:
                continue
            p = tmp_root / info["file"]
            orig = p.read_text(encoding="utf-8")
            assert info["target"] in orig, f"Target not found for {name}"
            p.write_text(orig.replace(info["target"], info["replace"]), encoding="utf-8")
            try:
                rc, out = run_test(tmp_root, info["test"], is_mlx=False)
                status = "KILLED" if rc != 0 else "SURVIVED"
                results[name] = (status, rc, info["desc"], out)
                first_fail = [l.strip() for l in out.splitlines() if "FAILED" in l or "passed" in l][-2:]
                print(f"[{status}] {name} (rc={rc}): {first_fail}", flush=True)
            finally:
                p.write_text(orig, encoding="utf-8")

        # Baseline MLX run
        print("\n=== BASELINE: Native MLX Tests (under lock) ===", flush=True)
        rc, out = run_test(tmp_root, "tests/v9/experiments/test_s5_student_mlx.py -k test_distill_losses_average_only_inside_the_mask", is_mlx=True)
        print(f"test_s5_student_mlx.py baseline rc={rc}", flush=True)
        assert rc == 0, f"Baseline MLX failed: {out}"

        # Run MLX mutations
        print("\n=== RUNNING MLX MUTATIONS (K5 - K6) ===", flush=True)
        for name, info in mutations.items():
            if not info["is_mlx"]:
                continue
            p = tmp_root / info["file"]
            orig = p.read_text(encoding="utf-8")
            assert info["target"] in orig, f"Target not found for {name}"
            p.write_text(orig.replace(info["target"], info["replace"]), encoding="utf-8")
            try:
                rc, out = run_test(tmp_root, info["test"], is_mlx=True)
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
