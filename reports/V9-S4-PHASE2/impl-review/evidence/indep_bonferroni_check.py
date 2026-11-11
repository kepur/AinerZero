"""P214 独立核对：gate_stats 里每个门统计量传给 bootstrap 的 m 与种子；并在合成记录上核对 Bonferroni 区间
就是 bootstrap 分布的 (0.025/11, 1-0.025/11) 分位、负对照用 95%（m=1）。纯 CPU。
用法：PYTHONPATH=<src>:<tests/v9/experiments> python indep_bonferroni_check.py"""
import numpy as np

from ainerzero.v9.experiments.s4 import analysis_p2 as P2
from ainerzero.v9.experiments.s4 import metrics as Me
import test_s4_analysis_p2 as T          # 只借用合成记录生成器 records()

calls = []
orig = Me.bootstrap


def recorder(stat, sums, **kw):
    calls.append((stat.__name__, sorted(sums), kw.get("seed"), kw.get("m")))
    return orig(stat, sums, **kw)


P2.Me.bootstrap = recorder
main, extrap = T.records(), T.records(100, "extrap", seed=1, coll_share=0.38)
st = P2.gate_stats(main, extrap)
P2.Me.bootstrap = orig
for key, c in zip(st, calls):
    print(f"{key:18s} stat={c[0]:9s} seed={c[2]} m={c[3]}")
ok_m = all(c[3] == 11 for c in calls[:11]) and all(c[3] == 1 for c in calls[11:]) and len(calls) == 13
ok_seed = all(c[2] == 20261111 for c in calls)
# Bonferroni 分位的直接重算（GC）
sums = {"x": P2.event_sums(main, "L-int-g", "collision"), "b": P2.event_sums(main, "E-B", "collision"), "p": P2.event_sums(main, "E-P", "collision")}
rng = np.random.default_rng(20261111)
draws = rng.integers(0, len(main), size=(10_000, len(main)))
tot = {k: v[draws].sum(-1) for k, v in sums.items()}
boot = (tot["x"] - tot["b"]) / (tot["p"] - tot["b"])
lo11, hi11 = np.quantile(boot, [0.025 / 11, 1 - 0.025 / 11])
lo1, hi1 = np.quantile(boot, [0.025, 0.975])
gc = st["GC"]
print("GC bonf", gc["bonf_low"], gc["bonf_high"], "recomputed", lo11, hi11)
print("GC 95% ", gc["ci_low"], gc["ci_high"], "recomputed", lo1, hi1)
ok_q = np.isclose(gc["bonf_low"], lo11) and np.isclose(gc["bonf_high"], hi11) and np.isclose(gc["ci_low"], lo1) and np.isclose(gc["ci_high"], hi1)
print("m per statistic ok:", ok_m, "| seed ok:", ok_seed, "| GC quantiles ok:", bool(ok_q))
print("PASSED" if ok_m and ok_seed and ok_q else "FAILED")
