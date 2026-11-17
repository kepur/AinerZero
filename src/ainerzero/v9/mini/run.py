"""一条命令跑通：生成数据 → 训练 → 预测指标 → 代价诊断 → 到达目标。

用法（仓库根目录）：
    .venv/bin/python -m ainerzero.v9.mini.run --quick --out reports/V9-MINI/explore/quick
    .venv/bin/python -m ainerzero.v9.mini.run --out reports/V9-MINI/explore/<名字> [--seed 0]

这是探索性运行，不是登记运行：结果只用于调方案，不算证据。确认性运行要另写预登记、冻结代码、
生成新的留出图，并由非作者复算。

运行期间持有共享 MLX 锁 artifacts/locks/m0-worker.lock（flock，非阻塞；锁忙直接退出 75）。
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import mlx.core as mx

from . import data as D
from . import evaluate as E
from . import world as W
from .train import TrainConfig, train

ROOT = Path(__file__).resolve().parents[4]
LOCK = ROOT / "artifacts" / "locks" / "m0-worker.lock"

PRESETS = {
    "quick": dict(layouts=60, tpl=4, horizon=200, steps=3000, eval_layouts=12, prefix=400, n_short=2, n_long=4,
                  diag_layouts=6),
    "full": dict(layouts=400, tpl=4, horizon=200, steps=12000, eval_layouts=50, prefix=400, n_short=3, n_long=4,
                 diag_layouts=20),
}


def _code_sha() -> str:
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int)
    args = ap.parse_args(argv)
    preset = dict(PRESETS["quick" if args.quick else "full"])
    if args.steps:
        preset["steps"] = args.steps

    fh = open(LOCK, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("m0-worker.lock 忙，退出", flush=True)
        return 75

    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "log.txt", "w")

    def log(msg: str) -> None:
        print(msg, flush=True)
        logf.write(msg + "\n")
        logf.flush()

    cfg = W.Config()
    t0 = time.time()
    meta = {"preset": preset, "seed": args.seed, "world": cfg.__dict__, "code_sha256": _code_sha(),
            "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
            "mlx": mx.__version__, "python": sys.version.split()[0], "machine": platform.machine(),
            "status": "exploratory, not evidence"}
    log(f"[data] {preset['layouts']} 张训练图 × {preset['tpl']} 条 × {preset['horizon']} 步")
    ds = D.generate(preset["layouts"], preset["tpl"], preset["horizon"], cfg, seed0=D.TRAIN_SEED0 + 1000 * args.seed)
    log(f"[train] {preset['steps']} 步")
    model, tinfo = train(ds, preset["tpl"], TrainConfig(steps=preset["steps"], seed=args.seed), log=log)
    log(f"[train] 参数 {tinfo['params']}，{tinfo['train_sec']} 秒")
    pred = E.prediction_metrics(model, cfg, preset["diag_layouts"])
    log(f"[pred] {pred}")
    diag = E.cost_diagnostics(model, cfg, preset["diag_layouts"])
    log(f"[cost] {diag}")
    tasks = E.make_tasks(cfg, preset["eval_layouts"], preset["prefix"], preset["n_short"], preset["n_long"])
    log(f"[tasks] {len(tasks)} 个回合（短 {sum(t['kind'] == 'short' for t in tasks)}，长 {sum(t['kind'] == 'long' for t in tasks)}）")
    ev = E.evaluate_tasks(model, cfg, tasks, seed=args.seed, log=log)
    log("[success]")
    for k, v in ev["summary"].items():
        log(f"  {k:28s} n={v['n']:3d}  success={v['success']:.3f}  spl={v['spl']:.3f}")
    meta["wall_sec"] = round(time.time() - t0, 1)
    result = {"meta": meta, "train": tinfo, "prediction": pred, "cost_diagnostics": diag,
              "success": ev["summary"]}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    (out / "episodes.json").write_text(json.dumps(ev["episodes"], ensure_ascii=False))
    log(f"[done] {meta['wall_sec']} 秒 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
