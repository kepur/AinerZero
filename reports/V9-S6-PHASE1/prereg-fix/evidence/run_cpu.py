"""Run only P261 CPU tests with an unconditional MLX import blocker."""
import importlib.abc
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

class NoMLX(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mlx' or fullname.startswith('mlx.'):
            raise RuntimeError('P261 FORBIDDEN MLX IMPORT: ' + fullname)

sys.meta_path.insert(0, NoMLX())
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / 'src'))
import pytest
args = [str(root / 'tests/v9/experiments/test_s6_prereg.py'), '-c', '/dev/null',
        '--rootdir', str(root), '--confcutdir', str(root / 'tests/v9/experiments'),
        '-p', 'no:cacheprovider', '-v', *sys.argv[2:]]
print('ARGV', json.dumps([sys.executable, *args]), flush=True)
rc = pytest.main(args)
print('MLX_IN_SYS_MODULES', any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules), flush=True)
raise SystemExit(rc)
