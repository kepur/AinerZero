"""Hermetic sitecustomize for child Python processes.

Installs function-level guards for fcntl.flock, fcntl.lockf, and sqlite3.connect
to prevent any child Python process from touching protected repository artifacts.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlparse

# Production guard root is hardcoded to the real repository root; never redirected away.
REAL_REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
LOCAL_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

HERMETIC_SENSITIVE_PATTERNS = [
    "artifacts/locks/**",
    "artifacts/locks",
    "artifacts/control.sqlite3*",
    "artifacts/v9/**/control.sqlite3*",
    "artifacts/v9/s1/**/*.sqlite3*",
    "artifacts/v9/e1/**",
]

HERMETIC_WHITELIST: dict[str, str] = {}

_hermetic_guards_active = True
_orig_flock = fcntl.flock
_orig_lockf = fcntl.lockf
_orig_sqlite_connect = sqlite3.connect


def guard_resolve_path(target) -> str | None:
    if target is None:
        return None
    if isinstance(target, int):
        try:
            buf = b" " * 1024
            res_buf = fcntl.fcntl(target, 50, buf)
            raw = res_buf.split(b"\x00", 1)[0].decode("utf-8", "replace")
            if raw:
                return os.path.realpath(raw)
        except OSError:
            pass
        try:
            proc_path = f"/proc/self/fd/{target}"
            if os.path.islink(proc_path):
                return os.path.realpath(proc_path)
        except Exception:
            pass
        return None
    if hasattr(target, "fileno"):
        try:
            return guard_resolve_path(target.fileno())
        except Exception:
            return None
    target_str = str(target)
    if not target_str or target_str == ":memory:":
        return None
    if target_str.startswith("file:"):
        target_str = urlparse(target_str).path
    try:
        return os.path.realpath(target_str)
    except Exception:
        return None


def check_hermetic_access(
    target,
    op_name: str,
    root: Path = REAL_REPO_ROOT,
    whitelist: dict | None = None,
) -> None:
    if not _hermetic_guards_active:
        return
    resolved = guard_resolve_path(target)
    if not resolved:
        return
    active_whitelist = HERMETIC_WHITELIST if whitelist is None else whitelist
    roots = [root]
    if root == REAL_REPO_ROOT and LOCAL_REPO_ROOT != REAL_REPO_ROOT and LOCAL_REPO_ROOT.is_dir():
        roots.append(LOCAL_REPO_ROOT)
    # Extra test root for isolated self-testing of child processes
    extra_test_root = os.environ.get("_HERMETIC_SUBPROCESS_TEST_ROOT")
    if extra_test_root:
        roots.append(Path(extra_test_root).resolve())

    for r in roots:
        art_dir = os.path.realpath(r / "artifacts")
        if resolved == art_dir or resolved.startswith(art_dir + os.sep):
            if resolved not in active_whitelist:
                raise RuntimeError(
                    f"Hermetic test guard violation: {op_name} called on protected artifact: {resolved}. "
                    f"Tests must use tmp_path or staged copies and must never touch real artifacts."
                )


def make_guarded_flock(root: Path = REAL_REPO_ROOT, orig_flock=_orig_flock, whitelist=None):
    def _flock(fd, operation):
        check_hermetic_access(fd, "fcntl.flock", root=root, whitelist=whitelist)
        return orig_flock(fd, operation)
    return _flock


def make_guarded_lockf(root: Path = REAL_REPO_ROOT, orig_lockf=_orig_lockf, whitelist=None):
    def _lockf(fd, cmd, *args, **kwargs):
        check_hermetic_access(fd, "fcntl.lockf", root=root, whitelist=whitelist)
        return orig_lockf(fd, cmd, *args, **kwargs)
    return _lockf


def make_guarded_connect(root: Path = REAL_REPO_ROOT, orig_connect=_orig_sqlite_connect, whitelist=None):
    def _connect(database, *args, **kwargs):
        check_hermetic_access(database, "sqlite3.connect", root=root, whitelist=whitelist)
        return orig_connect(database, *args, **kwargs)
    return _connect


guarded_flock = make_guarded_flock(REAL_REPO_ROOT)
guarded_lockf = make_guarded_lockf(REAL_REPO_ROOT)
guarded_connect = make_guarded_connect(REAL_REPO_ROOT)


def install_hermetic_function_guards() -> None:
    fcntl.flock = guarded_flock
    fcntl.lockf = guarded_lockf
    sqlite3.connect = guarded_connect
    if "sqlite3" in sys.modules:
        sys.modules["sqlite3"].connect = guarded_connect


# Auto-install when sitecustomize is loaded by Python
install_hermetic_function_guards()
