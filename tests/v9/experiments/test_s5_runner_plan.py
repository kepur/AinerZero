"""S5 冻结前运行器的纯 CPU 部分：格清单、选 A*、调参平局、功效，以及 dry-run 不拿锁。"""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

# Repo root derived from this file, so a copy of the repo tests its own code (tier-1 fix, 11-12).
LIVE = Path(__file__).resolve().parents[3]
# The real working repository; mutation and throwaway roots must never be this path.
REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PLAN_PATH = LIVE / "reports/V9-S5-PHASE1/plan_s5p1.py"
RUNNER = LIVE / "reports/V9-S5-PHASE1/run_s5p1.py"


def _plan():
    spec = importlib.util.spec_from_file_location("plan_s5p1_live", PLAN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage_cell_counts_match_the_design_grid():
    plan = _plan()
    probe = plan.stage_cells("probe")
    tune = plan.stage_cells("dev-tune")
    distill = plan.stage_cells("dev-distill")
    assert sum(cell["kind"] == "distill" for cell in probe) == 3
    assert sum(cell["arm"] == "A0" and cell["kind"] == "supervised" for cell in probe) == 3
    assert any(cell["arm"] == "A4" and cell.get("eta") == 0.5 for cell in probe)
    assert any(cell["arm"] == "A0-R" and cell.get("tau") == 0.02 for cell in probe)
    assert sum(cell["kind"] == "heads" for cell in probe) == 9
    assert len(tune) == 2 + 6 + 3
    assert sum(cell["kind"] == "distill" for cell in distill) == 6
    assert sum(cell["kind"] == "heads" for cell in distill) == 54
    assert sum(cell["arm"] == "A0" for cell in distill) == 3
    assert all(not str(cell["partition"]).startswith("s5p1-final") for cell in probe + tune + distill)
    assert all(cell["steps"] >= 1 for cell in probe)


def test_select_a_star_tie_takes_the_earlier_arm():
    plan = _plan()
    rows = []
    for arm, score in (("A1", 0.50), ("A2", 0.90), ("A3", 0.20)):
        for distill_seed in (0, 1):
            for readout_seed in (0, 1, 2):
                rows.append({
                    "arm": arm, "distill_seed": distill_seed,
                    "readout_seed": readout_seed, "r2_ap": score,
                })
    assert plan.select_a_star(rows)["arm"] == "A2"
    tied = []
    for arm in ("A1", "A2", "A3"):
        for distill_seed in (0, 1):
            for readout_seed in (0, 1, 2):
                tied.append({
                    "arm": arm, "distill_seed": distill_seed,
                    "readout_seed": readout_seed, "r2_ap": 0.4,
                })
    chosen = plan.select_a_star(tied)
    assert chosen["arm"] == "A1"
    assert chosen["tied"] == ["A1", "A2", "A3"]


def test_tune_tie_takes_the_smaller_value():
    plan = _plan()
    rows = [
        {"lr": 1e-3, "r2_ap": 0.4},
        {"lr": 3e-4, "r2_ap": 0.4},
        {"lr": 1e-3, "r2_ap": 0.2},
    ]
    assert plan.choose_value(rows, "lr")["value"] == pytest.approx(3e-4)
    eta_rows = [{"eta": 1.0, "r2_ap": 0.7}, {"eta": 0.1, "r2_ap": 0.7}, {"eta": 0.5, "r2_ap": 0.3}]
    assert plan.choose_smaller(eta_rows, "eta")["value"] == pytest.approx(0.1)


def test_power_uses_equal_tail_and_caps_at_96():
    plan = _plan()
    sigma = 0.12
    got = plan.worlds_for_power(sigma)
    z_ci = plan.normal_ppf(1.0 - (0.05 / 3.0) / 2.0)
    z_pow = plan.normal_ppf(0.80)
    expect = math.ceil((sigma * (z_ci + z_pow) / 0.05) ** 2)
    assert got["n_uncapped"] == expect
    assert got["n_worlds"] == expect
    assert got["level"] == pytest.approx(1.0 - 0.05 / 3.0)
    wide = plan.worlds_for_power(10.0)
    assert wide["n_uncapped"] > 96
    assert wide["n_worlds"] == 96
    assert wide["capped"] is True
    # 不把分位减半时，临界值更小，算出的世界数不该和等尾公式相同。
    z_wrong = plan.normal_ppf(1.0 - (0.05 / 3.0))
    wrong_n = math.ceil((sigma * (z_wrong + z_pow) / 0.05) ** 2)
    assert wrong_n != expect


def test_tie_order_mutation_is_rejected(tmp_path: Path):
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    text = PLAN_PATH.read_text(encoding="utf-8")
    old = 'ARM_ORDER = ("A1", "A2", "A3")'
    assert text.count(old) == 1
    dest = tmp_path / "plan_s5p1.py"
    dest.write_text(text.replace(old, 'ARM_ORDER = ("A3", "A2", "A1")', 1), encoding="utf-8")
    script = tmp_path / "check.py"
    script.write_text(
        "import importlib.util\n"
        "from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('plan_bad', Path('plan_s5p1.py'))\n"
        "plan = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(plan)\n"
        "rows = [{'arm': arm, 'distill_seed': 0, 'readout_seed': 0, 'r2_ap': 1.0} for arm in ('A1','A2','A3')]\n"
        "assert plan.select_a_star(rows)['arm'] == 'A1'\n",
        encoding="utf-8",
    )
    ran = subprocess.run([sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True)
    assert ran.returncode != 0, ran.stdout + ran.stderr


def test_dry_run_prints_the_grid_without_taking_the_lock(tmp_path: Path):
    ran = subprocess.run(
        [sys.executable, str(RUNNER), "--stage", "probe", "--dry-run"],
        cwd=LIVE, capture_output=True, text=True, timeout=60,
    )
    assert ran.returncode == 0, ran.stderr[-1500:]
    payload = json.loads(ran.stdout)
    assert payload["dry_run"] is True
    assert payload["takes_lock"] is False
    assert payload["n_cells"] == 17
    assert payload["dev_uses"] == 1


def test_dry_run_dev_distill_heads_wall_clock_estimation():
    plan = _plan()
    distill_cells = plan.stage_cells("dev-distill")
    summary = plan.summarize_stage("dev-distill", distill_cells)

    # 验证 54 个读出头按「缓存一次学生特征 + 只训读出头」估算
    heads_cells = [c for c in distill_cells if c["kind"] == "heads"]
    assert len(heads_cells) == 54
    assert "heads_wall_est_h" in summary
    assert "heads_design_ref_h" in summary
    assert summary["heads_design_ref_h"] == 0.75
    # 估算值与设计 §6 的 0.75h 高度吻合（0.7h - 0.9h），而不是全量 ViT 反传的 >8h
    assert 0.70 <= summary["heads_wall_est_h"] <= 0.90
    assert summary["wall_h_est"] < 4.0, f"Total stage wall clock should be < 4.0h, got {summary['wall_h_est']}"
    assert "heads_note" in summary


def test_dry_run_uses_probe_step_compute_and_cached_data_estimate():
    plan = _plan()
    assert plan.STEP_COMPUTE_S == pytest.approx(0.16)
    assert plan.CACHED_STEP_DATA_S > 0.0
    assert plan.COLD_READ_S_PER_CLIP > 0.0

    # 验证全量蒸馏单格 (4000 段, 15 轮, 7500 步) 的墙钟 = 4000 * COLD_READ + 7500 * (0.16 + CACHED_STEP_DATA)
    expected_distill_s = 4000 * plan.COLD_READ_S_PER_CLIP + 7500 * (plan.STEP_COMPUTE_S + plan.CACHED_STEP_DATA_S)
    assert plan.wall_seconds(4000, 15, kind="distill") == pytest.approx(expected_distill_s)

    for stage, expected_design_h in (("probe", 0.5), ("dev-tune", 1.6), ("dev-distill", 3.22)):
        ran = subprocess.run(
            [sys.executable, str(RUNNER), "--stage", stage, "--dry-run"],
            cwd=LIVE, capture_output=True, text=True, timeout=60,
        )
        assert ran.returncode == 0, ran.stderr[-1500:]
        payload = json.loads(ran.stdout)
        assert payload["design_wall_h"] == pytest.approx(expected_design_h)
        assert payload["step_compute_s"] == pytest.approx(0.16)
        assert payload["lab_subset_seed"] == 20261112

