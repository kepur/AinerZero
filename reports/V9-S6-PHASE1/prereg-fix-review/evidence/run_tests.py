"""Independent P262 driver: tests only inside reviewed archive/copies, no MLX."""
import importlib.abc
import json
import os
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parents[1]
ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else OUT / 'snapshot'
LABEL = sys.argv[2] if len(sys.argv) > 2 else 'baseline'
EXTRA = sys.argv[3:]
assert ROOT.is_relative_to(OUT)
sys.dont_write_bytecode = True
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
os.environ['TMPDIR'] = str(OUT / 'tmp' / LABEL)
Path(os.environ['TMPDIR']).mkdir(parents=True, exist_ok=True)


class DenyMLX(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mlx' or fullname.startswith('mlx.'):
            raise RuntimeError('FORBIDDEN_MLX_IMPORT: ' + fullname)


sys.meta_path.insert(0, DenyMLX())


def audit(event, args):
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)) and flags & (1 | 2 | 64 | 512 | 1024):
            if not Path(path).resolve().is_relative_to(OUT):
                raise RuntimeError('WRITE_OUTSIDE_REVIEW: ' + str(path))
    if event == 'subprocess.Popen':
        _, argv, cwd, _ = args
        if argv and Path(str(argv[0])).name == 'git' and any(x in argv for x in ('init', 'add', 'commit')):
            base = Path(argv[argv.index('-C') + 1]) if '-C' in argv else Path(cwd or Path.cwd())
            assert base.resolve().is_relative_to(OUT), 'git mutation outside synthetic fixture'


sys.addaudithook(audit)
sys.path.insert(0, str(ROOT / 'src'))
import pytest

args = ['-q', '-c', '/dev/null', '--rootdir', str(ROOT), '--confcutdir', str(ROOT),
        '--basetemp', str(OUT / 'tmp' / LABEL / 'pytest'), '-p', 'no:cacheprovider', '-p', 'no:logging',
        str(ROOT / 'tests/v9/experiments/test_s6_prereg.py')]
independent = ROOT / 'tests/v9/experiments/test_p262_independent.py'
if independent.exists():
    args.append(str(independent))
args.extend(EXTRA)
print('PYTEST_ARGV', json.dumps(args), flush=True)
rc = pytest.main(args)
print('MLX_IN_SYS_MODULES', any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules), flush=True)
raise SystemExit(rc)
