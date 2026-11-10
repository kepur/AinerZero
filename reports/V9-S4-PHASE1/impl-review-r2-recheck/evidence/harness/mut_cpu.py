"""复核者 claude-s4impl-rev2-1110 的纯 CPU 变异（a767ac7）。每个变异复制 src/ainerzero、tests/conftest.py、S4 测试（含数据）、
pyproject.toml、reports/V9-S4-PHASE1 到新临时目录，改一处（恰好一次、过语法检查），PYTHONPATH 指向副本，跑默认入口（纯 CPU）的 S4 测试。
用法：mut_cpu.py <副本根> <输出 json> [变异名 ...]"""
import ast, json, os, re, shutil, signal, subprocess, sys, tempfile, time
from pathlib import Path
BASE, OUT = Path(sys.argv[1]), Path(sys.argv[2]); ONLY = set(sys.argv[3:])
HERE = Path(__file__).resolve().parent
S4 = "src/ainerzero/v9/experiments/s4/"
AN, ME, VL = S4 + "analysis.py", S4 + "metrics.py", "reports/V9-S4-PHASE1/verify_labels.py"
TESTS = ["tests/v9/experiments/test_s4_world.py", "tests/v9/experiments/test_s4_filter_metrics.py", "tests/v9/experiments/test_s4_analysis.py",
         "tests/v9/experiments/test_s4_verify_labels.py"]
M = [
    ("an_neg_C_ignored", AN, ',\n                        c_ind["ci_low"], c_ind["ci_low"] is not None and c_ind["ci_low"] < T["negative_control"]["C_low_below"]),', "),"),
    ("an_neg_voids_HD_only", AN, '        for k in ("HD", "H1"):\n', '        for k in ("HD",):\n'),
    ("an_samples_dyn_ignored", AN, " and n_coll_steps >= DYN_FLOOR * dyn_expected)", ")"),
    ("an_samples_no_upper", AN, "abs(n_coll_events - expected) <= SAMPLE_BAND * expected", "n_coll_events >= (1 - SAMPLE_BAND) * expected"),
    ("an_floor_ecv_ignored", AN, 'floor = not missing and acc["E-CV"] < acc["E-B"] < acc["E-P"]', 'floor = not missing and acc["E-B"] < acc["E-P"]'),
    ("an_complete_extrap_ignored", AN, '"passed": len(main) == n_main and len(extrap) == n_extrap,', '"passed": len(main) == n_main,'),
    ("an_complete_always", AN, '"passed": len(main) == n_main and len(extrap) == n_extrap,', '"passed": True,'),
    ("an_mut_row_unaligned", AN, "any(not np.array_equal(np.asarray(x)[: len(y)], y) for x, y in zip(a[cut + 1:], b[cut + 1:]))", "any(not np.array_equal(np.asarray(x), y) for x, y in zip(a[cut + 1:], b[cut + 1:]))"),
    ("an_mut_row_consumed_steps_only", AN, '"consumed": len(b) == len(mut) and all(', '"consumed": all('),
    ("an_mut_row_prefix_short", AN, "all(np.array_equal(x, y) for x, y in zip(a[: cut + 1], b[: cut + 1]))", "all(np.array_equal(x, y) for x, y in zip(a[: cut], b[: cut]))"),
    ("an_future_mutation_no_shift", AN, "return [d if t <= cut else d[:-1] + 0.5 for t, d in enumerate(dets)]", "return [d if t <= cut else d[:-1] for t, d in enumerate(dets)]"),
    ("an_floor_undefined_passes", AN, 'floor = not missing and acc["E-CV"] < acc["E-B"] < acc["E-P"]', 'floor = bool(missing) or (acc["E-CV"] < acc["E-B"] < acc["E-P"])'),
    ("an_H2_vs_EB", AN, 'h2 = diff_of(main, "L-int", "L-ind")', 'h2 = diff_of(main, "L-int", "E-B")'),
    ("an_samples_all_events", AN, "    n_coll_events = int(n_events(main).sum())\n", "    n_coll_events = int(n_events(main, collision=False).sum())\n"),
    ("an_HF_uses_extrap", AN, 'd, hf = D_of(main, "L-int"), HF_of(main, "L-int")', 'd, hf = D_of(main, "L-int"), HF_of(extrap, "L-int")'),
    ("an_student_ignored", AN, '"student_view": {"passed": bool(student_ok)}', '"student_view": {"passed": True}'),
    ("an_determinism_ignored", AN, '"determinism": {"passed": bool(replay_ok)}', '"determinism": {"passed": True}'),
    ("an_extrap_offset_zero", AN, "EXTRAP_OFFSET = 1000", "EXTRAP_OFFSET = 0"),
    ("an_train_disks_fixed", AN, "TRAIN_DISKS = (4, 8)", "TRAIN_DISKS = (6, 6)"),
    ("an_seed_sum_not_mean", AN, 'per = np.mean([np.asarray(r["reid"][Cell(arm, s, variant).key], dtype=np.float64) for s in SEEDS], axis=0)', 'per = np.sum([np.asarray(r["reid"][Cell(arm, s, variant).key], dtype=np.float64) for s in SEEDS], axis=0)'),
    ("an_neg_uses_extrap", AN, 'd_ind, c_ind = D_of(main, "L-ind"), C_of(main, "L-ind")', 'd_ind, c_ind = D_of(extrap, "L-ind"), C_of(extrap, "L-ind")'),
    ("me_dyn_skip_graze_only", ME, "        if not coll and not graze:\n            continue\n", "        if not coll:\n            continue\n"),
    ("vl_no_dyn_check", VL, '        if r["dyn"]["E-B"]["n_coll"] != n_coll:', "        if False:"),
    ("vl_no_reid_len_check", VL, "            if len(c) != len(r[\"events\"]):", "            if False:"),
    ("vl_world_list_unchecked", VL, '    if [(r["kind"], r["world"]) for r in records] != [(g["kind"], g["world"]) for g in labels]:', "    if False:"),
    ("vl_gap_one", VL, "t - last >= 2 and", "t - last >= 1 and"),
    ("vl_passed_always", VL, '"passed": not bad,', '"passed": True,'),
]
def copy_tree(dst, src):
    shutil.copytree(src / "src/ainerzero", dst / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(src / "tests", dst / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(src / "pyproject.toml", dst / "pyproject.toml")
    shutil.copytree(src / "reports/V9-S4-PHASE1", dst / "reports/V9-S4-PHASE1", ignore=shutil.ignore_patterns("__pycache__", "mutants"))
def pytest(dst, files):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}; env["PYTHONPATH"] = str(dst / "src"); env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, str(HERE / "pyt.py"), str(dst), "-q", "-x", "-p", "no:cacheprovider", *files], env=env, capture_output=True, text=True, timeout=900)
    return r.returncode, r.stdout[-400:]
res = []
with tempfile.TemporaryDirectory(prefix="s4impl-rv-") as tmp:
    base = Path(tmp) / "base"; copy_tree(base, BASE)
    rc, tail = pytest(base, TESTS); print("unmutated", rc, tail[-80:].replace("\n", " "), flush=True)
    assert rc == 0
    for name, path, old, new in M:
        if ONLY and name not in ONLY:
            continue
        d = Path(tmp) / name; copy_tree(d, base); f = d / path; t = f.read_text()
        if t.count(old) != 1:
            res.append({"name": name, "status": "stale", "count": t.count(old)}); print(name, "STALE", t.count(old), flush=True); shutil.rmtree(d); continue
        t = t.replace(old, new); ast.parse(t); f.write_text(t)
        t0 = time.monotonic(); rc, tail = pytest(d, TESTS)
        m = re.search(r"FAILED \S+::(\S+)", tail)
        res.append({"name": name, "file": path, "status": "killed" if rc else "SURVIVED", "by": m.group(1) if m else (tail[-120:] if rc else None), "seconds": round(time.monotonic() - t0, 1)})
        print(name, res[-1]["status"], res[-1]["by"], flush=True); shutil.rmtree(d)
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1)); print("killed", sum(r["status"] == "killed" for r in res), "of", len(res), flush=True)
