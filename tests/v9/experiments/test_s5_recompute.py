"""S5 登记运行独立复算契约测试（纯 CPU，默认入口）。

覆盖：
- 独立 R2 AP / R1 RMSE 与生产 metrics 逐值一致；
- 合成逐段预测下门必过 / 必不过 / 恰在阈值；
- 自助法同种子可复现；
- 种子平均顺序：先读出后蒸馏；
- 坏对照（副本改源码）：平均顺序反转、Bonferroni→95%、GA 不插值，相关断言失败。
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

from ainerzero.v9.experiments.s5 import metrics as M

LIVE = Path(__file__).resolve().parents[3]
REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
RECOMPUTE_PATH = LIVE / "reports/V9-S5-PHASE1/recompute_s5p1_final.py"

CPW = 2
N_WORLD = 4
N_BOOT = 64
BOOT_SEED = 20261114


def _load_recompute(path: Path | None = None):
    path = path or RECOMPUTE_PATH
    spec = importlib.util.spec_from_file_location(f"recompute_s5p1_{path.stat().st_mtime_ns}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------------
# 合成 eval / 登记运行目录
# ------------------------------------------------------------------------------------------------


def _eval_with_pos_rank(n_worlds: int, cpw: int, rank: int, *, rmse: float = 0.5, keep: float = 1.0) -> dict:
    """每个段一个正例；通过控制负例分数使该正例排在第 ``rank`` 位（1-based），AP=1/rank。"""
    assert 1 <= rank <= 12 * 7
    n = n_worlds * cpw
    targets = np.zeros((n, 12, 7), dtype=np.int64)
    scores = np.zeros((n, 12, 7), dtype=np.float64)
    # 单元格线性下标 0..83；正例放在 0；前 rank-1 个负例分数更高
    for i in range(n):
        targets[i, 0, 0] = 1
        scores[i, 0, 0] = 0.0  # 正例分数
        flat = scores[i].ravel()
        # 其余默认 -1（低于正例）
        flat[:] = -1.0
        flat[0] = 0.0
        for k in range(1, rank):
            flat[k] = float(rank - k + 1)  # 全部 > 0
        scores[i] = flat.reshape(12, 7)

    logd = np.full((n, 16, 14, 14), rmse, dtype=np.float64)
    target = np.zeros((n, 16, 14, 14), dtype=np.float64)
    # 非天空：有限 target；误差恒为 rmse
    pred = target + rmse
    return {
        "r2_logit": scores,
        "r3_logit": scores.copy(),
        "r2": targets,
        "r3": targets.copy(),
        "r1_logd": pred,
        "r1_target": target,
        "r1_sky": np.zeros((n, 16, 14, 14), dtype=np.float64),
        "r1_obj": np.ones((n, 16, 14, 14), dtype=np.float64),
        "world_ids": np.arange(n_worlds, dtype=np.int64),
        "clips_per_world": cpw,
        "keep_rate_per_clip": np.full(n, keep, dtype=np.float64),
    }


def _ap_of(ev: dict) -> float:
    return float(M.grid_ap(ev["r2_logit"], ev["r2"]))


def _write_npz(path: Path, ev: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "r1_logd": ev["r1_logd"],
        "r2_logit": ev["r2_logit"],
        "r3_logit": ev["r3_logit"],
        "r1_target": ev["r1_target"],
        "r1_sky": ev["r1_sky"],
        "r1_obj": ev["r1_obj"],
        "r2": ev["r2"],
        "r3": ev["r3"],
        "world_ids": ev["world_ids"],
        "clips_per_world": np.asarray(ev["clips_per_world"], dtype=np.int64),
    }
    if "keep_rate_per_clip" in ev:
        payload["keep_rate_per_clip"] = ev["keep_rate_per_clip"]
    np.savez_compressed(path, **payload)


def _prereg_doc(**overrides) -> dict:
    doc = {
        "a_star": "A2",
        "boot_seed": BOOT_SEED,
        "n_boot": N_BOOT,
        "distill_seeds": [0, 1],
        "readout_seeds": [0, 1, 2],
        "supervised_seeds": [0, 1, 2],
        "gates": {
            "GT1": {"effect": 0.05, "level": 1.0 - 0.05 / 3.0},
            "GT2": {"effect": 0.03, "level": 1.0 - 0.05 / 3.0},
            "GT3": {"margin_frac": 0.05, "level": 1.0 - 0.05 / 3.0},
            "GA": {"target_frac": 0.95, "ratio_max": 0.7},
            "GR": {
                "keep_max": 0.8,
                "wall_drop_min": 0.15,
                "ap_drop_ci_max": 0.03,
                "ap_level": 0.95,
            },
        },
        "ga_cap": 1600,
    }
    doc.update(overrides)
    return doc


def _ga_curve_json(steps, ap, cap=1600) -> dict:
    return {"steps": list(steps), "r2_ap": list(ap), "cap": cap}


def _build_run(
    root: Path,
    *,
    star_rank: int,
    a0_rank: int,
    csh_rank: int,
    star_rmse: float,
    a0_rmse: float,
    r_rank: int | None = None,
    keep: float = 0.7,
    wall_r: float = 0.20,
    wall_csh: float = 0.30,
    ga_a0=None,
    ga_a4=None,
    include_l512: bool = True,
) -> Path:
    """构造最小登记运行目录（只含复算需要的文件）。"""
    assert root.resolve() not in (LIVE, REAL_REPO)
    run = root / "run"
    metrics = run / "metrics"
    timing = run / "timing"
    metrics.mkdir(parents=True)
    timing.mkdir(parents=True)

    part = "s5p1-final"
    star = _eval_with_pos_rank(N_WORLD, CPW, star_rank, rmse=star_rmse, keep=1.0)
    a0 = _eval_with_pos_rank(N_WORLD, CPW, a0_rank, rmse=a0_rmse, keep=1.0)
    csh = _eval_with_pos_rank(N_WORLD, CPW, csh_rank, rmse=a0_rmse, keep=1.0)
    r_ev = _eval_with_pos_rank(N_WORLD, CPW, r_rank or star_rank, rmse=star_rmse, keep=keep)

    for d in (0, 1):
        for r in (0, 1, 2):
            _write_npz(metrics / f"heads-A2-d{d}-L64-r{r}.{part}.npz", star)
            _write_npz(metrics / f"heads-C-sh-d{d}-L64-r{r}.{part}.npz", csh)
            if include_l512:
                _write_npz(metrics / f"heads-A2-d{d}-L512-r{r}.{part}.npz", star)
                _write_npz(metrics / f"heads-R-d{d}-L512-r{r}.{part}.npz", r_ev)
        (timing / f"distill-R-s{d}.json").write_text(
            json.dumps({"seconds_per_step": wall_r}), encoding="utf-8"
        )
        (timing / f"distill-C-sh-s{d}.json").write_text(
            json.dumps({"seconds_per_step": wall_csh}), encoding="utf-8"
        )

    for s in (0, 1, 2):
        _write_npz(metrics / f"A0-L64-s{s}.{part}.npz", a0)
        if include_l512:
            _write_npz(metrics / f"A0-L512-s{s}.{part}.npz", a0)

    # GA curves
    if ga_a0 is None:
        # 末次 AP 中位 0.62 → 达标线 0.589；三种子步数 1200/1300/1400
        ga_a0 = [
            ([100 * i for i in range(1, 17)], [0.40 + 0.015 * i for i in range(16)]),
            ([100 * i for i in range(1, 17)], [0.38 + 0.016 * i for i in range(16)]),
            ([100 * i for i in range(1, 17)], [0.36 + 0.017 * i for i in range(16)]),
        ]
        # 覆盖为可控曲线（与 test_s5_metrics P228 类似）
        steps = [100 * (i + 1) for i in range(16)]
        ga_a0 = [
            (steps, np.linspace(0.40, 0.62, 16).tolist()),
            (steps, np.linspace(0.40, 0.62, 16).tolist()),
            (steps, np.linspace(0.40, 0.62, 16).tolist()),
        ]
    if ga_a4 is None:
        steps = [100 * (i + 1) for i in range(16)]
        # 更快到达 → 通过
        ga_a4 = [
            (steps, np.linspace(0.50, 0.70, 16).tolist()),
            (steps, np.linspace(0.50, 0.70, 16).tolist()),
            (steps, np.linspace(0.50, 0.70, 16).tolist()),
        ]

    for s, (steps, ap) in enumerate(ga_a0):
        stem = f"ckpt-A0-L512-s{s}.{part}"
        _write_npz(metrics / f"{stem}.npz", a0)
        (metrics / f"{stem}.json").write_text(json.dumps(_ga_curve_json(steps, ap)), encoding="utf-8")
    for s, (steps, ap) in enumerate(ga_a4):
        stem = f"ckpt-A4-L512-s{s}.{part}"
        _write_npz(metrics / f"{stem}.npz", a0)
        (metrics / f"{stem}.json").write_text(json.dumps(_ga_curve_json(steps, ap)), encoding="utf-8")

    (run / "PREREG.json").write_text(json.dumps(_prereg_doc()), encoding="utf-8")
    return run


# ------------------------------------------------------------------------------------------------
# 独立实现核对
# ------------------------------------------------------------------------------------------------


def test_independent_grid_ap_matches_production():
    R = _load_recompute()
    rng = np.random.default_rng(0)
    for _ in range(12):
        scores = rng.standard_normal((3, 12, 7))
        targets = rng.integers(0, 2, size=(3, 12, 7))
        a = R.independent_grid_ap(scores, targets)
        b = M.grid_ap(scores, targets)
        if math.isnan(a) and math.isnan(b):
            continue
        assert a == pytest.approx(b, abs=1e-15)


def test_independent_logd_rmse_matches_production():
    R = _load_recompute()
    rng = np.random.default_rng(1)
    for _ in range(8):
        pred = rng.normal(size=(2, 16, 14, 14))
        target = rng.normal(size=(2, 16, 14, 14))
        target[0, 0, 0, 0] = np.nan
        a = R.independent_logd_rmse(pred, target)
        b = M.logd_rmse(pred, target)
        assert a == pytest.approx(b, abs=1e-15)


# ------------------------------------------------------------------------------------------------
# 种子平均顺序
# ------------------------------------------------------------------------------------------------


def test_seed_mean_readouts_then_distills_order():
    R = _load_recompute()
    # 非齐备网格：正确顺序与反向顺序结果不同
    values = {
        0: {0: 1.0, 1: 2.0, 2: 3.0},  # mean 2
        1: {0: 10.0, 1: 10.0},  # mean 10；缺 r=2
    }
    correct = R.mean_over_readouts_then_distills(values)
    wrong = R.mean_over_distills_then_readouts(values)
    assert correct == pytest.approx(6.0)
    assert wrong == pytest.approx((5.5 + 6.0 + 3.0) / 3.0)
    assert correct != pytest.approx(wrong)
    assert R.SEED_MEAN is R.mean_over_readouts_then_distills


# ------------------------------------------------------------------------------------------------
# 门：必过 / 必不过 / 阈值
# ------------------------------------------------------------------------------------------------


def test_gates_must_pass(tmp_path: Path):
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    # AP*: rank1 → 1.0；A0 rank20 → 0.05；差 0.95
    # C-sh rank10 → 0.1；差 0.9
    # RMSE* 0.10 vs A0 0.50 → 差 -0.40，上界 << 0.05*0.50
    run = _build_run(
        tmp_path,
        star_rank=1,
        a0_rank=20,
        csh_rank=10,
        star_rmse=0.10,
        a0_rmse=0.50,
        r_rank=1,
        keep=0.70,
        wall_r=0.20,
        wall_csh=0.30,
    )
    out = R.recompute_all(run)
    assert out["gates"]["GT1"]["passed"] is True
    assert out["gates"]["GT2"]["passed"] is True
    assert out["gates"]["GT3"]["passed"] is True
    assert out["gates"]["GA"]["passed"] is True
    assert out["gates"]["GR"]["passed"] is True
    # 写出并与自身比对应无差异
    gates_path = run / "gates.json"
    gates_path.write_text(json.dumps({"gates": out["gates"]}, allow_nan=True), encoding="utf-8")
    diffs = R.compare_gates(out, json.loads(gates_path.read_text(encoding="utf-8")))
    assert diffs == []


def test_gates_must_fail(tmp_path: Path):
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    steps = [100 * (i + 1) for i in range(16)]
    # A4 更慢 → GA 失败；教师更差 → GT 失败；keep 过高、墙钟无降、AP 大跌 → GR 失败
    slow = [(steps, np.linspace(0.20, 0.40, 16).tolist())] * 3
    fast_a0 = [(steps, np.linspace(0.40, 0.62, 16).tolist())] * 3
    run = _build_run(
        tmp_path,
        star_rank=20,  # AP 0.05
        a0_rank=1,  # AP 1.0 → 差负
        csh_rank=1,
        star_rmse=1.0,
        a0_rmse=0.1,  # A* 差很多 → GT3 失败
        r_rank=40,  # AP 大跌
        keep=0.95,
        wall_r=0.30,
        wall_csh=0.30,
        ga_a0=fast_a0,
        ga_a4=slow,
    )
    out = R.recompute_all(run)
    assert out["gates"]["GT1"]["passed"] is False
    assert out["gates"]["GT2"]["passed"] is False
    assert out["gates"]["GT3"]["passed"] is False
    assert out["gates"]["GA"]["passed"] is False
    assert out["gates"]["GR"]["passed"] is False


def test_gates_at_threshold(tmp_path: Path):
    """恰在阈值：GT1 的 effect 贴齐点估计；GA 比值=0.7；GR keep=0.8。"""
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    a0_curves = []
    for hit in (900.0, 1000.0, 1100.0):
        a0_curves.append(([100.0, 500.0, hit, 1500.0, 1600.0], [0.40, 0.50, 0.589, 0.62, 0.62]))
    a4_curves = []
    for hit in (600.0, 700.0, 800.0):
        a4_curves.append(([100.0, 400.0, hit, 1500.0, 1600.0], [0.40, 0.50, 0.589, 0.62, 0.62]))

    run = _build_run(
        tmp_path,
        star_rank=2,
        a0_rank=6,
        csh_rank=4,
        star_rmse=0.50,
        a0_rmse=0.50,
        r_rank=2,
        keep=0.8,
        wall_r=0.20,
        wall_csh=0.30,
        ga_a0=a0_curves,
        ga_a4=a4_curves,
    )
    # 先算一次拿 GT1 点估计，再把 effect 钉到该点（恰在阈值）
    probe = R.recompute_all(run)
    point = float(probe["gates"]["GT1"]["point_estimate"])
    assert point > 0.0
    preg = json.loads((run / "PREREG.json").read_text(encoding="utf-8"))
    preg["gates"]["GT1"]["effect"] = point
    (run / "PREREG.json").write_text(json.dumps(preg), encoding="utf-8")

    out = R.recompute_all(run)
    assert out["gates"]["GT1"]["point_estimate"] == pytest.approx(point, abs=1e-12)
    assert out["gates"]["GT1"]["point_estimate"] == pytest.approx(out["gates"]["GT1"]["effect"], abs=1e-12)
    assert out["gates"]["GT1"]["passed"] is True
    assert out["gates"]["GA"]["point_estimate"] == pytest.approx(0.7, abs=1e-9)
    assert out["gates"]["GA"]["passed"] is True
    assert out["gates"]["GR"]["keep_rate"] == pytest.approx(0.8, abs=1e-12)
    assert out["gates"]["GR"]["keep_ok"] is True


# ------------------------------------------------------------------------------------------------
# 自助法可复现
# ------------------------------------------------------------------------------------------------


def test_bootstrap_reproducible_with_same_seed(tmp_path: Path):
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    run = _build_run(
        tmp_path,
        star_rank=1,
        a0_rank=20,
        csh_rank=10,
        star_rmse=0.1,
        a0_rmse=0.5,
    )
    a = R.recompute_all(run)
    b = R.recompute_all(run)
    for g in ("GT1", "GT2", "GT3", "GR"):
        assert a["gates"][g]["point_estimate"] == b["gates"][g]["point_estimate"]
        assert a["gates"][g]["ci_lower"] == b["gates"][g]["ci_lower"]
        assert a["gates"][g]["ci_upper"] == b["gates"][g]["ci_upper"]


# ------------------------------------------------------------------------------------------------
# 坏对照突变
# ------------------------------------------------------------------------------------------------


def _mutate_copy(tmp_path: Path, old: str, new: str) -> Path:
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    dest = tmp_path / "recompute_s5p1_final.py"
    text = RECOMPUTE_PATH.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    dest.write_text(text.replace(old, new, 1), encoding="utf-8")
    return dest


def test_mutation_seed_order_reversed_is_caught(tmp_path: Path):
    """把 SEED_MEAN 绑到反向平均后，顺序测试必须失败。"""
    bad = _mutate_copy(
        tmp_path,
        "SEED_MEAN = mean_over_readouts_then_distills",
        "SEED_MEAN = mean_over_distills_then_readouts",
    )
    R = _load_recompute(bad)
    values = {
        0: {0: 1.0, 1: 2.0, 2: 3.0},
        1: {0: 10.0, 1: 10.0},
    }
    # 生产断言：SEED_MEAN 必须是正确函数，且正确均值=6
    with pytest.raises(AssertionError):
        assert R.SEED_MEAN is R.mean_over_readouts_then_distills
        assert R.SEED_MEAN(values) == pytest.approx(6.0)


def _heterogeneous_run(root: Path) -> Path:
    """世界间 AP 差不同，使自助区间有宽度（才能区分 98.3% 与 95%）。"""
    run = _build_run(
        root,
        star_rank=1,
        a0_rank=8,
        csh_rank=4,
        star_rmse=0.1,
        a0_rmse=0.5,
    )
    part = "s5p1-final"
    metrics = run / "metrics"
    # 覆写 A2 / A0：世界 0 差距大，世界 3 差距小
    star = _eval_with_pos_rank(N_WORLD, CPW, 1, rmse=0.1)
    a0 = _eval_with_pos_rank(N_WORLD, CPW, 8, rmse=0.5)
    for w in range(N_WORLD):
        # 把世界 w 的正例分数调成随 w 变差，制造异质差
        for c in range(CPW):
            i = w * CPW + c
            star["r2_logit"][i, 0, 0] = 10.0 - 0.5 * w
            a0["r2_logit"][i, 0, 0] = 1.0 - 0.2 * w
            # 给每个世界不同数量的高分负例
            flat = a0["r2_logit"][i].ravel()
            flat[1 : 2 + w * 3] = 5.0 + w
            a0["r2_logit"][i] = flat.reshape(12, 7)
    for d in (0, 1):
        for r in (0, 1, 2):
            _write_npz(metrics / f"heads-A2-d{d}-L64-r{r}.{part}.npz", star)
    for s in (0, 1, 2):
        _write_npz(metrics / f"A0-L64-s{s}.{part}.npz", a0)
    return run


def test_mutation_bonferroni_to_95_is_caught(tmp_path: Path):
    """把 Bonferroni 水平换成 95% 后，与冻结 98.3% 区间不再一致。"""
    bad = _mutate_copy(
        tmp_path,
        "GT_LEVEL = 1.0 - 0.05 / BONFERRONI_M  # ≈ 0.983333...",
        "GT_LEVEL = 0.95  # mutated away from Bonferroni",
    )
    R_good = _load_recompute()
    R_bad = _load_recompute(bad)

    run = _heterogeneous_run(tmp_path / "data")
    preg = json.loads((run / "PREREG.json").read_text(encoding="utf-8"))
    for g in ("GT1", "GT2", "GT3"):
        preg["gates"][g].pop("level", None)
    preg.pop("gt_level", None)
    (run / "PREREG.json").write_text(json.dumps(preg), encoding="utf-8")

    good = R_good.recompute_all(run)
    bad_out = R_bad.recompute_all(run)
    assert good["gates"]["GT1"]["level"] == pytest.approx(1.0 - 0.05 / 3.0)
    assert bad_out["gates"]["GT1"]["level"] == pytest.approx(0.95)
    # 水平被换成 95% 后，要求仍等于 Bonferroni 98.3% 的断言必须失败
    with pytest.raises(AssertionError):
        assert bad_out["gates"]["GT1"]["level"] == pytest.approx(1.0 - 0.05 / 3.0)


def test_mutation_ga_no_interpolation_is_caught(tmp_path: Path):
    """GA 改成阶梯步数（不插值）后，阈值插值断言失败。"""
    old = "decision = M.ga_decision(a0_curves, a4_curves, cap=cap)"
    # 保持与源文件相同缩进（4 空格 × 嵌套）
    new = (
        "    _d = M.ga_decision(a0_curves, a4_curves, cap=cap)\n"
        "    decision = {\n"
        "        **_d,\n"
        "        \"a0_steps\": _d[\"stair\"][\"a0_steps\"],\n"
        "        \"a4_steps\": _d[\"stair\"][\"a4_steps\"],\n"
        "        \"a0_censored\": _d[\"stair\"][\"a0_censored\"],\n"
        "        \"a4_censored\": _d[\"stair\"][\"a4_censored\"],\n"
        "        \"median_a0\": _d[\"stair\"][\"median_a0\"],\n"
        "        \"median_a4\": _d[\"stair\"][\"median_a4\"],\n"
        "        \"ratio\": _d[\"stair\"][\"ratio\"],\n"
        "        \"passed\": _d[\"stair\"][\"passed\"],\n"
        "    }"
    )
    text = RECOMPUTE_PATH.read_text(encoding="utf-8")
    assert text.count(old) == 1
    # old 行本身带缩进
    old_line = "    " + old
    assert old_line in text
    bad = tmp_path / "recompute_s5p1_final.py"
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    bad.write_text(text.replace(old_line, new, 1), encoding="utf-8")
    R_bad = _load_recompute(bad)

    # 曲线：末次 0.62 → target=0.589；0.50@200 与 0.70@300 之间插值=244.5，阶梯=300
    steps = [100.0, 200.0, 300.0, 1600.0]
    a0 = [(steps, [0.40, 0.50, 0.70, 0.62])] * 3
    a4 = [(steps, [0.40, 0.55, 0.70, 0.62])] * 3
    run = _build_run(
        tmp_path / "ga",
        star_rank=1,
        a0_rank=20,
        csh_rank=10,
        star_rmse=0.1,
        a0_rmse=0.5,
        ga_a0=a0,
        ga_a4=a4,
    )
    out = R_bad.recompute_all(run)
    expected_interp = 200.0 + (0.589 - 0.50) / (0.70 - 0.50) * 100.0
    assert out["gates"]["GA"]["median_a0"] == pytest.approx(300.0, abs=1e-9)  # 阶梯
    with pytest.raises(AssertionError):
        assert out["gates"]["GA"]["median_a0"] == pytest.approx(expected_interp, abs=1e-6)


def test_cli_writes_recompute_and_compares(tmp_path: Path):
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    run = _build_run(
        tmp_path,
        star_rank=1,
        a0_rank=20,
        csh_rank=10,
        star_rmse=0.1,
        a0_rmse=0.5,
    )
    out = R.recompute_all(run)
    (run / "gates.json").write_text(json.dumps({"gates": out["gates"]}, allow_nan=True), encoding="utf-8")
    rc = R.main(["--run-dir", str(run), "--out", str(run / "recompute.json")])
    assert rc == 0
    doc = json.loads((run / "recompute.json").read_text(encoding="utf-8"))
    assert doc["compare"]["n_diffs"] == 0
    assert "GT1" in doc["gates"]
