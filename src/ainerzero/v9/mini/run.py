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
from . import residual as R
from . import world as W
from .train import TrainConfig, train

ROOT = Path(__file__).resolve().parents[4]
LOCK = ROOT / "artifacts" / "locks" / "m0-worker.lock"

PRESETS = {
    "medium": dict(layouts=200, tpl=4, horizon=200, steps=6000, eval_layouts=30, prefix=400, n_short=2, n_long=4,
                   diag_layouts=12, belief_steps=3000),
    "quick": dict(layouts=60, tpl=4, horizon=200, steps=3000, eval_layouts=12, prefix=400, n_short=2, n_long=4,
                  diag_layouts=6, belief_steps=1500),
    "full": dict(layouts=400, tpl=4, horizon=200, steps=12000, eval_layouts=50, prefix=400, n_short=3, n_long=4,
                 diag_layouts=20, belief_steps=4000),
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
    ap.add_argument("--preset", choices=("quick", "medium", "full"))
    ap.add_argument("--arms", help="只跑这些臂，逗号分隔（默认全部）")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int)
    ap.add_argument("--eval-layouts", type=int, help="留出图张数（覆盖预设）")
    ap.add_argument("--eval-seed0", type=int,
                    help="留出图种子起点（默认 data.EVAL_SEED0，探索段三个种子共用）；确认段每个种子传不同的值，留出图互不重叠")
    ap.add_argument("--world", choices=("m1", "m2"), default="m1",
                    help="m1：规律全部已知；m2：两间冰房 + 两个单向传送门（解析先验不知道）")
    args = ap.parse_args(argv)
    preset = dict(PRESETS[args.preset or ("quick" if args.quick else "full")])
    if args.steps:
        preset["steps"] = args.steps
    if args.eval_layouts:
        preset["eval_layouts"] = args.eval_layouts
    eval_seed0 = D.EVAL_SEED0 if args.eval_seed0 is None else args.eval_seed0
    train_lo = D.TRAIN_SEED0 + 1000 * args.seed
    train_hi = train_lo + preset["layouts"]
    eval_hi = eval_seed0 + max(preset["eval_layouts"], preset["diag_layouts"] * 4)
    if eval_seed0 < train_hi and train_lo < eval_hi:
        raise SystemExit(f"留出图种子 [{eval_seed0}, {eval_hi}) 与训练图种子 [{train_lo}, {train_hi}) 重叠")

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

    cfg = W.Config() if args.world == "m1" else W.Config(ice_rooms=2, portals=2)
    t0 = time.time()
    meta = {"preset": preset, "seed": args.seed, "eval_seed0": eval_seed0, "world": cfg.__dict__, "code_sha256": _code_sha(),
            "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
            "mlx": mx.__version__, "python": sys.version.split()[0], "machine": platform.machine(),
            "status": "exploratory, not evidence"}
    log(f"[data] {preset['layouts']} 张训练图 × {preset['tpl']} 条 × {preset['horizon']} 步")
    ds = D.generate(preset["layouts"], preset["tpl"], preset["horizon"], cfg, seed0=D.TRAIN_SEED0 + 1000 * args.seed)
    log(f"[train] {preset['steps']} 步")
    model, tinfo = train(ds, preset["tpl"], TrainConfig(steps=preset["steps"], seed=args.seed), log=log)
    log(f"[train] 参数 {tinfo['params']}，{tinfo['train_sec']} 秒")
    pred = E.prediction_metrics(model, cfg, preset["diag_layouts"], eval_seed0=eval_seed0)
    log(f"[pred] {pred}")
    # 前进模型：解析先验 / 门控残差 / 不门控，训练图与世界模型相同；样本量曲线在留出图上测
    seed0 = D.TRAIN_SEED0 + 1000 * args.seed
    rx, ry = R.collect(cfg, preset["layouts"], preset["tpl"], preset["horizon"], seed0, seed=args.seed)
    hx, hy = R.collect(cfg, preset["diag_layouts"] * 4, 4, preset["horizon"], eval_seed0, seed=args.seed + 99)
    fms = {"analytic": R.fit("analytic", rx, ry)}
    curve = {"analytic": R.accuracy(fms["analytic"], hx, hy)}
    import numpy as _np
    rs = _np.random.default_rng(args.seed)
    for n in (300, 1000, 3000, 10000, len(rx)):
        n = min(n, len(rx))
        idx = rs.permutation(len(rx))[:n]
        for kind in ("gated", "ungated"):
            fm = R.fit(kind, rx[idx], ry[idx], seed=args.seed)
            curve[f"{kind}@{n}"] = {**R.accuracy(fm, hx, hy), "n_events_train": fm.n_events}
            if n == len(rx):
                fms[kind] = fm
    ax, ay = R.collect(cfg, preset["layouts"], preset["tpl"], preset["horizon"], seed0, seed=args.seed,
                       near_mask_prob=0.15)
    fms["ungated_aug"] = R.fit("ungated", ax, ay, seed=args.seed)
    curve[f"ungated_aug@{len(ax)}"] = R.accuracy(fms["ungated_aug"], hx, hy)
    # M3：前进模型的训练标签不用真值，改由只有解析先验的地图智能体自己的定位给出
    sx, sy, squal = R.collect_self(cfg, preset["layouts"], preset["tpl"], preset["horizon"], seed0, seed=args.seed)
    fms["gated_self"] = R.fit("gated", sx, sy, seed=args.seed)
    curve[f"gated_self@{len(sx)}"] = {**R.accuracy(fms["gated_self"], hx, hy), "n_events_train": fms["gated_self"].n_events}
    log(f"[m3] 自监督标签 {squal}")
    for k, v in curve.items():
        log(f"[forward] {k:16s} all={v['all']:.4f} event={v['event']:.3f} non_event={v['non_event']:.4f} "
            f"(留出事件 {v['n_event']}/{v['n']}，训练事件 {v.get('n_events_train', '-')})")
    diag = E.cost_diagnostics(model, cfg, preset["diag_layouts"], eval_seed0=eval_seed0)
    log(f"[cost] {diag}")
    arms = tuple(args.arms.split(",")) if args.arms else E.ARMS
    belief, binfo, bdiag = None, {}, {}
    if "gru_belief" in arms:
        from .belief import train_belief
        log(f"[belief] 训练 GRU 信念 {preset['belief_steps']} 步")
        belief, binfo = train_belief(model, ds, preset["tpl"], steps=preset["belief_steps"], seed=args.seed, log=log)
        bdiag = E.belief_diagnostics(model, belief, cfg, preset["diag_layouts"], eval_seed0=eval_seed0)
        log(f"[belief] {bdiag}")
    tasks = E.make_tasks(cfg, preset["eval_layouts"], preset["prefix"], preset["n_short"], preset["n_long"],
                         eval_seed0=eval_seed0)
    log(f"[tasks] {len(tasks)} 个回合（短 {sum(t['kind'] == 'short' for t in tasks)}，长 {sum(t['kind'] == 'long' for t in tasks)}）")
    log(f"[tasks] 规律相关 {sum(t['law_relevant'] for t in tasks)} 个")
    ev = E.evaluate_tasks(model, cfg, tasks, fms, arms=arms, seed=args.seed, log=log, belief=belief)
    log("[success]")
    for k, v in ev["summary"].items():
        sr = f"  surprise={v['surprise_rate']:.3f}" if v.get("surprise_rate") is not None else ""
        log(f"  {k:30s} n={v['n']:3d}  success={v['success']:.3f}  spl={v['spl']:.3f}{sr}")
    meta["wall_sec"] = round(time.time() - t0, 1)
    result = {"meta": meta, "train": tinfo, "prediction": pred, "forward_model": curve, "cost_diagnostics": diag,
              "belief": {**binfo, "diagnostics": bdiag},
              "m3_label_quality": squal,
              "success": ev["summary"]}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    (out / "episodes.json").write_text(json.dumps(ev["episodes"], ensure_ascii=False))
    log(f"[done] {meta['wall_sec']} 秒 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
