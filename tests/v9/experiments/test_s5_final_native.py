"""S5 登记运行器的原生冒烟：替身分区、极小学生，端到端跑训练格、评测和门。

- 绝不生成、读取真实的 ``s5p1-final`` / ``s5p1-final-shift``：替身名字都以 ``s5test-`` 开头，测试开头就断言。
- 一切都在一次性仓库副本里跑：副本有自己的锁、runs、data 和 teachers。
- 冻结前的 66 个钉住权重用极小学生随机初始化后保存（可加载），不训练。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.native_mlx

LIVE = Path(__file__).resolve().parents[3]
REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PHASE1 = "reports/V9-S5-PHASE1"
TINY = {"d": 16, "depth": 1, "heads": 1}
POOL, LAB = "s5test-smoke-pool", "s5test-smoke-lab"
FINAL, SHIFT = "s5test-regfinal", "s5test-regfinal-shift"
CLIPS = [0, 1]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _child(root: Path, code: str, timeout: int = 900) -> subprocess.CompletedProcess:
    """在副本里起一个新解释器：sys.path 只指向副本的 src 和 PHASE1。"""
    assert root.resolve() not in (LIVE, REAL_REPO)
    prelude = (
        "import sys\n"
        f"sys.path.insert(0, {str(root / 'src')!r})\n"
        f"sys.path.insert(0, {str(root / PHASE1)!r})\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(root / "src")
    return subprocess.run([sys.executable, "-I", "-c", prelude + code], cwd=root, env=env,
                          capture_output=True, text=True, timeout=timeout)


def _make_root(tmp_path: Path) -> Path:
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    root = tmp_path / "repo"
    shutil.copytree(LIVE / "src/ainerzero", root / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    (root / PHASE1).mkdir(parents=True)
    for name in ("run_s5p1.py", "plan_s5p1.py", "run_s5p1_final.py", "make_prereg_s5p1.py"):
        shutil.copy2(LIVE / PHASE1 / name, root / PHASE1 / name)
    (root / "artifacts/locks").mkdir(parents=True)
    (root / ".gitignore").write_text("artifacts/\n__pycache__/\nreports/V9-S5-FINAL/\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "copy")
    assert root.resolve() not in (LIVE, REAL_REPO)
    return root


SETUP = r'''
import json, hashlib
from pathlib import Path
import numpy as np
import mlx.core as mx
import run_s5p1 as pre
from ainerzero.v9.experiments.s5.materialize import materialize_partition
from ainerzero.v9.experiments.s5.data import ClipIndex
from ainerzero.v9.experiments.s5.student import Student
from ainerzero.v9.experiments.s5.heads import FlatHead, R1Head
from ainerzero.v9.experiments.s5.train import HeadsContainer

root = Path.cwd()
data = root / "artifacts/v9/s5/data"
teachers = root / "artifacts/v9/s5/teachers"
for name, n in ((POOL, 2), (LAB, 2)):
    materialize_partition(name, data / name, world_range=(0, n))
pool = ClipIndex(data / POOL, clips=CLIPS)
lab = ClipIndex(data / LAB, clips=CLIPS)
# 与运行器一致的布局：teachers/<teacher>/<partition>
tmp_pool = pre._write_fake_teachers(pool, root / "tmp-teachers/pool")
tmp_lab = pre._write_fake_teachers(lab, root / "tmp-teachers/lab")
for teacher, src in (("vjepa", tmp_pool["vjepa"]), ("da2", tmp_pool["da2"])):
    (teachers / teacher).mkdir(parents=True, exist_ok=True)
    Path(src).rename(teachers / teacher / POOL)
Path(tmp_lab["vjepa"]).rename(teachers / "vjepa" / LAB)

run = root / "artifacts/v9/s5/runs/dev-distill-standin-20261113T000000Z"
(run / "weights").mkdir(parents=True)
events = [{"event": "stage_start", "stage": "dev-distill", "use_id": "standin"}]
def save(module, name, seed):
    mx.random.seed(seed)
    return pre._save_weights(module, run / "weights" / name)
def readout(seed):
    mx.random.seed(seed)
    return HeadsContainer(r1=R1Head(d=TINY["d"]), r2=FlatHead(d=TINY["d"], k=4), r3=FlatHead(d=TINY["d"], k=4))
k = 0
for arm in ("A1", "A2", "A3"):
    for d in (0, 1):
        cid = f"distill-{arm}-s{d}"
        mx.random.seed(k); stu = Student(**TINY); k += 1
        files = {f"{cid}-student.npz": pre._save_weights(stu, run / "weights" / f"{cid}-student.npz"),
                 f"{cid}-heads.npz": pre._save_weights(readout(k), run / "weights" / f"{cid}-heads.npz")}
        events.append({"event": "cell_end", "cell_id": cid, "files": files})
        for L in (64, 512, 2048):
            for r in (0, 1, 2):
                hid = f"heads-{arm}-d{d}-L{L}-r{r}"
                k += 1
                events.append({"event": "cell_end", "cell_id": hid,
                               "files": {f"{hid}.npz": pre._save_weights(readout(k), run / "weights" / f"{hid}.npz")}})
for s in (0, 1, 2):
    cid = f"A0-L64-s{s}"
    mx.random.seed(100 + s); stu = Student(**TINY)
    files = {f"{cid}-student.npz": pre._save_weights(stu, run / "weights" / f"{cid}-student.npz"),
             f"{cid}-heads.npz": pre._save_weights(readout(200 + s), run / "weights" / f"{cid}-heads.npz")}
    events.append({"event": "cell_end", "cell_id": cid, "files": files})
events.append({"event": "stage_end", "failed": None, "n_completed": 63})
(run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
stage = {"stage": "dev-distill", "use_id": "standin", "failed": None, "n_completed": 63,
         "selection": {"a_star": {"arm": "A1", "score": 0.03, "tied": ["A1"]},
                       "power": {"n_worlds": 1, "n_uncapped": 1, "capped": False}}}
(run / "stage.json").write_text(json.dumps(stage), encoding="utf-8")
tune = root / "reports/V9-S5-PHASE1/tune-standin.json"
tune.write_text(json.dumps({"distill_lr": 3e-4, "supervised_lr": 1e-3, "eta": 1.0}) + "\n", encoding="utf-8")

import make_prereg_s5p1 as mp
overrides = {
    "standin_test": True,
    "partitions": {"pool": POOL, "lab": LAB, "final": FINAL, "final_shift": SHIFT},
    "student_kwargs": TINY, "clips": CLIPS,
    "l_worlds_map": {"64": 1, "512": 1, "2048": 2},
    "effective_l_clips": {"64": 2, "512": 2, "2048": 4},
    "pool_n_clips": 4, "distill_epochs": 1, "batch_size": 2,
    # L=512：2 段 / 批量 2 × 16 轮 = 16 步，每步一个检查点，正好凑满 GA 要的 16 个（生产是 3840 步、每 240 步一个）
    "super_epochs": {"64": 1, "512": 16, "2048": 1}, "readout_epochs": {"64": 1, "512": 1, "2048": 1},
    "n_boot": 50,
}
doc = mp.build_prereg(run, tune_file=tune, n_final=1, budget_h=1.0, repo=root, standin_overrides=overrides)
out = root / "reports/V9-S5-FINAL/PREREG.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
print(json.dumps({"prereg": str(out), "sha": hashlib.sha256(out.read_bytes()).hexdigest()}))
'''


def _setup(root: Path) -> tuple[Path, str]:
    consts = f"POOL={POOL!r}\nLAB={LAB!r}\nFINAL={FINAL!r}\nSHIFT={SHIFT!r}\nCLIPS={CLIPS!r}\nTINY={TINY!r}\n"
    res = _child(root, consts + SETUP)
    assert res.returncode == 0, res.stderr[-3000:] + res.stdout[-1000:]
    info = json.loads(res.stdout.strip().splitlines()[-1])
    return Path(info["prereg"]), info["sha"]


def _run_final(root: Path, prereg: Path, sha: str, *extra: str, timeout: int = 1800):
    assert root.resolve() not in (LIVE, REAL_REPO)
    pyc = root.parent / f"pyc-{time.monotonic_ns()}"
    pyc.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    cmd = [sys.executable, "-I", "-X", f"pycache_prefix={pyc}", str(root / PHASE1 / "run_s5p1_final.py"),
           "--prereg", str(prereg), "--prereg-sha", sha, "--report", str(root / "reports/final-out.json"), *extra]
    return subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=timeout)


def _the_run(root: Path) -> Path:
    runs = [p for p in (root / "artifacts/v9/s5/runs").iterdir() if p.name.startswith("final-")]
    assert len(runs) == 1, runs
    return runs[0]


def test_standin_names_are_not_registered():
    sys.path.insert(0, str(LIVE / "src"))
    from ainerzero.v9.experiments.s5 import world

    assert world.REGISTERED == frozenset({"s5p1-final", "s5p1-final-shift"})
    for name in (FINAL, SHIFT, POOL, LAB):
        assert name.startswith("s5test-") and name not in world.REGISTERED and "s5p1-final" not in name


def test_registered_runner_end_to_end_on_standin_partitions(tmp_path: Path):
    root = _make_root(tmp_path)
    prereg, sha = _setup(root)
    ran = _run_final(root, prereg, sha, "--run-id", "standin-1")
    assert ran.returncode == 0, ran.stderr[-4000:] + ran.stdout[-2000:]
    run = _the_run(root)
    events = [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    ends = [e["cell_id"] for e in events if e["event"] == "cell_end"]
    assert len(ends) == 49 and not [e for e in events if e["event"] == "cell_fail"], events[-5:]
    # 评测只在全部训练格之后开始
    kinds = [e["event"] for e in events]
    assert kinds.index("eval_start") > max(i for i, k in enumerate(kinds) if k == "cell_end")
    # 替身 final 只在本次运行里生成；真实 final 名字从未出现
    data = root / "artifacts/v9/s5/data"
    assert (data / FINAL).is_dir() and (data / SHIFT).is_dir()
    assert not (data / "s5p1-final").exists() and not (data / "s5p1-final-shift").exists()
    # SPEC 补记 1 的命名约定
    metrics = run / "metrics"
    expect = ["heads-A1-d0-L64-r0", "heads-C-sh-d1-L2048-r2", "heads-R-d0-L512-r1",
              "A0-L64-s2", "A0-L2048-s0", "A4-L512-s1", "A0-R-L512-s0", "FT-L64-s2"]
    for model_id in expect:
        for part in (FINAL, SHIFT):
            assert any(metrics.glob(f"{model_id}.{part}*.npz")), (model_id, part, sorted(p.name for p in metrics.iterdir())[:20])
    for arm in ("A0", "A4"):
        for s in (0, 1, 2):
            curve = json.loads((metrics / f"ckpt-{arm}-L512-s{s}.json").read_text(encoding="utf-8"))
            assert len(curve["steps"]) == len(curve["r2_ap"]) >= 1 and curve["steps"] == sorted(curve["steps"])
    for cid in ("distill-R-s0", "distill-R-s1", "distill-C-sh-s0", "distill-C-sh-s1"):
        timing = json.loads((run / "timing" / f"{cid}.json").read_text(encoding="utf-8"))
        assert timing["seconds_per_step"] > 0
    gates = json.loads((run / "gates.json").read_text(encoding="utf-8"))["gates"]
    for g in ("GT1", "GT2", "GT3", "GA", "GR"):
        assert g in gates and isinstance(gates[g]["passed"], bool), (g, gates.get(g))
        assert {"point_estimate", "ci_lower", "ci_upper", "level"} <= set(gates[g]) or g == "GA", (g, gates[g])
    # 登记账本只认这一次成功运行；dev 账本没被动过
    ledger = json.loads((root / "artifacts/v9/s5/registered-runs.json").read_text(encoding="utf-8"))
    assert json.dumps(ledger).count("standin-1") >= 1
    assert not (root / "artifacts/v9/s5/dev-uses.json").exists()

    # 同一 PREREG 不许再跑第二次
    again = _run_final(root, prereg, sha, "--run-id", "standin-2", timeout=300)
    assert again.returncode != 0
    assert len([p for p in (root / "artifacts/v9/s5/runs").iterdir() if p.name.startswith("final-")]) == 1


def test_tampered_pinned_weight_is_refused_before_any_output(tmp_path: Path):
    root = _make_root(tmp_path)
    prereg, sha = _setup(root)
    weight = next((root / "artifacts/v9/s5/runs").glob("dev-distill-standin-*/weights/heads-A1-d0-L64-r0.npz"))
    raw = bytearray(weight.read_bytes())
    raw[-1] ^= 1
    weight.write_bytes(bytes(raw))
    ran = _run_final(root, prereg, sha, "--run-id", "standin-t", timeout=300)
    assert ran.returncode != 0 and "SHA" in ran.stderr, ran.stderr[-2000:]
    assert not [p for p in (root / "artifacts/v9/s5/runs").iterdir() if p.name.startswith("final-")]
    assert not (root / "artifacts/v9/s5/registered-runs.json").exists()
    assert not (root / "artifacts/v9/s5/data" / FINAL).exists()
