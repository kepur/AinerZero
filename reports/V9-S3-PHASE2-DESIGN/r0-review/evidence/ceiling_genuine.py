"""§1「上限」的成色：可见答案里有多少是真的看到了目标格（只用 s3p1-probe 的 explore- 回合，纯数据，无模型）。"""
import json, os, sys
from pathlib import Path
import numpy as np
import ainerzero
assert Path(ainerzero.__file__).resolve().is_relative_to(Path(os.environ["REVIEW_ROOT"]).resolve())
from ainerzero.v9.experiments.s3 import batching as B, data as D, spec
LONG = B.BUCKET_CODE[spec.BUCKET_LONG]; NS = spec.NAMESPACE_PROBE
vis = lambda o: o[:spec.VIEW_FEAT_DIM].reshape(9, spec.CELL_FEAT_DIM)[:, spec.NUM_TERRAIN_CLASSES:].argmax(1)
rows = []
for w in range(200):
    for e in range(2):
        ep = D.generate_episode(D.derive_seed(NS, "explore-world", w), D.derive_seed(NS, "explore-ep", w, e), family="F1")
        p = B.prepare_episode(ep, 1.0, perm_seed=40_000_000 + w * 100 + e)
        evs = {v["t"]: v for v in ep["events"]}
        near = lambda t, c: abs(int(ep["steps"][t]["truth"]["x"]) - c[0]) <= 1 and abs(int(ep["steps"][t]["truth"]["y"]) - c[1]) <= 1
        for i in range(len(p.query_t)):
            if not (p.bucket[i] == LONG and p.swapped[i]): continue
            a, c = int(p.answer[i]), evs[int(p.query_t[i])]["cell"]
            cs = [int(x) for x, m in zip(p.candidates[i], p.cand_mask[i]) if m]; top = int(p.top1[i])
            rows.append((a in vis(p.obs[top]), (a in vis(p.obs[top])) and near(top, c), any(a in vis(p.obs[x]) for x in cs), any((a in vis(p.obs[x])) and near(x, c) for x in cs)))
A = np.array(rows, dtype=float).mean(0); n = len(rows)
print(json.dumps({"n": n, "top1_any": round(A[0], 4), "top1_any_genuine_near_cell": round(A[1], 4), "pool_any": round(A[2], 4), "pool_any_genuine_near_cell": round(A[3], 4), "top1_any_plus_guess_1_of_7": round(A[0] + (1 - A[0]) / 7, 4)}))
