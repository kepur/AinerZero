"""S5 冻结后预登记生成器 make_prereg_s5p1.py 与登记运行器 run_s5p1_final.py 的纯 CPU 契约与守卫测试。

默认 pytest 入口运行，不加载 MLX / Metal，不触碰实盘分区或实盘账本。
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

LIVE = Path(__file__).resolve().parents[3]
REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PHASE1_REL = "reports/V9-S5-PHASE1"

sys.path.insert(0, str(LIVE / "src"))
sys.path.insert(0, str(LIVE / PHASE1_REL))

from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s5 import world as s5_world  # noqa: E402
import make_prereg_s5p1 as make_prereg  # noqa: E402
import recompute_s5p1_final as recompute  # noqa: E402
import run_s5p1_final as final_runner  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_fake_dev_distill_and_tune(
    base_dir: Path,
    *,
    a_star: str = "A2",
    n_capped: int = 48,
    failed: str | None = None,
) -> tuple[Path, Path]:
    """在临时目录构造齐备的 dev-distill 运行目录（含 66 个权重文件与 events.jsonl/stage.json）与 tune.json。"""
    dev_run = base_dir / "artifacts/v9/s5/runs/dev-distill-d1-20261112T230000Z"
    weights_dir = dev_run / "weights"
    metrics_dir = dev_run / "metrics"
    weights_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)

    events: list[dict[str, Any]] = [
        {"event": "stage_start", "stage": "dev-distill", "use_id": "d1", "lock": "artifacts/locks/m0-worker.lock"}
    ]

    def _write_weight(fname: str, tag: str) -> str:
        p = weights_dir / fname
        arr = np.frombuffer(hashlib.sha256(tag.encode("utf-8")).digest(), dtype=np.uint8)
        np.savez(p, w=arr)
        return _sha256(p)

    # 6 个蒸馏学生 + 6 个蒸馏投影头
    for arm in ("A1", "A2", "A3"):
        for d_seed in (0, 1):
            cid = f"distill-{arm}-s{d_seed}"
            s_name = f"{cid}-student.npz"
            h_name = f"{cid}-heads.npz"
            s_sha = _write_weight(s_name, s_name)
            h_sha = _write_weight(h_name, h_name)
            events.append({
                "event": "cell_end",
                "cell_id": cid,
                "wall_s": 2100.0 + d_seed * 30.0,
                "steps_logged": 7500,
                "files": {s_name: s_sha, h_name: h_sha},
            })

    # 54 个读出头
    for arm in ("A1", "A2", "A3"):
        for d_seed in (0, 1):
            for label_n in (64, 512, 2048):
                for r_seed in (0, 1, 2):
                    cid = f"heads-{arm}-d{d_seed}-L{label_n}-r{r_seed}"
                    fname = f"{cid}.npz"
                    f_sha = _write_weight(fname, fname)
                    events.append({
                        "event": "cell_end",
                        "cell_id": cid,
                        "wall_s": 27.0,
                        "steps_logged": 300,
                        "files": {fname: f_sha},
                    })

    # 3 个 A0-L64 学生与读出头
    for seed in (0, 1, 2):
        cid = f"A0-L64-s{seed}"
        s_name = f"{cid}-student.npz"
        h_name = f"{cid}-heads.npz"
        s_sha = _write_weight(s_name, s_name)
        h_sha = _write_weight(h_name, h_name)
        events.append({
            "event": "cell_end",
            "cell_id": cid,
            "wall_s": 660.0,
            "steps_logged": 2400,
            "files": {s_name: s_sha, h_name: h_sha},
        })

    events.append({"event": "stage_end", "failed": failed, "n_completed": 63})
    (dev_run / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events),
        encoding="utf-8",
    )

    stage_doc = {
        "stage": "dev-distill",
        "use_id": "d1",
        "failed": failed,
        "n_completed": 63,
        "selection": {
            "a_star": {
                "arm": a_star,
                "r2_ap": 0.215,
                "means": {"A1": 0.180, "A2": 0.215, "A3": 0.205},
                "tied": 1,
            },
            "power": {
                "n_worlds": n_capped,
                "n_capped": n_capped,
                "n_uncapped": n_capped,
                "capped": n_capped >= 96,
                "sigma": 0.08,
                "effect": 0.05,
                "alpha": 0.05 / 3.0,
                "power": 0.80,
            },
        },
    }
    (dev_run / "stage.json").write_text(json.dumps(stage_doc, indent=1), encoding="utf-8")

    tune_path = base_dir / "reports/V9-S5-PHASE1/tune.json"
    tune_path.parent.mkdir(parents=True, exist_ok=True)
    tune_doc = {
        "distill_lr": 0.0003,
        "supervised_lr": 0.001,
        "eta": 1.0,
    }
    tune_path.write_text(json.dumps(tune_doc, indent=1) + "\n", encoding="utf-8")
    return dev_run, tune_path


def _make_repo_copy(tmp_path: Path) -> Path:
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    root = tmp_path / "repo_copy"
    shutil.copytree(
        LIVE / "src/ainerzero",
        root / "src/ainerzero",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    phase = root / PHASE1_REL
    phase.mkdir(parents=True)
    for name in ("run_s5p1.py", "plan_s5p1.py", "run_s5p1_final.py", "make_prereg_s5p1.py", "recompute_s5p1_final.py"):
        shutil.copy2(LIVE / PHASE1_REL / name, phase / name)
    (root / "artifacts/locks").mkdir(parents=True)
    (root / ".gitignore").write_text("artifacts/\n__pycache__/\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init copy")
    assert root.resolve() not in (LIVE, REAL_REPO)
    return root


def test_make_prereg_validates_and_pins_all_66_weights(tmp_path: Path):
    assert s5_world.REGISTERED == frozenset({"s5p1-final", "s5p1-final-shift"})
    dev_run, tune_path = _make_fake_dev_distill_and_tune(tmp_path, a_star="A2", n_capped=64)
    out_prereg = tmp_path / "PREREG.json"

    rc = make_prereg.main([
        "--dev-distill-run", str(dev_run),
        "--tune-file", str(tune_path),
        "--budget-h", "10.0",
        "--out", str(out_prereg),
    ])
    assert rc == 0
    assert out_prereg.is_file()

    prereg = json.loads(out_prereg.read_text(encoding="utf-8"))
    assert prereg["schema"] == "s5.phase1.prereg.v1"
    assert prereg["a_star"] == "A2"
    assert prereg["frozen"]["a_star"] == "A2"
    assert prereg["frozen"]["n_final"] == 64
    assert prereg["frozen"]["distill_lr"] == 0.0003
    assert prereg["frozen"]["supervised_lr"] == 0.001
    assert prereg["frozen"]["eta"] == 1.0
    assert prereg["frozen"]["tau"] == 0.02
    assert prereg["frozen"]["csh_perm_seed"] == 20261113
    assert prereg["frozen"]["lab_subset_seed"] == 20261112
    assert prereg["frozen"]["boot_seed"] == 20261114
    assert prereg["frozen"]["n_boot"] == 2000

    pinned = prereg["pinned_artifacts"]
    assert len(pinned["distill_students"]) == 6
    assert len(pinned["readout_heads"]) == 54
    assert len(pinned["a0_l64_students"]) == 3
    assert len(pinned["a0_l64_heads"]) == 3
    assert pinned["tune_sha256"] == _sha256(tune_path)

    # 传递闭包清单必须覆盖 run_s5p1_final.py、run_s5p1.py、plan_s5p1.py 及 src/ainerzero/v9/experiments/s5/*
    manifest = prereg["manifest"]
    assert "reports/V9-S5-PHASE1/run_s5p1_final.py" in manifest
    assert "reports/V9-S5-PHASE1/run_s5p1.py" in manifest
    assert "reports/V9-S5-PHASE1/plan_s5p1.py" in manifest
    assert "src/ainerzero/v9/experiments/s5/train.py" in manifest
    assert "src/ainerzero/v9/experiments/s5/evaluate.py" in manifest
    assert "src/ainerzero/v9/experiments/s5/metrics.py" in manifest

    # 拒绝覆盖已存在的 PREREG.json
    rc_dup = make_prereg.main([
        "--dev-distill-run", str(dev_run),
        "--tune-file", str(tune_path),
        "--budget-h", "10.0",
        "--out", str(out_prereg),
    ])
    assert rc_dup != 0

    # 篡改任一读出头权重后，build_prereg 必须拒绝
    tampered_head = dev_run / "weights/heads-A2-d0-L64-r0.npz"
    raw = bytearray(tampered_head.read_bytes())
    raw[-1] ^= 0xFF
    tampered_head.write_bytes(bytes(raw))
    with pytest.raises(GD.GuardError, match="SHA mismatch"):
        make_prereg.build_prereg(dev_run, tune_file=tune_path, budget_h=10.0)


def test_n_final_clamping_and_failed_dev_distill_rejection(tmp_path: Path):
    dev_run_low, tune_path = _make_fake_dev_distill_and_tune(tmp_path / "low", a_star="A1", n_capped=32)
    doc_low = make_prereg.build_prereg(dev_run_low, tune_file=tune_path, budget_h=10.0)
    assert doc_low["frozen"]["n_final"] == 48

    dev_run_high, _ = _make_fake_dev_distill_and_tune(tmp_path / "high", a_star="A3", n_capped=140)
    doc_high = make_prereg.build_prereg(dev_run_high, tune_file=tune_path, budget_h=10.0)
    assert doc_high["frozen"]["n_final"] == 96

    with pytest.raises(GD.GuardError, match="must be in \\[48, 96\\]"):
        make_prereg.build_prereg(dev_run_low, tune_file=tune_path, n_final=20, budget_h=10.0)

    dev_run_fail, _ = _make_fake_dev_distill_and_tune(tmp_path / "fail", failed="timeout")
    with pytest.raises(GD.GuardError, match="dev-distill run failed"):
        make_prereg.build_prereg(dev_run_fail, tune_file=tune_path, budget_h=10.0)


def test_final_cells_and_model_specs_match_prereg_without_touching_dev_or_final(tmp_path: Path):
    dev_run, tune_path = _make_fake_dev_distill_and_tune(tmp_path, a_star="A3", n_capped=48)
    prereg = make_prereg.build_prereg(dev_run, tune_file=tune_path, budget_h=10.0)
    cells = final_runner.build_final_cells(prereg)

    # 2 (C-sh) + 2 (R) + 6 (A0 L=512,2048) + 3 (A4) + 3 (A0-R) + 9 (FT) + 18 (heads C-sh) + 6 (heads R) = 49 格
    assert len(cells) == 49
    by_group: dict[str, list[dict[str, Any]]] = {}
    for c in cells:
        by_group.setdefault(c["group"], []).append(c)
        assert c["partition"] in ("s5p1-pool", "s5p1-lab")
        assert "final" not in c["partition"] and "dev" not in c["partition"]

    assert len(by_group["C-sh"]) == 2
    assert all(c["arm"] == "A3" and c["perm_seed"] == 20261113 and c["lr"] == 0.0003 for c in by_group["C-sh"])

    assert len(by_group["R"]) == 2
    assert all(c["arm"] == "A3" and c["tau"] == 0.02 and c["lr"] == 0.0003 for c in by_group["R"])

    assert len(by_group["A0"]) == 6
    assert {c["label_n"] for c in by_group["A0"]} == {512, 2048}
    assert all(c["save_ckpts"] == (c["label_n"] == 512) for c in by_group["A0"])

    assert len(by_group["A4"]) == 3
    assert all(c["label_n"] == 512 and c["eta"] == 1.0 and c["save_ckpts"] is True for c in by_group["A4"])

    assert len(by_group["A0-R"]) == 3
    assert all(c["label_n"] == 512 and c["tau"] == 0.02 and c["save_ckpts"] is False for c in by_group["A0-R"])

    assert len(by_group["FT"]) == 9
    assert {c["label_n"] for c in by_group["FT"]} == {64, 512, 2048}
    assert all(c["init_student_file"].endswith("distill-A3-s1-student.npz") for c in by_group["FT"])

    assert len(by_group["heads-C-sh"]) == 18
    assert len(by_group["heads-R"]) == 6
    assert all(c["label_n"] == 512 and c["tau"] == 0.02 for c in by_group["heads-R"])

    specs = final_runner.build_model_specs(prereg, tmp_path / "final_weights")
    assert len(specs) == 102
    a0_l64_specs = [s for s in specs if s["arm"] == "A0" and s["label_n"] == 64]
    assert len(a0_l64_specs) == 3
    assert all(Path(s["student_file"]).parent == (dev_run / "weights") for s in a0_l64_specs)


def test_dry_run_does_not_take_lock_and_flags_budget(tmp_path: Path):
    root = _make_repo_copy(tmp_path)
    dev_run, tune_path = _make_fake_dev_distill_and_tune(root, a_star="A2", n_capped=48)
    prereg_path = root / "reports/V9-S5-FINAL/PREREG.json"
    prereg_path.parent.mkdir(parents=True, exist_ok=True)
    doc = make_prereg.build_prereg(dev_run, tune_file=tune_path, budget_h=5.0, repo=root)
    prereg_path.write_text(json.dumps(doc), encoding="utf-8")
    prereg_sha = _sha256(prereg_path)

    # 先占住锁，验证 --dry-run 不抢锁且退出码为 0
    lock_file = root / "artifacts/locks/m0-worker.lock"
    fh = lock_file.open("a+")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        res = subprocess.run(
            [
                sys.executable,
                str(root / PHASE1_REL / "run_s5p1_final.py"),
                "--prereg", str(prereg_path),
                "--prereg-sha", prereg_sha,
                "--dry-run",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        fh.close()

    assert res.returncode == 0, res.stderr
    plan_out = json.loads(res.stdout)
    assert plan_out["n_cells"] == 49
    assert plan_out["exceeds_budget"] is True
    assert "WARNING" in str(plan_out["budget_warning"])
    assert not (root / "artifacts/v9/s5/registered-runs.json").exists()
    assert not (root / "artifacts/v9/s5/dev-uses.json").exists()


def test_guard_order_busy_lock_and_tampered_inputs_write_nothing(tmp_path: Path):
    root = _make_repo_copy(tmp_path)
    dev_run, tune_path = _make_fake_dev_distill_and_tune(root, a_star="A2", n_capped=48)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "add tune")

    prereg_path = root / "PREREG.json"
    doc = make_prereg.build_prereg(dev_run, tune_file=tune_path, budget_h=10.0, repo=root)
    prereg_path.write_text(json.dumps(doc), encoding="utf-8")
    prereg_sha = _sha256(prereg_path)

    fresh_pyc = tmp_path / "pyc"
    fresh_pyc.mkdir()

    def _invoke(*extra_args: str):
        cmd = [
            sys.executable, "-I", "-X", f"pycache_prefix={fresh_pyc}",
            str(root / PHASE1_REL / "run_s5p1_final.py"),
            *extra_args,
        ]
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        return subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=60)

    # 1. 锁被占时退出码 75，且不写 registered-runs.json、report 或新运行目录
    lock_file = root / "artifacts/locks/m0-worker.lock"
    fh = lock_file.open("a+")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        r_busy = _invoke(
            "--prereg", str(prereg_path),
            "--prereg-sha", prereg_sha,
            "--run-id", "r1",
            "--report", str(root / "reports/out.json"),
        )
    finally:
        fh.close()
    assert r_busy.returncode == 75
    assert "lock is busy" in r_busy.stderr
    assert not (root / "artifacts/v9/s5/registered-runs.json").exists()
    assert not (root / "reports/out.json").exists()

    # 2. PREREG SHA 不符时拒绝，不写账本与报告
    r_bad_sha = _invoke(
        "--prereg", str(prereg_path),
        "--prereg-sha", "0" * 64,
        "--run-id", "r1",
        "--report", str(root / "reports/out.json"),
    )
    assert r_bad_sha.returncode == 1
    assert "PREREG SHA mismatch" in r_bad_sha.stderr
    assert not (root / "artifacts/v9/s5/registered-runs.json").exists()
    assert not (root / "reports/out.json").exists()

    # 3. 篡改冻结前权重文件后拒绝，不写账本与报告
    w_target = dev_run / "weights/A0-L64-s0-student.npz"
    orig_bytes = w_target.read_bytes()
    tampered = bytearray(orig_bytes)
    tampered[-1] ^= 1
    w_target.write_bytes(bytes(tampered))
    try:
        r_bad_w = _invoke(
            "--prereg", str(prereg_path),
            "--prereg-sha", prereg_sha,
            "--run-id", "r1",
            "--report", str(root / "reports/out.json"),
        )
        assert r_bad_w.returncode == 1
        assert "SHA mismatch" in r_bad_w.stderr
        assert not (root / "artifacts/v9/s5/registered-runs.json").exists()
    finally:
        w_target.write_bytes(orig_bytes)


def test_compute_gates_matches_independent_recompute_and_seed_order(tmp_path: Path):
    """构造合成评测产物，验证 compute_gates_from_metrics 与 recompute_s5p1_final.py 零差异，且种子平均顺序敏感。"""
    dev_run, tune_path = _make_fake_dev_distill_and_tune(tmp_path, a_star="A2", n_capped=48)
    prereg = make_prereg.build_prereg(dev_run, tune_file=tune_path, budget_h=10.0)

    run_dir = tmp_path / "run_final"
    metrics_dir = run_dir / "metrics"
    timing_dir = run_dir / "timing"
    metrics_dir.mkdir(parents=True)
    timing_dir.mkdir(parents=True)
    prereg_file = run_dir / "PREREG.json"
    prereg_file.write_text(json.dumps(prereg, indent=1), encoding="utf-8")

    n_worlds = 6
    cpw = 16
    n_clips = n_worlds * cpw
    rng = np.random.default_rng(42)
    r2_target = (rng.uniform(size=(n_clips, 12, 7)) < 0.25).astype(np.int64)
    r3_target = (rng.uniform(size=(n_clips, 12, 7)) < 0.25).astype(np.int64)
    r1_target = rng.uniform(0.5, 2.5, size=(n_clips, 16, 14, 14)).astype(np.float32)
    r1_sky = np.zeros((n_clips, 16, 14, 14), dtype=np.float32)
    r1_obj = np.ones((n_clips, 16, 14, 14), dtype=np.float32)
    world_ids = np.arange(n_worlds, dtype=np.int64)

    def _make_ev(ap_boost: float, rmse_noise: float, *, keep_rate: float | None = None) -> dict[str, Any]:
        r2_logit = r2_target.astype(np.float32) * float(ap_boost) + rng.normal(0, 0.5, size=r2_target.shape).astype(np.float32)
        r3_logit = r3_target.astype(np.float32) * float(ap_boost) + rng.normal(0, 0.5, size=r3_target.shape).astype(np.float32)
        r1_logd = r1_target + rng.normal(0, float(rmse_noise), size=r1_target.shape).astype(np.float32)
        ev = {
            "r1_logd": r1_logd,
            "r2_logit": r2_logit,
            "r3_logit": r3_logit,
            "r1_target": r1_target,
            "r1_sky": r1_sky,
            "r1_obj": r1_obj,
            "r2": r2_target,
            "r3": r3_target,
            "world_ids": world_ids,
            "clips_per_world": cpw,
            "threshold": 0.5,
            "tau": 0.02 if keep_rate is not None else None,
            "disk_groups": [[] for _ in range(n_clips)],
            "ordering_pairs": [[] for _ in range(n_clips)],
            "metrics": {"r2_ap": 0.5, "r3_ap": 0.5, "r1_rmse": float(rmse_noise)},
        }
        if keep_rate is not None:
            ev["keep_rate_per_clip"] = np.full(n_clips, float(keep_rate), dtype=np.float64)
            ev["metrics"]["keep_rate"] = float(keep_rate)
        return ev

    specs = final_runner.build_model_specs(prereg, run_dir / "weights")
    for spec in specs:
        mid = spec["model_id"]
        arm = spec["arm"]
        boost = 2.5 if arm == "A2" else (2.4 if arm == "R" else 1.0)
        noise = 0.10 if arm in ("A2", "R") else 0.12
        kr = 0.65 if spec["tau"] is not None else None
        ev = _make_ev(boost, noise, keep_rate=kr)
        for part_tag in ("s5p1-final", "s5p1-final-shift", "s5p1-final-shift.shift_bg", "s5p1-final-shift.shift_all"):
            final_runner._save_eval_artifacts(metrics_dir, mid, part_tag, ev)

    # 写入 GA 检查点曲线
    steps_16 = [240 * (i + 1) for i in range(16)]
    for arm_name, ap_curve in (
        ("A0", [0.10 + 0.02 * i for i in range(16)]),
        ("A4", [0.25 + 0.02 * i for i in range(16)]),
    ):
        for s in (0, 1, 2):
            cid = f"ckpt-{arm_name}-L512-s{s}"
            cdoc = {"steps": steps_16, "r2_ap": ap_curve, "cap": 3840}
            (metrics_dir / f"{cid}.json").write_text(json.dumps(cdoc), encoding="utf-8")
            (metrics_dir / f"{cid}.s5p1-final.json").write_text(json.dumps(cdoc), encoding="utf-8")
            ev_dummy = _make_ev(1.5, 0.1)
            np.savez_compressed(
                metrics_dir / f"{cid}.s5p1-final.npz",
                r1_logd=ev_dummy["r1_logd"],
                r2_logit=ev_dummy["r2_logit"],
                r3_logit=ev_dummy["r3_logit"],
                r1_target=ev_dummy["r1_target"],
                r1_sky=ev_dummy["r1_sky"],
                r1_obj=ev_dummy["r1_obj"],
                r2=ev_dummy["r2"],
                r3=ev_dummy["r3"],
                world_ids=ev_dummy["world_ids"],
                clips_per_world=np.asarray(cpw, dtype=np.int64),
            )

    # 写入 timing 文件
    completed_cells = []
    for d in (0, 1):
        c_row = {"cell_id": f"distill-C-sh-s{d}", "median_step_total_s": 0.30, "wall_per_step_s": 0.30, "wall_s": 2250.0, "steps_logged": 7500}
        r_row = {"cell_id": f"distill-R-s{d}", "median_step_total_s": 0.22, "wall_per_step_s": 0.22, "wall_s": 1650.0, "steps_logged": 7500}
        final_runner._write_timing_file(timing_dir, c_row)
        final_runner._write_timing_file(timing_dir, r_row)
        completed_cells.extend([c_row, r_row])

    gates_doc = final_runner.compute_gates_from_metrics(
        prereg,
        metrics_dir,
        completed_cells=completed_cells,
    )
    (run_dir / "gates.json").write_text(json.dumps(gates_doc, indent=1), encoding="utf-8")

    recomp_doc = recompute.recompute_all(run_dir, prereg_file)
    diffs = recompute.compare_gates(recomp_doc, gates_doc)
    assert diffs == [], f"Expected 0 gate diffs between runner and independent recompute, got: {diffs}"
    assert all(gates_doc["gates"][g]["passed"] is True for g in ("GT1", "GT2", "GT3", "GA", "GR"))


def test_production_prereg_refuses_stand_in_fields_and_off_design_constants():
    """非 stand-in 的 PREREG 出现测试专用字段、改了分区名或设计常量，都必须在任何输出之前被拒（tier-1, 11-13）。"""
    good = {"partitions": dict(final_runner.REAL_FINAL_PARTITIONS), "distill_epochs": 15, "batch_size": 8,
            "tau": 0.02, "ckpt_every_frac": 1.0 / 16.0,
            "super_epochs": {"64": 300, "512": 60, "2048": 20}, "readout_epochs": {"64": 300, "512": 60, "2048": 20}}
    final_runner.check_production_frozen(good)
    bad_cases = [
        dict(good, student_kwargs={"d": 16}),
        dict(good, data_root="/tmp/x"),
        dict(good, clips=[0, 1]),
        dict(good, partitions=dict(final_runner.REAL_FINAL_PARTITIONS, final="s5test-x")),
        dict(good, distill_epochs=1),
        dict(good, batch_size=2),
        dict(good, super_epochs={"64": 300, "512": 16, "2048": 20}),
        dict(good, readout_epochs={"64": 1, "512": 60, "2048": 20}),
        dict(good, tau=0.05),
    ]
    for frozen in bad_cases:
        with pytest.raises(GD.GuardError):
            final_runner.check_production_frozen(frozen)
    # stand-in 模式照常放行（替身冒烟要用这些字段）
    final_runner.check_production_frozen(dict(good, standin_test=True, student_kwargs={"d": 16}, batch_size=2))
