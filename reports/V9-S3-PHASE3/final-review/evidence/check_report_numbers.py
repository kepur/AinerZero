"""从 final.json 取出 FINAL-REPORT 引用的每个数字（复核者自写），另核对 Bonferroni 方向、探针与 final 的判断。"""
import json, sys
from pathlib import Path
REPO = Path(sys.argv[1]); F = json.load(open(REPO / "reports/V9-S3-PHASE3/final.json")); R = F["result"]
PR = json.load(open(REPO / "reports/V9-S3-PHASE3/probe-p1.json"))["result"]
d, o, g, L = R["descriptive"], R["offsets"], R["diagnostics"], R["legality"]
f3 = lambda x: f"{x:+.3f}"
ci = lambda k: f'{f3(d[k]["delta"])} ({f3(d[k]["ci_low"])}, {f3(d[k]["ci_high"])}) n={d[k]["n_events"]} w={d[k]["n_worlds"]}'
out = {}
out["run"] = {"elapsed": F["elapsed_s"], "peak_GB": F["peak_rss_bytes"] / 1e9, "K3_checkpoints": L["K3_restore_replay"]["checkpoints_replayed"]}
for k in d: out[k] = ci(k)
out["acc_stable"] = {p: round(g["accuracy"]["decoy_stable"][p], 3) for p in ("L", "MODE", "G", "GNR")}
out["U0_won_by_past"] = round(g["D2_U0_won_by_past"], 4)
out["recovery"] = {e: {p: round(v[p], 3) for p in ("C", "G", "L")} for e, v in g["D4_recovery"]["by_episode"].items()}
out["first_G_beats_C"] = g["D4_recovery"]["first_episode_G_beats_C"]
out["SR_fast_rate_queries"] = round(g["D5_SR_fast_rate_queries"], 4)
out["offsets"] = {k: {n: f'{f3(v["delta"])} ({f3(v["ci_low"])}, {f3(v["ci_high"])})' for n, v in o[k].items()} for k in o}
it = g["D8_items"]
out["D8"] = it | {"off_frac": round(it["slow_off_persistent"] / it["slow"], 3), "write_tie_rate": round(it["write_ties"] / it["writes_matched"], 4),
                 "vote_tie_rate": round(it["vote_ties"] / it["votes"], 4), "slow_hit_on_cell": round(g["D8_slow_hit_on_cell"], 4)}
allc = {**d, **{f"k{k}/{n}": v for k, vv in o.items() for n, v in vv.items()}}
side = lambda lo, hi: "pos" if lo > 0 else ("neg" if hi < 0 else "zero")
out["bonferroni_changes_95_decision"] = [n for n, v in allc.items() if side(v["ci_low"], v["ci_high"]) != side(v["bonf_low"], v["bonf_high"])]
pd = PR["descriptive"]
out["probe_vs_final_sign"] = [n for n in d if side(pd[n]["ci_low"], pd[n]["ci_high"]) != side(d[n]["ci_low"], d[n]["ci_high"])]
out["probe_vs_final_delta"] = {n: [round(pd[n]["delta"], 3), round(d[n]["delta"], 3)] for n in d}
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
for k, v in out.items():
    if k != "probe_vs_final_delta": print(k, v)
