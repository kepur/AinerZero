"""P214 复核者建议补的运行器测试（MLX，经锁）。不改仓库测试；由 run_proposed_tests.py 复制进隔离副本的
tests/v9/experiments/ 下运行，借用同目录 test_s4p2_runner_native.py 的辅助函数（假仓库、冻结探针、运行、拒绝判断）。
在被审提交上应通过；在变异 M08b、X06 上应失败。"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("mlx.core")

import test_s4p2_runner_native as R  # noqa: E402


def _freeze(root):
    R._frozen(root)
    R._git(root, "add", ".")
    R._git(root, "commit", "-qm", "freeze")


# M08b：final 时，权重文件 SHA 不符必须在写只读一次标记之前拒绝（现有测试只在 smoke 上改权重文件）。
def test_final_refuses_a_changed_weight_file_before_the_marker(tmp_path) -> None:
    root = R._make_root(tmp_path)
    _freeze(root)
    w = root / R.WEIGHTS / "L-int#2.safetensors"           # artifacts/ 不进 git，改它不会让 git 变脏
    b = bytearray(w.read_bytes())
    b[-1] ^= 1
    w.write_bytes(bytes(b))
    R._refused(R._run(root, *R.FINAL, report="reports/final.json"), "weights missing or changed")
    assert not (root / R.ARTS / "FINAL_READ_ONCE.json").exists()
    assert not (root / "reports/final.json").exists()


# X06：剩余墙钟不够评测预留时，final 必须拒绝且不写标记（现有测试没有覆盖这条守卫）。
def test_final_refuses_when_the_wall_clock_left_is_below_the_reserve(tmp_path) -> None:
    root = R._make_root(tmp_path)
    R._frozen(root)
    pre = json.loads((root / R.PREREG).read_text())
    pre["budget"]["eval_reserve_s"] = 10 ** 6
    (root / R.PREREG).write_text(json.dumps(pre))
    R._git(root, "add", ".")
    R._git(root, "commit", "-qm", "freeze with a reserve above the limit")
    R._refused(R._run(root, *R.FINAL, report="reports/final.json"), "the final read is not spent")
    assert not (root / R.ARTS / "FINAL_READ_ONCE.json").exists()
