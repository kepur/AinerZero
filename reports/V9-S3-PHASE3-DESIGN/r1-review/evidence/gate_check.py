"""在一个（可能变异过的）副本上，用 s3p3x-explore 前 N 个世界跑主分析和契约门 K1–K4（K5 需要整 100 个世界，不跑）。
K2 用副本自己的 verify_worlds.py 在子进程里跑。另报复核者的「events 与日志一致」检查和几个描述量。复核者自写。

用法：gate_check.py <副本根> <世界数>
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
    logs.append(lg)
ev = A.to_arrays(cols)
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "worlds.jsonl"
    p.write_text("".join(json.dumps(lg, ensure_ascii=False, sort_keys=True) + "\n" for lg in logs), encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", str(COPY / "reports/V9-S3-PHASE3/verify_worlds.py"), str(p)], capture_output=True, text=True)
    external = json.loads(r.stdout) if r.returncode == 0 else {"passed": False}
res = A.evaluate(ev, logs, stage=None, n_worlds=NW, external=external, offsets=None)
s = A.event_sets(ev)
qlog = sorted((lg["world"], q["episode"], q["t"], q["pred_G"], q["pred_L"]) for lg in logs for q in lg["queries"])
qev = sorted(zip(ev["world"][s["query"]].tolist(), ev["episode"][s["query"]].tolist(), ev["t"][s["query"]].tolist(),
                 ev["pred_G"][s["query"]].tolist(), ev["pred_L"][s["query"]].tolist()))
d = res["descriptive"]
print(json.dumps({"valid": res["valid"], "gates": {k: v["passed"] for k, v in res["legality"].items() if isinstance(v, dict)},
                  "events_match_log": qlog == qev,
                  "D3_G_minus_L": round(d["D3_G_minus_L"]["delta"], 4), "D4_G_minus_GNR": round(d["D4_G_minus_GNR"]["delta"], 4),
                  "D7_GT_minus_G_relocated": round(d["D7_GT_minus_G_relocated"]["delta"], 4)}))
