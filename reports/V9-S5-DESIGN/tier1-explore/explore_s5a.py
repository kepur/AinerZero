"""S5 摸底第 A 轮（未登记，只用于设计）：两个教师在自渲染圆盘世界上给不给有用的信号。

不训练学生，只回答写设计稿前必须知道的几件事：
1. DA2（Core ML）在这类画面上的输出与真值深度是否单调相关、方向如何。
   对照：只按行号猜深度（地面深度只取决于行号，容易把相关性抬高），并单独看物体像素。
2. V-JEPA 2.1 在 224 分辨率、16 帧一段上跑多快、占多少内存。
3. V-JEPA 的逐块特征能否被线性探针读出逐块深度、圆盘占比。
   对照：同一探针读原始像素块。训练用世界 0-2，测试用世界 3。

画面、真值都由本仓库代码生成；对象编号只用于标签。
运行（须持锁）：
  .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py \
      artifacts/locks/m0-worker.lock envs/teachers/.venv-t4/bin/python -I \
      reports/V9-S5-DESIGN/tier1-explore/explore_s5a.py
"""
from __future__ import annotations

import gc
import json
import math
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "src"), str(HERE)]

import numpy as np  # noqa: E402

import render as R  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

NAMESPACE = "s5x-explore"          # unregistered exploration namespace
WORLDS = (0, 1, 2, 3)              # 0-2 train the probes, 3 tests them
N_DISKS = 6
STEPS = 64                         # 4 clips of 16 frames per world
CLIP = 16
SIZE = 224
PATCH = 16
TEXTURE = True                     # world-anchored floor checker and wall stripes (render.py)
DA2_W, DA2_H = 518, 392
VJEPA_DIR = ROOT / "artifacts/teachers/t4-approved/b0674736bad10eb16bd765942a9065e7e2ee9a54"
DA2_PATH = ROOT / "artifacts/teachers/t4-approved/cfef6f6f2a70783dedc0bfae40cecbc2052285d3/DepthAnythingV2SmallF16.mlpackage"
OUT = HERE / "round-a"


def peak_rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9   # bytes on macOS


def rank(a: np.ndarray) -> np.ndarray:
    o = np.argsort(a, kind="mergesort")
    r = np.empty(len(a))
    r[o] = np.arange(len(a))
    return r


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(rank(a), rank(b))[0, 1])


def ridge_fit_eval(xtr, ytr, xte, yte, lam):
    mu, sd = xtr.mean(0), xtr.std(0) + 1e-6
    a, b = (xtr - mu) / sd, (xte - mu) / sd
    ym = ytr.mean(0)
    w = np.linalg.solve(a.T @ a + lam * np.eye(a.shape[1]), a.T @ (ytr - ym))
    pred = b @ w + ym
    ss_res = ((yte - pred) ** 2).sum(0)
    ss_tot = ((yte - yte.mean(0)) ** 2).sum(0)
    return (1 - ss_res / ss_tot).tolist()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    res: dict = {"texture": TEXTURE, "namespace": NAMESPACE, "worlds": list(WORLDS), "n_disks": N_DISKS, "steps": STEPS,
                 "size": SIZE, "clip": CLIP}

    # --- 1. render --------------------------------------------------------------------------
    t0 = time.time()
    frames, depths, ids, da2_frames, da2_depths, da2_ids = {}, {}, {}, {}, {}, {}
    for w in WORLDS:
        ep = W.generate_episode(NAMESPACE, w, N_DISKS, steps=STEPS)
        fs, ds, iss, f2, d2, i2 = [], [], [], [], [], []
        for st in ep.steps:
            img, dep, oid = R.render(st.agent, st.positions, ep.pillars, width=SIZE, height=SIZE, return_ids=True, texture=TEXTURE)
            fs.append(R.to_uint8(img)); ds.append(dep); iss.append(oid)
            if st.t % 8 == 0:   # every 8th frame at DA2's native input size
                img2, dep2, oid2 = R.render(st.agent, st.positions, ep.pillars, width=DA2_W, height=DA2_H,
                                            return_ids=True, texture=TEXTURE)
                f2.append(R.to_uint8(img2)); d2.append(dep2); i2.append(oid2)
        frames[w], depths[w], ids[w] = np.stack(fs), np.stack(ds), np.stack(iss)
        da2_frames[w], da2_depths[w], da2_ids[w] = np.stack(f2), np.stack(d2), np.stack(i2)
    res["render_s"] = time.time() - t0
    disk_frac = {w: float(((ids[w] >= 100).sum((1, 2)) > 0).mean()) for w in WORLDS}
    res["share_frames_with_a_disk"] = disk_frac
    print("render", round(res["render_s"], 2), "s; frames with a disk", disk_frac, flush=True)

    # --- 2. DA2 -----------------------------------------------------------------------------
    import coremltools as ct
    from PIL import Image
    t0 = time.time()
    da2 = ct.models.MLModel(str(DA2_PATH), compute_units=ct.ComputeUnit.CPU_AND_NE)
    out_name = None
    rows = []
    n_da2 = 0
    t_pred = 0.0
    for w in WORLDS:
        for k in range(len(da2_frames[w])):
            t1 = time.time()
            pr = da2.predict({"image": Image.fromarray(da2_frames[w][k])})
            t_pred += time.time() - t1
            n_da2 += 1
            if out_name is None:
                out_name = sorted(pr)[0]
            pred = pr[out_name]
            if not hasattr(pred, "convert"):
                pred = Image.fromarray(np.asarray(pred, dtype=np.float32).squeeze())
            res.setdefault("da2_raw_output_size", list(pred.size))
            pred = pred.convert("F")
            if pred.size != (DA2_W, DA2_H):
                pred = pred.resize((DA2_W, DA2_H), Image.BILINEAR)
            pred = np.asarray(pred, dtype=np.float64)
            true = da2_depths[w][k]
            oid = da2_ids[w][k]
            nonsky = np.isfinite(true)
            obj = oid >= 0
            rowmap = np.broadcast_to(np.arange(DA2_H)[:, None], true.shape)
            rows.append({
                "world": w, "k": k,
                "rho_nonsky": spearman(pred[nonsky], true[nonsky]),
                "rho_objects": spearman(pred[obj], true[obj]),
                "rho_row_only_nonsky": spearman(-rowmap[nonsky].astype(float), true[nonsky]),
                "rho_row_only_objects": spearman(-rowmap[obj].astype(float), true[obj]),
                "object_share": float(obj.mean()),
            })
            if w == WORLDS[0] and k < 3:
                np.save(OUT / f"da2_w{w}_k{k}.npy", pred.astype(np.float32))
    res["da2"] = {
        "output_name": out_name, "frames": n_da2, "fps": n_da2 / t_pred, "load_and_run_s": time.time() - t0,
        "median": {key: float(np.nanmedian([r[key] for r in rows]))
                   for key in ("rho_nonsky", "rho_objects", "rho_row_only_nonsky", "rho_row_only_objects")},
        "per_frame": rows,
    }
    print("DA2", json.dumps(res["da2"]["median"]), "fps", round(res["da2"]["fps"], 1), flush=True)
    del da2
    gc.collect()

    # --- 3. V-JEPA 2.1 at 224, 16-frame clips -----------------------------------------------
    import mlx.core as mx
    import vjepa2_core_mlx.utils.weights as weights
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)[:, None, None, None]
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)[:, None, None, None]
    t0 = time.time()
    enc = weights.from_pretrained(VJEPA_DIR, img_size=(SIZE, SIZE), num_frames=CLIP)
    load_s = time.time() - t0
    g = SIZE // PATCH
    feats, times = {}, []
    for w in WORLDS:
        per = []
        for c in range(STEPS // CLIP):
            clip = frames[w][c * CLIP:(c + 1) * CLIP]                         # [T, H, W, 3] uint8
            x = (clip.transpose(3, 0, 1, 2).astype(np.float32) / 255.0 - mean) / std
            t1 = time.time()
            y = enc(mx.array(x[None]))
            mx.eval(y)
            times.append(time.time() - t1)
            per.append(np.array(y[0]).reshape(CLIP // 2, g, g, -1))              # [8, 14, 14, 1024]
        feats[w] = np.stack(per)                                              # [4, 8, 14, 14, 1024]
    res["vjepa"] = {"load_s": load_s, "first_clip_s": times[0], "median_clip_s": float(np.median(times[1:])),
                    "clips": len(times), "tokens_per_clip": int(feats[WORLDS[0]][0].size // feats[WORLDS[0]].shape[-1]),
                    "dim": int(feats[WORLDS[0]].shape[-1]),
                    "feature_std_mean": float(np.mean([feats[w].std() for w in WORLDS])),
                    "metal_peak_gb": float(mx.get_peak_memory() / 1e9) if hasattr(mx, "get_peak_memory") else None}
    print("V-JEPA", json.dumps({k: v for k, v in res["vjepa"].items()}), flush=True)
    del enc
    gc.collect()
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None   # optional: keep features to re-run probes
    if cache is not None:
        np.savez(cache, **{f"w{w}": feats[w].astype(np.float16) for w in WORLDS})

    # --- 4. linear probes per patch: teacher features vs raw pixels ------------------------
    def patch_targets(w):
        d, o = depths[w], ids[w]                                              # [STEPS, H, W]
        d = d.reshape(STEPS // 2, 2, g, PATCH, g, PATCH)
        o = o.reshape(STEPS // 2, 2, g, PATCH, g, PATCH)
        inv = np.where(np.isfinite(d), 1.0 / np.maximum(d, 1e-3), 0.0)       # inverse depth, sky = 0
        inv_mean = inv.mean((1, 3, 5))                                        # [32, g, g]
        disk = (o >= 100).mean((1, 3, 5))
        return np.stack([inv_mean, disk], -1).reshape(-1, 2)

    def patch_pixels(w):
        f = frames[w].astype(np.float32) / 255.0                              # [STEPS, H, W, 3]
        f = f.reshape(STEPS // 2, 2, g, PATCH, g, PATCH, 3).mean(1)          # tubelet mean
        f = f[:, :, ::4, :, ::4, :]                                          # 4x4 subsample per patch -> 48 dims
        f = f.transpose(0, 1, 3, 2, 4, 5).reshape(STEPS // 2, g, g, -1)
        rowcol = np.stack(np.meshgrid(np.arange(g), np.arange(g), indexing="ij"), -1) / g
        rc = np.broadcast_to(rowcol, (STEPS // 2, g, g, 2))
        return np.concatenate([f, rc], -1).reshape(-1, f.shape[-1] + 2)

    def patch_feats(w):
        return feats[w].reshape(-1, feats[w].shape[-1])                       # clip, t, gh, gw -> rows

    tr, te = WORLDS[:3], WORLDS[3:]
    ytr = np.concatenate([patch_targets(w) for w in tr]); yte = np.concatenate([patch_targets(w) for w in te])
    probes = {}
    for name, fn, lam in (("vjepa", patch_feats, 1e3), ("pixels+rowcol", patch_pixels, 1.0)):
        xtr = np.concatenate([fn(w) for w in tr]); xte = np.concatenate([fn(w) for w in te])
        r2 = ridge_fit_eval(xtr, ytr, xte, yte, lam)
        probes[name] = {"r2_inverse_depth": r2[0], "r2_disk_share": r2[1], "dims": int(xtr.shape[1]),
                        "train_rows": int(len(xtr)), "test_rows": int(len(xte)), "lambda": lam}
    res["probes"] = probes
    print("probes", json.dumps(probes), flush=True)

    res["peak_rss_gb"] = peak_rss_gb()
    (OUT / "result.json").write_text(json.dumps(res, indent=1))
    print("wrote", OUT / "result.json", "peak rss GB", round(res["peak_rss_gb"], 2))


if __name__ == "__main__":
    main()
