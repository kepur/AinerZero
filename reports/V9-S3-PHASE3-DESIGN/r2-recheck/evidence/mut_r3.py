"""复核者 r2 复查后的变异集（941d9bc）：重打 r1 漏网的 11 个和 an_pred_G_decoupled（按当前代码改写），另加 K6、K2(e)、K2b、K5、运行器、make_prereg 的新变异。
每个变异：复制 src/ainerzero、tests/conftest.py、第三阶段 5 个测试、pyproject.toml、运行器、两个校验器、make_prereg 到新临时目录，
改一处（恰好出现一次、过语法检查），先跑四个快测试，没抓到再跑运行器测试。没被测试抓到的非运行器变异，再用 gate_check_r2.py 在
s3p3x-explore 的前 30 个世界上跑 K1–K4、K6 和 K2、K2b（K5 需要整 100 个世界，不跑）。

用法：mut_r2.py <副本根> <输出 json> [变异名 ...]
"""
import ast, json, os, shutil, signal, subprocess, sys, tempfile, time
from pathlib import Path

BASE, OUT = Path(sys.argv[1]), Path(sys.argv[2])
ONLY = set(sys.argv[3:])
HERE = Path(__file__).resolve().parent
S3 = "src/ainerzero/v9/experiments/s3/"
PRF, ANF = S3 + "promotion.py", S3 + "analysis_p3.py"
RUN, VF, VG, MP = "reports/V9-S3-PHASE3/run_phase3.py", "reports/V9-S3-PHASE3/verify_worlds.py", "reports/V9-S3-PHASE3/verify_generation.py", "reports/V9-S3-PHASE3/make_prereg.py"
FAST = ["tests/v9/experiments/test_s3p3_persist_promotion.py", "tests/v9/experiments/test_s3p3_analysis.py",
        "tests/v9/experiments/test_s3p3_verify_worlds.py", "tests/v9/experiments/test_s3p3_verify_generation.py"]
SLOW = ["tests/v9/experiments/test_s3p3_runner_guards.py"]

M = [
    # r2 复查漏网的 5 个
    ("r2_an_lt_fallback_latest", ANF, "if len(at_cell) else shown", "if len(at_cell) else latest"),
    ("r2_an_query_tie_all", ANF, 'rate(ev, s["query"] & (ev["g_slow"] == 1), "query_tie")', 'rate(ev, s["query"], "query_tie")'),
    ("r2_k6_worlds_ignored", ANF, 'worlds == sorted(set(ev["world"].tolist())) and ', ""),
    ("r2_vg_forbidden_ignored", VG, "    if loaded:\n", "    if False:\n"),
    ("r2_run_timeout_fixed", RUN, "capture_output=True, text=True, timeout=left)", "capture_output=True, text=True, timeout=1200)"),
    # K7
    ("k7_not_required", ANF, "    if offsets is not None or stage is not None:  # a registered stage must carry its offset files", "    if offsets is not None:"),
    ("k7_no_answer", ANF, 'IDENTITY = ("kind", "world", "episode", "t", "answer", "shown", "decoy", "relocated", "tok_before", "tok_after", "first_ok")', 'IDENTITY = ("kind", "world", "episode", "t", "shown", "decoy", "relocated", "tok_before", "tok_after", "first_ok")'),
    ("k7_missing_level_ok", ANF, '"passed": bool(sorted(offsets) == sorted(OFFSETS) and not any(bad.values()))', '"passed": bool(not any(bad.values()))'),
    # K6 读回（作者标为等价）
    ("k6_in_memory_EQUIV", RUN, 'R["result"] = A.evaluate(ev, on_disk,', 'R["result"] = A.evaluate(ev, logs,'),
    # K2b 授权
    ("auth_no_marker", VG, 'if p.parent != root / "final-final" or not (root / "FINAL_READ_ONCE.json").is_file():', 'if p.parent != root / "final-final":'),
    ("auth_no_dir", VG, 'if p.parent != root / "final-final" or not (root / "FINAL_READ_ONCE.json").is_file():', 'if not (root / "FINAL_READ_ONCE.json").is_file():'),
    ("auth_no_resolve", VG, "p, root = Path(path).resolve(), Path(root).resolve()", "p, root = Path(path), Path(root)"),
    ("auth_name_off", VG, 'if p.name != "worlds.jsonl":', "if False:"),
    ("auth_dev_prefix_off", VG, ' or not p.parent.name.startswith("dev-")', ""),
    ("auth_names_check_off", VG, "if FINAL_NAMES | DEV_NAMES != PS.REGISTERED:", "if False:"),
    ("auth_unknown_registered_ok", VG, 'return False, f"{ns}: registered partition with no registered run"', "return True, None"),
    ("auth_bypassed", VG, "ok, why = authorize(path, ns, root=ROOT, final_names=FINAL_NAMES, dev_names=DEV_NAMES, registered=PS.REGISTERED)", "ok, why = True, None"),
    ("auth_root_wrong", VG, 'ROOT = REPO / "artifacts/v9/s3/phase3"', 'ROOT = REPO / "artifacts/v9/s3"'),
]


def copy_tree(dst, src):
    shutil.copytree(src / "src/ainerzero", dst / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    (dst / "tests/v9/experiments").mkdir(parents=True)
    shutil.copy2(src / "tests/conftest.py", dst / "tests/conftest.py")
    for t in FAST + SLOW:
        shutil.copy2(src / t, dst / t)
    shutil.copy2(src / "pyproject.toml", dst / "pyproject.toml")
    (dst / "reports/V9-S3-PHASE3").mkdir(parents=True)
    for f in (RUN, VF, VG, MP):
        shutil.copy2(src / f, dst / f)


def pytest(dst, files):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(dst / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, str(HERE / "pyt.py"), str(dst), "-q", "-x", "-p", "no:cacheprovider", *files], env=env,
                       capture_output=True, text=True, timeout=1200, preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    return r.returncode, r.stdout[-400:]


def gates(dst):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, "-I", str(HERE / "gate_check_r2.py"), str(dst), "30"], env=env, capture_output=True, text=True, timeout=900)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"crashed": True, "stderr": r.stderr[-400:]}


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="s3p3-rv2-mut-") as tmp:
        base = Path(tmp) / "base"
        copy_tree(base, BASE)
        rc, tail = pytest(base, FAST + SLOW)
        print("unmutated", rc, tail[-120:].replace("\n", " "), flush=True)
        if rc != 0:
            raise SystemExit("unmutated copy fails:\n" + tail)
        for name, path, old, new in M:
            if ONLY and name not in ONLY:
                continue
            d = Path(tmp) / name
            copy_tree(d, base)
            f = d / path
            text = f.read_text(encoding="utf-8")
            if text.count(old) != 1:
                results.append({"name": name, "status": "stale", "count": text.count(old)})
                print(name, "STALE", text.count(old), flush=True)
                shutil.rmtree(d)
                continue
            text = text.replace(old, new)
            ast.parse(text)
            f.write_text(text, encoding="utf-8")
            t0 = time.monotonic()
            rc, tail = pytest(d, FAST)
            stage = "fast"
            if rc == 0:
                rc, tail = pytest(d, SLOW)
                stage = "runner"
            row = {"name": name, "file": path, "status": "killed" if rc else "SURVIVED", "by": stage if rc else None, "tail": tail[-250:]}
            if not rc and path not in (RUN, MP):
                row["gates_on_30_explore_worlds"] = gates(d)
            row["seconds"] = round(time.monotonic() - t0, 1)
            results.append(row)
            print(name, row["status"], stage, row["seconds"], json.dumps(row.get("gates_on_30_explore_worlds", ""))[:260], flush=True)
            shutil.rmtree(d)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("killed", sum(r["status"] == "killed" for r in results), "of", len(results), flush=True)


if __name__ == "__main__":
    main()
