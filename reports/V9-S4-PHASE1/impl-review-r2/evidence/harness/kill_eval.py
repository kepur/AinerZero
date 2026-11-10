"""上轮必修第三部分的触发：评测中途 SIGKILL 运行器（smoke，替身分区，假根目录），看 worlds.partial.jsonl 是否已逐世界落盘、
每行可解析，且与同配置完整运行的对应世界逐位相同（「已算完的部分可以复算」）。用 a767ac7 副本测试里的 _make_root。
用法：kill_eval.py <副本根> <输出 json>（在共享锁下运行）"""
import json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
COPY, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(COPY / "src")); sys.path.insert(0, str(COPY / "tests/v9/experiments"))
import test_s4p1_runner_native as T
assert T.REPO == COPY, T.REPO
EXTRA = [('"smoke": {"n_train": 6, "sizes": (2, 1), "limit": 900, "pool": 300, "sigma": 200}', '"smoke": {"n_train": 6, "sizes": (10, 2), "limit": 1800, "pool": 300, "sigma": 200}'),
         ("WORKERS = 2", "WORKERS = 1")]
res = {}
with tempfile.TemporaryDirectory(prefix="s4impl-kill-") as tmp:
    tmp = Path(tmp)
    a = T._make_root(tmp / "a", extra=EXTRA)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    fresh = tmp / "pyc-a"; fresh.mkdir()
    cmd = [sys.executable, "-I", "-X", f"pycache_prefix={fresh}", str(a / T.RUNNER), "--report", str(a / "reports/out.json"), *T.SMOKE]
    p = subprocess.Popen(cmd, cwd=a, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    part = a / T.ARTS / "smoke-s1" / "worlds.partial.jsonl"
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1500:
        if part.exists() and len(part.read_text().splitlines()) >= 3:
            break
        if p.poll() is not None:
            break
        time.sleep(0.5)
    n_before = len(part.read_text().splitlines()) if part.exists() else 0
    os.killpg(p.pid, signal.SIGKILL); p.wait()
    lines = part.read_text().splitlines() if part.exists() else []
    parsed = [json.loads(x) for x in lines]
    rep = json.loads((a / "reports/out.json").read_text()) if (a / "reports/out.json").exists() else {}
    res["killed_run"] = {"lines_when_killed": n_before, "lines_after_kill": len(lines), "all_parse": True, "indices": sorted(x["index"] for x in parsed),
                         "worlds_jsonl_exists": (a / T.ARTS / "smoke-s1" / "worlds.jsonl").exists(), "report_has_result": "result" in rep,
                         "seconds_to_kill": round(time.monotonic() - t0, 1)}
    print("killed", res["killed_run"], flush=True)
    b = T._make_root(tmp / "b", extra=EXTRA)
    r = T._run(b, *T.SMOKE, timeout=3000)
    res["complete_run_rc"] = r.returncode
    full = [json.loads(x) for x in (b / T.ARTS / "smoke-s1" / "worlds.jsonl").read_text().splitlines()]
    res["complete_worlds"] = len(full)
    res["partial_equals_complete"] = [{"index": x["index"], "equal": x["record"] == full[x["index"]]} for x in parsed]
    # 第 6 项：verify_replay 能否发现篡改（在完整运行 b 的运行目录上，逐项改一处后单独调用校验脚本）
    import shutil
    run = b / T.ARTS / "smoke-s1"; vr = b / T.VERIFY[1]
    def verify(worlds):
        q = subprocess.run([sys.executable, "-I", str(vr), str(run / "replay.json"), str(worlds), str(run)], cwd=b, env=env, capture_output=True, text=True, timeout=600)
        return json.loads(q.stdout) if q.returncode == 0 else {"rc": q.returncode, "stderr": q.stderr[-300:]}
    res["replay_honest"] = verify(run / "worlds.jsonl")
    recs = [json.loads(x) for x in (run / "worlds.jsonl").read_text().splitlines()]
    t1 = [dict(r) for r in recs]; k = next(iter(t1[0]["ids_sha256"])); t1[0] = dict(t1[0], ids_sha256=dict(t1[0]["ids_sha256"], **{k: "0" * 64}))
    (tmp / "w_digest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in t1))
    res["replay_tampered_digest"] = verify(tmp / "w_digest.jsonl")
    t2 = [dict(r) for r in recs]; t2[0] = dict(t2[0], reid={kk: [1 - c for c in vv] for kk, vv in t2[0]["reid"].items()})
    (tmp / "w_reid.jsonl").write_text("".join(json.dumps(r) + "\n" for r in t2))
    res["replay_tampered_reid_flags_only"] = verify(tmp / "w_reid.jsonl")
    w1, w2 = run / "weights" / "L-int#1.safetensors", run / "weights" / "L-int#2.safetensors"
    keep = w1.read_bytes(); shutil.copy2(w2, w1)
    res["replay_swapped_weights"] = verify(run / "worlds.jsonl")
    w1.write_bytes(keep)
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1)); print(json.dumps(res, ensure_ascii=False))
