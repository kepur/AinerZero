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



# ------------------------------------------------------------------------------------------------
# dev-tune-b（用户 2026-11-12 批准追加约 1 h）：dev-tune 的第二段。
# 先在 dev 上评两个蒸馏学习率候选的读出头（dev-tune 只训练、没评测），再补跑 3 h 时限内没跑完的 η 格。
# ------------------------------------------------------------------------------------------------
def _runner_in_process():
    import time

    spec = importlib.util.spec_from_file_location(f"run_s5p1_plan_{time.monotonic_ns()}", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dev_tune_b_cells_are_the_readouts_then_the_dev_tune_eta_cells():
    plan = _plan()
    tune = plan.stage_cells("dev-tune")
    original_eta = {cell["eta"]: cell for cell in tune if cell.get("role") == "eta"}
    distill_ids = [cell["cell_id"] for cell in tune if cell.get("role") == "distill_lr"]
    assert sorted(original_eta) == [0.1, 0.5, 1.0]
    assert distill_ids == ["tune-distill-A2-lr0.0003", "tune-distill-A2-lr0.001"]
    cells = plan.stage_cells("dev-tune-b", etas=(1.0, 0.5))
    heads, etas = cells[:2], cells[2:]
    # 读出头格：每个蒸馏学习率候选一格，读 dev-tune 里训出的那个学生，L=512、读出种子 0、设计轮数
    assert [cell["student_cell"] for cell in heads] == distill_ids
    for cell, lr in zip(heads, (3e-4, 1e-3)):
        assert (
            cell["cell_id"], cell["kind"], cell["arm"], cell["seed"], cell["readout_seed"], cell["distill_lr"],
            cell["label_n"], cell["n_clips"], cell["epochs"], cell["steps"], cell["partition"], cell["role"], cell["lr"],
        ) == (
            f"tune-heads-A2-dlr{lr}", "heads", "A2", 0, 0, lr,
            512, 512, 60, 3840, "s5p1-lab", "distill_lr", None,
        )
    # η 格按设计网格顺序，与 dev-tune 里同一 η 的格逐字段相同（学习率由运行器填）
    assert [cell["eta"] for cell in etas] == [0.5, 1.0]
    for cell in etas:
        assert cell == original_eta[cell["eta"]]
        assert (
            cell["cell_id"], cell["kind"], cell["arm"], cell["seed"], cell["label_n"],
            cell["n_clips"], cell["epochs"], cell["steps"], cell["partition"], cell["role"], cell["lr"],
        ) == (
            f"tune-A4-eta{cell['eta']}", "supervised", "A4", 0, 512,
            512, 60, 3840, "s5p1-lab", "eta", None,
        )
    assert [cell.get("eta") for cell in plan.stage_cells("dev-tune-b")[2:]] == [0.1, 0.5, 1.0]


def test_dev_tune_b_rejects_bad_eta_lists():
    plan = _plan()
    for bad in ((), (0.3,), (0.5, 0.5), (0.5, 2.0)):
        with pytest.raises(ValueError):
            plan.stage_cells("dev-tune-b", etas=bad)
    for stage in ("probe", "dev-tune", "dev-distill"):
        with pytest.raises(ValueError):
            plan.stage_cells(stage, etas=(0.5,))


def test_tuned_stages_take_their_learning_rates_from_the_tune_file():
    mod = _runner_in_process()
    plan = _plan()
    tune = {"distill_lr": 0.001, "supervised_lr": 0.0003}
    cells = mod.stage_cells_with_tune("dev-tune-b", tune, (0.5, 1.0))
    assert [(cell["cell_id"], cell["lr"]) for cell in cells] == [
        ("tune-heads-A2-dlr0.0003", 0.0003), ("tune-heads-A2-dlr0.001", 0.0003),
        ("tune-A4-eta0.5", 0.0003), ("tune-A4-eta1.0", 0.0003),
    ]
    distill = mod.stage_cells_with_tune("dev-distill", tune)
    reference = plan.stage_cells("dev-distill", pool_worlds=250, lab_worlds=128)
    assert [cell["cell_id"] for cell in distill] == [cell["cell_id"] for cell in reference]
    for cell, ref in zip(distill, reference):
        assert cell == dict(ref, lr=0.001 if ref["kind"] == "distill" else 0.0003)
    assert mod.stage_cells_with_tune("dev-tune", None) == plan.stage_cells("dev-tune", pool_worlds=250, lab_worlds=128)


def test_tune_file_keys_are_checked_per_stage():
    mod = _runner_in_process()
    mod._require_tune_keys("dev-tune-b", {"supervised_lr": 3e-4})
    mod._require_tune_keys("dev-distill", {"distill_lr": 3e-4, "supervised_lr": 1e-3})
    bad = (
        ("dev-tune-b", {"distill_lr": 3e-4}),
        ("dev-distill", {"supervised_lr": 3e-4}),
        ("dev-tune-b", {"supervised_lr": 0}),
        ("dev-tune-b", {"supervised_lr": -1e-3}),
        ("dev-tune-b", {"supervised_lr": "3e-4"}),
        ("dev-tune-b", {"supervised_lr": True}),
    )
    for stage, tune in bad:
        with pytest.raises(mod.GD.GuardError):
            mod._require_tune_keys(stage, tune)


def _fake_tune_run(runs: Path, *, stage: str = "dev-tune", finished=("tune-distill-A2-lr0.0003", "tune-distill-A2-lr0.001")) -> Path:
    import hashlib

    run = runs / "dev-tune-x-20261112T000000Z"
    (run / "weights").mkdir(parents=True)
    events = [{"event": "stage_start", "stage": stage, "use_id": "x"}]
    for i, cell_id in enumerate(finished):
        path = run / "weights" / f"{cell_id}-student.npz"
        path.write_bytes(f"student-{i}".encode())
        events.append({"event": "cell_end", "cell_id": cell_id,
                       "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}})
    (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return run


def test_resolve_tune_students_binds_paths_and_shas(tmp_path: Path):
    mod = _runner_in_process()
    plan = _plan()
    runs = tmp_path / "runs"
    run = _fake_tune_run(runs)
    cells = mod.resolve_tune_students(run, plan.stage_cells("dev-tune-b", etas=(0.5,)), runs_root=runs)
    heads = [cell for cell in cells if cell["kind"] == "heads"]
    assert [Path(cell["student_file"]).name for cell in heads] == [
        "tune-distill-A2-lr0.0003-student.npz", "tune-distill-A2-lr0.001-student.npz"]
    import hashlib
    for cell in heads:
        assert cell["student_sha"] == hashlib.sha256(Path(cell["student_file"]).read_bytes()).hexdigest()
    assert all("student_file" not in cell for cell in cells if cell["kind"] != "heads")


def test_resolve_tune_students_refuses_a_bad_tune_run(tmp_path: Path):
    mod = _runner_in_process()
    plan = _plan()
    cells = plan.stage_cells("dev-tune-b", etas=(0.5,))
    runs = tmp_path / "runs"
    good = _fake_tune_run(runs)
    with pytest.raises(mod.GD.GuardError, match="needs --tune-run"):
        mod.resolve_tune_students(None, cells, runs_root=runs)
    with pytest.raises(mod.GD.GuardError, match="under"):
        mod.resolve_tune_students(good, cells, runs_root=tmp_path / "elsewhere")
    tampered = good / "weights" / "tune-distill-A2-lr0.001-student.npz"
    tampered.write_bytes(b"changed")
    with pytest.raises(mod.GD.GuardError, match="SHA mismatch"):
        mod.resolve_tune_students(good, cells, runs_root=runs)
    other = tmp_path / "other"
    with pytest.raises(mod.GD.GuardError, match="not a dev-tune run"):
        mod.resolve_tune_students(_fake_tune_run(other, stage="probe"), cells, runs_root=other)
    partial = tmp_path / "partial"
    with pytest.raises(mod.GD.GuardError, match="did not finish"):
        mod.resolve_tune_students(_fake_tune_run(partial, finished=("tune-distill-A2-lr0.0003",)), cells, runs_root=partial)


def test_dry_run_dev_tune_b_lists_only_the_requested_cells(tmp_path: Path):
    ran = subprocess.run(
        [sys.executable, "-I", str(RUNNER), "--stage", "dev-tune-b", "--dry-run", "--etas", "1.0,0.5"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert ran.returncode == 0, ran.stderr
    payload = json.loads(ran.stdout)
    assert payload["takes_lock"] is False
    assert payload["limit_s"] == 3600
    assert [cell["cell_id"] for cell in payload["cells"]] == [
        "tune-heads-A2-dlr0.0003", "tune-heads-A2-dlr0.001", "tune-A4-eta0.5", "tune-A4-eta1.0"]
    for args in (
        ["--stage", "dev-tune-b", "--dry-run", "--etas", "0.3"],
        ["--stage", "dev-tune-b", "--dry-run", "--etas", "0.5,0.5"],
        ["--stage", "dev-distill", "--dry-run", "--etas", "0.5"],
    ):
        bad = subprocess.run([sys.executable, "-I", str(RUNNER), *args], cwd=tmp_path, capture_output=True, text=True)
        assert bad.returncode == 1, (args, bad.stdout[-400:])
        assert "etas" in bad.stderr
