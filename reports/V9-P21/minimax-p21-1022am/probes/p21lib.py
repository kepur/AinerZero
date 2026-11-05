"""Shared helpers for the ainerzero.V9.P21 independent review probes.

CPU only.  No MLX import, no real model forward/gradient/update, no train/eval
CLI runtime, no downloads, no writes outside this review directory and the
explicit scratch root below.

The reviewer never edits the reviewed source: every probe imports the product
modules from the repository ``src/`` tree and drives them through their public
entry points.  Where a probe needs an isolated host anchor it uses the same
controlled seam the project's own CPU test kit uses (``spec.REGISTERED_HOST_ROOT``
/ ``spec.PHASE1_ROOT``), never a modification of the reviewed files.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT = REPO / "reports/V9-P21/minimax-p21-1022am"
EVIDENCE = OUT / "evidence"
LOGS = OUT / "logs"
PROBES = OUT / "probes"

# Approved external scratch area (never a real library/user directory).
SCRATCH = Path(
    os.environ.get(
        "P21_SCRATCH",
        "/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p21-scratch",
    )
)

FROZEN_REVIEW_INPUTS = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-morning/"
    "P15-r7-review-inputs.json"
)

if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))


def sha256_file(path: Path | str) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(name: str, payload: object) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    return path


def scratch_dir(prefix: str) -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    return Path(
        subprocess.run(
            ["mktemp", "-d", f"{SCRATCH}/{prefix}-XXXXXX"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )


def mlx_imported() -> bool:
    return any(name == "mlx" or name.startswith("mlx.") for name in sys.modules)


def real_mlx_loaded() -> bool:
    """True only when the *real* MLX extension is in sys.modules."""
    module = sys.modules.get("mlx.core")
    if module is None:
        return False
    origin = getattr(getattr(module, "__spec__", None), "origin", "") or ""
    return origin.endswith((".so", ".dylib")) or "site-packages/mlx" in origin


def install_mlx_stub() -> dict:
    """Install a *stub* ``mlx`` package so that ``arms.py``'s module level
    ``import mlx.core`` never loads the real MLX runtime.

    ``src/ainerzero/v9/experiments/s1/arms.py`` imports ``mlx.core`` and
    ``mlx.nn`` at module level, so every import of that module pulls the real
    runtime in.  The review is CPU-only, so a stub is installed first; the
    stub is only good enough for the class definitions (``nn.Module`` as a base
    class).  No MLX code runs: the D-candidate identity validator is pure
    hashlib/JSON and the forward is a CPU substitute.
    """
    import types

    if "mlx" in sys.modules:
        return {"installed": False, "reason": "mlx already imported"}
    mlx = types.ModuleType("mlx")
    mlx.__path__ = []  # type: ignore[attr-defined]
    core = types.ModuleType("mlx.core")
    core.__spec__ = types.SimpleNamespace(origin="p21-stub")  # type: ignore[attr-defined]
    nn = types.ModuleType("mlx.nn")
    nn.__spec__ = types.SimpleNamespace(origin="p21-stub")  # type: ignore[attr-defined]

    class _Module:  # minimal stand-in for mlx.nn.Module
        pass

    nn.Module = _Module  # type: ignore[attr-defined]
    mlx.core = core  # type: ignore[attr-defined]
    mlx.nn = nn  # type: ignore[attr-defined]
    sys.modules["mlx"] = mlx
    sys.modules["mlx.core"] = core
    sys.modules["mlx.nn"] = nn
    return {"installed": True, "real_mlx_loaded": real_mlx_loaded()}


def file_identity(path: Path | str) -> dict:
    path = Path(path)
    record = {"path": str(path), "exists": path.is_file()}
    if record["exists"]:
        stat = path.stat()
        record.update(
            {
                "sha256": sha256_file(path),
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return record


def host_ledger_identities() -> dict:
    """Identity of the real central ledger and its WAL side files (read only)."""
    phase1 = REPO / "artifacts/v9/s1/phase1"
    return {
        "control.sqlite3": file_identity(phase1 / "control.sqlite3"),
        "control.sqlite3-wal": file_identity(phase1 / "control.sqlite3-wal"),
        "control.sqlite3-shm": file_identity(phase1 / "control.sqlite3-shm"),
        "m0-worker.lock": file_identity(REPO / "artifacts/locks/m0-worker.lock"),
    }


def copy_ledger_bytes(source: Path, destination: Path) -> dict:
    """Byte-for-byte copy of a ledger (plus its -wal/-shm when present)."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = sha256_file(source)
    shutil.copyfile(source, destination)
    after = sha256_file(destination)
    return {
        "source": str(source),
        "source_sha256": before,
        "copy": str(destination),
        "copy_sha256": after,
        "byte_identical": before == after,
    }


def frozen_review_inputs() -> dict:
    return json.loads(FROZEN_REVIEW_INPUTS.read_text(encoding="utf-8"))


def frozen_identity_snapshot(tag: str) -> dict:
    """SHA256 of every file the coordinator froze for this review."""
    data = frozen_review_inputs()
    rows = []
    for entry in data["files"]:
        path = entry["path"]
        actual = sha256_file(path)
        rows.append(
            {
                "path": path,
                "expected_sha256": entry["sha256"],
                "actual_sha256": actual,
                "match": actual == entry["sha256"],
                "exists": Path(path).is_file(),
                "tag": entry.get("bound_by_prereg")
                or entry.get("author_changed_file_identity")
                or entry.get("report_manifest_match")
                or entry.get("additional_identity"),
            }
        )
    mismatches = [row for row in rows if not row["match"]]
    return {
        "schema": "ainerzero.v9.p21.frozen_identity.v1",
        "tag": tag,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": str(FROZEN_REVIEW_INPUTS),
        "source_sha256": sha256_file(FROZEN_REVIEW_INPUTS),
        "count": len(rows),
        "mismatches": mismatches,
        "mismatch_count": len(mismatches),
        "all_match": not mismatches,
        "rows": rows,
    }


def git_state() -> dict:
    proc = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain=v1", "--untracked-files=no"],
        capture_output=True,
        text=True,
    )
    head = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return {
        "head": head.stdout.strip(),
        "status_porcelain": proc.stdout.splitlines(),
        "clean": not proc.stdout.strip(),
    }


def make_checkout(destination: Path) -> Path:
    """An independent copy of the real source tree (a second checkout)."""
    destination = Path(destination)
    (destination / "src").mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        REPO / "src" / "ainerzero",
        destination / "src" / "ainerzero",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return destination


def checkout_anchor(checkout: Path, *, cwd: Path | None = None, env_extra: dict | None = None):
    """Resolve the host anchor from inside a checkout, in its own process."""
    script = (
        "import json;"
        "from ainerzero.v9.experiments.s1 import spec, worker, commands;"
        "print(json.dumps({"
        "'spec_file': spec.__file__,"
        "'registered_host_root': str(spec.REGISTERED_HOST_ROOT),"
        "'repo_root': str(spec.REPO_ROOT),"
        "'phase1_root': str(spec.PHASE1_ROOT),"
        "'ledger': str(worker.canonical_ledger_path()),"
        "'lock': str(commands._lock_path()),"
        "'approval_log': str(spec.RESEARCH_LOG),"
        "'anchor_state': spec.host_anchor_state(),"
        "'cwd': __import__('os').getcwd(),"
        "}))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(checkout) / "src")
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(cwd or checkout),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {"ok": False, "returncode": proc.returncode, "stderr": proc.stderr[-2000:]}
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    payload["ok"] = True
    return payload
