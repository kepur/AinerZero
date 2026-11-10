"""复核者 claude-s4impl-rev2-1110 的 MLX 部分（a767ac7 的隔离副本）：测试计数、代码约束违例、learned_mlx 与运行器变异。
每项复制 src/ainerzero、tests、pyproject.toml、reports/V9-S4-PHASE1（不含 mutants）到新临时目录，改一处（恰好一次、过语法检查），
PYTHONPATH 指向副本，--native-mlx 跑对应测试。用法：mut_mlx.py <副本根> <输出目录> <阶段...>，阶段 = counts cc lm ru"""
import ast, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
BASE, OUT = Path(sys.argv[1]), Path(sys.argv[2]); PHASES = sys.argv[3:]
HERE = Path(__file__).resolve().parent
S4 = "src/ainerzero/v9/experiments/s4/"
LM, RU, VR = S4 + "learned_mlx.py", "reports/V9-S4-PHASE1/run_s4p1.py", "reports/V9-S4-PHASE1/verify_replay.py"
T = "tests/v9/experiments/"
CPU_T = [T + "test_s4_world.py", T + "test_s4_filter_metrics.py", T + "test_s4_analysis.py", T + "test_s4_verify_labels.py"]
LM_T, RU_T = [T + "test_s4_learned_mlx.py"], [T + "test_s4_verify_labels.py", T + "test_s4p1_runner_native.py"]
CC_T = [T + "test_s4_learned_mlx.py::test_model_code_does_not_use_the_world_physics", T + "test_s4_learned_mlx.py::test_forward_path_has_no_contact_rule"]
V1 = ("        v_next = v + o[..., 2:4]\n",
      "        v_next = v + o[..., 2:4]\n"
      "        dp_, dv_, dist_, mask_ = pair_geometry(p, v)\n"
      "        n_ = dp_ / dist_\n"
      "        hit_ = mx.sigmoid((2 * RADIUS - dist_) * 200.0) * mask_\n"
      "        v_next = v_next + (hit_ * (dv_ * n_).sum(-1, keepdims=True) * n_).sum(2)\n")
V2 = ("        v_next = v + o[..., 2:4]\n",
      "        v_next = v + o[..., 2:4]\n"
      "        dp_, dv_, dist_, mask_ = pair_geometry(p, v)\n"
      "        n_ = dp_ / dist_\n"
      "        hard_ = mx.clip((2 * RADIUS - dist_) * 1e6, 0.0, 1.0) * mask_\n"
      "        approach_ = mx.clip(-(dv_ * n_).sum(-1, keepdims=True) * 1e6, 0.0, 1.0)\n"
      "        v_next = v_next + (hard_ * approach_ * (dv_ * n_).sum(-1, keepdims=True) * n_).sum(2)\n")
CC = [("cc_smooth_elastic_exchange", LM, *V1), ("cc_hard_contact_via_clip", LM, *V2)]

def _gate(v):
    old, new = v
    body = new[len(old):]
    return old, old + "        if self.interact:\n" + "".join("    " + ln + "\n" for ln in body.splitlines())
CCG = [("ccg_smooth_elastic_interacting_arms", LM, *_gate(V1)), ("ccg_hard_contact_interacting_arms", LM, *_gate(V2))]
LMM = [
    ("lm_sigma_mean_not_loaded", LM, "        model.load_weights(list(tree_flatten(mean_model.parameters())), strict=False)\n", ""),
    ("lm_sigma_var1_frozen", LM, "        model.var1.unfreeze()\n", ""),
    ("lm_bucket_unweighted", LM, "j = int(rng.choice(len(ns), p=w))", "j = int(rng.choice(len(ns)))"),
    ("lm_clip_result_unused", LM, "        grads, norm = optim.clip_grad_norm(grads, max_norm=CLIP)\n", "        _, norm = optim.clip_grad_norm(grads, max_norm=CLIP)\n"),
    ("lm_time_limit_doubled", LM, "time.monotonic() - started > time_limit:", "time.monotonic() - started > 2 * time_limit:"),
    ("lm_batch_rng_seed_fixed", LM, "    rng = np.random.default_rng(seed)\n    log:", "    rng = np.random.default_rng(0)\n    log:"),
    ("lm_init_seed_fixed", LM, "    mx.random.seed(seed)\n", "    mx.random.seed(0)\n"),
    ("lm_mean_arm_unchecked", LM, 'if mean_model is None or mean_model.arm != "L-int":', "if mean_model is None:"),
    ("lm_contact_share_halved", LM, "k, q = int(round(batch * coll_share)), int(round(batch * near_share))", "k, q = int(round(batch * coll_share / 2)), int(round(batch * near_share))"),
    ("lm_keep_one_disk", LM, "    if keep.sum() < 2:\n        keep[:2] = True\n", "    if keep.sum() < 1:\n        keep[:1] = True\n"),
]
RES_BLOCK = ('            reserve = float(pre["budget"]["eval_reserve_s"])\n'
             '            if deadline.left() < reserve:\n'
             '                raise GD.GuardError(f"only {deadline.left():.0f} s left, the evaluation needs {reserve:.0f} s: the final read is not spent")\n'
             '            # The one read of the registered partition starts here; nothing above generates it.\n'
             '            GD.consume_final_read(lock, FINAL_MARKER, a.approval, pre["final_approval_line"], prereg_sha256=pre_sha, expected_lock=LOCK)\n')
RES_SWAP = ('            reserve = float(pre["budget"]["eval_reserve_s"])\n'
            '            GD.consume_final_read(lock, FINAL_MARKER, a.approval, pre["final_approval_line"], prereg_sha256=pre_sha, expected_lock=LOCK)\n'
            '            if deadline.left() < reserve:\n'
            '                raise GD.GuardError(f"only {deadline.left():.0f} s left, the evaluation needs {reserve:.0f} s: the final read is not spent")\n')
RUM = [
    ("ru_generate_before_marker", RU, '        registered = a.stage == "final"\n        if registered:\n',
     '        registered = a.stage == "final"\n        _early = [W.generate_episode(ns["eval"], w, n, allow_registered=registered) for kind, w, n in A.eval_world_ids(cfg["sizes"])]\n        if registered:\n'),
    ("ru_marker_before_reserve", RU, RES_BLOCK, RES_SWAP),
    ("ru_reserve_tenth", RU, "            if deadline.left() < reserve:", "            if deadline.left() < reserve / 10:"),
    ("ru_student_ok_true", RU, 'student_ok=st["passed"]', "student_ok=True"),
    ("ru_n_main_from_records", RU, 'n_main=cfg["sizes"][0]', "n_main=len(main_r)"),
    ("ru_late_modules_skipped", RU, ' + GD.check_loaded_modules(REPO, pre["manifest"])\n            R["late_violations"]', '\n            R["late_violations"]'),
    ("ru_marker_exists_unchecked", RU, '        if a.stage == "final" and FINAL_MARKER.exists():\n', "        if False:\n"),
    ("ru_final_accepts_cli_steps", RU, "    if a.steps is not None or a.batch is not None or a.use_id is not None:\n", "    if a.use_id is not None:\n"),
    ("ru_isolated_unchecked", RU, "    if not sys.flags.isolated:\n", "    if False:\n"),
    ("ru_fresh_pycache_unchecked", RU, "    GD.require_fresh_pycache(STARTED)\n", ""),
    ("ru_versions_unchecked", RU, '    if versions != pre["third_party"]:\n', "    if False:\n"),
    ("ru_git_dirty_unchecked", RU, "    if dirty:\n        raise GD.GuardError(\"frozen files are not committed", "    if False:\n        raise GD.GuardError(\"frozen files are not committed"),
    ("ru_partial_not_hashed", RU, 'for f in (worlds, out / "worlds.partial.jsonl", labels, replay)', "for f in (worlds, labels, replay)"),
    ("vr_passes_with_nothing_checked", VR, '"passed": checked > 0 and not bad', '"passed": not bad'),
]
def copy_tree(dst, src):
    shutil.copytree(src / "src/ainerzero", dst / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(src / "tests", dst / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(src / "pyproject.toml", dst / "pyproject.toml")
    shutil.copytree(src / "reports/V9-S4-PHASE1", dst / "reports/V9-S4-PHASE1", ignore=shutil.ignore_patterns("__pycache__", "mutants"))
def env_for(dst):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}; env["PYTHONPATH"] = str(dst / "src"); env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env
def pytest(dst, files, x=True, timeout=1800):
    r = subprocess.run([sys.executable, str(HERE / "pyt.py"), str(dst), "-q", *(["-x"] if x else []), "-p", "no:cacheprovider", "--native-mlx", *files],
                       env=env_for(dst), capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout
def run_mutants(name_tag, muts, tests, tmp, base):
    res = []
    for name, path, old, new in muts:
        d = Path(tmp) / name; copy_tree(d, base); f = d / path; t = f.read_text()
        if t.count(old) != 1:
            res.append({"name": name, "status": "stale", "count": t.count(old)}); print(name, "STALE", flush=True); shutil.rmtree(d); continue
        t = t.replace(old, new); ast.parse(t); f.write_text(t)
        t0 = time.monotonic(); rc, out = pytest(d, tests, x=(name_tag != "cc"))
        failed = re.findall(r"FAILED (\S+)", out)
        res.append({"name": name, "file": path, "status": "killed" if rc else "SURVIVED", "failed": failed[:8], "summary": out.strip().splitlines()[-1] if out.strip() else "", "seconds": round(time.monotonic() - t0, 1)})
        print(name, res[-1]["status"], failed[:3], res[-1]["summary"], flush=True); shutil.rmtree(d)
    (OUT / f"mut_mlx_{name_tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(name_tag, "killed", sum(r["status"] == "killed" for r in res), "of", len(res), flush=True)
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="s4impl-mlx-") as tmp:
    base = Path(tmp) / "base"; copy_tree(base, BASE)
    where = subprocess.run([sys.executable, "-c", "import ainerzero.v9.experiments.s4.learned_mlx as m; print(m.__file__)"], cwd=base, env=env_for(base), capture_output=True, text=True).stdout.strip()
    assert where.startswith(str(base)), where
    print("copy imports", where, flush=True)
    if "counts" in PHASES:
        counts = {}
        for label, files in (("cpu_default", None), ("mlx_learned", LM_T), ("runner", [T + "test_s4p1_runner_native.py"]), ("all_s4_native", CPU_T + LM_T + [T + "test_s4p1_runner_native.py"])):
            t0 = time.monotonic()
            if files is None:
                r = subprocess.run([sys.executable, str(HERE / "pyt.py"), str(base), "-q", "-p", "no:cacheprovider", *CPU_T, T + "test_s4_learned_mlx.py", T + "test_s4p1_runner_native.py"], env=env_for(base), capture_output=True, text=True, timeout=1800)
                rc, out = r.returncode, r.stdout
            else:
                rc, out = pytest(base, files, x=False)
            counts[label] = {"rc": rc, "summary": out.strip().splitlines()[-1] if out.strip() else "", "seconds": round(time.monotonic() - t0, 1), "failed": re.findall(r"FAILED (\S+)", out)[:10]}
            print(label, counts[label], flush=True)
        (OUT / "counts.json").write_text(json.dumps(counts, ensure_ascii=False, indent=1))
    if "cc" in PHASES:
        run_mutants("cc", CC, CC_T, tmp, base)
        run_mutants("cc_full", [(n + "_fullfile", *rest) for n, *rest in CC], LM_T, tmp, base)
    if "ccg" in PHASES:
        run_mutants("ccg_two_tests", CCG, CC_T, tmp, base)
        run_mutants("ccg_fullfile", [(n + "_fullfile", *rest) for n, *rest in CCG], LM_T, tmp, base)
    if "lm" in PHASES:
        run_mutants("lm", LMM, LM_T, tmp, base)
    if "ru" in PHASES:
        run_mutants("ru", RUM, RU_T, tmp, base)
print("done", flush=True)
