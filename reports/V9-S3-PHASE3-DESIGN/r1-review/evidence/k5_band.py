"""K5 带宽：用两个探索命名空间的 200 个世界做世界级重采样，估计 final（200 世界）事件数的波动、误判失败的概率与能抓到的丢失比例。"""
import json, sys
import numpy as np
sys.path.insert(0, sys.argv[1] + "/src")
from ainerzero.v9.experiments.s3 import analysis_p3 as A
per = []
for f in sys.argv[2:4]:
    ev = dict(np.load(f))
    s = A.event_sets(ev)
    for w in np.unique(ev["world"]):
        m = ev["world"] == w
        per.append([int((s[k] & m).sum()) for k in A.EXPECTED_PER_100])
per = np.array(per, dtype=float)
rng = np.random.default_rng(20261110)
tot = per[rng.integers(0, len(per), size=(20000, 200))].sum(1)
exp = np.array([A.EXPECTED_PER_100[k] * 2 for k in A.EXPECTED_PER_100])
lo, hi = exp * A.SAMPLE_BAND[0], exp * A.SAMPLE_BAND[1]
out = {"keys": list(A.EXPECTED_PER_100), "expected_200": exp.tolist(), "sd_200": tot.std(0).round(1).tolist(), "cv_200": (tot.std(0) / tot.mean(0)).round(4).tolist(),
       "p_false_fail_any": float(((tot < lo) | (tot > hi)).any(1).mean())}
for loss in (0.05, 0.10, 0.15, 0.20, 0.25):
    out[f"p_detect_loss_{loss}"] = [float(((t * (1 - loss)) < l).mean()) for t, l in zip(tot.T, lo)]
print(json.dumps(out, ensure_ascii=False)); json.dump(out, open(sys.argv[4], "w"), ensure_ascii=False, indent=1)
