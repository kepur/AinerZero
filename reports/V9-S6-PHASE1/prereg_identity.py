"""S6 phase 1 freeze identity (DESIGN-r3 §7 item 5): the probe ran on one commit, the frozen code differs from it
only in three runner constants that are not on the numerical path.

Read-only, CPU, no MLX import. Used by make_prereg.py together with prereg_evidence.py.

- ``probe_tree``: the probe's code, exported from git at the probe's commit (never the working directory), and its
  manifest recomputed there.
- ``runner_diff``: the two runner sources must have identical syntax trees once three nodes are replaced by
  placeholders: SETS["final"]["train_cap_s"], SETS["final"]["eval_limit_s"] and THIRD_PARTY. Old values may only be
  numeric constants or a product of numeric constants; new values must be numeric literals (strings for
  THIRD_PARTY), with the exact registered values.
- ``current_identity``: the code to freeze is committed and clean; its manifest has the probe manifest's file set and
  every file byte-identical except the runner, whose difference passes ``runner_diff``.
- ``final_versions`` / ``distributions``: library versions from installed metadata, never "unknown"; the record the
  final runner will compare at start is {"numpy", "mlx.core"}.
- ``mlx_environment``: any MLX_* variable refuses the freeze.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

import numpy as np

from ainerzero.v9.experiments.s3 import run_guard as GD

RUNNER_REL = "reports/V9-S6-PHASE1/run_s6p1.py"
VERIFY_REL = "reports/V9-S6-PHASE1/verify_s6p1.py"
OLD = {"train_cap_s": 21600.0, "eval_limit_s": 3600, "third_party": ("numpy", "mlx")}
NEW = {"train_cap_s": 19800, "eval_limit_s": 5400, "third_party": ("numpy", "mlx.core")}
DISTRIBUTIONS = ("mlx", "mlx-metal", "numpy")
_PLACEHOLDER = "__S6_R3_PLACEHOLDER__"


class IdentityError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise IdentityError(message)


def manifest_sha(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _git(repo, *args, binary=False):
    r = subprocess.run(["git", "--no-optional-locks", *args], cwd=repo, capture_output=True, text=not binary)
    require(r.returncode == 0, f"git {' '.join(args[:2])} failed")
    return r.stdout if binary else r.stdout.strip()


def _is_commit(text):
    return type(text) is str and len(text) == 40 and all(c in "0123456789abcdef" for c in text)


@contextlib.contextmanager
def probe_tree(repo, commit):
    """Yield (directory, manifest, manifest_sha) of the probe's code exported from git at ``commit``."""
    require(_is_commit(commit), "probe commit must be a full 40-character hash")
    data = _git(repo, "archive", commit, "src", RUNNER_REL, VERIFY_REL, binary=True)
    with tempfile.TemporaryDirectory(prefix="s6-probe-tree-") as tmp:
        root = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for m in archive.getmembers():
                require(not m.name.startswith("/") and ".." not in Path(m.name).parts and (m.isfile() or m.isdir()),
                        "unexpected member in the probe archive")
            archive.extractall(root, filter="data")
        manifest = GD.build_manifest(root, [root / RUNNER_REL], src_root=root / "src", extra=[root / VERIFY_REL])
        yield root, manifest, manifest_sha(manifest)


# --- runner syntax-tree difference -----------------------------------------------------------------------------
def _number(node, *, fold):
    """A numeric literal; with ``fold`` also a product of two numeric literals. Booleans are not numbers."""
    def lit(n):
        return isinstance(n, ast.Constant) and type(n.value) in (int, float)
    if lit(node):
        return node.value
    if fold and isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult) and lit(node.left) and lit(node.right):
        return node.left.value * node.right.value
    raise IdentityError("a registered constant is not a plain numeric literal" + (" or a product of two" if fold else ""))


def _strings(node):
    require(isinstance(node, ast.Tuple) and all(isinstance(e, ast.Constant) and type(e.value) is str for e in node.elts),
            "THIRD_PARTY must be a tuple of string literals")
    return tuple(e.value for e in node.elts)


def _extract(src, *, old):
    """Parse a runner, replace the three registered nodes by placeholders, return (dump, values)."""
    tree = ast.parse(src)
    sets = [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "SETS"]
    third = [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
             and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "THIRD_PARTY"]
    require(len(sets) == 1 and len(third) == 1, "the runner must assign SETS and THIRD_PARTY exactly once at module level")
    require(isinstance(sets[0].value, ast.Dict), "SETS must be a dict literal")
    finals = [v for k, v in zip(sets[0].value.keys, sets[0].value.values) if isinstance(k, ast.Constant) and k.value == "final"]
    require(len(finals) == 1 and isinstance(finals[0], ast.Dict), "SETS must hold exactly one dict literal under 'final'")
    final = finals[0]
    values = {}
    for name in ("train_cap_s", "eval_limit_s"):
        idx = [i for i, k in enumerate(final.keys) if isinstance(k, ast.Constant) and k.value == name]
        require(len(idx) == 1, f"SETS['final'] must name {name} exactly once")
        values[name] = _number(final.values[idx[0]], fold=old)
        final.values[idx[0]] = ast.Constant(_PLACEHOLDER + name)
    values["third_party"] = _strings(third[0].value)
    third[0].value = ast.Constant(_PLACEHOLDER + "third_party")
    return ast.dump(tree, include_attributes=False), values


def runner_diff(old_src, new_src):
    """Proof that the new runner differs from the old one only in the three registered values."""
    old_dump, old_values = _extract(old_src, old=True)
    new_dump, new_values = _extract(new_src, old=False)
    require(old_dump == new_dump, "the runner differs from the probe's beyond the three registered constants")
    for name in ("train_cap_s", "eval_limit_s"):
        require(old_values[name] == OLD[name], f"probe runner {name} is {old_values[name]}, expected {OLD[name]}")
        require(new_values[name] == NEW[name], f"frozen runner {name} is {new_values[name]}, expected {NEW[name]}")
    require(old_values["third_party"] == OLD["third_party"], "probe runner THIRD_PARTY differs from the registered old value")
    require(new_values["third_party"] == NEW["third_party"], "frozen runner THIRD_PARTY differs from the registered new value")
    return {"old": {k: list(v) if isinstance(v, tuple) else v for k, v in old_values.items()},
            "new": {k: list(v) if isinstance(v, tuple) else v for k, v in new_values.items()},
            "masked_tree_sha256": hashlib.sha256(old_dump.encode()).hexdigest()}


def current_identity(repo, probe_root, probe_manifest):
    """The code to freeze: committed and clean, same file set as the probe, byte-identical except the runner."""
    repo = Path(repo)
    current = GD.build_manifest(repo, [repo / RUNNER_REL], src_root=repo / "src", extra=[repo / VERIFY_REL])
    require(set(current) == set(probe_manifest), "the frozen code's file set differs from the probe's")
    changed = sorted(rel for rel in current if current[rel] != probe_manifest[rel])
    require(changed == [RUNNER_REL], f"files other than the runner differ from the probe's code: {changed}")
    require(not _git(repo, "status", "--porcelain", "--", *current), "the code to freeze is not committed")
    head = _git(repo, "rev-parse", "HEAD")
    data = _git(repo, "archive", head, *current, binary=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for rel, digest in current.items():
            require(hashlib.sha256(archive.extractfile(rel).read()).hexdigest() == digest, f"committed {rel} differs")
    proof = runner_diff((probe_root / RUNNER_REL).read_text(encoding="utf-8"), (repo / RUNNER_REL).read_text(encoding="utf-8"))
    return {"head": head, "manifest": current, "manifest_sha256": manifest_sha(current), "changed": changed, "runner_diff": proof}


# --- libraries and environment ------------------------------------------------------------------------------------
def _version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise IdentityError(f"{name} is not installed") from exc


def final_versions():
    """What the frozen runner records at start (THIRD_PARTY = ("numpy", "mlx.core")), read without importing MLX.
    mlx.core.__version__ equals the installed mlx distribution's version (checked by a native test)."""
    out = {"numpy": str(np.__version__), "mlx.core": _version("mlx")}
    require(out["numpy"] == _version("numpy"), "numpy module and distribution versions differ")
    require(all(v and v != "unknown" for v in out.values()), "a library version is unknown")
    return out


def distributions():
    """Installed versions, the SHA of each distribution's RECORD and its dist-info directory time."""
    out = {}
    for name in DISTRIBUTIONS:
        dist = importlib.metadata.distribution(name)
        record = dist.read_text("RECORD")
        require(record, f"{name} has no RECORD")
        path = getattr(dist, "_path", None)
        out[name] = {"version": dist.version, "record_sha256": hashlib.sha256(record.encode()).hexdigest(),
                     "dist_info_mtime": os.stat(path).st_mtime if path is not None else None}
        require(out[name]["version"] and out[name]["version"] != "unknown", f"{name} version unknown")
    return out


def mlx_environment(environ=None):
    env = os.environ if environ is None else environ
    found = {k: v for k, v in env.items() if k.startswith("MLX_")}
    require(not found, f"MLX_* environment variables are set: {sorted(found)}")
    return found
