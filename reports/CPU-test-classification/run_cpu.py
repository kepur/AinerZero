"""A39 runner: pure-CPU pytest under shared lock + 16 GiB memory guard + MLX sentinel."""
import fcntl, json, os, subprocess, sys, threading, time
from pathlib import Path
ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero'); OUT = ROOT / 'reports/CPU-test-classification'
PY = ROOT / '.venv-ainerzero/bin/python'; RESERVE = 16 * 2**30
MODES = {
  'original-collection': ['--collect-only', '--noconftest', 'tests'],
  'native-collection-blocked': ['--collect-only', '--native-mlx', '-m', 'native_mlx', 'tests'],
  'default-collection': ['--collect-only', 'tests'],
  'default-cpu-run': ['tests'],
}
mode = sys.argv[1]; run = OUT / mode; run.mkdir(exist_ok=False)
def avail():
    out = subprocess.run(['vm_stat'], capture_output=True, text=True).stdout
    page = int(out.split('page size of ')[1].split()[0]); v = {}
    for line in out.splitlines()[1:]:
        k, _, n = line.partition(':'); v[k.strip()] = int(n.strip().rstrip('.') or 0)
    return page * (v['Pages free'] + v['Pages inactive'] + v['Pages speculative'] + v.get('Pages purgeable', 0))
lock = open(ROOT / 'artifacts/locks/m0-worker.lock', 'a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if held: never bypass
start_mem = avail(); assert start_mem > RESERVE, start_mem
env = dict(os.environ, PYTHONPATH=str(OUT / 'guard') + os.pathsep + str(ROOT / 'src'), A39_RUN_DIR=str(run),
           PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
cmd = [str(PY), '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--basetemp=' + str(run / 'tmp'),
       '--junitxml=' + str(run / 'pytest.xml')] + MODES[mode]
t0 = time.time(); low = {'min': start_mem, 'aborted': False}
with (run / 'pytest.log').open('w') as log:
    log.write('command: ' + json.dumps(cmd) + '\n'); log.flush()
    p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    while p.poll() is None:
        m = avail(); low['min'] = min(low['min'], m)
        if m < RESERVE:
            low['aborted'] = True; p.terminate(); p.wait(); break
        time.sleep(2)
res = {'mode': mode, 'command': cmd, 'returncode': p.returncode, 'seconds': round(time.time() - t0, 2),
       'lock': 'artifacts/locks/m0-worker.lock flock EX held by runner', 'mem_start_gib': round(start_mem / 2**30, 1),
       'mem_min_gib': round(low['min'] / 2**30, 1), 'reserve_gib': 16, 'memory_abort': low['aborted'],
       'mlx_import_attempts_file_exists': (run / 'mlx-import-attempts.jsonl').exists()}
procs = [json.loads(f.read_text()) for f in run.glob('process-*.json')]
res['processes'] = len(procs); res['processes_with_real_mlx'] = sum(1 for x in procs if x['real_mlx_modules'])
(run / 'command-result.json').write_text(json.dumps(res, indent=2) + '\n')
print(json.dumps(res, indent=1)); print((run / 'pytest.log').read_text()[-1500:])
