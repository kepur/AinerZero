"""建议修法的检验：suffix_changed 改为按对齐前缀比较 any(not array_equal(a[t][:len(b[t])], b[t]))。
诚实跟踪器（E-P）应为真；只读长度、不读位置的桩应为假；「从不关联、编号只是新建计数」的跟踪器（模拟 3 步训练的模型）应为真。"""
import json, sys
import numpy as np
COPY, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, COPY + "/src")
from ainerzero.v9.experiments.s4 import analysis as A, filter as F, models as Mo, world as W
assert A.__file__.startswith(COPY) and "mlx" not in sys.modules
CUT = 150
eps = [W.generate_episode("s4x-explore", w, 6) for w in (0, 1)]
def counter_tracker(dets, *a, **k):
    out, c = [], 0
    for d in dets:
        out.append(np.arange(c, c + len(d))); c += len(d)
    return out, c
real = F.track; cache = {}
def length_only(dets, pillars, model, rng, cfg=F.FilterConfig()):
    key = tuple(map(tuple, pillars)); cache.setdefault(key, [d.copy() for d in dets])
    ids, n = real(cache[key], pillars, model, rng, cfg)
    return [i[: len(d)] for i, d in zip(ids, dets)], n
R = {}
for name, tr in (("honest_E-P", lambda d, p: real(d, p, Mo.true_physics, np.random.default_rng(7))),
                 ("new_track_counter", lambda d, p: counter_tracker(d)),
                 ("length_only", lambda d, p: length_only(d, p, Mo.true_physics, np.random.default_rng(7)))):
    cache.clear(); rows = []
    for ep in eps:
        dets = A.student_detections(ep); mut = [d if t <= CUT else d[:-1] + 0.5 for t, d in enumerate(dets)]
        a, _ = tr(dets, ep.pillars); b, _ = tr(mut, ep.pillars)
        rows.append({"current_rule": any(not np.array_equal(x, y) for x, y in zip(a[CUT + 1:], b[CUT + 1:])),
                     "aligned_rule": any(not np.array_equal(x[: len(y)], y) for x, y in zip(a[CUT + 1:], b[CUT + 1:]))})
    R[name] = rows
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1); print(json.dumps(R))
