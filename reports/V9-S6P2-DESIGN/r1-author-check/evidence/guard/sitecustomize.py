"""Test-process guard: reject MLX imports and writes outside this delivery directory."""
import atexit
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import sys

DEST = Path(__file__).resolve().parents[2]
ROOT = DEST.parents[2]
blocked_imports = []
blocked_writes = []
sys.dont_write_bytecode = True


class NoMLX(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mlx" or fullname.startswith("mlx."):
            blocked_imports.append(fullname)
            raise ImportError("MLX prohibited in this author-side CPU check: " + fullname)


sys.meta_path.insert(0, NoMLX())


def check_write(path, event):
    if isinstance(path, int) or path is None:
        return
    resolved = Path(os.fsdecode(path)).resolve()
    if not resolved.is_relative_to(DEST):
        blocked_writes.append({"event": event, "path": str(resolved)})
        raise PermissionError("Author check write boundary: " + str(resolved))


def audit(event, args):
    if event == "open":
        path, mode, flags = args
        if (mode and any(c in mode for c in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            check_write(path, event)
    elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.chown", "os.utime", "os.truncate"}:
        check_write(args[0], event)
    elif event in {"os.rename", "os.link", "os.symlink"}:
        check_write(args[0], event)
        check_write(args[1], event)


sys.addaudithook(audit)


@atexit.register
def finish():
    local = {}
    for name, mod in list(sys.modules.items()):
        raw = getattr(mod, "__file__", None)
        if raw:
            p = Path(raw).resolve()
            if p.is_relative_to(ROOT) and p.suffix == ".py" and not p.is_relative_to(ROOT / ".venv"):
                local[name] = {"path": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    result = {"guard_active": True, "blocked_mlx_imports": blocked_imports,
              "loaded_mlx_modules": [n for n in sys.modules if n == "mlx" or n.startswith("mlx.")],
              "blocked_writes": blocked_writes, "local_loaded_modules": local,
              "numpy_version": getattr(sys.modules.get("numpy"), "__version__", None),
              "python": sys.version}
    (DEST / "evidence" / "pytest-guard.json").write_text(json.dumps(result, indent=2) + "\n")
