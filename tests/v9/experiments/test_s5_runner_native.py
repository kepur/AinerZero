"""S5 冻结前运行器：在一次性副本里跑 smoke，并核对锁、超时和 dev-tune SHA。

副本不是实盘仓库。改源码只发生在副本里，而且先断言路径不是 /Users/mac/AinerWorkFlow/AinerZero。
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("mlx.core")
pytestmark = pytest.mark.native_mlx

# Repo root derived from this file, so a copy of the repo tests its own code (tier-1 fix, 11-12).
LIVE = Path(__file__).resolve().parents[3]
# The real working repository; mutation and throwaway roots must never be this path.
REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
HERE = "reports/V9-S5-PHASE1"
RUNS = "artifacts/v9/s5/runs"
LEDGER = "artifacts/v9/s5/dev-uses.json"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root, check=True, capture_output=True,
    )


def _make_root(tmp_path: Path) -> Path:
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    root = tmp_path / "fake"
    shutil.copytree(LIVE / "src/ainerzero", root / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    phase = root / HERE
    phase.mkdir(parents=True)
    for name in ("run_s5p1.py", "plan_s5p1.py"):
        shutil.copy2(LIVE / HERE / name, phase / name)
    (root / "artifacts/locks").mkdir(parents=True)
    (root / ".gitignore").write_text("artifacts/\n__pycache__/\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "code")
    assert root.resolve() not in (LIVE, REAL_REPO)
    return root


def _run(root: Path, *args: str, env_extra: dict | None = None, timeout: int = 900):
    assert root.resolve() not in (LIVE, REAL_REPO)
    fresh = root.parent / f"pyc-{time.monotonic_ns()}"
    fresh.mkdir()
    cmd = [sys.executable, "-I", "-X", f"pycache_prefix={fresh}", str(root / HERE / "run_s5p1.py"), *args]
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=timeout)


def _mutate(root: Path, old: str, new: str, *, commit: bool = False) -> None:
    assert root.resolve() not in (LIVE, REAL_REPO)
    path = root / HERE / "run_s5p1.py"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    if commit:
        _git(root, "add", "-u")
        _git(root, "commit", "-qm", "mutate")


def test_smoke_end_to_end_does_not_touch_dev_uses(tmp_path: Path):
    root = _make_root(tmp_path)
    report = "reports/smoke.json"
    ran = _run(root, "--stage", "smoke", "--use-id", "s1", "--report", report)
    assert ran.returncode == 0, ran.stderr[-4000:] + ran.stdout[-2000:]
    assert not (root / LEDGER).exists()
    runs = list((root / RUNS).iterdir())
    assert len(runs) == 1
    out = runs[0]
    events = [json.loads(line) for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[0]["event"] == "stage_start"
    assert events[0]["lock"].endswith("artifacts/locks/m0-worker.lock")
    stage = json.loads((out / "stage.json").read_text(encoding="utf-8"))
    assert stage["failed"] is None
    assert stage["dev_ledger_written"] is False
    assert stage["smoke_partitions"]["dev"] == "s5test-smoke-dev"
    blob = json.dumps(stage)
    assert "s5p1-final" not in blob
    logged = [row for row in events if row["event"] == "cell_end"]
    assert logged
    assert all(row["steps_logged"] == 2 for row in logged)
    assert (out / "metrics" / "smoke-A0.json").is_file()
    assert (out / "metrics" / "smoke-A0R.json").is_file()
    # 验证训练与评测使用默认 GPU 设备，未被降级为 CPU
    devices = [row.get("device", "") for row in logged]
    assert devices and all("gpu" in d.lower() for d in devices), f"Expected GPU device in cell_end events, got {devices}"
    assert stage.get("cell_runner_name") == "_execute_cell_body"


def test_busy_lock_writes_nothing(tmp_path: Path):
    root = _make_root(tmp_path)
    lock = root / "artifacts/locks/m0-worker.lock"
    handle = lock.open("a+")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        ran = _run(root, "--stage", "smoke", "--use-id", "s1", "--report", "reports/out.json")
    finally:
        handle.close()
    assert ran.returncode == 75, ran.stderr[-1500:]
    assert "lock is busy" in ran.stderr
    assert not (root / RUNS).exists()
    assert not (root / "reports/out.json").exists()
    assert not (root / LEDGER).exists()


def test_cell_timeout_keeps_the_finished_cell(tmp_path: Path):
    root = _make_root(tmp_path)
    # 格子 0 正常，格子 1 时限设为 1.0 秒
    _mutate(
        root,
        "def cell_limit_seconds(cell_index: int) -> float:\n    return float(CELL_LIMIT_S)\n",
        "def cell_limit_seconds(cell_index: int) -> float:\n    return 1e9 if cell_index == 0 else 1.0\n",
        commit=True,
    )
    # 让格子 1 (smoke-heads-A1) 记录起睡时刻并故意睡 25 秒
    _mutate(
        root,
        "    t0 = time.perf_counter()\n",
        "    if cell['cell_id'].startswith('smoke-heads-A1'):\n"
        "        (ctx['out'] / 'c1_sleep_start.txt').write_text(str(time.monotonic()), encoding='utf-8')\n"
        "        time.sleep(25.0)\n"
        "    t0 = time.perf_counter()\n",
        commit=True,
    )
    ran = _run(
        root, "--stage", "smoke", "--use-id", "s1", "--report", "reports/out.json",
        timeout=90,
    )
    t_after = time.monotonic()
    assert ran.returncode == 2, ran.stderr[-1500:] + ran.stdout[-800:]
    out = next((root / RUNS).iterdir())
    # 验证超时子进程在时限（1.0s）加几秒内被硬性终止，远早于 25 秒睡眠结束
    t_sleep_start = float((out / "c1_sleep_start.txt").read_text(encoding="utf-8"))
    since_sleep = t_after - t_sleep_start
    assert since_sleep < 6.0, f"Child process was not terminated promptly, slept {since_sleep}s"
    events = [json.loads(line) for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    fails = [row for row in events if row["event"] == "cell_fail"]
    assert len(fails) == 1
    assert fails[0]["cell_id"] == "smoke-heads-A1"
    assert fails[0]["error"] == "timeout"
    assert fails[0]["wall_s"] < 5.0
    # 之前完成的格子 0 权重健全保留
    assert (out / "weights" / "smoke-distill-A1-student.npz").is_file()
    assert (out / "weights" / "smoke-distill-A1-heads.npz").is_file()
    # 跑飞超时的格子 1 未生成最终产物
    assert not (out / "weights" / "smoke-heads-A1.npz").exists()
    stage = json.loads((out / "stage.json").read_text(encoding="utf-8"))
    assert stage["completed"] == ["smoke-distill-A1"]
    assert stage["n_completed"] == 1
    assert "timeout" in str(stage["failed"]).lower()


def test_changed_tune_file_is_refused_before_any_output(tmp_path: Path):
    root = _make_root(tmp_path)
    tune = root / "reports/tune.json"
    tune.write_text('{"distill_lr": 0.0003, "supervised_lr": 0.0003, "eta": 0.1}\n', encoding="utf-8")
    import hashlib
    digest = hashlib.sha256(tune.read_bytes()).hexdigest()
    raw = bytearray(tune.read_bytes())
    raw[-2] ^= 1
    tune.write_bytes(bytes(raw))
    ran = _run(
        root, "--stage", "dev-distill", "--use-id", "d1", "--report", "reports/out.json",
        "--tune-file", str(tune), "--tune-sha", digest, timeout=120,
    )
    assert ran.returncode != 0, ran.stdout[-800:]
    assert "SHA mismatch" in ran.stderr
    assert not (root / RUNS).exists()
    assert not (root / LEDGER).exists()
    assert not (root / "reports/out.json").exists()


def test_writing_before_the_lock_is_caught(tmp_path: Path):
    root = _make_root(tmp_path)
    _mutate(
        root,
        "    # acquire the shared lock before any run directory\n    try:\n",
        "    RUNS.mkdir(parents=True, exist_ok=True)\n    (RUNS / 'leaked').write_text('x')\n    try:\n",
    )
    lock = root / "artifacts/locks/m0-worker.lock"
    handle = lock.open("a+")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        ran = _run(root, "--stage", "smoke", "--use-id", "s1", "--report", "reports/out.json", timeout=60)
    finally:
        handle.close()
    assert (root / RUNS / "leaked").is_file()
    assert not (ran.returncode == 75 and not (root / RUNS).exists())


def test_timeout_exit_mutation_is_caught(tmp_path: Path):
    root = _make_root(tmp_path)
    # 坏对照：把子进程带时限等待去掉（p.join(timeout=None)），跑飞的格子将不会被按时终止
    _mutate(root, "            p.join(timeout=timeout_s)\n", "            p.join(timeout=None)\n")
    _mutate(
        root,
        "def cell_limit_seconds(cell_index: int) -> float:\n    return float(CELL_LIMIT_S)\n",
        "def cell_limit_seconds(cell_index: int) -> float:\n    return 1e9 if cell_index == 0 else 0.5\n",
        commit=True,
    )
    _mutate(
        root,
        "    t0 = time.perf_counter()\n",
        "    if cell['cell_id'].startswith('smoke-heads-A1'):\n        time.sleep(2.0)\n    t0 = time.perf_counter()\n",
        commit=True,
    )
    ran = _run(
        root, "--stage", "smoke", "--use-id", "s1", "--report", "reports/out.json",
        timeout=90,
    )
    # 去掉终止逻辑后，超时格子没有被终止而是跑完返回 0，违反「超时返回 2 且终止子进程」的断言
    assert ran.returncode != 2


def test_cpu_device_mutation_is_rejected(tmp_path: Path):
    root = _make_root(tmp_path)
    # 坏对照：强行在 _execute_cell_body 加上 mx.set_default_device(mx.cpu)
    _mutate(
        root,
        "    kind = cell[\"kind\"]\n",
        "    mx.set_default_device(mx.cpu)\n    kind = cell[\"kind\"]\n",
        commit=True,
    )
    ran = _run(root, "--stage", "smoke", "--use-id", "s1", "--report", "reports/out.json")
    assert ran.returncode == 0
    out = next((root / RUNS).iterdir())
    events = [json.loads(line) for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    logged = [row for row in events if row["event"] == "cell_end"]
    devices = [row.get("device", "") for row in logged]
    # 证明一旦加入该行，设备就会变成 cpu 而不是 gpu
    assert any("cpu" in d.lower() for d in devices)
    assert not all("gpu" in d.lower() for d in devices)


def test_s5_fake_cell_env_is_ignored(tmp_path: Path):
    root = _make_root(tmp_path)
    ran = _run(
        root, "--stage", "smoke", "--use-id", "s1", "--report", "reports/out.json",
        env_extra={"S5_FAKE_CELL": "1"}, timeout=120,
    )
    assert ran.returncode == 0
    out = next((root / RUNS).iterdir())
    # 证明即使设置 S5_FAKE_CELL=1，也不会生成 c0.ok，仍然按真实 smoke 跑满 9 个格子
    assert not (out / "weights" / "c0.ok").exists()
    stage = json.loads((out / "stage.json").read_text(encoding="utf-8"))
    assert stage["n_completed"] == 9
    assert (out / "metrics" / "smoke-A0.json").is_file()


# ------------------------------------------------------------------------------------------------
# P236 第 3 轮（一级补）：拒绝 final 分区、核对格子输出 SHA
# ------------------------------------------------------------------------------------------------
def _mutate_file(root: Path, rel: str, old: str, new: str) -> None:
    assert root.resolve() not in (LIVE, REAL_REPO)
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    _git(root, "add", "-u")
    _git(root, "commit", "-qm", "fault injection")


def _events(root: Path) -> list[dict]:
    out = next((root / RUNS).iterdir())
    return [json.loads(line) for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def test_final_partition_cell_is_refused_before_any_cell(tmp_path: Path):
    """A planned cell on s5p1-final must stop the stage before any cell starts or any data is touched."""
    root = _make_root(tmp_path)
    _mutate_file(root, f"{HERE}/plan_s5p1.py",
                 'n_clips=pool_clips, epochs=distill_epochs, partition="s5p1-pool",',
                 'n_clips=pool_clips, epochs=distill_epochs, partition="s5p1-final",')
    ran = _run(root, "--stage", "probe", "--use-id", "p-final", "--report", "reports/out.json")
    assert ran.returncode != 0, ran.stdout[-2000:] + ran.stderr[-2000:]
    events = _events(root)
    assert not [e for e in events if e["event"] == "cell_start"], events
    errors = " ".join(str(e.get("error", "")) for e in events)
    assert "final partition" in errors, events
    assert not [p for p in root.rglob("*") if "s5p1-final" in p.name], "no final data may be created"


def test_cell_output_sha_mismatch_fails_the_cell(tmp_path: Path):
    """If a cell's reported output SHA does not match the file on disk, the cell fails and is not completed."""
    root = _make_root(tmp_path)
    _mutate_file(root, f"{HERE}/run_s5p1.py",
                 '            result = json.loads(result_path.read_text(encoding="utf-8"))\n',
                 '            result = json.loads(result_path.read_text(encoding="utf-8"))\n'
                 '            result["files"] = {k: "0" * 64 for k in result.get("files", {})}\n')
    ran = _run(root, "--stage", "smoke", "--use-id", "s-sha", "--report", "reports/out.json")
    assert ran.returncode == 2, ran.stdout[-2000:] + ran.stderr[-2000:]
    events = _events(root)
    fails = [e for e in events if e["event"] == "cell_fail"]
    assert fails and "SHA mismatch" in fails[0]["error"], events
    assert not [e for e in events if e["event"] == "cell_end"]
    stage = json.loads(next((root / RUNS).iterdir()).joinpath("stage.json").read_text(encoding="utf-8"))
    assert stage["n_completed"] == 0


# ------------------------------------------------------------------------------------------------
# 一级 11-12：真实阶段的输入预检（教师特征按分区存放），在消耗 dev 使用之前做
# ------------------------------------------------------------------------------------------------
def _write_inputs(root: Path, *, partitioned_teachers: bool) -> None:
    data = root / "artifacts/v9/s5/data"
    for name in ("s5p1-pool", "s5p1-lab", "s5p1-dev"):
        (data / name / "world_0000").mkdir(parents=True)
        (data / name / "manifest.json").write_text("{}", encoding="utf-8")
        (data / name / "world_0000" / "clip_00.npy").write_bytes(b"x")
    teachers = root / "artifacts/v9/s5/teachers"
    groups = {("vjepa", "s5p1-pool"): "clip_00.vjepa.npy", ("da2", "s5p1-pool"): "da2_00.da2.npy",
              ("vjepa", "s5p1-lab"): "clip_00.vjepa.npy"}
    for (teacher, part), fname in groups.items():
        d = teachers / teacher / part if partitioned_teachers else teachers / teacher
        (d / "world_0000").mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text("{}", encoding="utf-8")
        (d / "world_0000" / fname).write_bytes(b"x")


def _preflight(root: Path) -> subprocess.CompletedProcess:
    code = (
        "import importlib.util, sys\n"
        f"sys.path.insert(0, {str(root / 'src')!r})\n"
        f"spec = importlib.util.spec_from_file_location('r', {str(root / HERE / 'run_s5p1.py')!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "m._preflight_real_inputs(); print('preflight ok')\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    return subprocess.run([sys.executable, "-I", "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=120)


def test_probe_without_real_inputs_fails_before_spending_a_dev_use(tmp_path: Path):
    root = _make_root(tmp_path)
    ran = _run(root, "--stage", "probe", "--use-id", "p-pre", "--report", "reports/out.json")
    assert ran.returncode != 0
    assert "preflight" in (ran.stdout + ran.stderr)
    assert not (root / LEDGER).exists(), "no dev use may be spent when inputs are missing"
    assert not (root / RUNS).exists() or not any((root / RUNS).iterdir())


def test_preflight_requires_teacher_features_stored_per_partition(tmp_path: Path):
    wrong = _make_root(tmp_path / "wrong")
    _write_inputs(wrong, partitioned_teachers=False)
    r = _preflight(wrong)
    assert r.returncode != 0 and "preflight" in r.stderr, r.stdout + r.stderr
    right = _make_root(tmp_path / "right")
    _write_inputs(right, partitioned_teachers=True)
    r = _preflight(right)
    assert r.returncode == 0 and "preflight ok" in r.stdout, r.stdout + r.stderr
