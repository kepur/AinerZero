"""应修 1 的复查：suffix_changed 是否仅因检测数变少就成立。桩跟踪器按世界缓存第一次（未变异）的检测，
之后只读传入列表的长度、从不读传入的位置。另试「只平移不删」和「大平移」两种变异下诚实跟踪器的 suffix_changed。"""
import ast, json, sys, types
import numpy as np
COPY, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, COPY + "/src")
from ainerzero.v9.experiments.s4 import analysis as A, filter as F, models as Mo, world as W
assert A.__file__.startswith(COPY) and "mlx" not in sys.modules
tree = ast.parse(open(COPY + "/reports/V9-S4-PHASE1/run_s4p1.py").read())
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "student_check")
ns = {"W": W, "A": A, "F": F, "Mo": Mo, "np": np, "STUDENT_WORLDS": 2, "STUDENT_CUT": 150, "L": types.SimpleNamespace(as_process_model=lambda net: Mo.true_physics)}
exec(compile(ast.Module([fn], []), "sc", "exec"), ns)
eps = [W.generate_episode("s4x-explore", w, 6) for w in (0, 1)]
real = F.track; cache = {}
def length_only(dets, pillars, model, rng, cfg=F.FilterConfig(), **kw):
    key = tuple(map(tuple, pillars)); cache.setdefault(key, [d.copy() for d in dets])
    ids, n = real(cache[key], pillars, model, rng, cfg, **kw)
    return [i[: len(d)] for i, d in zip(ids, dets)], n
F.track = length_only
out = ns["student_check"](eps, {"L-int#1": None})
F.track = real
R = {"length_only_tracker_passed": out["passed"], "rows": [{k: r[k] for k in ("world", "model", "prefix_equal", "consumed", "suffix_changed")} for r in out["rows"]]}
# 诚实跟踪器在其他变异下 suffix 是否变化（建议的修法用）
for name, mutf in (("shift_0.5_only", lambda d: d + 0.5), ("shift_3.0_only", lambda d: d + 3.0), ("reverse_order", lambda d: d[::-1].copy())):
    rows = []
    for ep in eps:
        dets = A.student_detections(ep); mut = [d if t <= 150 else mutf(d) for t, d in enumerate(dets)]
        a, _ = real(dets, ep.pillars, Mo.true_physics, np.random.default_rng(7)); b, _ = real(mut, ep.pillars, Mo.true_physics, np.random.default_rng(7))
        rows.append(any(not np.array_equal(x, y) for x, y in zip(a[151:], b[151:])))
    R[f"honest_suffix_changed_{name}"] = rows
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1); print(json.dumps(R, ensure_ascii=False))
