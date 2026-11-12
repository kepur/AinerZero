import subprocess, sys, os
from pathlib import Path

M = Path(sys.argv[1]).resolve()
assert str(M) != "/Users/mac/AinerWorkFlow/AinerZero", "refusing to mutate live repository"
assert not str(M).startswith("/Users/mac/AinerWorkFlow/AinerZero/"), "refusing to mutate inside live repository"

R = M / "reports/V9-S5-PHASE1/run_s5p1.py"
assert R.is_file(), f"missing {R}"

VENV_PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"

muts = {
    "M1_refuse_final_exact_only": (
        R,
        '    if str(name).startswith("s5p1-final"):\n',
        '    if str(name) == "s5p1-final":\n',
        ["tests/v9/experiments/test_s5_runner_native.py", "-k", "test_final_partition_cell_is_refused_before_any_cell"]
    ),
    "M2_sha_only_checks_first_file": (
        R,
        '                for fname, expected_sha in result.get("files", {}).items():\n',
        '                for fname, expected_sha in list(result.get("files", {}).items())[:1]:\n',
        ["tests/v9/experiments/test_s5_runner_native.py", "-k", "test_cell_output_sha_mismatch_fails_the_cell"]
    ),
    "M3_ignore_child_exit_code": (
        R,
        '            if p.exitcode != 0:\n',
        '            if False and p.exitcode != 0:\n',
        ["tests/v9/experiments/test_s5_runner_native.py", "-k", "timeout_exit_mutation or output_sha_mismatch"]
    ),
    "M4_preflight_skips_lab_teacher": (
        R,
        '    for group in REAL_TEACHERS.values():\n',
        '    for group in [REAL_TEACHERS["pool"]]:\n',
        ["tests/v9/experiments/test_s5_runner_native.py", "-k", "preflight or without_real_inputs"]
    ),
    "M5_preflight_skips_data_clip_check": (
        R,
        '        if not (d / "manifest.json").is_file() or not any(d.glob("world_*/clip_*.npy")):\n',
        '        if not (d / "manifest.json").is_file():\n',
        ["tests/v9/experiments/test_s5_runner_native.py", "-k", "preflight or without_real_inputs"]
    ),
}

env = dict(os.environ, PYTHONPATH=str(M / "src"))

def run_test(args):
    cmd = [VENV_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf", *args]
    r = subprocess.run(cmd, cwd=M, env=env, capture_output=True, text=True, timeout=120)
    failed = [l.split("::")[-1][:60] for l in r.stdout.splitlines() if l.startswith("FAILED")]
    summary = [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
    return r.returncode, failed, summary

print("=== RUNNING R3 ADVERSARIAL MUTATIONS ===", flush=True)
for name, (p, old_str, new_str, test_args) in muts.items():
    orig = p.read_text(encoding="utf-8")
    assert orig.count(old_str) == 1, f"Anchor count != 1 for {name}"
    
    # Run baseline on target test
    base_rc, base_f, base_s = run_test(test_args)
    
    # Mutate
    p.write_text(orig.replace(old_str, new_str, 1), encoding="utf-8")
    mut_rc, mut_f, mut_s = run_test(test_args)
    p.write_text(orig, encoding="utf-8")
    
    # If mut_rc == base_rc (tests passed or had same failure), it SURVIVED!
    status = "SURVIVED (漏网)" if (mut_rc == 0 or mut_rc == base_rc) else "KILLED (被拦住)"
    print(f"{name}: {status} | base_rc={base_rc} mut_rc={mut_rc} | {mut_f} | {mut_s}", flush=True)

