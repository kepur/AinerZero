"""复核者 r2 变异集（240b1ac）：重打 r1 漏网的 11 个和 an_pred_G_decoupled（按当前代码改写），另加 K6、K2(e)、K2b、K5、运行器、make_prereg 的新变异。
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
    # r1 漏网的 11 个与 an_pred_G_decoupled
    ("r1_an_pred_G_decoupled", ANF, '"C": shown, "L": latest, "G": g, "GNR":', '"C": shown, "L": latest, "G": (shown if e >= 9 else g), "GNR":'),
    ("r1_an_gt_no_rollback", ANF, "truth_store = PR.TruthKeyedStore(rollback=True)", "truth_store = PR.TruthKeyedStore(rollback=False)"),
    ("r1_an_lt_fallback_latest", ANF, "if len(at_cell) else shown", "if len(at_cell) else latest"),
    ("r1_an_mixed_ge1", ANF, "for m in it.members}) > 1 for it in store.items)", "for m in it.members}) >= 1 for it in store.items)"),
    ("r1_an_several_slow_ge1", ANF, "sum(on.count(c) > 1 for c in persistent)", "sum(on.count(c) >= 1 for c in persistent)"),
    ("r1_an_k3_versions_only", ANF, "if json.loads(json.dumps(s.state())) != final_state:", 'if json.loads(json.dumps(s.state()))["versions"] != final_state["versions"]:'),
    ("r1_an_u0past_all_fast", ANF, '"D2_U0_won_by_past": rate(ev, s["fast_e1"], "u0_past"),', '"D2_U0_won_by_past": rate(ev, s["fast"], "u0_past"),'),
    ("r1_an_gnr_rollback", ANF, "GNR = PR.PromotionStore(rollback=False)", "GNR = PR.PromotionStore(rollback=True)"),
    ("r1_an_query_tie_all", ANF, 'rate(ev, s["query"] & (ev["g_slow"] == 1), "query_tie")', 'rate(ev, s["query"], "query_tie")'),
    ("r1_an_fast_sr_no_gate", ANF, "            f = top1(R, fast_pool(R, e, t), qi, eligible_only=True)\n            if f is not None:", "            f = top1(R, fast_pool(R, e, t), qi)\n            if f is not None:"),
    ("r1_vf_no_query_count", VF, '"passed": bool(n_w > 0 and n_q > 0 and not problems)', '"passed": bool(n_w > 0 and not problems)'),
    ("r1_run_offsets_k0", RUN, "ck, _ = A.analyse_world(seq, offset=k, full=False)", "ck, _ = A.analyse_world(seq, offset=0, full=False)"),
    # K6
    ("k6_no_preds", ANF, 'for k in ("world", "episode", "t", "answer", "shown", "decoy", "relocated", "pred_G", "pred_L")', 'for k in ("world", "episode", "t", "answer", "shown", "decoy", "relocated")'),
    ("k6_fast_ignored", ANF, "ok_q, ok_f = logged_q == event_q, logged_f == event_f", "ok_q, ok_f = logged_q == event_q, True"),
    ("k6_worlds_ignored", ANF, 'worlds == sorted(set(ev["world"].tolist())) and ', ""),
    ("k6_not_gating", ANF, 'out["K6_events_match_log"] = log_linkage(ev, logs)', 'out["K6_events_match_log"] = log_linkage(ev, logs) | {"passed": True}'),
    # K2(e)、K2b 的接入
    ("k2e_counts_off", ANF, 'counts_ok = external is not None and external.get("worlds") == n_worlds and external.get("queries") == n_q', "counts_ok = True"),
    ("k2e_worlds_only", ANF, ' and external.get("queries") == n_q\n', "\n"),
    ("k2b_fast_count_off", ANF, ' and external_gen.get("fast_events") == int(s["fast"].sum()))', ")"),
    ("k2b_ignored", ANF, 'out["K2b_generator"] = {"passed": bool(gen_ok)', 'out["K2b_generator"] = {"passed": True'),
    ("k5_band_wide", ANF, 'SAMPLE_BAND = {"fast": 0.07, "decoy_stable": 0.13, "relocated": 0.21}', 'SAMPLE_BAND = {"fast": 0.2, "decoy_stable": 0.2, "relocated": 0.2}'),
    # verify_generation.py
    ("vg_no_obs", VG, 'if lg["observations"] != obs:', "if False:"),
    ("vg_no_queries", VG, "if logged != queries:", "if False:"),
    ("vg_no_fast", VG, 'if lg["fast_events"] != fast:', "if False:"),
    ("vg_no_seed", VG, 'if lg.get("world_seed") != seq.world_seed or lg.get("layout_sha256") != seq.layout_sha256:', "if False:"),
    ("vg_keys_no_answer", VG, 'KEYS = ("episode", "t", "xy", "terrain", "shown", "answer", "decoy", "relocated")', 'KEYS = ("episode", "t", "xy", "terrain", "shown", "decoy", "relocated")'),
    ("vg_keys_no_relocated", VG, 'KEYS = ("episode", "t", "xy", "terrain", "shown", "answer", "decoy", "relocated")', 'KEYS = ("episode", "t", "xy", "terrain", "shown", "answer", "decoy")'),
    ("vg_dwell_no_token", VG, "key = (r.est_pose[0], r.est_pose[1], r.observed_token)", "key = (r.est_pose[0], r.est_pose[1])"),
    ("vg_query_last_arrival", VG, "                        })\n                        break\n", "                        })\n"),
    ("vg_order_ignored", VG, "if worlds != list(range(len(worlds))):", "if False:"),
    ("vg_forbidden_ignored", VG, "    if loaded:\n", "    if False:\n"),
    ("vg_passed_always", VG, '"passed": bool(worlds and n_q > 0 and not problems)', '"passed": True'),
    ("vg_fast_unswapped", VG, 'if ev["bucket"] == spec.BUCKET_LONG and ev["swapped"]:', 'if ev["bucket"] == spec.BUCKET_LONG:'),
    ("vg_relocated_late", VG, '"relocated": int(e >= PS.RELOCATION_EPISODE and c in seq.relocated)', '"relocated": int(e > PS.RELOCATION_EPISODE and c in seq.relocated)'),
    ("vg_queries_from_e0", VG, "        if e >= 1:\n", "        if e >= 0:\n"),
    # 运行器
    ("run_k2b_faked", RUN, '        k2b = independent_check(VERIFY_GEN, worlds, ns, cfg["episodes"], deadline=deadline)\n',
     '        k2b = {"passed": True, "worlds": cfg["worlds"], "queries": int((ev["kind"] == A.KIND_QUERY).sum()), "fast_events": int((ev["kind"] == A.KIND_FAST).sum())}\n'),
    ("run_k2_faked", RUN, "        k2 = independent_check(VERIFY, worlds, deadline=deadline)\n",
     '        k2 = {"passed": True, "worlds": cfg["worlds"], "queries": int((ev["kind"] == A.KIND_QUERY).sum())}\n'),
    ("run_offsets_swapped", RUN, "ck, _ = A.analyse_world(seq, offset=k, full=False)", "ck, _ = A.analyse_world(seq, offset={1: 2, 2: 1}.get(k, k), full=False)"),
    ("run_timeout_fixed", RUN, "capture_output=True, text=True, timeout=left)", "capture_output=True, text=True, timeout=1200)"),
    ("run_code_dirty_hidden", RUN, "code_head, code_dirty = GD.check_git_clean(REPO, list(code))", "code_head, code_dirty = GD.check_git_clean(REPO, list(code))[0], []"),
    ("run_smoke_reads_probe", RUN, "            ns = SMOKE_NAMESPACE\n", '            ns = A.NAMESPACES["probe"]\n'),
    ("run_probe_no_use_id", RUN, 'if a.stage in ("smoke", "probe") and not a.use_id:', 'if a.stage in ("smoke",) and not a.use_id:'),
    # make_prereg.py
    ("mp_no_code_check", MP, 'if pr.get("code_manifest_sha256") != code_sha or pr.get("code_dirty") != []:', "if False:"),
    ("mp_dirty_ignored", MP, ' or pr.get("code_dirty") != []:', ":"),
    ("mp_dev_uses_two", MP, '"dev_max_uses": 0,', '"dev_max_uses": 2,'),
    ("mp_probe_invalid_ok", MP, ' or not pr.get("result", {}).get("valid"):', ":"),
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
