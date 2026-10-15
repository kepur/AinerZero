"""A40 Independent Review Runner:
Executes independent verification of A39 test classification under shared lock + 16 GiB guard + MLX sentinel.
"""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
OUT = ROOT / 'reports/CPU-test-classification-review'
GUARD = OUT / 'guard'
PY = ROOT / '.venv-ainerzero/bin/python'
RESERVE = 16 * 2**30

RUNS_DIR = OUT / 'runs'
RUNS_DIR.mkdir(parents=True, exist_ok=True)

MODES = {
    'collection-sentinel': ['--collect-only', 'tests'],
    'test-cpu-collection': ['tests/test_cpu_collection.py'],
    'onestep-identity': ['tests/test_action_preservation_onestep.py'],
    'smoke-budget-failclosed': ['tests/test_smoke.py::test_exhausted_shared_daily_budget_blocks_before_loading_backend'],
    'gridlab-cpu': ['tests/test_gridlab_s07_r2.py'],
    'native-blocked-audit': ['--collect-only', '--native-mlx', '-m', 'native_mlx', 'tests'],
}

EXPECTED_RC = {
    'collection-sentinel': 0,
    'test-cpu-collection': 0,
    'onestep-identity': 0,
    'smoke-budget-failclosed': 0,
    'gridlab-cpu': 0,
    'native-blocked-audit': 2,  # Expected 9 collection errors under sentinel
}


def avail_memory():
    out = subprocess.run(['vm_stat'], capture_output=True, text=True).stdout
    page = int(out.split('page size of ')[1].split()[0])
    v = {}
    for line in out.splitlines()[1:]:
        k, _, n = line.partition(':')
        v[k.strip()] = int(n.strip().rstrip('.') or 0)
    return page * (v['Pages free'] + v['Pages inactive'] + v['Pages speculative'] + v.get('Pages purgeable', 0))


def run_mode(mode_name, args):
    run_dir = RUNS_DIR / mode_name
    run_dir.mkdir(parents=True, exist_ok=True)

    start_mem = avail_memory()
    assert start_mem > RESERVE, f"Memory {start_mem / 2**30:.1f} GiB below 16 GiB reserve"

    env = dict(
        os.environ,
        PYTHONPATH=str(GUARD) + os.pathsep + str(ROOT / 'src'),
        A40_RUN_DIR=str(run_dir),
        PYTHONDONTWRITEBYTECODE='1',
        PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
    )
    cmd = [
        str(PY), '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
        '--basetemp=' + str(run_dir / 'tmp'),
        '--junitxml=' + str(run_dir / 'pytest.xml'),
    ] + args

    t0 = time.time()
    low = {'min': start_mem, 'aborted': False}
    with (run_dir / 'pytest.log').open('w') as log:
        log.write('command: ' + json.dumps(cmd) + '\n')
        log.flush()
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        while p.poll() is None:
            m = avail_memory()
            low['min'] = min(low['min'], m)
            if m < RESERVE:
                low['aborted'] = True
                p.terminate()
                p.wait()
                break
            time.sleep(1)

    expected_rc = EXPECTED_RC[mode_name]

    attempts_file = run_dir / 'mlx-import-attempts.jsonl'
    procs = [json.loads(f.read_text()) for f in run_dir.glob('process-*.json')]
    
    # Parse xml if exists
    xml_path = run_dir / 'pytest.xml'
    xml_stats = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    if xml_path.exists():
        import xml.etree.ElementTree as ET
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            suite = root if root.tag == 'testsuite' else root.find('testsuite')
            if suite is not None:
                xml_stats['tests'] = int(suite.attrib.get('tests', 0))
                xml_stats['failures'] = int(suite.attrib.get('failures', 0))
                xml_stats['errors'] = int(suite.attrib.get('errors', 0))
                xml_stats['skipped'] = int(suite.attrib.get('skipped', 0))
        except Exception as e:
            xml_stats['parse_error'] = str(e)

    res = {
        'mode': mode_name,
        'command': cmd,
        'returncode': p.returncode,
        'expected_returncode': expected_rc,
        'seconds': round(time.time() - t0, 2),
        'mem_start_gib': round(start_mem / 2**30, 1),
        'mem_min_gib': round(low['min'] / 2**30, 1),
        'reserve_gib': 16,
        'memory_abort': low['aborted'],
        'mlx_import_attempts_file_exists': attempts_file.exists(),
        'mlx_import_attempts_count': len(attempts_file.read_text().splitlines()) if attempts_file.exists() else 0,
        'processes_count': len(procs),
        'processes_with_real_mlx': sum(1 for x in procs if x.get('real_mlx_modules')),
        'xml_stats': xml_stats,
    }
    (run_dir / 'command-result.json').write_text(json.dumps(res, indent=2) + '\n')
    print(f"[{mode_name}] returncode={p.returncode} in {res['seconds']}s, procs={res['processes_count']}, real_mlx_procs={res['processes_with_real_mlx']}, xml={xml_stats}")
    return res


def main():
    lock_path = ROOT / 'artifacts/locks/m0-worker.lock'
    lock_file = open(lock_path, 'a')
    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("Locked artifacts/locks/m0-worker.lock exclusively.")

    all_results = {}
    try:
        modes_to_run = sys.argv[1:] if len(sys.argv) > 1 else list(MODES.keys())
        for m in modes_to_run:
            all_results[m] = run_mode(m, MODES[m])
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
        print("Unlocked artifacts/locks/m0-worker.lock.")

    (OUT / 'all-runs-summary.json').write_text(json.dumps(all_results, indent=2) + '\n')
    print("Completed all verification runs successfully.")


if __name__ == '__main__':
    main()
