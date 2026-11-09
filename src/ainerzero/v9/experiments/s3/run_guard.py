"""Guards for registered S3 runs from phase 2 on. Standard library only.

Implements the fixes demanded by the second non-author review of P208
(``reports/V9-S3-PHASE1-review/claude-s3rev-1109/REPORT.md``):

- the shared lock is taken before any ledger or marker is written, so a busy lock
  cannot burn a dev use or the single final read;
- smoke runs may not read a dev or final namespace;
- the frozen manifest is the transitive import closure of the entry files, and the
  modules actually loaded at run time must all be inside it;
- reports are never overwritten.

Every failure raises :class:`GuardError`; nothing here falls back to a passing value.
"""

from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Iterable, Mapping


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
    """Every source of ``package`` reachable from ``entries``, ancestor ``__init__`` included.

    Static analysis cannot see dynamic imports; :func:`check_loaded_modules` covers those at
    run time.
    """
    seen: set[Path] = set()
    stack = [Path(e).resolve() for e in entries]
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        inside = path.is_relative_to(src_root.resolve())
        for name in _imported_names(path, src_root if inside else None):
            if name != package and not name.startswith(package + "."):
                continue
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                found = _module_file(src_root, ".".join(parts[:i]))
                if found is not None and found.resolve() not in seen:
                    stack.append(found.resolve())
    return sorted(seen)


def build_manifest(repo: Path, entries: Iterable[Path], *, src_root: Path, extra: Iterable[Path] = ()) -> dict[str, str]:
    """``{repo-relative path: sha256}`` for the import closure plus ``extra`` files."""
    repo = repo.resolve()
    paths = set(import_closure(src_root, entries)) | {Path(p).resolve() for p in extra}
    return {str(p.relative_to(repo)): sha256_file(p) for p in sorted(paths)}


def check_manifest(repo: Path, manifest: Mapping[str, str]) -> list[str]:
    """Return one line per missing or changed file; an empty manifest is itself a failure."""
    if not manifest:
        return ["manifest is empty"]
    bad = []
    for rel, want in manifest.items():
        p = repo / rel
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
    package: str = "ainerzero",
) -> list[str]:
    """Project modules loaded in this process that the manifest does not cover."""
    repo = repo.resolve()
    known = {(repo / rel).resolve() for rel in manifest}
    bad = []
    for name, mod in sorted((sys.modules if modules is None else modules).items()):
        if name != package and not name.startswith(package + "."):
            continue
        file = getattr(mod, "__file__", None)
        if file is None:
            continue
        if Path(file).resolve() not in known:
            bad.append(f"not frozen: {name} ({file})")
    return bad


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
        self._fh = fh
        return self

    def __exit__(self, *exc) -> None:
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()
        self._fh = None


def _require_held(lock: RunLock) -> None:
    if not isinstance(lock, RunLock) or not lock.held:
        raise GuardError("the shared lock must be held before any ledger or marker is written")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def consume_dev_use(lock: RunLock, ledger: Path, use_id: str | None, purpose: str | None, *, max_uses: int = 2) -> list[dict]:
    """Record one dev use. Requires a held lock, a fresh id and a stated purpose."""
    _require_held(lock)
    if not use_id or not (purpose or "").strip():
        raise GuardError("a dev use needs both a use id and a purpose")
    uses = json.loads(ledger.read_text(encoding="utf-8")) if ledger.is_file() else []
    if not isinstance(uses, list):
        raise GuardError(f"malformed dev ledger: {ledger}")
    if use_id in [u.get("id") for u in uses]:
        raise GuardError(f"dev use id already recorded: {use_id}")
    if len(uses) >= max_uses:
        raise GuardError(f"dev uses exhausted ({len(uses)}/{max_uses})")
    uses.append({"id": use_id, "purpose": purpose.strip(), "at": time.time()})
    _atomic_write(ledger, json.dumps(uses, ensure_ascii=False, indent=1))
    return uses


def consume_final_read(lock: RunLock, marker: Path, approval: str | None, expected: str, *, prereg_sha256: str) -> None:
    """Write the one-time final marker. Requires a held lock and the exact approval line."""
    _require_held(lock)
    if not expected:
        raise GuardError("no final approval line is registered")
    if marker.exists():
        raise GuardError("final has already been read")
    if (approval or "").strip() != expected:
        raise GuardError("missing the unique approval line")
    marker.parent.mkdir(parents=True, exist_ok=True)
    with marker.open("x", encoding="utf-8") as fh:
        json.dump({"at": time.time(), "prereg_sha256": prereg_sha256}, fh)


def check_stage_namespace(stage: str, namespace: str, *, probe: str, dev: str, final: str) -> None:
    """Each stage reads exactly its own partition; smoke reads only probe."""
    wanted = {"smoke": probe, "dev": dev, "final": final}
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
    """Wall-clock limit that callers check inside training loops."""

    def __init__(self, seconds: float, *, clock=time.monotonic):
        self._clock, self._end = clock, clock() + seconds

    def left(self) -> float:
        return self._end - self._clock()

    def check(self) -> None:
        if self.left() <= 0:
            raise GuardError("wall-clock limit reached")
