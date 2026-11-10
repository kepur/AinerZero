"""复核者自己的变异集（6e274fa）。每个变异：从隔离副本复制 src/ainerzero、tests/conftest.py、第三阶段 4 个测试、
pyproject.toml、运行器与校验器到新临时目录，改一处（恰好出现一次、改完过语法检查），先跑三个快测试，没抓到再跑运行器测试。
没被测试抓到的，再用 gate_check.py 在 s3p3x-explore 的前 30 个世界上跑契约门，看门能不能抓到。

用法：mut_r1.py <副本根> <输出 json> [变异名 ...]
"""
import ast, json, os, shutil, signal, subprocess, sys, tempfile, time
from pathlib import Path

BASE, OUT = Path(sys.argv[1]), Path(sys.argv[2])
ONLY = set(sys.argv[3:])
HERE = Path(__file__).resolve().parent
S3 = "src/ainerzero/v9/experiments/s3/"
PRF, ANF, RUN, VF = S3 + "promotion.py", S3 + "analysis_p3.py", "reports/V9-S3-PHASE3/run_phase3.py", "reports/V9-S3-PHASE3/verify_worlds.py"
FAST = ["tests/v9/experiments/test_s3p3_persist_promotion.py", "tests/v9/experiments/test_s3p3_analysis.py", "tests/v9/experiments/test_s3p3_verify_worlds.py"]
SLOW = ["tests/v9/experiments/test_s3p3_runner_guards.py"]

M = [
    # analysis_p3.py：统计输入与校验过的日志脱钩、对照臂、诊断量、契约门
    ("an_pred_G_decoupled", ANF, '"C": shown, "L": latest, "G": g, "GNR":', '"C": shown, "L": latest, "G": (shown if e >= 9 else g), "GNR":'),
    ("an_pred_L_decoupled", ANF, '"C": shown, "L": latest, "G": g, "GNR":', '"C": shown, "L": shown, "G": g, "GNR":'),
    ("an_gt_no_rollback", ANF, "truth_store = PR.TruthKeyedStore(rollback=True)", "truth_store = PR.TruthKeyedStore(rollback=False)"),
    ("an_lt_fallback_latest", ANF, "if len(at_cell) else shown", "if len(at_cell) else latest"),
    ("an_mixed_ge1", ANF, "for m in it.members}) > 1 for it in store.items)", "for m in it.members}) >= 1 for it in store.items)"),
    ("an_several_slow_ge1", ANF, "sum(on.count(c) > 1 for c in persistent)", "sum(on.count(c) >= 1 for c in persistent)"),
    ("an_k4_stable_pre_only", ANF, 'stable = q & (ev["relocated"] == 0)', 'stable = q & (ev["relocated"] == 0) & (ev["episode"] < PS.RELOCATION_EPISODE)'),
    ("an_k3_versions_only", ANF, "if json.loads(json.dumps(s.state())) != final_state:", 'if json.loads(json.dumps(s.state()))["versions"] != final_state["versions"]:'),
    ("an_u0past_all_fast", ANF, '"D2_U0_won_by_past": rate(ev, s["fast_e1"], "u0_past"),', '"D2_U0_won_by_past": rate(ev, s["fast"], "u0_past"),'),
    ("an_gp_of_latest", ANF, '"GP": perm.get(g, g)', '"GP": perm.get(latest, latest)'),
    ("an_mode_fallback_shown", ANF, "mode = latest if j_any is None else", "mode = shown if j_any is None else"),
    ("an_sr_fallback_latest", ANF, '"SR": g if f is None else int(R.token[f])', '"SR": latest if f is None else int(R.token[f])'),
    ("an_gnr_rollback", ANF, "GNR = PR.PromotionStore(rollback=False)", "GNR = PR.PromotionStore(rollback=True)"),
    ("an_k5_expected_fast", ANF, '"fast": 2030', '"fast": 2300'),
    ("an_bonf_m_small", ANF, "N_COMPARISONS = len(COMPARISONS) + len(OFFSET_COMPARISONS) * len(OFFSETS)", "N_COMPARISONS = len(COMPARISONS)"),
    ("an_query_tie_all", ANF, 'rate(ev, s["query"] & (ev["g_slow"] == 1), "query_tie")', 'rate(ev, s["query"], "query_tie")'),
    ("an_offset_seed_k1", ANF, 'derive_seed(seq.namespace, "offset", seq.world_index, e, k)', 'derive_seed(seq.namespace, "offset", seq.world_index, e, 1)'),
    ("an_offset_skip_e0", ANF, "    for e in range(len(seq.episodes)):\n        rng = random.Random", "    for e in range(1, len(seq.episodes)):\n        rng = random.Random"),
    ("an_first_ok_any_visit", ANF, "int(R.t[own[0]]) == t)", "t in R.t[own].tolist())"),
    ("an_fast_sr_no_gate", ANF, "            f = top1(R, fast_pool(R, e, t), qi, eligible_only=True)\n            if f is not None:", "            f = top1(R, fast_pool(R, e, t), qi)\n            if f is not None:"),
    ("an_recovery_vs_L", ANF, 'if first is None and row["G"] > row["C"]:', 'if first is None and row["G"] > row["L"]:'),
    # verify_worlds.py
    ("vf_in_force_le", VF, 'in_force = [x for x in versions if x["episode"] < q["episode"]]', 'in_force = [x for x in versions if x["episode"] <= q["episode"]]'),
    ("vf_vote_eq_episode", VF, '(eps and eps[-1] > v["episode"])', '(eps and eps[-1] >= v["episode"])'),
    ("vf_no_query_count", VF, '"passed": bool(n_w > 0 and n_q > 0 and not problems)', '"passed": bool(n_w > 0 and not problems)'),
    ("vf_first_world_only", VF, "        for line in fh:\n", "        for line in list(fh)[:1]:\n"),
    ("vf_place_sim08", VF, "(d <= D_MAX and sim >= 1.0)", "(d <= D_MAX and sim >= 0.8)"),
    ("vf_rebuild_promoted_only", VF, "j = best([(it[0], it[1], it[2], it[0]) for it in items], xy, ter)", "j = best([(it[0], it[1], it[2], it[0]) for it in items if it[4] is not None], xy, ter)"),
    ("vf_G_fallback_shown", VF, "G = L if slow is None else slow", 'G = q["shown"] if slow is None else slow'),
    ("vf_rebuild_len_only", VF, 'if [v["hash"] for v in rebuilt] != [v["hash"] for v in versions]:', "if len(rebuilt) != len(versions):"),
    ("vf_reanswer_G_only", VF, 'if L != q["pred_L"] or G != q["pred_G"]:', 'if G != q["pred_G"]:'),
    ("vf_terrain_ignored", VF, "sim = sum(1 for a, b in zip(ater, ter) if int(a) == int(b)) / len(ater)", "sim = 1.0"),
    # run_phase3.py
    ("run_log_first_world", RUN, "            for lg in logs:\n                fh.write(", "            for lg in logs[:1]:\n                fh.write("),
    ("run_sha_main_only", RUN, "for name in list(files) + [worlds.name]}", 'for name in ["events.npz", worlds.name]}'),
    ("run_offsets_k0", RUN, "ck, _ = A.analyse_world(seq, offset=k, full=False)", "ck, _ = A.analyse_world(seq, offset=0, full=False)"),
    # promotion.py
    ("pr_snapshot_no_sim", PRF, "if d > D_MAX or sim < SIM_MIN:", "if d > D_MAX:"),
    ("pr_state_no_slow", PRF, "[list(v) for v in it.votes], it.slow] for it in self.items]", "[list(v) for v in it.votes], None] for it in self.items]"),
    ("pr_dwell_no_token_split", PRF, "key = (float(xy[i][0]), float(xy[i][1]), int(token[i]))", "key = (float(xy[i][0]), float(xy[i][1]))"),
]


def copy_tree(dst, src):
    shutil.copytree(src / "src/ainerzero", dst / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    (dst / "tests/v9/experiments").mkdir(parents=True)
    shutil.copy2(src / "tests/conftest.py", dst / "tests/conftest.py")
    for t in FAST + SLOW:
        shutil.copy2(src / t, dst / t)
    shutil.copy2(src / "pyproject.toml", dst / "pyproject.toml")
    (dst / "reports/V9-S3-PHASE3").mkdir(parents=True)
    shutil.copy2(src / RUN, dst / RUN)
    shutil.copy2(src / VF, dst / VF)


def pytest(dst, files):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(dst / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, str(HERE / "pyt.py"), str(dst), "-q", "-x", "-p", "no:cacheprovider", *files], env=env,
                       capture_output=True, text=True, timeout=900, preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    return r.returncode, r.stdout[-400:]


def gates(dst):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, "-I", str(HERE / "gate_check.py"), str(dst), "30"], env=env, capture_output=True, text=True, timeout=900)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"crashed": True, "stderr": r.stderr[-400:]}


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="s3p3-rv-mut-") as tmp:
        base = Path(tmp) / "base"
        copy_tree(base, BASE)
        rc, tail = pytest(base, FAST + SLOW)
        print("unmutated", rc, flush=True)
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
            if not rc and path != RUN:
                row["gates_on_30_explore_worlds"] = gates(d)
            row["seconds"] = round(time.monotonic() - t0, 1)
            results.append(row)
            print(name, row["status"], stage, row["seconds"], json.dumps(row.get("gates_on_30_explore_worlds", ""))[:300], flush=True)
            shutil.rmtree(d)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("killed", sum(r["status"] == "killed" for r in results), "of", len(results), flush=True)


if __name__ == "__main__":
    main()
