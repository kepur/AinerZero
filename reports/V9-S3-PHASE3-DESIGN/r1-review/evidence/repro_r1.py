"""用 6e274fa 的 analysis_p3 在探索命名空间上重算描述量与契约门，并与 r0 复核的数字比对。复核者自写。

用法：repro_r1.py <副本根> <命名空间> <世界数> <输出目录> <r0 adv json 或 -> <stage>
命名空间只用 s3p3x-explore 或 s3p3x-rv1109。不写 artifacts/。
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

COPY, NS, NW, OUT, R0, STAGE = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4]), sys.argv[5], sys.argv[6]
assert NS in ("s3p3x-explore", "s3p3x-rv1109"), NS
sys.path.insert(0, COPY + "/src")
from ainerzero.v9.experiments.s3 import analysis_p3 as A, persist as PS  # noqa: E402

OUT.mkdir(parents=True, exist_ok=True)
T0 = time.monotonic()
cols = {k: [] for k in A.FIELDS}
off = {k: {f: [] for f in A.FIELDS} for k in A.OFFSETS}
logs = []
for w in range(NW):
    seq = PS.generate_sequence(NS, w)
    c, lg = A.analyse_world(seq)
    for f in cols:
        cols[f] += c[f]
    lg["world_seed"], lg["layout_sha256"] = seq.world_seed, seq.layout_sha256
    logs.append(lg)
    for k in A.OFFSETS:
        ck, _ = A.analyse_world(seq, offset=k, full=False)
        for f in off[k]:
            off[k][f] += ck[f]
    if (w + 1) % 25 == 0:
        print(f"[{time.monotonic() - T0:6.1f}s] world {w + 1}", flush=True)
ev = A.to_arrays(cols)
offa = {k: A.to_arrays(v) for k, v in off.items()}
worlds = OUT / f"worlds_{NS}.jsonl"
with worlds.open("w", encoding="utf-8") as fh:
    for lg in logs:
        fh.write(json.dumps(lg, ensure_ascii=False, sort_keys=True) + "\n")
np.savez_compressed(OUT / f"events_{NS}.npz", **ev)
r = subprocess.run([sys.executable, "-I", COPY + "/reports/V9-S3-PHASE3/verify_worlds.py", str(worlds)], capture_output=True, text=True)
external = json.loads(r.stdout) if r.returncode == 0 else {"passed": False, "error": r.stderr[-1500:]}
res = A.evaluate(ev, logs, stage=STAGE, n_worlds=NW, external=external, offsets=offa)
res["seconds"] = round(time.monotonic() - T0, 1)

# ---- 复核者的额外核对 ----
s = A.event_sets(ev)
extra = {}
extra["fast_pred_G_equals_pred_C"] = float((ev["pred_G"][s["fast"]] == ev["pred_C"][s["fast"]]).mean())
# events 与 worlds.jsonl 的查询预测是否逐条一致
qlog = [(lg["world"], q["episode"], q["t"], q["pred_G"], q["pred_L"]) for lg in logs for q in lg["queries"]]
qev = list(zip(ev["world"][s["query"]].tolist(), ev["episode"][s["query"]].tolist(), ev["t"][s["query"]].tolist(),
               ev["pred_G"][s["query"]].tolist(), ev["pred_L"][s["query"]].tolist()))
extra["events_vs_log_queries_identical"] = sorted(qlog) == sorted(qev)
extra["n_queries"] = len(qlog)
res["reviewer_extra"] = extra

# ---- 与 r0 复核数字比对 ----
if R0 != "-":
    r0 = json.load(open(R0))
    acc = res["diagnostics"]["accuracy"]
    pa = r0["persistent_acc"]
    pairs = [
        ("stable_decoy L", acc["decoy_stable"]["L"], pa["stable_decoy"]["L"][0]),
        ("stable_decoy G", acc["decoy_stable"]["G"], pa["stable_decoy"]["G"][0]),
        ("stable_decoy GNR", acc["decoy_stable"]["GNR"], pa["stable_decoy"]["GNR"][0]),
        ("stable_decoy MODE", acc["decoy_stable"]["MODE"], pa["stable_decoy"]["MODE"][0]),
        ("stable_decoy GT", acc["decoy_stable"]["GT"], pa["stable_decoy"]["GT"][0]),
        ("stable_decoy LT", acc["decoy_stable"]["LT"], pa["stable_decoy"]["LT"][0]),
        ("relocated C", acc["relocated"]["C"], pa["relocated"]["C"][0]),
        ("relocated L", acc["relocated"]["L"], pa["relocated"]["L"][0]),
        ("relocated G", acc["relocated"]["G"], pa["relocated"]["G"][0]),
        ("relocated GNR", acc["relocated"]["GNR"], pa["relocated"]["GNR"][0]),
        ("relocated MODE", acc["relocated"]["MODE"], pa["relocated"]["MODE"][0]),
        ("clean G", acc["clean"]["G"], pa["clean"]["G"][0]),
        ("all queries G", acc["query"]["G"], pa["all"]["G"][0]),
        ("all queries C", acc["query"]["C"], pa["all"]["C"][0]),
        ("fast e>=1 C", acc["fast_e1"]["C"], r0["within_episode_e_ge_1"]["C"][0]),
        ("fast e>=1 U0", acc["fast_e1"]["U0"], r0["within_episode_e_ge_1"]["U0"][0]),
        ("fast e>=1 U05", acc["fast_e1"]["U05"], r0["within_episode_e_ge_1"]["U_rec0.5"][0]),
        ("fast e>=1 U1", acc["fast_e1"]["U1"], r0["within_episode_e_ge_1"]["U_rec1.0"][0]),
        ("fast e>=1 U2", acc["fast_e1"]["U2"], r0["within_episode_e_ge_1"]["U_rec2.0"][0]),
        ("count fast", int(s["fast"].sum()), r0["counts"]["within_episode"]),
        ("count stable decoy", int(s["decoy_stable"].sum()), r0["counts"]["stable_decoy"]),
        ("count relocated", int(s["relocated"].sum()), r0["counts"]["relocated"]),
        ("D8 items", res["diagnostics"]["D8_items"]["items"], r0["r2_ambiguity"]["items"]),
        ("D8 mixed items", res["diagnostics"]["D8_items"]["mixed_items"], r0["r2_ambiguity"]["items_multi_cell"]),
        ("D8 slow", res["diagnostics"]["D8_items"]["slow"], r0["r2_ambiguity"]["slow_final"]),
        ("D8 slow off persistent", res["diagnostics"]["D8_items"]["slow_off_persistent"], r0["r2_ambiguity"]["slow_final"] - r0["r2_ambiguity"]["slow_final_on_pcell"]),
        ("D8 votes", res["diagnostics"]["D8_items"]["votes"], r0["r2_ambiguity"]["item_episode_votes"]),
        ("D8 vote ties", res["diagnostics"]["D8_items"]["vote_ties"], r0["r2_ambiguity"]["item_episode_vote_tie"]),
        ("D8 slow hit rate", res["diagnostics"]["D8_slow_hit_rate"], r0["slow_answered_frac"][0]),
        ("D2 U0 won by past (e>=1 here; all in r0)", res["diagnostics"]["D2_U0_won_by_past"], r0["within_episode"]["U0_won_by_past"][0]),
    ]
    for e, row in r0["relocated_by_episode"].items():
        mine = res["diagnostics"]["D4_recovery"]["by_episode"].get(str(e), {})
        for p in ("C", "L", "G", "GNR", "MODE"):
            pairs.append((f"recovery e{e} {p}", mine.get(p), row[p][0]))
    res["vs_r0"] = [{"what": n, "r1_code": (round(a, 4) if isinstance(a, float) else a), "r0_review": b,
                     "same": (abs(a - b) < 6e-5 if isinstance(a, float) and isinstance(b, float) else a == b)} for n, a, b in pairs]
json.dump(res, open(OUT / f"repro_{NS}.json", "w"), ensure_ascii=False, indent=1, default=float)
print(json.dumps({"seconds": res["seconds"], "valid": res["valid"], "legality": {k: v.get("passed") for k, v in res["legality"].items() if isinstance(v, dict)},
                  "external": {k: external.get(k) for k in ("worlds", "queries", "versions", "n_problems", "passed")}, "extra": extra}, ensure_ascii=False), flush=True)
if R0 != "-":
    for row in res["vs_r0"]:
        print(("  " if row["same"] else "≠ ") + f'{row["what"]}: r1 {row["r1_code"]}  r0 {row["r0_review"]}')
