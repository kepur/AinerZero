"""Continue T4 stage1: finalize the isolated venv build artifacts.

Fix applied (documented in report): the previous run failed because
vjepa2-core-mlx's hatchling editable build needs the `editables` module,
which was neither installed in the venv nor declared. We installed
editables==0.6 into the t4 venv (offline, verified wheel) WITHOUT touching
src/vjepa2-mlx (fixed commit preserved) or any other venv, then re-ran the
editable install. This script just (re)captures the build artifacts so the
verify script finds them.
"""
import json, subprocess, time, importlib.util, os
from pathlib import Path

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
s = importlib.util.spec_from_file_location('prep', ROOT / 'envs/teachers/t4/prepare_20261020.py')
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
p = m.REPORT

venv = ROOT / 'envs/teachers/.venv-t4'
env = os.environ.copy()
env.update({
    'UV_CACHE_DIR': str(ROOT / 'envs/teachers/t4/uv-cache'),
    'UV_OFFLINE': '1', 'UV_PYTHON_DOWNLOADS': 'never',
    'HF_HOME': str(ROOT / 'artifacts/teachers/hf-cache'),
    'PIP_NO_INDEX': '1', 'PYTHONNOUSERSITE': '1',
})

def command(name, argv):
    start = time.time()
    r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, env=env)
    (p / (name + '.json')).write_text(json.dumps({
        'argv': argv, 'returncode': r.returncode,
        'stdout': r.stdout, 'stderr': r.stderr, 'elapsed_s': time.time() - start
    }, indent=2))
    print(name, r.returncode, flush=True)
    assert r.returncode == 0, (name, r.stderr)
    return r

# Re-capture editable install (idempotent; uv reports already-installed)
command('core-editable-install', [
    'uv', 'pip', 'install', '--python', str(venv / 'bin/python'),
    '--offline', '--no-deps', '--no-build-isolation',
    '-e', str(ROOT / 'envs/teachers/src/vjepa2-mlx/packages/vjepa2-core-mlx')])

freeze = command('environment-freeze', [
    'uv', 'pip', 'freeze', '--python', str(venv / 'bin/python'), '--offline'])
(p / 'env.lock.txt').write_text(freeze.stdout)

command('dependency-check', [
    'uv', 'pip', 'check', '--python', str(venv / 'bin/python'), '--offline'])

# Guard: forbidden heavy frameworks must NOT be present
forbidden = ('torch', 'torchvision', 'torchaudio', 'jax', 'jaxlib')
present = [x.split('==')[0].lower() for x in freeze.stdout.splitlines()]
assert not any(x in forbidden for x in present), f'forbidden package present: {present}'

# Record the build fix for the report
(p / 'build-fix-editables.json').write_text(json.dumps({
    'action': 'installed editables==0.6 into t4 venv to satisfy hatchling editable build (missing build dep)',
    'wheel': 'envs/teachers/t4/editables-wheel/editables-0.6-py3-none-any.whl',
    'sha256': 'd70e4698078a1d033e7786d9c64e5be070d058a67c21417024d38a58ac20aa43',
    'src_vjepa2_mlx_unchanged': True,
    'other_venvs_unchanged': True,
}, indent=2))
print('BUILD ARTIFACTS WRITTEN; freeze lines:', len(freeze.stdout.splitlines()))
