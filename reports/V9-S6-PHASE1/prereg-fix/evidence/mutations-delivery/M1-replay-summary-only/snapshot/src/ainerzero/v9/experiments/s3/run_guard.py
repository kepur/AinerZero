"""Guards for registered S3 runs from phase 2 on. Standard library only.

Implements the fixes demanded by the non-author reviews of P208 and of the phase 2 design
(``reports/V9-S3-PHASE1-review/claude-s3rev-1109/REPORT.md``,
``reports/V9-S3-PHASE2-DESIGN/r0-review/REPORT.md``):

- the registered lock is taken before any ledger or marker is written, and each ledger
  has its own mutex, so a busy lock cannot burn a dev use or the single final read;
- smoke runs may not read a dev or final namespace;
- the frozen manifest is the transitive import closure of the entry files, and every
  module loaded from inside the repository must be in it, ``__main__`` included;
- reports are never overwritten.

Guards refuse by raising and never fall back to a passing value. They protect against
mistakes by an honest executor: deleting a ledger, for instance, resets it.
"""

from __future__ import annotations

import ast
import contextlib
import fcntl
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Iterable, Iterator, Mapping


class GuardError(RuntimeError):
    """A registered-run guard refused to proceed."""


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _dotted(src_root: Path, path: Path) -> tuple[str, bool]:
    rel = path.resolve().relative_to(src_root.resolve()).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        return ".".join(parts[:-1]), True
    return ".".join(parts), False


def _module_file(src_root: Path, dotted: str) -> Path | None:
    base = src_root.joinpath(*dotted.split("."))
    init = base / "__init__.py"
    if init.is_file():
        return init
    file = base.with_suffix(".py")
    return file if file.is_file() else None


def _imported_names(path: Path, src_root: Path | None) -> set[str]:
    """Dotted names ``path`` imports. ``a.b import c`` yields both ``a.b`` and ``a.b.c``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if src_root is None:
                    continue
                dotted, is_pkg = _dotted(src_root, path)
                parts = dotted.split(".")
                drop = node.level - 1 if is_pkg else node.level
                base_parts = parts[: len(parts) - drop] if drop else parts
                base = ".".join(base_parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return names


def import_closure(src_root: Path, entries: Iterable[Path], *, package: str = "ainerzero") -> list[Path]:
    """Sources reachable from ``entries``: the project package plus modules beside a script.

    Ancestor ``__init__`` files are included. Static analysis cannot see dynamic imports;
    :func:`check_loaded_modules` covers those at run time.
    """
    src_root = Path(src_root).resolve()
    seen: set[Path] = set()
    stack = [Path(e).resolve() for e in entries]
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        inside = path.is_relative_to(src_root)
        for name in _imported_names(path, src_root if inside else None):
            if not inside:
                sibling = path.parent / f"{name.split('.')[0]}.py"
                if sibling.is_file():
                    stack.append(sibling.resolve())
            if name != package and not name.startswith(package + "."):
                continue
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                found = _module_file(src_root, ".".join(parts[:i]))
                if found is not None:
                    stack.append(found.resolve())
    return sorted(seen)


def build_manifest(repo: Path, entries: Iterable[Path], *, src_root: Path, extra: Iterable[Path] = ()) -> dict[str, str]:
    """``{repo-relative path: sha256}`` for the import closure plus ``extra`` files."""
    repo = Path(repo).resolve()
    paths = set(import_closure(src_root, entries)) | {Path(p).resolve() for p in extra}
    return {str(p.relative_to(repo)): sha256_file(p) for p in sorted(paths)}


def check_manifest(repo: Path, manifest: Mapping[str, str]) -> list[str]:
    """Return one line per missing or changed file; an empty manifest is itself a failure."""
    if not manifest:
        return ["manifest is empty"]
    bad = []
    for rel, want in manifest.items():
        p = Path(repo) / rel
        if not p.is_file():
            bad.append(f"missing: {rel}")
        elif sha256_file(p) != want:
            bad.append(f"changed: {rel}")
    return bad


def check_loaded_modules(
    repo: Path,
    manifest: Mapping[str, str],
    *,
    modules: Mapping[str, ModuleType | None] | None = None,
    ignore_roots: Iterable[Path | str] | None = None,
) -> list[str]:
    """Modules loaded from inside the repository that the manifest does not cover.

    ``__main__`` counts. The interpreter's own prefix is ignored by default because the
    virtual environment lives inside the repository.
    """
    repo = Path(repo).resolve()
    known = {(repo / rel).resolve() for rel in manifest}
    ignored = [Path(r).resolve() for r in ([sys.prefix] if ignore_roots is None else ignore_roots)]
    bad = []
    for name, mod in sorted((sys.modules if modules is None else modules).items()):
        file = getattr(mod, "__file__", None)
        if file is None:
            continue
        path = Path(file).resolve()
        if not path.is_relative_to(repo) or any(path.is_relative_to(r) for r in ignored):
            continue
        if path not in known:
            bad.append(f"not frozen: {name} ({file})")
    return bad


def third_party_versions(repo: Path, names: Iterable[str]) -> dict[str, str]:
    """Versions of third-party libraries, refusing a copy that shadows one from the repository."""
    repo = Path(repo).resolve()
    prefix = Path(sys.prefix).resolve()
    out = {}
    for name in names:
        mod = importlib.import_module(name)
        file = getattr(mod, "__file__", None)
        if file is not None:
            path = Path(file).resolve()
            if path.is_relative_to(repo) and not path.is_relative_to(prefix):
                raise GuardError(f"{name} is shadowed by a repository file: {file}")
        out[name] = str(getattr(mod, "__version__", "unknown"))
    return out


def require_fresh_pycache(started: float, *, tolerance: float = 10.0) -> None:
    """Refuse bytecode written before this process began: stale ``.pyc`` can differ from source.

    ``started`` is taken before the project is imported; ``tolerance`` covers interpreter
    start-up, which can write to the cache just before the script runs.
    """
    if sys.pycache_prefix is None:
        raise GuardError("start the run with -X pycache_prefix or PYTHONPYCACHEPREFIX set to a fresh directory")
    for path in Path(sys.pycache_prefix).rglob("*.pyc"):
        if path.stat().st_mtime < started - tolerance:
            raise GuardError(f"stale bytecode in the pycache prefix: {path}")


def check_git_clean(repo: Path, paths: Iterable[str]) -> tuple[str, list[str]]:
    """Return ``(HEAD, dirty lines)`` so a run can require committed frozen files."""
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=False)
    head = run("rev-parse", "HEAD")
    if head.returncode != 0:
        raise GuardError(f"not a git checkout: {head.stderr.strip()}")
    status = run("status", "--porcelain", "--", *paths)
    if status.returncode != 0:
        raise GuardError(f"git status failed: {status.stderr.strip()}")
    return head.stdout.strip(), [line for line in status.stdout.splitlines() if line]


class RunLock:
    """Exclusive non-blocking hold on the shared worker lock."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._fh = None

    @property
    def held(self) -> bool:
        return self._fh is not None

    def __enter__(self) -> "RunLock":
        fh = self.path.open("a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            fh.close()
            raise GuardError(f"lock is busy: {self.path}") from exc
        try:
            replaced = os.fstat(fh.fileno()).st_ino != os.stat(self.path).st_ino
        except FileNotFoundError:
            replaced = True
        if replaced:
            fh.close()
            raise GuardError(f"lock file was replaced while being acquired: {self.path}")
        self._fh = fh
        return self

    def __exit__(self, *exc) -> None:
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()
        self._fh = None


def _require_held(lock: RunLock, expected_lock: Path | str) -> None:
    if not isinstance(lock, RunLock) or not lock.held:
        raise GuardError("the shared lock must be held before any ledger or marker is written")
    if lock.path.resolve() != Path(expected_lock).resolve():
        raise GuardError(f"held lock {lock.path} is not the registered lock {expected_lock}")


@contextlib.contextmanager
def _ledger_mutex(ledger: Path) -> Iterator[None]:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.with_name(ledger.name + ".lock").open("a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def valid_use_id(use_id: str | None) -> bool:
    """A use id names a directory: letters, digits, ``_`` and ``-`` only, so it cannot escape."""
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", use_id or ""))


def consume_dev_use(
    lock: RunLock,
    ledger: Path,
    use_id: str | None,
    purpose: str | None,
    *,
    max_uses: int,
    expected_lock: Path | str,
) -> list[dict]:
    """Record one dev use. Needs the registered lock, a fresh id and a stated purpose."""
    _require_held(lock, expected_lock)
    if not valid_use_id(use_id) or not (purpose or "").strip():
        raise GuardError("a dev use needs both a use id and a purpose")
    with _ledger_mutex(ledger):
        try:
            uses = json.loads(ledger.read_text(encoding="utf-8")) if ledger.is_file() else []
        except json.JSONDecodeError as exc:
            raise GuardError(f"malformed dev ledger: {ledger}") from exc
        if not isinstance(uses, list):
            raise GuardError(f"malformed dev ledger: {ledger}")
        if use_id in [u.get("id") for u in uses]:
            raise GuardError(f"dev use id already recorded: {use_id}")
        if len(uses) >= max_uses:
            raise GuardError(f"dev uses exhausted ({len(uses)}/{max_uses})")
        uses.append({"id": use_id, "purpose": purpose.strip(), "at": time.time()})
        _atomic_write(ledger, json.dumps(uses, ensure_ascii=False, indent=1))
    return uses


def consume_final_read(
    lock: RunLock,
    marker: Path,
    approval: str | None,
    expected: str,
    *,
    prereg_sha256: str,
    expected_lock: Path | str,
) -> None:
    """Write the one-time final marker. Needs the registered lock and the exact approval line."""
    _require_held(lock, expected_lock)
    if not expected:
        raise GuardError("no final approval line is registered")
    if marker.exists():
        raise GuardError("final has already been read")
    if (approval or "").strip() != expected:
        raise GuardError("missing the unique approval line")
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        with marker.open("x", encoding="utf-8") as fh:
            json.dump({"at": time.time(), "prereg_sha256": prereg_sha256}, fh)
    except FileExistsError as exc:
        raise GuardError("final has already been read") from exc


def check_stage_namespace(stage: str, namespace: str, *, train: str, probe: str, dev: str, final: str) -> None:
    """Partitions are distinct and each stage evaluates its own; smoke and probe read only probe."""
    if len({train, probe, dev, final}) != 4:
        raise GuardError(f"partitions must be distinct: {[train, probe, dev, final]}")
    wanted = {"smoke": probe, "probe": probe, "dev": dev, "final": final}
    if stage not in wanted:
        raise GuardError(f"unknown stage: {stage!r}")
    if namespace != wanted[stage]:
        raise GuardError(f"stage {stage!r} must read {wanted[stage]!r}, got {namespace!r}")


def claim_report(path: Path) -> None:
    """Create the report file exclusively so that an earlier report is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.open("x", encoding="utf-8").close()
    except FileExistsError as exc:
        raise GuardError(f"report already exists: {path}") from exc


class Deadline:
    """Wall-clock limit checked inside training loops. Counts time the machine is asleep."""

    def __init__(self, seconds: float, *, clock=time.time):
        self._clock, self._end = clock, clock() + seconds

    def left(self) -> float:
        return self._end - self._clock()

    def check(self) -> None:
        if self.left() <= 0:
            raise GuardError("wall-clock limit reached")
