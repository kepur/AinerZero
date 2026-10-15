"""A40 independent review sentinel: block real MLX and audit subprocess execution."""
import atexit
import builtins
import io
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
OUT = ROOT / 'reports/CPU-test-classification-review'
RUN = Path(os.environ.get('A40_RUN_DIR', str(OUT / 'runs/default')))
RUN.mkdir(parents=True, exist_ok=True)
GUARD = OUT / 'guard'

_open = builtins.open
_io_open = io.open
_mkdir = Path.mkdir
_popen = subprocess.Popen

OUTPUT_FILES = (
    'artifacts/reports/E27-onestep/source-full-chain/probe-log.json',
    'artifacts/reports/E25-weighted/source-full-chain/probe-log.json',
    'artifacts/reports/E25-weighted/source-compat/duty-migration.json',
)
MAPPING = {str(ROOT / rel): RUN / 'redirected' / rel for rel in OUTPUT_FILES}
for target in MAPPING.values():
    target.parent.mkdir(parents=True, exist_ok=True)


def _path(value):
    if isinstance(value, (str, bytes, os.PathLike)):
        return Path(os.fsdecode(value)).absolute()
    return None


def _mapped(value):
    path = _path(value)
    return MAPPING.get(str(path), value)


def _mapped_open(file, *args, **kwargs):
    return _open(_mapped(file), *args, **kwargs)


def _mapped_io_open(file, *args, **kwargs):
    return _io_open(_mapped(file), *args, **kwargs)


def _mapped_mkdir(self, *args, **kwargs):
    if self.absolute() == ROOT / 'artifacts/reports/E25-weighted/source-compat':
        self = RUN / 'redirected/artifacts/reports/E25-weighted/source-compat'
    return _mkdir(self, *args, **kwargs)


builtins.open = _mapped_open
io.open = _mapped_io_open
Path.mkdir = _mapped_mkdir


class BlockRealMLX:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mlx' or fullname.startswith('mlx.'):
            with _open(RUN / 'mlx-import-attempts.jsonl', 'a') as handle:
                handle.write(json.dumps({'pid': os.getpid(), 'module': fullname}) + '\n')
            raise RuntimeError('A40 review CPU-only: real MLX import blocked: ' + fullname)


sys.meta_path.insert(0, BlockRealMLX())


def _guarded_popen(*args, **kwargs):
    env = dict(kwargs.get('env') or os.environ)
    old_path = env.get('PYTHONPATH', '')
    if str(GUARD) not in old_path.split(os.pathsep):
        env['PYTHONPATH'] = str(GUARD) + (os.pathsep + old_path if old_path else '')
    env['A40_RUN_DIR'] = str(RUN)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    kwargs['env'] = env
    return _popen(*args, **kwargs)


subprocess.Popen = _guarded_popen


def _audit(event, args):
    if event != 'open':
        return
    path = _path(args[0])
    if path is None or not path.is_relative_to(ROOT) or path.is_relative_to(OUT):
        return
    mode = args[1]
    flags = args[2]
    writing = (isinstance(mode, str) and any(char in mode for char in 'wax+'))
    writing = writing or (isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
    if writing:
        raise RuntimeError('A40 review CPU-only: write outside task review artifacts blocked: ' + str(path))


sys.addaudithook(_audit)


@atexit.register
def _finish():
    loaded = {name: getattr(module, '__file__', None) for name, module in sys.modules.items()
              if module is not None and (name == 'mlx' or name.startswith('mlx.'))}
    real = {name: value for name, value in loaded.items() if value is not None}
    with _open(RUN / f'process-{os.getpid()}.json', 'w') as handle:
        json.dump({'pid': os.getpid(), 'argv': sys.argv, 'mlx_modules': loaded,
                   'real_mlx_modules': real, 'guard_active': True}, handle, indent=2)
