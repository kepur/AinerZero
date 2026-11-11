"""第 A 轮探针重算（纯 CPU，读第 A 轮缓存的 V-JEPA 特征）。

第 A 轮的逐块逆深度标签没截断：圆盘贴近相机时逆深度可到几百，少数极端值主导了 R²。
这里改用：
- 截断逆深度：深度先截到 ≥ 0.5（相机高度），天空记 0；
- 非天空像素的平均对数深度（只在天空占比 < 0.5 的块上评）；
- 圆盘占比。
对照：
- 像素（4×4 下采样 + 行列，50 维，与第 A 轮相同）；
- 全像素（管长 2 × 16 × 16 × 3 = 1536 维 + 行列）。
另外分「含物体的块」「纯地面或天空的块」两组报 R²。
用法：explore_s5a_probes.py <特征缓存 .npz>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "src"), str(HERE)]

import numpy as np  # noqa: E402

import render as R  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

WORLDS, N_DISKS, STEPS, SIZE, P = (0, 1, 2, 3), 6, 64, 224, 16
g = SIZE // P
cache = np.load(sys.argv[1])
assert json.loads((HERE / "round-a" / "result.json").read_text())["texture"] is True

frames, depths, ids = {}, {}, {}
for w in WORLDS:
    ep = W.generate_episode("s5x-explore", w, N_DISKS, steps=STEPS)
    out = [R.render(s.agent, s.positions, ep.pillars, return_ids=True, texture=True) for s in ep.steps]
    frames[w] = np.stack([R.to_uint8(o[0]) for o in out]); depths[w] = np.stack([o[1] for o in out])
    ids[w] = np.stack([o[2] for o in out])


def tub(a, w_px=1):
    """[STEPS, H, W, ...] -> [STEPS//2, 2, g, P, g, P, ...]"""
    return a.reshape(STEPS // 2, 2, g, P, g, P, *a.shape[3:])


def targets(w):
    d, o = tub(depths[w]), tub(ids[w])
    fin = np.isfinite(d)
    inv = np.where(fin, 1.0 / np.maximum(d, 0.5), 0.0).mean((1, 3, 5))
    logd = np.where(fin, np.log(np.maximum(d, 0.5)), 0.0).sum((1, 3, 5)) / np.maximum(fin.sum((1, 3, 5)), 1)
    sky = 1 - fin.mean((1, 3, 5))
    disk = (o >= 100).mean((1, 3, 5))
    has_obj = (o >= 0).any((1, 3, 5))
    return {"inv": inv.ravel(), "logd": logd.ravel(), "sky": sky.ravel(), "disk": disk.ravel(), "obj": has_obj.ravel()}


def x_vjepa(w):
    return cache[f"w{w}"].astype(np.float32).reshape(-1, cache[f"w{w}"].shape[-1])


def rowcol():
    rc = np.stack(np.meshgrid(np.arange(g), np.arange(g), indexing="ij"), -1) / g
    return np.broadcast_to(rc, (STEPS // 2, g, g, 2))


def x_pix_sub(w):
    f = tub(frames[w].astype(np.float32) / 255).mean(1)[:, :, ::4, :, ::4, :]
    f = f.transpose(0, 1, 3, 2, 4, 5).reshape(STEPS // 2, g, g, -1)
    return np.concatenate([f, rowcol()], -1).reshape(-1, 50)


def x_pix_full(w):
    f = tub(frames[w].astype(np.float32) / 255).transpose(0, 2, 4, 1, 3, 5, 6).reshape(STEPS // 2, g, g, -1)
    return np.concatenate([f, rowcol()], -1).reshape(-1, f.shape[-1] + 2)


def ridge(xtr, ytr, lam):
    mu, sd = xtr.mean(0), xtr.std(0) + 1e-6
    a = (xtr - mu) / sd
    w = np.linalg.solve(a.T @ a + lam * np.eye(a.shape[1]), a.T @ (ytr - ytr.mean()))
    return lambda x: ((x - mu) / sd) @ w + ytr.mean()


def r2(y, p):
    return float(1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()) if len(y) > 2 else float("nan")


tr, te = WORLDS[:3], WORLDS[3:]
T = {k: np.concatenate([targets(w)[k] for w in tr]) for k in ("inv", "logd", "sky", "disk", "obj")}
V = {k: np.concatenate([targets(w)[k] for w in te]) for k in ("inv", "logd", "sky", "disk", "obj")}
res = {"target_stats_test": {"inv_max": float(V["inv"].max()), "disk_nonzero_share": float((V["disk"] > 0).mean()),
                             "obj_patch_share": float(V["obj"].mean())}}
for name, fn in (("vjepa", x_vjepa), ("pixels_sub50", x_pix_sub), ("pixels_full1538", x_pix_full)):
    xtr = np.concatenate([fn(w) for w in tr]); xte = np.concatenate([fn(w) for w in te])
    row = {"dims": int(xtr.shape[1])}
    for lam in (1.0, 1e2, 1e3, 1e4):
        rr = {}
        for k in ("inv", "disk"):
            pred = ridge(xtr, T[k], lam)(xte)
            rr[f"{k}_all"] = r2(V[k], pred)
            rr[f"{k}_obj"] = r2(V[k][V["obj"]], pred[V["obj"]])
        m_tr, m_te = T["sky"] < 0.5, V["sky"] < 0.5
        pred = ridge(xtr[m_tr], T["logd"][m_tr], lam)(xte[m_te])
        rr["logd_nonsky"] = r2(V["logd"][m_te], pred)
        rr["logd_nonsky_obj"] = r2(V["logd"][m_te & V["obj"]], pred[V["obj"][m_te]])
        row[f"lambda={lam:g}"] = rr
    res[name] = row
    print(name, json.dumps(row), flush=True)
(HERE / "round-a" / "probes-r2.json").write_text(json.dumps(res, indent=1))
