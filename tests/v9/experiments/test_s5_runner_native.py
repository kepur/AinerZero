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
    _write_inputs(root, partitioned_teachers=True)        # pass the preflight so the final refusal is reached
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



# ------------------------------------------------------------------------------------------------
# P238 之后一级补测（复核者 gemini-h8q4 指出的五处缺口）
# ------------------------------------------------------------------------------------------------
def _runner_module(root: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"run_s5p1_{time.monotonic_ns()}", root / HERE / "run_s5p1.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refuse_final_rejects_every_final_partition_name():
    from ainerzero.v9.experiments.s3 import run_guard as GD
    mod = _runner_module(LIVE)
    for name in ("s5p1-final", "s5p1-final-shift"):
        with pytest.raises(GD.GuardError, match="final partition"):
            mod._refuse_final(name)
    mod._refuse_final("s5p1-dev")                      # non-final names pass


def test_output_sha_mismatch_on_a_later_file_fails_the_cell(tmp_path: Path):
    """Only the second reported file has a wrong SHA; every file must be checked, not just the first."""
    root = _make_root(tmp_path)
    _mutate_file(root, f"{HERE}/run_s5p1.py",
                 '            result = json.loads(result_path.read_text(encoding="utf-8"))\n',
                 '            result = json.loads(result_path.read_text(encoding="utf-8"))\n'
                 '            result["files"] = {k: (v if i == 0 else "0" * 64) '
                 'for i, (k, v) in enumerate(result.get("files", {}).items())}\n')
    ran = _run(root, "--stage", "smoke", "--use-id", "s-sha2", "--report", "reports/out.json")
    assert ran.returncode == 2, ran.stdout[-2000:] + ran.stderr[-2000:]
    fails = [e for e in _events(root) if e["event"] == "cell_fail"]
    assert fails and "SHA mismatch" in fails[0]["error"]


def test_child_exception_is_reported_and_not_counted(tmp_path: Path):
    """A cell whose child process raises must fail with that exception, never be recorded as completed."""
    root = _make_root(tmp_path)
    _mutate_file(root, f"{HERE}/run_s5p1.py",
                 "def _execute_cell_body(cell: dict, ctx: dict) -> dict:\n",
                 "def _execute_cell_body(cell: dict, ctx: dict) -> dict:\n"
                 "    raise RuntimeError(\"injected cell failure\")\n")
    ran = _run(root, "--stage", "smoke", "--use-id", "s-raise", "--report", "reports/out.json")
    assert ran.returncode == 2, ran.stdout[-2000:] + ran.stderr[-2000:]
    events = _events(root)
    fails = [e for e in events if e["event"] == "cell_fail"]
    assert fails and "injected cell failure" in fails[0]["error"], fails
    assert not [e for e in events if e["event"] == "cell_end"]


def test_preflight_requires_the_lab_teacher_directory(tmp_path: Path):
    import shutil
    root = _make_root(tmp_path)
    _write_inputs(root, partitioned_teachers=True)
    shutil.rmtree(root / "artifacts/v9/s5/teachers/vjepa/s5p1-lab")
    r = _preflight(root)
    assert r.returncode != 0 and "preflight" in r.stderr and "s5p1-lab" in r.stderr, r.stdout + r.stderr


def test_preflight_requires_clip_files_not_only_a_manifest(tmp_path: Path):
    root = _make_root(tmp_path)
    _write_inputs(root, partitioned_teachers=True)
    (root / "artifacts/v9/s5/data/s5p1-dev/world_0000/clip_00.npy").unlink()
    r = _preflight(root)
    assert r.returncode != 0 and "preflight" in r.stderr and "s5p1-dev" in r.stderr, r.stdout + r.stderr


# ------------------------------------------------------------------------------------------------
# P239：运行器按 label_n 取 lab 子集 + 训练循环共用 ItemCache 缓存
# ------------------------------------------------------------------------------------------------
def _setup_single_l64_cell_in_copy(root: Path) -> None:
    assert root.resolve() not in (LIVE, REAL_REPO)
    # s5test-smoke-lab 物化 2 个世界（32 段），把 L_WORLDS[64] 设为 1 个世界（16 段），用来区分「取子集」与「用全集」
    _mutate_file(
        root,
        f"{HERE}/plan_s5p1.py",
        "L_WORLDS = {64: 4, 512: 32, 2048: 128}",
        "L_WORLDS = {64: 1, 512: 32, 2048: 128}",
    )
    # 只跑一个带 label_n=64 的 supervised 小格：epochs=2, batch_size=8 -> 16 * 2 // 8 = 4 步
    _mutate_file(
        root,
        f"{HERE}/run_s5p1.py",
        # 锚定 smoke_cells() 的 return（运行器里另有 return cells，tier-1 2026-11-12）
        "smoke cell left the smoke namespace: {cell['partition']}\")\n    return cells\n",
        "smoke cell left the smoke namespace: {cell['partition']}\")\n"
        "    return [{\n"
        "        'cell_id': 'smoke-A0-L64', 'kind': 'supervised', 'arm': 'A0', 'seed': 0,\n"
        "        'lr': 1e-3, 'label_n': 64, 'epochs': 2, 'batch_size': 8, 'n_clips': 16,\n"
        "        'steps': 4, 'partition': SMOKE_PARTITIONS['lab'],\n"
        "    }]\n",
    )


def test_label_n_subset_is_used_in_supervised_cell(tmp_path: Path):
    from ainerzero.v9.experiments.s5.data import ClipIndex

    root = _make_root(tmp_path)
    _setup_single_l64_cell_in_copy(root)
    ran = _run(root, "--stage", "smoke", "--use-id", "s-l64", "--report", "reports/out.json")
    assert ran.returncode == 0, ran.stderr[-2000:] + ran.stdout[-2000:]

    out = next((root / RUNS).iterdir())
    events = _events(root)
    starts = [e for e in events if e["event"] == "cell_start"]
    ends = [e for e in events if e["event"] == "cell_end"]
    assert len(starts) == 1 and len(ends) == 1

    lab_dir = out / "data" / "s5test-smoke-lab"
    expected_sub = ClipIndex(lab_dir).subset_by_worlds(1, seed=20261112)
    assert len(expected_sub.worlds) == 1
    assert len(expected_sub) == 1 * 16 == 16

    # cell_start 记下子集世界清单与段数
    assert starts[0]["worlds"] == expected_sub.worlds
    assert starts[0]["n_worlds"] == 1
    assert starts[0]["n_clips"] == 1 * 16 == 16

    # cell_end 记实际步数 = 段数(16) * epochs(2) // batch(8) = 4
    assert ends[0]["worlds"] == expected_sub.worlds
    assert ends[0]["n_clips"] == 16
    assert ends[0]["steps_logged"] == 4
    assert ends[0]["steps"] == 4


def test_removing_subset_by_worlds_mutation_is_caught(tmp_path: Path):
    root = _make_root(tmp_path)
    _setup_single_l64_cell_in_copy(root)
    # 坏对照：去掉 _index_for 中的 subset_by_worlds，导致直接用整个 lab 分区（2 世界 = 32 段，8 步）
    _mutate_file(
        root,
        f"{HERE}/run_s5p1.py",
        "    if label_n is not None:\n"
        "        return ClipIndex(partition_dir).subset_by_worlds(\n"
        "            plan.L_WORLDS[int(label_n)], seed=LAB_SUBSET_SEED\n"
        "        )\n",
        "    if label_n is not None:\n"
        "        return ClipIndex(partition_dir)\n",
    )
    ran = _run(root, "--stage", "smoke", "--use-id", "s-l64-bad", "--report", "reports/out.json")
    assert ran.returncode == 0, ran.stderr[-2000:] + ran.stdout[-2000:]
    events = _events(root)
    starts = [e for e in events if e["event"] == "cell_start"]
    ends = [e for e in events if e["event"] == "cell_end"]
    # 去掉 subset_by_worlds 后，世界数变成 2、段数变成 32、步数变成 8，违反子集断言
    assert not (
        starts[0].get("n_worlds") == 1
        and starts[0].get("n_clips") == 16
        and ends[0].get("steps_logged") == 4
    )


def test_train_loops_use_item_cache_across_epochs(tmp_path: Path, monkeypatch):
    from ainerzero.v9.experiments.s5 import data as D
    from ainerzero.v9.experiments.s5 import train as T
    from ainerzero.v9.experiments.s5.materialize import materialize_partition
    from ainerzero.v9.experiments.s5.student import Student

    part_dir = tmp_path / "part"
    materialize_partition("s5test-cache", part_dir, world_range=(0, 1))
    # 只保留前 2 段以加速测试
    wdir = part_dir / "world_0000"
    for cf in list(wdir.glob("clip_*.npy")) + list(wdir.glob("labels_*.npz")):
        c_num = int(cf.name.split("_")[1].split(".")[0])
        if c_num >= 2:
            cf.unlink()

    idx = D.ClipIndex(part_dir)
    assert len(idx) == 2

    mod = _runner_module(LIVE)
    teachers = mod._write_fake_teachers(idx, tmp_path / "teachers")

    load_calls = []
    real_np_load = D.np.load

    def counting_load(file, *args, **kwargs):
        load_calls.append(str(file))
        return real_np_load(file, *args, **kwargs)

    monkeypatch.setattr(D.np, "load", counting_load)

    cfg = T.TrainConfig(lr=1e-3, batch_size=2, epochs=3, seed=0)
    student = Student(d=16, depth=1, heads=1)

    # 1. distill 跑 3 轮（2 段数据）：每段 clip、labels、vjepa、da2 只在首轮读 1 次，共 2 * 4 = 8 次 np.load（若无缓存则是 24 次）
    load_calls.clear()
    T.distill("A3", idx, teachers, cfg, student=student)
    assert len(load_calls) == 8, f"Expected 8 np.load calls with cache across 3 epochs, got {len(load_calls)}"

    # 2. train_supervised 跑 3 轮（2 段数据，无教师）：每段 clip、labels 只在首轮读 1 次，共 2 * 2 = 4 次（若无缓存则是 12 次）
    load_calls.clear()
    T.train_supervised(idx, cfg, student=student)
    assert len(load_calls) == 4, f"Expected 4 np.load calls with cache across 3 epochs, got {len(load_calls)}"

    # 3. train_heads 跑 3 轮（2 段数据）：前置缓存特征时读 1 次 clip + labels，后续 3 轮训练读出头时 0 次磁盘读取，共 4 次（若无缓存则是 4 + 3*4 = 16 次）
    load_calls.clear()
    T.train_heads(student, idx, cfg)
    assert len(load_calls) == 4, f"Expected 4 np.load calls in train_heads with cache, got {len(load_calls)}"



def test_code_change_during_a_stage_stops_the_next_cell(tmp_path: Path):
    """Each cell re-checks the frozen manifest; editing a frozen file mid-stage must stop the stage (tier-1, 11-12)."""
    root = _make_root(tmp_path)
    _mutate_file(root, f"{HERE}/run_s5p1.py",
                 "def _execute_cell_body(cell: dict, ctx: dict) -> dict:\n",
                 "def _execute_cell_body(cell: dict, ctx: dict) -> dict:\n"
                 "    _t = REPO / 'src/ainerzero/v9/experiments/s5/train.py'\n"
                 "    _t.write_text(_t.read_text() + '\\n# touched mid-stage by a test\\n')\n")
    ran = _run(root, "--stage", "smoke", "--use-id", "s-edit", "--report", "reports/out.json")
    assert ran.returncode == 2, ran.stdout[-2000:] + ran.stderr[-2000:]
    events = _events(root)
    assert [e["cell_id"] for e in events if e["event"] == "cell_end"] == ["smoke-distill-A1"], events
    fails = [e for e in events if e["event"] == "cell_fail"]
    assert fails and "code changed during stage" in fails[0]["error"] and "train.py" in fails[0]["error"], fails


# ------------------------------------------------------------------------------------------------
# dev-tune-b（用户 2026-11-12 批准追加约 1 h）：评两个蒸馏学习率候选的读出头，补跑没跑完的 η 格
# ------------------------------------------------------------------------------------------------
def _write_tune(root: Path, text: str, name: str = "tune.json") -> tuple[Path, str]:
    import hashlib

    tune = root / "reports" / name
    tune.write_text(text, encoding="utf-8")
    return tune, hashlib.sha256(tune.read_bytes()).hexdigest()


def _fake_dev_tune_run(root: Path) -> Path:
    import hashlib

    run = root / RUNS / "dev-tune-t-20261112T000000Z"
    (run / "weights").mkdir(parents=True)
    events = [{"event": "stage_start", "stage": "dev-tune", "use_id": "t"}]
    for i, lr in enumerate(("0.0003", "0.001")):
        path = run / "weights" / f"tune-distill-A2-lr{lr}-student.npz"
        path.write_bytes(f"student-{i}".encode())
        events.append({"event": "cell_end", "cell_id": f"tune-distill-A2-lr{lr}",
                       "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}})
    (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return run


def _new_runs(root: Path, before: set[str]) -> list[Path]:
    runs = root / RUNS
    return [p for p in runs.iterdir() if p.name not in before] if runs.exists() else []


def test_dev_tune_b_refuses_bad_arguments_before_any_output(tmp_path: Path):
    root = _make_root(tmp_path)
    _write_inputs(root, partitioned_teachers=True)
    run = _fake_dev_tune_run(root)
    before = {p.name for p in (root / RUNS).iterdir()}
    tune, digest = _write_tune(root, '{"distill_lr": 0.0003, "supervised_lr": 0.0003}\n')
    lacking, lacking_sha = _write_tune(root, '{"distill_lr": 0.0003}\n', "tune-lacking.json")
    base = ["--stage", "dev-tune-b", "--report", "reports/out.json"]
    ok_tune = ["--tune-file", str(tune), "--tune-sha", digest]
    cases = [
        (base + ["--use-id", "e1", "--etas", "0.5", "--tune-run", str(run)], "needs --tune-file"),
        (base + ["--use-id", "e2", *ok_tune, "--tune-run", str(run)], "needs --etas"),
        (base + ["--use-id", "e3", *ok_tune, "--etas", "0.3", "--tune-run", str(run)], "invalid --etas"),
        (base + ["--use-id", "e4", "--tune-file", str(lacking), "--tune-sha", lacking_sha, "--etas", "0.5",
                 "--tune-run", str(run)], "lacks"),
        (base + ["--use-id", "e5", *ok_tune, "--etas", "0.5"], "needs --tune-run"),
        (["--stage", "dev-distill", "--report", "reports/out.json", "--use-id", "e6", *ok_tune, "--etas", "0.5"],
         "only valid"),
        (["--stage", "dev-distill", "--report", "reports/out.json", "--use-id", "e7", *ok_tune,
          "--tune-run", str(run)], "only valid"),
    ]
    for args, message in cases:
        ran = _run(root, *args, timeout=120)
        assert ran.returncode != 0, (args, ran.stdout[-800:])
        assert message in ran.stderr, (args, ran.stderr[-800:])
        assert not _new_runs(root, before), args
        assert not (root / LEDGER).exists(), args
        assert not (root / "reports/out.json").exists(), args
    # 学生权重被改过：在花 dev 使用之前就拒绝
    (run / "weights" / "tune-distill-A2-lr0.001-student.npz").write_bytes(b"changed")
    ran = _run(root, *base, "--use-id", "e8", *ok_tune, "--etas", "0.5", "--tune-run", str(run), timeout=120)
    assert ran.returncode != 0 and "SHA mismatch" in ran.stderr, ran.stderr[-800:]
    assert not _new_runs(root, before) and not (root / LEDGER).exists()


def test_dev_tune_b_runs_the_readouts_and_eta_cells_with_the_tuned_lr(tmp_path: Path):
    root = _make_root(tmp_path)
    _write_inputs(root, partitioned_teachers=True)
    run = _fake_dev_tune_run(root)
    # 假输入只有 1 个 lab 世界，把 L=512 的子集改成 1 个世界；格子主体换成只回报收到的参数，不训练
    _mutate_file(root, f"{HERE}/plan_s5p1.py",
                 "L_WORLDS = {64: 4, 512: 32, 2048: 128}",
                 "L_WORLDS = {64: 1, 512: 1, 2048: 1}")
    _mutate_file(root, f"{HERE}/run_s5p1.py",
                 "def _execute_cell_body(cell: dict, ctx: dict) -> dict:\n",
                 "def _execute_cell_body(cell: dict, ctx: dict) -> dict:\n"
                 "    if ctx['stage'] == 'dev-tune-b':\n"
                 "        return {'cell_id': cell['cell_id'], 'kind': cell['kind'], 'lr': cell['lr'], 'eta': cell.get('eta'),\n"
                 "                'distill_lr': cell.get('distill_lr'), 'student_file': cell.get('student_file'),\n"
                 "                'student_sha': cell.get('student_sha'), 'arm': cell['arm'], 'epochs': cell['epochs'],\n"
                 "                'teachers': ctx['teachers'], 'files': {}}\n")
    tune, digest = _write_tune(root, '{"distill_lr": 0.001, "supervised_lr": 0.0003}\n')
    ran = _run(root, "--stage", "dev-tune-b", "--use-id", "b-1", "--report", "reports/out.json",
               "--tune-file", str(tune), "--tune-sha", digest, "--etas", "1.0,0.5", "--tune-run", str(run), timeout=300)
    assert ran.returncode == 0, ran.stderr[-2000:] + ran.stdout[-2000:]
    out = next(p for p in (root / RUNS).iterdir() if p.name.startswith("dev-tune-b-"))
    events = [json.loads(line) for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    ends = [e for e in events if e["event"] == "cell_end"]
    assert [(e["cell_id"], e["kind"], e["lr"], e["eta"], e["distill_lr"], e["arm"], e["epochs"]) for e in ends] == [
        ("tune-heads-A2-dlr0.0003", "heads", 0.0003, None, 0.0003, "A2", 60),
        ("tune-heads-A2-dlr0.001", "heads", 0.0003, None, 0.001, "A2", 60),
        ("tune-A4-eta0.5", "supervised", 0.0003, 0.5, None, "A4", 60),
        ("tune-A4-eta1.0", "supervised", 0.0003, 1.0, None, "A4", 60),
    ]
    import hashlib
    for e, lr in zip(ends[:2], ("0.0003", "0.001")):
        path = Path(e["student_file"])
        assert path == (run / "weights" / f"tune-distill-A2-lr{lr}-student.npz").resolve()
        assert e["student_sha"] == hashlib.sha256(path.read_bytes()).hexdigest()
    # A4 的对齐特征取 lab 分区的 V-JEPA 教师
    lab_vjepa = {"vjepa": str(root.resolve() / "artifacts/v9/s5/teachers/vjepa/s5p1-lab")}
    assert all(e["teachers"] == lab_vjepa for e in ends[2:]), ends
    assert "b-1" in (root / LEDGER).read_text(encoding="utf-8")
    stage = json.loads((out / "stage.json").read_text(encoding="utf-8"))
    assert stage["failed"] is None and stage["n_completed"] == 4
