"""探索（不算证据）：只训练注意力记忆组并在探索留出图上评测，存权重，附代价校准诊断。

诊断用真值（只作分析，不进智能体）：每个回合起点，Q 的最小值与真值最短步数 d* 的秩相关；
以及在真值最短路的第一步上，学到的代价是否最小（「第一步对不对」）。

用法（仓库根目录，持有 m0-worker.lock）：
    .venv/bin/python reports/V9-MINI/explore/attn/attn_explore.py --world m1 --seed 0 --out reports/V9-MINI/explore/attn/x \
        [--cfg '{"steps": 6000}'] [--nets 已存权重.npz]
"""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[4]

import mlx.core as mx  # noqa: E402
import numpy as np  # noqa: E402

from ainerzero.v9.mini import agents as A  # noqa: E402
from ainerzero.v9.mini import attn as AT  # noqa: E402
from ainerzero.v9.mini import data as D  # noqa: E402
from ainerzero.v9.mini import evaluate as E  # noqa: E402
from ainerzero.v9.mini import world as W  # noqa: E402
from ainerzero.v9.mini.run import PRESETS  # noqa: E402


def spearman(x, y):
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    rx -= rx.mean()
    ry -= ry.mean()
    return float((rx * ry).sum() / np.sqrt((rx ** 2).sum() * (ry ** 2).sum()))


def calibration(nets, cfg, tasks):
    rows = []
    for task in tasks:
        layout = W.make_layout(task["layout_seed"], cfg)
        poses = task["prefix_poses"]
        obs = W.iter_views(layout, poses)
        g = task["goal"]
        ep = A.Episode(obs, None, None, list(task["prefix_acts"]), W.encode_obs(W.ego_view(layout, g), g[2]), None, None)
        ag = AT.AttnAgent(nets, eps=0.0)
        ag.reset(ep)
        q = ag.q_last()
        dm = W.reverse_bfs_to_cell(layout, (g[0], g[1]))
        start = task["start"]
        dn = np.array([dm.get(W.step(layout, start, a), 10 ** 6) for a in range(W.N_ACTIONS)])
        rows.append({"kind": task["kind"], "d_star": task["d_star"], "q_min": float(q.min()),
                     "first_step_ok": bool(dn[int(np.argmin(q))] == dn.min()),
                     "first_step_chance": float((dn == dn.min()).mean())})
    out = {}
    for kind in ("short", "long", "all"):
        sub = [r for r in rows if kind == "all" or r["kind"] == kind]
        if len(sub) < 3:
            continue
        out[kind] = {"n": len(sub),
                     "rho_qmin_dstar": spearman(np.array([r["q_min"] for r in sub]), np.array([r["d_star"] for r in sub])),
                     "q_min_mean": float(np.mean([r["q_min"] for r in sub])),
                     "d_star_mean": float(np.mean([r["d_star"] for r in sub])),
                     "first_step_ok": float(np.mean([r["first_step_ok"] for r in sub])),
                     "first_step_chance": float(np.mean([r["first_step_chance"] for r in sub]))}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", choices=("m1", "m2"), default="m1")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cfg", default="{}", help="AttnConfig 覆盖项（JSON）")
    ap.add_argument("--nets", type=Path, help="读已存的权重，跳过训练")
    ap.add_argument("--ckpts", default="", help="逗号分隔的步数：到这些步时存权重并做诊断（不含最后一步）")
    ap.add_argument("--train-layout-diag", action="store_true",
                    help="诊断也在前 30 张训练图上做（任务的前缀游走与训练游走不同；只作分析）")
    args = ap.parse_args(argv)
    fh = open(ROOT / "artifacts/locks/m0-worker.lock", "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("m0-worker.lock 忙，退出", flush=True)
        return 75
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "log.txt", "a")

    def log(m):
        print(m, flush=True)
        logf.write(m + "\n")
        logf.flush()

    preset = PRESETS["medium"]
    cfg = W.Config() if args.world == "m1" else W.Config(ice_rooms=2, portals=2)
    acfg = AT.AttnConfig(**{"steps": preset["steps"], "seed": args.seed, **json.loads(args.cfg)})
    t0 = time.time()
    tasks = E.make_tasks(cfg, preset["eval_layouts"], preset["prefix"], preset["n_short"], preset["n_long"])
    seed0 = D.TRAIN_SEED0 + 1000 * args.seed
    tr_tasks = E.make_tasks(cfg, preset["eval_layouts"], preset["prefix"], preset["n_short"], preset["n_long"],
                            eval_seed0=seed0) if args.train_layout_diag else None
    ckpts = {int(c) for c in args.ckpts.split(",") if c}
    diag = {}

    def diagnose(tag, nets):
        row = {"heldout_calib": calibration(nets, cfg, tasks)}
        ev = E.evaluate_tasks(None, cfg, tasks, {}, arms=("latent_attn",), seed=args.seed, log=lambda *_: None, attn=nets)
        row["heldout_success"] = {k: v["success"] for k, v in ev["summary"].items()}
        if tr_tasks is not None:
            row["trainlayout_calib"] = calibration(nets, cfg, tr_tasks)
            ev2 = E.evaluate_tasks(None, cfg, tr_tasks, {}, arms=("latent_attn",), seed=args.seed, log=lambda *_: None, attn=nets)
            row["trainlayout_success"] = {k: v["success"] for k, v in ev2["summary"].items()}
        diag[tag] = row
        log(f"[diag {tag}] {json.dumps(row, ensure_ascii=False)}")

    def on_step(step, nets):
        if step in ckpts:
            nets.save_weights(str(out / f"nets-{step}.npz"))
            diagnose(f"step{step}", nets)

    if args.nets:
        nets = AT.AttnNets(W.obs_dim(cfg), d=acfg.d, layers=acfg.layers, heads=acfg.heads, scale=acfg.scale, q_init=acfg.q_init)
        nets.load_weights(str(args.nets))
        info = {"loaded": str(args.nets)}
    else:
        dl = AT.long_walks(cfg, preset["layouts"], preset["tpl"], preset["horizon"], seed0=D.TRAIN_SEED0 + 1000 * args.seed)
        nets, info = AT.train_attn(dl, acfg, log=log, on_step=on_step)
        nets.save_weights(str(out / "nets.npz"))
    if tr_tasks is not None:
        diagnose("final", nets)
    cal = calibration(nets, cfg, tasks)
    log(f"[calib] {json.dumps(cal, ensure_ascii=False)}")
    ev = E.evaluate_tasks(None, cfg, tasks, {}, arms=("random", "latent_attn"), seed=args.seed, log=log, attn=nets)
    for k, v in ev["summary"].items():
        log(f"  {k:24s} n={v['n']:3d} success={v['success']:.3f} spl={v['spl']:.3f}")
    res = {"world": args.world, "seed": args.seed, "attn_config": acfg.__dict__, "train": info, "calibration": cal,
           "checkpoint_diagnostics": diag,
           "success": ev["summary"], "wall_sec": round(time.time() - t0, 1), "status": "exploratory, not evidence"}
    (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    (out / "episodes.json").write_text(json.dumps(ev["episodes"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
