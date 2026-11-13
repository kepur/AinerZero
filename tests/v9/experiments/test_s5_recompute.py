"""S5 登记运行独立复算契约测试（纯 CPU，默认入口）。

覆盖：
- 独立 R2 AP / R1 RMSE 与生产 metrics 逐值一致；
- 合成逐段预测下门必过 / 必不过 / 恰在阈值；
- 每个门的子条件单独翻转；
- 自助法同种子可复现；
- 种子平均顺序：先读出后蒸馏；
- Bonferroni 区间是 1-0.05/3，不是 95%；
- 分区名从 PREREG frozen.partitions 读取，换域含 shift_bg / shift_all；
- PREREG 阈值与设计 r1 不一致时标红并以非 0 退出。
坏对照不在本文件里自写必然失败的断言：见
``reports/V9-S5-FINAL/RECOMPUTE-IMPL/evidence/mutation_controls.py``，
它在 git archive 副本里改源码后跑本文件，正式测试必须失败。
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
    part: str = "s5p1-final",
    shift_part: str | None = None,
    n_boot: int | None = None,
) -> Path:
    """构造最小登记运行目录（只含复算需要的文件）。"""
    assert root.resolve() not in (LIVE, REAL_REPO)
    run = root / "run"
    metrics = run / "metrics"
    timing = run / "timing"
    metrics.mkdir(parents=True)
    timing.mkdir(parents=True)
    if shift_part is None:
        shift_part = part + "-shift"
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

    doc = _prereg_doc()
    if n_boot is not None:
        doc["n_boot"] = int(n_boot)
    doc["frozen"] = {
        "a_star": doc["a_star"],
        "partitions": {"final": part, "final_shift": shift_part},
    }
    (run / "PREREG.json").write_text(json.dumps(doc), encoding="utf-8")
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
    assert out["threshold_audit"]["status"] == "ok"
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


def _eval_ks(ks, *, cpw: int = 1, rmse: float = 0.5, keep: float = 1.0, rmse_by_world=None) -> dict:
    """每个世界固定 k 个高分负例。重抽世界会改变微平均 AP；RMSE 可按世界给定。"""
    n_worlds = len(ks)
    n = n_worlds * cpw
    scores = np.zeros((n, 12, 7), dtype=np.float64)
    targets = np.zeros((n, 12, 7), dtype=np.int64)
    pred = np.zeros((n, 16, 14, 14), dtype=np.float64)
    for w, k in enumerate(ks):
        err = float(rmse if rmse_by_world is None else rmse_by_world[w])
        for c in range(cpw):
            i = w * cpw + c
            flat = np.full(12 * 7, -1000.0 - w, dtype=np.float64)
            flat[0] = 0.0
            for j in range(1, 1 + int(k)):
                flat[j] = 1.0
            scores[i] = flat.reshape(12, 7)
            targets[i, 0, 0] = 1
            pred[i] = err
    return {
        "r2_logit": scores,
        "r3_logit": scores.copy(),
        "r2": targets,
        "r3": targets.copy(),
        "r1_logd": pred,
        "r1_target": np.zeros_like(pred),
        "r1_sky": np.zeros_like(pred),
        "r1_obj": np.ones_like(pred),
        "world_ids": np.arange(n_worlds, dtype=np.int64),
        "clips_per_world": cpw,
        "keep_rate_per_clip": np.full(n, keep, dtype=np.float64),
    }


def _final_part(run: Path) -> str:
    doc = json.loads((run / "PREREG.json").read_text(encoding="utf-8"))
    return str(doc["frozen"]["partitions"]["final"])


def _overwrite_heads(run: Path, arm: str, label: int, ev: dict, part: str) -> None:
    metrics = run / "metrics"
    for d in (0, 1):
        for r in (0, 1, 2):
            _write_npz(metrics / f"heads-{arm}-d{d}-L{label}-r{r}.{part}.npz", ev)


def _overwrite_sup(run: Path, arm: str, label: int, ev: dict, part: str) -> None:
    metrics = run / "metrics"
    for s in (0, 1, 2):
        _write_npz(metrics / f"{arm}-L{label}-s{s}.{part}.npz", ev)


def _base_run(root: Path, **kwargs) -> Path:
    params = dict(
        star_rank=1, a0_rank=20, csh_rank=10, star_rmse=0.1, a0_rmse=0.5,
    )
    params.update(kwargs)
    return _build_run(root, **params)


# ------------------------------------------------------------------------------------------------
# 子条件翻转：点估计与区间各自单独不达标
# ------------------------------------------------------------------------------------------------


def test_gt1_gt2_point_ok_but_ci_lower_not_positive(tmp_path: Path):
    """点估计过阈值，但下界 ≤ 0：GT1、GT2 都不过。"""
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    run = _base_run(tmp_path)
    part = _final_part(run)
    star = _eval_ks([0, 0, 0, 10], rmse=0.1)
    base = _eval_ks([4, 4, 4, 4], rmse=0.5)
    _overwrite_heads(run, "A2", 64, star, part)
    _overwrite_heads(run, "C-sh", 64, base, part)
    _overwrite_sup(run, "A0", 64, base, part)
    out = R.recompute_all(run)
    for name, effect in (("GT1", 0.05), ("GT2", 0.03)):
        gate = out["gates"][name]
        assert gate["point_estimate"] + 1e-12 >= effect
        assert gate["ci_lower"] <= 0.0
        assert gate["passed"] is False


def test_gt1_gt2_ci_lower_positive_but_point_below_effect(tmp_path: Path):
    """下界 > 0，但点估计低于效应阈值：GT1、GT2 都不过。"""
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    run = _base_run(tmp_path)
    part = _final_part(run)
    star = _eval_ks([4, 4, 4, 4], rmse=0.1)
    base = _eval_ks([5, 5, 5, 5], rmse=0.5)
    _overwrite_heads(run, "A2", 64, star, part)
    _overwrite_heads(run, "C-sh", 64, base, part)
    _overwrite_sup(run, "A0", 64, base, part)
    out = R.recompute_all(run)
    gt1, gt2 = out["gates"]["GT1"], out["gates"]["GT2"]
    assert 0.0 < gt1["ci_lower"] <= gt1["point_estimate"] < 0.05
    assert 0.0 < gt2["ci_lower"] <= gt2["point_estimate"] < 0.03
    assert gt1["passed"] is False
    assert gt2["passed"] is False


def test_gt3_margin_strictly_inside_interval_fails(tmp_path: Path):
    """下界 ≤ 边际 < 上界：GT3 不过。用下界代替上界会误判为过。"""
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    run = _base_run(tmp_path)
    part = _final_part(run)
    errs = [0.8, 0.8, 0.8, 1.5, 1.5, 1.5]
    star = _eval_ks([0] * 6, rmse_by_world=errs)
    a0 = _eval_ks([0] * 6, rmse=1.0)
    _overwrite_heads(run, "A2", 64, star, part)
    _overwrite_heads(run, "C-sh", 64, a0, part)
    _overwrite_sup(run, "A0", 64, a0, part)
    gate = R.recompute_all(run)["gates"]["GT3"]
    assert gate["ci_lower"] <= gate["margin"] < gate["ci_upper"]
    assert gate["passed"] is False


def test_gr_subconditions_fail_independently(tmp_path: Path):
    """保留率、墙钟、AP 下降各自单独不达标时 GR 不过。"""
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    cases = [
        dict(keep=0.95, wall_r=0.20, wall_csh=0.30, r_rank=1, bad="keep_ok"),
        dict(keep=0.70, wall_r=0.30, wall_csh=0.30, r_rank=1, bad="wall_ok"),
        dict(keep=0.70, wall_r=0.20, wall_csh=0.30, r_rank=20, bad="ap_ok"),
    ]
    for i, case in enumerate(cases):
        bad = case["bad"]
        run = _base_run(
            tmp_path / f"c{i}",
            star_rank=1,
            r_rank=case["r_rank"],
            keep=case["keep"],
            wall_r=case["wall_r"],
            wall_csh=case["wall_csh"],
        )
        gate = R.recompute_all(run)["gates"]["GR"]
        assert gate["keep_ok"] is (bad != "keep_ok")
        assert gate["wall_ok"] is (bad != "wall_ok")
        assert gate["ap_ok"] is (bad != "ap_ok")
        assert gate["passed"] is False


def test_ga_interpolation_and_stair_disagree(tmp_path: Path):
    """线性插值判定通过，阶梯判定不通过。不插值会把本测试打失败。"""
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    a0 = [([100.0, 200.0, 1000.0], [0.40, 0.50, 0.70])] * 3
    a4 = [([100.0, 150.0, 900.0], [0.40, 0.66, 0.80])] * 3
    run = _base_run(tmp_path, ga_a0=a0, ga_a4=a4)
    gate = R.recompute_all(run)["gates"]["GA"]
    assert gate["median_a0"] == pytest.approx(860.0, abs=1e-6)
    assert gate["median_a4"] == pytest.approx(176.7857142857, abs=1e-6)
    assert gate["passed"] is True
    assert gate["stair"]["median_a0"] == pytest.approx(1000.0)
    assert gate["stair"]["passed"] is False


def test_ga_censor_uses_budget_cap(tmp_path: Path):
    """没有检查点达标时，删失步数是总步数（ga_cap），不是最后一次检查点。"""
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    a0 = [
        ([100.0, 400.0], [0.20, 0.30]),
        ([100.0, 800.0], [0.20, 0.90]),
        ([100.0, 900.0], [0.20, 0.90]),
    ]
    a4 = [([100.0, 200.0], [0.20, 0.90])] * 3
    run = _base_run(tmp_path, ga_a0=a0, ga_a4=a4)
    gate = R.recompute_all(run)["gates"]["GA"]
    censored = [step for step, flag in zip(gate["a0_steps"], gate["a0_censored"]) if flag]
    assert censored == pytest.approx([1600.0])
    assert 400.0 not in censored


def test_bonferroni_interval_is_not_95(tmp_path: Path):
    """PREREG 不写水平时，区间用 1-0.05/3，并且和下界的 95% 区间不同。"""
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    run = _base_run(tmp_path, n_boot=400)
    part = _final_part(run)
    star = _eval_ks(list(range(12)), rmse=0.2)
    base = _eval_ks([6] * 12, rmse=0.5)
    _overwrite_heads(run, "A2", 64, star, part)
    _overwrite_heads(run, "C-sh", 64, base, part)
    _overwrite_sup(run, "A0", 64, base, part)
    preg = json.loads((run / "PREREG.json").read_text(encoding="utf-8"))
    for g in ("GT1", "GT2", "GT3"):
        preg["gates"][g].pop("level", None)
    preg.pop("gt_level", None)
    (run / "PREREG.json").write_text(json.dumps(preg), encoding="utf-8")

    out = R.recompute_all(run)
    level = 1.0 - 0.05 / 3.0
    assert out["gates"]["GT1"]["level"] == pytest.approx(level)
    pr = R.load_prereg(run / "PREREG.json")
    catalog = R.load_run_catalog(run)
    nested = R._heads_nested(
        catalog, arm="A2", label_n=64, partition=part,
        distill_seeds=pr["distill_seeds"], readout_seeds=pr["readout_seeds"],
    )
    a0 = R._supervised_list(
        catalog, arm="A0", label_n=64, partition=part, seeds=pr["supervised_seeds"],
    )
    stat = R.nested_group_stat(nested, a0, "r2_ap")
    n_worlds = R._n_worlds(a0[0])
    b98 = R.bootstrap_gate(n_worlds, stat, n_boot=pr["n_boot"], seed=pr["boot_seed"], level=level)
    b95 = R.bootstrap_gate(n_worlds, stat, n_boot=pr["n_boot"], seed=pr["boot_seed"], level=0.95)
    assert b98["ci_lower"] != pytest.approx(b95["ci_lower"])
    assert out["gates"]["GT1"]["ci_lower"] == pytest.approx(b98["ci_lower"])
    assert out["gates"]["GT1"]["ci_lower"] != pytest.approx(b95["ci_lower"])


def test_partitions_come_from_prereg_including_shift_files(tmp_path: Path):
    """替身分区名来自 frozen.partitions；shift_bg / shift_all 进入只报告项。"""
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    final, shift = "s5test-regfinal", "s5test-regfinal-shift"
    run = _base_run(tmp_path, part=final, shift_part=shift, star_rank=1, a0_rank=20, csh_rank=10)
    bg = _eval_with_pos_rank(N_WORLD, CPW, 1, rmse=0.1)
    both = _eval_with_pos_rank(N_WORLD, CPW, 2, rmse=0.1)
    _overwrite_heads(run, "A2", 64, bg, f"{shift}.shift_bg")
    _overwrite_heads(run, "A2", 64, both, f"{shift}.shift_all")
    out = R.recompute_all(run)
    assert out["partitions"]["final"] == final
    assert out["partitions"]["shift_bg"] == f"{shift}.shift_bg"
    assert out["gates"]["GT1"]["passed"] is True
    shift_report = out["report_only"]["domain_shift"]
    assert shift_report["shift_bg"]["L64"]["a_star_r2_ap"] == pytest.approx(M.grid_ap(bg["r2_logit"], bg["r2"]))
    assert shift_report["shift_all"]["L64"]["a_star_r2_ap"] == pytest.approx(M.grid_ap(both["r2_logit"], both["r2"]))
    assert shift_report["shift_bg"]["L64"]["a_star_r2_ap"] > shift_report["shift_all"]["L64"]["a_star_r2_ap"]
    assert shift_report["shift_bg"]["L64"]["partition"] == f"{shift}.shift_bg"


def test_prereg_threshold_mismatch_is_red(tmp_path: Path):
    """PREREG 效应与设计 r1 不一致时，recompute.json 标红，进程非 0 退出。"""
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    R = _load_recompute()
    run = _base_run(tmp_path)
    preg = json.loads((run / "PREREG.json").read_text(encoding="utf-8"))
    preg["gates"]["GT1"]["effect"] = 0.0
    (run / "PREREG.json").write_text(json.dumps(preg), encoding="utf-8")
    probe = R.recompute_all(run)
    (run / "gates.json").write_text(json.dumps({"gates": probe["gates"]}, allow_nan=True), encoding="utf-8")
    rc = R.main(["--run-dir", str(run), "--out", str(run / "recompute.json")])
    assert rc != 0
    doc = json.loads((run / "recompute.json").read_text(encoding="utf-8"))
    assert doc["threshold_audit"]["status"] == "red"
    assert doc["threshold_audit"]["ok"] is False
    assert any(row["key"] == "gates.GT1.effect" for row in doc["threshold_audit"]["mismatches"])


def test_registered_prereg_matches_design_constants():
    R = _load_recompute()
    doc = json.loads((REAL_REPO / "reports/V9-S5-FINAL/PREREG.json").read_text(encoding="utf-8"))
    audit = R.audit_prereg_thresholds(doc)
    assert audit["status"] == "ok"
    assert audit["mismatches"] == []


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
    assert doc["threshold_audit"]["status"] == "ok"
    assert "GT1" in doc["gates"]
