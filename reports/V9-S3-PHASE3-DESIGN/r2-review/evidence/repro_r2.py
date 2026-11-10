"""用 240b1ac 的代码在探索命名空间上跑 K1–K6 和全部描述量，K2、K2b 在独立子进程里跑；与 r1 复现逐项比对。复核者自写。

用法：repro_r2.py <副本根> <命名空间> <世界数> <输出目录> <r1 repro json 或 -> <stage>
命名空间只用 s3p3x-explore 或 s3p3x-rv1109。不写 artifacts/。
"""
import json, subprocess, sys, time
from pathlib import Path
import numpy as np

COPY, NS, NW, OUT, R1, STAGE = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4]), sys.argv[5], sys.argv[6]
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
ev = A.to_arrays(cols)
offa = {k: A.to_arrays(v) for k, v in off.items()}
t_an = time.monotonic() - T0
worlds = OUT / f"worlds_{NS}.jsonl"
with worlds.open("w", encoding="utf-8") as fh:
    for lg in logs:
        fh.write(json.dumps(lg, ensure_ascii=False, sort_keys=True) + "\n")
np.savez_compressed(OUT / f"events_{NS}.npz", **ev)


def sub(script, *args):
    t = time.monotonic()
    r = subprocess.run([sys.executable, "-I", COPY + "/reports/V9-S3-PHASE3/" + script, *map(str, args)], capture_output=True, text=True)
    out = json.loads(r.stdout) if r.returncode == 0 else {"passed": False, "error": r.stderr[-1500:]}
    out["_seconds"] = round(time.monotonic() - t, 1)
    return out


k2 = sub("verify_worlds.py", worlds)
k2b = sub("verify_generation.py", worlds, NS, PS.N_EPISODES)
res = A.evaluate(ev, logs, stage=STAGE, n_worlds=NW, external=k2, external_gen=k2b, offsets=offa)
res["timing"] = {"analysis_s": round(t_an, 1), "k2_s": k2["_seconds"], "k2b_s": k2b["_seconds"]}
# 偏移档：事件本身（世界、回合、步、种类、答案、标签）应与主运行相同，只有预测不同
ident = ("kind", "world", "episode", "t", "answer", "decoy", "relocated")
res["reviewer_offsets_same_events"] = {k: all(np.array_equal(v[c], ev[c]) for c in ident) for k, v in offa.items()}
res["reviewer_offsets_preds_differ_from_main"] = {k: bool((v["pred_G"] != ev["pred_G"]).any()) for k, v in offa.items()}
if R1 != "-":
    r1 = json.load(open(R1))
    same, diff, new = [], [], []
    for name, v in res["descriptive"].items():
        if name not in r1["descriptive"]:
            new.append(name); continue
        a, b = v, r1["descriptive"][name]
        (same if all(a[k] == b[k] for k in ("delta", "ci_low", "ci_high", "bonf_low", "bonf_high", "n_events")) else diff).append(name)
    for k, v in res["offsets"].items():
        for name, x in v.items():
            y = r1["offsets"][k][name]
            (same if all(x[q] == y[q] for q in ("delta", "ci_low", "ci_high", "n_events")) else diff).append(f"offset{k}/{name}")
    res["vs_r1_repro"] = {"same": len(same), "differ": diff, "new": new,
                          "accuracy_same": res["diagnostics"]["accuracy"] == r1["diagnostics"]["accuracy"],
                          "D8_same": res["diagnostics"]["D8_items"] == r1["diagnostics"]["D8_items"]}
json.dump(res, open(OUT / f"repro_{NS}.json", "w"), ensure_ascii=False, indent=1, default=float)
print(json.dumps({"ns": NS, "valid": res["valid"], "gates": {k: v.get("passed") for k, v in res["legality"].items() if isinstance(v, dict)},
                  "k2": {k: k2.get(k) for k in ("worlds", "queries", "versions", "n_problems")},
                  "k2b": {k: k2b.get(k) for k in ("worlds", "queries", "fast_events", "observations", "n_problems", "forbidden_loaded")},
                  "timing": res["timing"], "offsets_same_events": res["reviewer_offsets_same_events"],
                  "vs_r1": res.get("vs_r1_repro"), "D7_LT_L_reloc": res["descriptive"]["D7_LT_minus_L_relocated"]["delta"]}, ensure_ascii=False, default=float))
