"""第 6 项补测：kill_eval.py 第一次改摘要时改到了 records[0] 的第一个键，它不是学习格（重放只核对学习格的基础变体），所以那次「通过」不算数。
这里在 smoke 运行目录上改学习格 L-int#1@base 的摘要，另改一个手工格的摘要作对照。用法：replay_tamper.py <副本根> <输出 json>（共享锁下）"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
COPY, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(COPY / "src")); sys.path.insert(0, str(COPY / "tests/v9/experiments"))
import test_s4p1_runner_native as T
assert T.REPO == COPY
res = {}
with tempfile.TemporaryDirectory(prefix="s4impl-rt-") as tmp:
    tmp = Path(tmp); b = T._make_root(tmp / "b")
    r = T._run(b, *T.SMOKE, timeout=1500); res["smoke_rc"] = r.returncode
    run = b / T.ARTS / "smoke-s1"; env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    def verify(worlds):
        q = subprocess.run([sys.executable, "-I", str(b / T.VERIFY[1]), str(run / "replay.json"), str(worlds), str(run)], cwd=b, env=env, capture_output=True, text=True, timeout=600)
        return json.loads(q.stdout) if q.returncode == 0 else {"rc": q.returncode, "stderr": q.stderr[-300:]}
    recs = [json.loads(x) for x in (run / "worlds.jsonl").read_text().splitlines()]
    rep = json.loads((run / "replay.json").read_text())
    i0 = next(i for i, r in enumerate(recs) if (r["kind"], r["world"]) == (rep["worlds"][0]["kind"], rep["worlds"][0]["world"]))
    res["keys_of_replayed_record"] = sorted(recs[i0]["ids_sha256"])[:6] + ["..."]
    for label, key in (("learned_L-int#1@base", "L-int#1@base"), ("hand_E-B#1@base", "E-B#1@base")):
        t = [dict(r) for r in recs]
        assert key in t[i0]["ids_sha256"], (key, list(t[i0]["ids_sha256"])[:5])
        t[i0] = dict(t[i0], ids_sha256=dict(t[i0]["ids_sha256"], **{key: "0" * 64}))
        p = tmp / f"w_{label}.jsonl"; p.write_text("".join(json.dumps(x) + "\n" for x in t))
        res[f"tampered_{label}"] = verify(p)
    res["honest"] = verify(run / "worlds.jsonl")
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1)); print(json.dumps(res, ensure_ascii=False))
