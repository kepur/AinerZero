import subprocess, sys, os
from pathlib import Path

M = Path(sys.argv[1]).resolve()
assert str(M) != "/Users/mac/AinerWorkFlow/AinerZero"
assert not str(M).startswith("/Users/mac/AinerWorkFlow/AinerZero/")

VENV_PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"
env = dict(os.environ, PYTHONPATH=str(M / "src"))

# Append proposed tests to tests/v9/experiments/test_s5_runner_native.py
test_file = M / "tests/v9/experiments/test_s5_runner_native.py"
orig_test_text = test_file.read_text(encoding="utf-8")

# Also repair test_final_partition_cell_is_refused_before_any_cell by writing inputs
repaired_final_test = '''
def test_final_partition_cell_is_refused_before_any_cell(tmp_path: Path):
    """A planned cell on s5p1-final must stop the stage before any cell starts or any data is touched."""
    root = _make_root(tmp_path)
    _write_inputs(root, partitioned_teachers=True)
    _mutate_file(root, f"{HERE}/plan_s5p1.py",
                 'n_clips=pool_clips, epochs=distill_epochs, partition="s5p1-pool",',
                 'n_clips=pool_clips, epochs=distill_epochs, partition="s5p1-final",')
    ran = _run(root, "--stage", "probe", "--use-id", "p-final", "--report", "reports/out.json")
    assert ran.returncode != 0, ran.stdout[-2000:] + ran.stderr[-2000:]
    events = _events(root)
    assert not [e for e in events if e["event"] == "cell_start"], events
    errors = " ".join(str(e.get("error", "")) for e in events)
    assert "final partition" in errors, events
    assert not [p for p in root.rglob("*") if "s5p1-final" in p.name], "no final data may be created"
'''

proposed_tests = '''

# --- PROPOSED TESTS BY P238 REVIEW ---
def test_refuse_final_rejects_all_final_variants():
    import importlib.util
    spec = importlib.util.spec_from_file_location("r", LIVE / HERE / "run_s5p1.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    import pytest
    from ainerzero.v9.experiments.s3 import run_guard as GD
    for part in ("s5p1-final", "s5p1-final-shift", "s5p1-final-eval"):
        with pytest.raises(GD.GuardError, match="must not touch a final partition"):
            m._refuse_final(part)


def test_preflight_fails_when_lab_teacher_unpartitioned(tmp_path: Path):
    wrong_lab = _make_root(tmp_path / "wrong_lab")
    _write_inputs(wrong_lab, partitioned_teachers=True)
    import shutil
    shutil.rmtree(wrong_lab / "artifacts/v9/s5/teachers/vjepa/s5p1-lab")
    r = _preflight(wrong_lab)
    assert r.returncode != 0 and "missing real inputs" in r.stderr and "s5p1-lab" in r.stderr


def test_preflight_fails_when_data_partition_has_manifest_but_no_clips(tmp_path: Path):
    empty_data = _make_root(tmp_path / "empty_data")
    _write_inputs(empty_data, partitioned_teachers=True)
    import shutil
    for p in (empty_data / "artifacts/v9/s5/data/s5p1-pool").glob("world_*"):
        shutil.rmtree(p)
    r = _preflight(empty_data)
    assert r.returncode != 0 and "missing real inputs" in r.stderr and "s5p1-pool" in r.stderr

'''

# Replace final test with repaired version and add proposed tests
patched_test_text = orig_test_text.replace(
    'def test_final_partition_cell_is_refused_before_any_cell(tmp_path: Path):\n    """A planned cell on s5p1-final must stop the stage before any cell starts or any data is touched."""\n    root = _make_root(tmp_path)\n    _mutate_file(root, f"{HERE}/plan_s5p1.py",\n                 \'n_clips=pool_clips, epochs=distill_epochs, partition="s5p1-pool",\',\n                 \'n_clips=pool_clips, epochs=distill_epochs, partition="s5p1-final",\')\n    ran = _run(root, "--stage", "probe", "--use-id", "p-final", "--report", "reports/out.json")\n    assert ran.returncode != 0, ran.stdout[-2000:] + ran.stderr[-2000:]\n    events = _events(root)\n    assert not [e for e in events if e["event"] == "cell_start"], events\n    errors = " ".join(str(e.get("error", "")) for e in events)\n    assert "final partition" in errors, events\n    assert not [p for p in root.rglob("*") if "s5p1-final" in p.name], "no final data may be created"',
    repaired_final_test.strip()
) + proposed_tests

test_file.write_text(patched_test_text, encoding="utf-8")

R = M / "reports/V9-S5-PHASE1/run_s5p1.py"

def run_test(args):
    cmd = [VENV_PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf", *args]
    r = subprocess.run(cmd, cwd=M, env=env, capture_output=True, text=True, timeout=120)
    failed = [l.split("::")[-1][:60] for l in r.stdout.splitlines() if l.startswith("FAILED")]
    summary = [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
    return r.returncode, failed, summary

print("=== VERIFYING PROPOSED TESTS KILL MUTANTS ===", flush=True)

# 1. Verify M1 is KILLED by test_refuse_final_rejects_all_final_variants
orig_R = R.read_text(encoding="utf-8")
R.write_text(orig_R.replace('    if str(name).startswith("s5p1-final"):\n', '    if str(name) == "s5p1-final":\n', 1), encoding="utf-8")
rc, f, s = run_test(["tests/v9/experiments/test_s5_runner_native.py", "-k", "test_refuse_final_rejects_all_final_variants"])
print(f"M1 with proposed test: {'KILLED' if rc != 0 else 'SURVIVED'} | rc={rc} | {f} | {s}")
R.write_text(orig_R, encoding="utf-8")

# 2. Verify M4 is KILLED by test_preflight_fails_when_lab_teacher_unpartitioned
R.write_text(orig_R.replace('    for group in REAL_TEACHERS.values():\n', '    for group in [REAL_TEACHERS["pool"]]:\n', 1), encoding="utf-8")
rc, f, s = run_test(["tests/v9/experiments/test_s5_runner_native.py", "-k", "test_preflight_fails_when_lab_teacher_unpartitioned"])
print(f"M4 with proposed test: {'KILLED' if rc != 0 else 'SURVIVED'} | rc={rc} | {f} | {s}")
R.write_text(orig_R, encoding="utf-8")

# 3. Verify M5 is KILLED by test_preflight_fails_when_data_partition_has_manifest_but_no_clips
R.write_text(orig_R.replace('        if not (d / "manifest.json").is_file() or not any(d.glob("world_*/clip_*.npy")):\n', '        if not (d / "manifest.json").is_file():\n', 1), encoding="utf-8")
rc, f, s = run_test(["tests/v9/experiments/test_s5_runner_native.py", "-k", "test_preflight_fails_when_data_partition_has_manifest_but_no_clips"])
print(f"M5 with proposed test: {'KILLED' if rc != 0 else 'SURVIVED'} | rc={rc} | {f} | {s}")
R.write_text(orig_R, encoding="utf-8")

# Revert test file
test_file.write_text(orig_test_text, encoding="utf-8")
print("=== VERIFICATION COMPLETE ===", flush=True)
