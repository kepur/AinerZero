"""S5 评测汇总的纯 CPU 契约：世界子集上重算，与直接调用 metrics 一致。"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from ainerzero.v9.experiments.s5 import metrics as M
from ainerzero.v9.experiments.s5.evaluate import metric_value, paired_group_stat, per_world_stat

# Repo root derived from this file, so a copy of the repo tests its own code (tier-1 fix, 11-12).
LIVE = Path(__file__).resolve().parents[3]
# The real working repository; mutation and throwaway roots must never be this path.
REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
CPW = 2


def _pack(scores: np.ndarray, targets: np.ndarray, *, shift: float = 0.0) -> dict:
    n = scores.shape[0]
    logd = np.full((n, 16, 14, 14), shift, dtype=np.float64)
    return {
        "r2_logit": scores,
        "r3_logit": scores - 1.0,
        "r2": targets,
        "r3": targets,
        "r1_logd": logd,
        "r1_target": np.zeros((n, 16, 14, 14)),
        "r1_sky": np.zeros((n, 16, 14, 14)),
        "r1_obj": np.ones((n, 16, 14, 14)),
        "disk_groups": [[] for _ in range(n)],
        "ordering_pairs": [[] for _ in range(n)],
        "world_ids": np.array([0, 1], dtype=np.int64),
        "clips_per_world": CPW,
        "threshold": 0.5,
    }


def _grids() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    scores_a = np.zeros((4, 12, 7), dtype=np.float64)
    scores_b = np.zeros((4, 12, 7), dtype=np.float64)
    targets = np.zeros((4, 12, 7), dtype=np.int64)
    # 世界 0：正例分数高。世界 1：正例分数低，前面堆负例。
    targets[0, 0, 0] = 1
    targets[1, 1, 0] = 1
    targets[2, 0, 0] = 1
    targets[3, 1, 0] = 1
    scores_a[0, 0, 0] = 4.0
    scores_a[1, 1, 0] = 3.0
    scores_a[2, 0, 0] = 0.0
    scores_a[3, 1, 0] = 0.0
    scores_a[2, 0, 1] = 5.0
    scores_b[:] = scores_a
    # 只改世界 1，把正例抬到最前。世界 0 的 AP 差为 0，两个世界一起则不是。
    scores_b[2, 0, 0] = 10.0
    scores_b[3, 1, 0] = 9.0
    return scores_a, scores_b, targets


def test_subset_matches_metrics_on_those_clips():
    scores_a, scores_b, targets = _grids()
    eval_a = _pack(scores_a, targets, shift=0.0)
    eval_b = _pack(scores_b, targets, shift=2.0)
    stat = per_world_stat(eval_a, eval_b, "r2_ap")
    clips = M.expand_world_index(np.array([0]), clips_per_world=CPW)
    expected = M.grid_ap(scores_a[clips], targets[clips]) - M.grid_ap(scores_b[clips], targets[clips])
    assert stat(np.array([0])) == pytest.approx(expected, abs=1e-8)
    assert stat(np.array([0])) == pytest.approx(0.0, abs=1e-8)
    both = per_world_stat(eval_a, eval_b, "r2_ap")(np.array([0, 1]))
    assert both != pytest.approx(0.0, abs=1e-6)


def test_repeated_world_is_expanded_before_metrics(monkeypatch):
    scores_a, scores_b, targets = _grids()
    eval_a = _pack(scores_a, targets)
    eval_b = _pack(scores_b, targets, shift=1.0)
    seen = {}
    real = M.expand_world_index

    def wrapped(idx, clips_per_world=16):
        seen["idx"] = np.asarray(idx).copy()
        seen["cpw"] = clips_per_world
        return real(idx, clips_per_world=clips_per_world)

    monkeypatch.setattr(M, "expand_world_index", wrapped)
    stat = per_world_stat(eval_a, eval_b, "r2_ap")
    worlds = np.array([0, 0])
    got = stat(worlds)
    clips = real(worlds, clips_per_world=CPW)
    expected = M.grid_ap(scores_a[clips], targets[clips]) - M.grid_ap(scores_b[clips], targets[clips])
    assert np.array_equal(seen["idx"], worlds)
    assert seen["cpw"] == CPW
    assert len(clips) == 4
    assert got == pytest.approx(expected, abs=1e-8)
    # 重复之后的段数是两倍，RMSE 用另一套预测确认走的是展开后的下标。
    rmse = per_world_stat(eval_a, eval_b, "r1_rmse")
    assert rmse(worlds) == pytest.approx(-1.0, abs=1e-8)


def test_floor_split_on_a_world_subset():
    scores_a, scores_b, targets = _grids()
    eval_a = _pack(scores_a, targets)
    eval_b = _pack(scores_b, targets)
    eval_a["r1_obj"][:] = 0.0
    eval_a["r1_sky"][:] = 0.0
    eval_b["r1_logd"][:] = 2.0
    eval_b["r1_obj"][:] = 0.0
    eval_b["r1_sky"][:] = 0.0
    # 边界：floor = 1 - sky - obj = 1，整组计入。obj 若改成 >0.5 才算 floor，这组会被丢掉。
    stat = per_world_stat(eval_a, eval_b, "r1_rmse_floor")
    clips = M.expand_world_index(np.array([1]), clips_per_world=CPW)
    rmse_a = M.logd_rmse(
        eval_a["r1_logd"][clips], eval_a["r1_target"][clips],
        sky=eval_a["r1_sky"][clips], obj=eval_a["r1_obj"][clips], split="floor",
    )
    rmse_b = M.logd_rmse(
        eval_b["r1_logd"][clips], eval_b["r1_target"][clips],
        sky=eval_b["r1_sky"][clips], obj=eval_b["r1_obj"][clips], split="floor",
    )
    assert stat(np.array([1])) == pytest.approx(rmse_a - rmse_b, abs=1e-8)
    assert rmse_a == pytest.approx(0.0, abs=1e-8)
    assert rmse_b == pytest.approx(2.0, abs=1e-8)


def test_group_stat_averages_seeds_then_subtracts():
    scores_a, scores_b, targets = _grids()
    group_a = [_pack(scores_a, targets), _pack(scores_a, targets)]
    group_b = [_pack(scores_b, targets)]
    stat = paired_group_stat(group_a, group_b, "r2_ap")
    worlds = np.array([0, 1])
    clips = M.expand_world_index(worlds, clips_per_world=CPW)
    mean_a = M.grid_ap(scores_a[clips], targets[clips])
    mean_b = M.grid_ap(scores_b[clips], targets[clips])
    assert stat(worlds) == pytest.approx(mean_a - mean_b, abs=1e-8)


def test_subtraction_mutation_is_rejected(tmp_path: Path):
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    dest_root = tmp_path / "copy"
    shutil.copytree(LIVE / "src/ainerzero", dest_root / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    src = dest_root / "src/ainerzero/v9/experiments/s5/evaluate.py"
    text = src.read_text(encoding="utf-8")
    old = "return float(metric_value(eval_a, clips, metric) - metric_value(eval_b, clips, metric))"
    assert text.count(old) == 1
    src.write_text(text.replace(old, "return float(metric_value(eval_a, clips, metric) + metric_value(eval_b, clips, metric))"), encoding="utf-8")
    script = tmp_path / "check.py"
    script.write_text(textwrap.dedent("""
        import numpy as np
        from ainerzero.v9.experiments.s5.evaluate import per_world_stat
        scores = np.zeros((2, 12, 7))
        targets = np.zeros((2, 12, 7), dtype=np.int64)
        targets[0, 0, 0] = 1
        scores[0, 0, 0] = 3
        def pack(shift):
            return {
                "r2_logit": scores, "r2": targets, "clips_per_world": 2,
            }
        # 两个模型的 AP 都是 1，差值必须是 0；改成相加会得到 2。
        stat = per_world_stat(pack(0), pack(0), "r2_ap")
        assert stat(np.array([0])) == 0.0
    """), encoding="utf-8")
    ran = subprocess.run(
        [sys.executable, str(script)],
        cwd=dest_root,
        env={"PYTHONPATH": str(dest_root / "src")},
        capture_output=True,
        text=True,
    )
    assert ran.returncode != 0, ran.stdout + ran.stderr
