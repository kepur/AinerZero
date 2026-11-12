import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]).resolve()
assert str(M) != "/Users/mac/AinerWorkFlow/AinerZero", "refusing to mutate the live repository"
R = M / "reports/V9-S5-PHASE1/run_s5p1.py"; P = M / "reports/V9-S5-PHASE1/plan_s5p1.py"
T = ["tests/v9/experiments/test_s5_runner_plan.py", "tests/v9/experiments/test_s5_runner_native.py", "tests/v9/experiments/test_s5_evaluate.py"]
muts = {
 "R1_force_cpu": (R, "    import mlx.core as mx\n\n    from ainerzero.v9.experiments.s5.evaluate import evaluate", "    import mlx.core as mx\n    mx.set_default_device(mx.cpu)\n\n    from ainerzero.v9.experiments.s5.evaluate import evaluate"),
 "R2_no_terminate": (R, "            if p.is_alive():\n                p.terminate()", "            if False and p.is_alive():\n                p.terminate()"),
 "R3_ignore_stage_left": (R, "            timeout_s = min(cell_limit, remaining_stage)", "            timeout_s = cell_limit"),
 "R4_smoke_consumes_dev": (R, "    if args.stage != \"smoke\":", "    if True:"),
 "R5_skip_tune_sha": (R, "        _verify_tune(Path(args.tune_file), args.tune_sha)", "        pass"),
 "R6_arm_order_reversed": (P, 'ARM_ORDER = ("A1", "A2", "A3")', 'ARM_ORDER = ("A3", "A2", "A1")'),
 "R7_no_refuse_final": (R, "    if str(name).startswith(\"s5p1-final\"):\n        raise", "    if False:\n        raise"),
 "R8_no_output_sha_check": (R, "                    if got_sha != expected_sha:", "                    if False and got_sha != expected_sha:"),
 "M1_refuse_final_exact_only": (R, '    if str(name).startswith("s5p1-final"):', '    if str(name) == "s5p1-final":'),
 "M2_sha_first_file_only": (R, '                for fname, expected_sha in result.get("files", {}).items():', '                for fname, expected_sha in list(result.get("files", {}).items())[:1]:'),
 "M3_ignore_child_exitcode": (R, "            if p.exitcode != 0:", "            if False and p.exitcode != 0:"),
 "M4_preflight_skips_lab": (R, "    for group in REAL_TEACHERS.values():", '    for group in [REAL_TEACHERS["pool"]]:'),
 "M5_preflight_manifest_only": (R, '        if not (d / "manifest.json").is_file() or not any(d.glob("world_*/clip_*.npy")):', '        if not (d / "manifest.json").is_file():'),
 "P1_teachers_unpartitioned": (R, '"pool": {"vjepa": TEACHERS / "vjepa" / "s5p1-pool", "da2": TEACHERS / "da2" / "s5p1-pool"},', '"pool": {"vjepa": TEACHERS / "vjepa", "da2": TEACHERS / "da2"},'),
 "P2_no_preflight": (R, "        _preflight_real_inputs()\n        GD.consume_dev_use(", "        GD.consume_dev_use("),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
def run():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-x", "-rf", *T], cwd=M, env=env, capture_output=True, text=True, timeout=3000)
    return r.returncode, [l.split("::")[-1][:55] for l in r.stdout.splitlines() if l.startswith("FAILED")], [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
print("BASELINE", *run(), flush=True)
for name, (p, a, b) in muts.items():
    orig = p.read_text(); n = orig.count(a)
    if n != 1: print(name, "ANCHOR", n, flush=True); continue
    p.write_text(orig.replace(a, b)); rc, f, t = run(); p.write_text(orig)
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f[:3]} {t}", flush=True)
