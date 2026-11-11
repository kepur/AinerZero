"""S5 摸底第 C 轮（未登记，纯 CPU）：自渲染画面上 RLT（式 10，T8 参考实现）的 token 保留率随 τ 怎么变。

块 16×16、按帧比较（管长 1）与按管长 2 比较各量一次。像素取 uint8 / 255，τ 是无穷范数阈值。
同时给出天空、地面这两类「静止背景块」在全部块里的占比，作为保留率的下界参照。
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
from ainerzero.v9.tokenization.rlt import rlt_frame_dropping  # noqa: E402

P, S, CLIP = 16, 224, 16
TEX = "--flat" not in sys.argv
TAUS = (0.0, 0.02, 0.05, 0.1, 0.2)
g = S // P
rows = {f"tau={t}": [] for t in TAUS}
rows_tub = {f"tau={t}": [] for t in TAUS}
bg_share = []
for w in range(4):
    ep = W.generate_episode("s5x-explore", w, 6, steps=64)
    fr, ids = [], []
    for st in ep.steps:
        img, _, oid = R.render(st.agent, st.positions, ep.pillars, return_ids=True, texture=TEX)
        fr.append(R.to_uint8(img).astype(np.float32) / 255.0); ids.append(oid)
    fr, ids = np.stack(fr), np.stack(ids)
    bg = (ids < 0).reshape(64, g, P, g, P).all((2, 4))                      # patch entirely sky or floor
    bg_share.append(float(bg.mean()))
    for c in range(64 // CLIP):
        clip = fr[c * CLIP:(c + 1) * CLIP]
        patches = clip.reshape(CLIP, g, P, g, P, 3).transpose(0, 1, 3, 2, 4, 5).reshape(CLIP, g, g, -1)
        tub = clip.reshape(CLIP // 2, 2, g, P, g, P, 3).transpose(0, 2, 4, 1, 3, 5, 6).reshape(CLIP // 2, g, g, -1)
        for t in TAUS:
            rows[f"tau={t}"].append(rlt_frame_dropping(patches, t)[4])
            rows_tub[f"tau={t}"].append(rlt_frame_dropping(tub, t)[4])
out = {"texture": TEX, "background_patch_share": float(np.mean(bg_share)),
       "keep_rate_per_frame_patches": {k: float(np.mean(v)) for k, v in rows.items()},
       "keep_rate_tubelet2_patches": {k: float(np.mean(v)) for k, v in rows_tub.items()}}
(HERE / "round-c").mkdir(exist_ok=True)
(HERE / "round-c" / ("result.json" if TEX else "result-flat.json")).write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
