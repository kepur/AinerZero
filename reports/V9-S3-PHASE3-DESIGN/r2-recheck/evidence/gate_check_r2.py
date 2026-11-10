"""在一个（可能变异过的）副本上，用 s3p3x-explore 前 N 个世界跑主分析与契约门 K1–K4、K6，以及 K2、K2b 子进程（K5 需整 100 个世界，不跑）。复核者自写。
用法：gate_check_r2.py <副本根> <世界数>
"""
import json, subprocess, sys, tempfile
from pathlib import Path
COPY, NW = Path(sys.argv[1]), int(sys.argv[2])
sys.path.insert(0, str(COPY / "src"))
from ainerzero.v9.experiments.s3 import analysis_p3 as A, persist as PS  # noqa: E402
cols = {k: [] for k in A.FIELDS}
logs = []
for w in range(NW):
    seq = PS.generate_sequence("s3p3x-explore", w)
    c, lg = A.analyse_world(seq)
    for f in cols:
        cols[f] += c[f]
    lg["world_seed"], lg["layout_sha256"] = seq.world_seed, seq.layout_sha256
    logs.append(lg)
ev = A.to_arrays(cols)
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "worlds.jsonl"
    p.write_text("".join(json.dumps(lg, ensure_ascii=False, sort_keys=True) + "\n" for lg in logs), encoding="utf-8")
    def sub(script, *args):
        r = subprocess.run([sys.executable, "-I", str(COPY / "reports/V9-S3-PHASE3" / script), *map(str, args)], capture_output=True, text=True)
        return json.loads(r.stdout) if r.returncode == 0 else {"passed": False}
    k2 = sub("verify_worlds.py", p)
    k2b = sub("verify_generation.py", p, "s3p3x-explore", PS.N_EPISODES)
res = A.evaluate(ev, logs, stage=None, n_worlds=NW, external=k2, external_gen=k2b, offsets=None)
d = res["descriptive"]
print(json.dumps({"valid": res["valid"], "gates": {k: v["passed"] for k, v in res["legality"].items() if isinstance(v, dict)},
                  "D4_G_minus_GNR": round(d["D4_G_minus_GNR"]["delta"], 4), "D7_GT_minus_G_relocated": round(d["D7_GT_minus_G_relocated"]["delta"], 4),
                  "D3_G_minus_L": round(d["D3_G_minus_L"]["delta"], 4)}))
