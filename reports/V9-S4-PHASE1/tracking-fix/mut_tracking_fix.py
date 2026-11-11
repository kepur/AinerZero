"""一级 claude 11-11：L-int-s 移出跟踪臂之后的测试计数与变异（含 P209 的四个变异复跑）。
每个变异复制 src/ainerzero、tests、pyproject.toml、reports/V9-S4-PHASE1（不含 mutants、probe-*、本目录）到新临时目录，
只改一处（原文恰好出现一次、改后过语法检查），PYTHONPATH 指向副本，--native-mlx 跑对应测试。
必须在共享锁下运行（hold_lock.py）。用法：mut_tracking_fix.py <仓库根> <输出目录>"""
import ast, json, os, re, shutil, signal, subprocess, sys, tempfile, time
from pathlib import Path

BASE, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
PYT = BASE / "reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/pyt.py"
S4 = "src/ainerzero/v9/experiments/s4/"
AN, RU, MP = S4 + "analysis.py", "reports/V9-S4-PHASE1/run_s4p1.py", "reports/V9-S4-PHASE1/make_prereg.py"
T = "tests/v9/experiments/"
CPU_T = [T + "test_s4_world.py", T + "test_s4_filter_metrics.py", T + "test_s4_analysis.py", T + "test_s4_verify_labels.py"]
LM_T, RU_T = [T + "test_s4_learned_mlx.py"], [T + "test_s4p1_runner_native.py"]
MUTS = [
    # P209 (gemini), rerun by the acceptor
    ("an_mut_row_consumed_steps_only", AN, '"consumed": len(b) == len(mut) and all(', '"consumed": all(', CPU_T),
    ("mp_reserve_eval_only", MP, 'eval_reserve = math.ceil(1.5 * scale * pr["post_marker_seconds"])', 'eval_reserve = math.ceil(1.5 * scale * pr["eval_seconds"])', RU_T),
    ("mp_budget_ignores_reserve", MP, "if 1.2 * train_s + eval_reserve > HARD_LIMIT_S:", "if 1.2 * train_s > HARD_LIMIT_S:", RU_T),
    ("ru_post_marker_after_generation", RU,
     "        t_post = time.monotonic()                                          # everything from here on is what the reserve must cover\n"
     "        eval_eps = [(kind, W.generate_episode(ns[\"eval\"], w, n, allow_registered=registered)) for kind, w, n in A.eval_world_ids(cfg[\"sizes\"])]\n",
     "        eval_eps = [(kind, W.generate_episode(ns[\"eval\"], w, n, allow_registered=registered)) for kind, w, n in A.eval_world_ids(cfg[\"sizes\"])]\n"
     "        t_post = time.monotonic()\n", RU_T),
    # the tracking fix
    ("ru_tracked_all", RU, 'TRACKED = tuple(a for a in LEARNED if a != "L-int-s")', "TRACKED = LEARNED", RU_T),
    ("ru_cells_learned", RU, "main_cells = [(c.arm, c.seed, c.variant) for c in A.plan_cells(TRACKED)]",
     "main_cells = [(c.arm, c.seed, c.variant) for c in A.plan_cells(LEARNED)]", RU_T),
    ("ru_replay_unfiltered", RU, 'for n, p in weights.items() if n.split("#")[0] in TRACKED}', "for n, p in weights.items()}", RU_T),
    ("ru_descriptive_learned", RU, "R[\"descriptive\"] = A.summarize_descriptive(main_r, ext_r, TRACKED)",
     "R[\"descriptive\"] = A.summarize_descriptive(main_r, ext_r, LEARNED)", RU_T),
]


def copy_tree(dst, src):
    shutil.copytree(src / "src/ainerzero", dst / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(src / "tests", dst / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(src / "pyproject.toml", dst / "pyproject.toml")
    shutil.copytree(src / "reports/V9-S4-PHASE1", dst / "reports/V9-S4-PHASE1",
                    ignore=shutil.ignore_patterns("__pycache__", "mutants", "probe-*", "tracking-fix", "impl-review*", "prefreeze-tests"))
    shutil.copy2(PYT, dst / "pyt.py")


def env_for(dst):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(dst / "src"); env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def pytest(dst, files, native=True, x=True):
    args = [sys.executable, str(dst / "pyt.py"), str(dst), "-q", "-p", "no:cacheprovider", *(["-x"] if x else []), *(["--native-mlx"] if native else []), *files]
    r = subprocess.run(args, env=env_for(dst), capture_output=True, text=True, timeout=1800)
    return r.returncode, r.stdout + r.stderr


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log = (OUT / "mut_tracking_fix.log").open("w")
    res = {"counts": {}, "mutants": []}
    with tempfile.TemporaryDirectory(prefix="s4-trackfix-") as tmp:
        base = Path(tmp) / "base"; copy_tree(base, BASE)
        where = subprocess.run([sys.executable, "-c", "import ainerzero.v9.experiments.s4.analysis as m; print(m.__file__)"],
                               cwd=base, env=env_for(base), capture_output=True, text=True).stdout.strip()
        assert where.startswith(str(base)), where
        for label, files, native in (("cpu_default", CPU_T, False), ("mlx_learned", LM_T, True), ("runner", RU_T, True)):
            t0 = time.monotonic(); rc, out = pytest(base, files, native=native, x=False)
            res["counts"][label] = {"rc": rc, "summary": out.strip().splitlines()[-1], "seconds": round(time.monotonic() - t0, 1),
                                    "failed": re.findall(r"FAILED (\S+)", out)[:10]}
            log.write(f"=== count {label} ===\n{out}\n"); log.flush()
            print(label, res["counts"][label], flush=True)
        for name, path, old, new, files in MUTS:
            d = Path(tmp) / name; copy_tree(d, BASE); f = d / path; text = f.read_text()
            if text.count(old) != 1:
                res["mutants"].append({"name": name, "status": "stale", "count": text.count(old)}); print(name, "STALE", flush=True)
                shutil.rmtree(d); continue
            text = text.replace(old, new); ast.parse(text); f.write_text(text)
            t0 = time.monotonic(); rc, out = pytest(d, files, native=files is not CPU_T)
            failed = re.findall(r"FAILED (\S+)", out)
            res["mutants"].append({"name": name, "file": path, "status": "killed" if rc else "SURVIVED", "failed": [x.split("::")[-1] for x in failed[:6]],
                                   "summary": out.strip().splitlines()[-1], "seconds": round(time.monotonic() - t0, 1)})
            log.write(f"=== mutant {name} ===\n{out}\n"); log.flush()
            print(name, res["mutants"][-1]["status"], res["mutants"][-1]["failed"], res["mutants"][-1]["summary"], flush=True)
            shutil.rmtree(d)
    (OUT / "mut_tracking_fix.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("killed", sum(m["status"] == "killed" for m in res["mutants"]), "of", len(res["mutants"]), flush=True)


if __name__ == "__main__":
    main()
