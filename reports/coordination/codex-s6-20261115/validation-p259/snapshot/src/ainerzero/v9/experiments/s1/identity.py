"""Stdlib-only identity verification of the frozen D candidate (S1 r8).

S1-R8-DECISION F6/F7: the read-only byte verification of the A2 baseline must
not drag the MLX runtime in through a module-level import, because identity
verification is a pure byte/digest operation on a CPU entry path.  This module
therefore imports nothing outside the standard library (and the MLX-free
``spec`` module) and is the only place the A2 trust root is resolved.

Trust chain (F6)
----------------
1. the A2 manifest *file bytes* are pinned by
   ``ARM_SPECS["arm1"]["identity"]["frozen_manifest_file_sha256"]``;
2. the manifest *self digest* is recomputed with the original A2 algorithm
   (``scripts/v9_baseline_manifest_r3.py``: sha256 over canonical JSON of every
   top-level field except ``generated_at``, ``manifest_digest`` and
   ``policy_check``) and compared with the registered
   ``frozen_manifest_digest`` -- never recomputed over a different payload;
3. every A2-pinned file below the candidate's pilot directory is re-hashed
   byte for byte;
4. the registered ``tensors.safetensors``, ``manifest.json`` and
   ``metadata.json`` digests are each compared with what was actually read.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from . import spec

SCHEMA = "ainerzero.v9.s1.d_identity.v2"
# The original r3 builder excludes exactly these fields from its self digest.
MANIFEST_DIGEST_EXCLUDED = ("generated_at", "manifest_digest", "policy_check")


class DIdentityError(RuntimeError):
    """The D candidate or its trust root is not the registered one."""


def canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def manifest_self_digest(manifest: Mapping[str, Any]) -> str:
    """The original A2 manifest digest algorithm (not a lookalike re-hash)."""
    payload = {
        key: value
        for key, value in manifest.items()
        if key not in MANIFEST_DIGEST_EXCLUDED
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _identity() -> dict:
    return dict(spec.ARM_SPECS["arm1"]["identity"])


def verify_d_candidate_identity(repo_root: Path | None = None) -> dict:
    """Recompute the A2 manifest and every pinned D-candidate file digest."""
    root = Path(repo_root or spec.REPO_ROOT)
    identity = _identity()
    manifest_path = Path(identity["frozen_manifest"])
    if not manifest_path.is_file():
        raise FileNotFoundError(f"A2 frozen manifest is missing: {manifest_path}")
    manifest_bytes = manifest_path.read_bytes()
    manifest_file_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    pinned_file_sha256 = identity.get("frozen_manifest_file_sha256")
    if not pinned_file_sha256:
        raise DIdentityError(
            "the registered D identity does not pin the A2 manifest bytes; the trust "
            "root cannot be verified"
        )
    if manifest_file_sha256 != pinned_file_sha256:
        raise DIdentityError(
            "the A2 manifest bytes differ from the registered trust root: "
            f"{manifest_file_sha256} != {pinned_file_sha256}"
        )

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    recomputed_digest = manifest_self_digest(manifest)
    registered_digest = identity.get("frozen_manifest_digest")
    if not registered_digest:
        raise DIdentityError(
            "the registered D identity does not carry the A2 manifest self digest"
        )
    if recomputed_digest != registered_digest:
        raise DIdentityError(
            "the A2 manifest self digest does not match the registered digest: "
            f"{recomputed_digest} != {registered_digest}"
        )

    prefix = f"{identity['pilot_dir']}/"
    entries = [
        row
        for row in manifest.get("files", [])
        if str(row.get("path", "")).startswith(prefix)
    ]
    if not entries:
        raise DIdentityError("A2 manifest has no entry for the D candidate pilot directory")
    checkpoint_id = identity.get("checkpoint_id") or spec.ARM_SPECS["arm1"]["identity"][
        "checkpoint_id"
    ]
    checkpoint_prefix = f"{prefix}checkpoints/{checkpoint_id}/"
    required_suffixes = ("tensors.safetensors", "manifest.json", "metadata.json")

    verified: dict[str, str] = {}
    for row in entries:
        rel = row["path"]
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(f"A2-pinned file is missing: {rel}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != row["sha256"]:
            raise DIdentityError(f"A2-pinned file changed: {rel}")
        verified[rel] = actual
    for suffix in required_suffixes:
        wanted = f"{checkpoint_prefix}{suffix}"
        if wanted not in verified:
            raise DIdentityError(f"A2 manifest does not pin the checkpoint file {wanted}")

    registered_fields = {
        "tensors_sha256": f"{checkpoint_prefix}tensors.safetensors",
        "manifest_sha256": f"{checkpoint_prefix}manifest.json",
        "metadata_sha256": f"{checkpoint_prefix}metadata.json",
    }
    field_state = {}
    for field, rel in registered_fields.items():
        expected = identity[field]
        actual = verified[rel]
        field_state[field] = {"expected": expected, "actual": actual, "match": expected == actual}
        if expected != actual:
            raise DIdentityError(
                f"D candidate {field} differs from the registered identity: {actual} != {expected}"
            )

    return {
        "schema": SCHEMA,
        "frozen_manifest": str(manifest_path),
        "frozen_manifest_file_sha256": manifest_file_sha256,
        "frozen_manifest_digest": recomputed_digest,
        "manifest_digest_rule": "sha256(canonical_json(manifest minus "
        + ", ".join(MANIFEST_DIGEST_EXCLUDED)
        + ")) -- the original A2 r3 builder algorithm",
        "manifest_digest_match": True,
        "registered_fields": field_state,
        "entries_verified": len(verified),
        "pilot_dir": identity["pilot_dir"],
        "checkpoint_id": checkpoint_id,
        "tensors_sha256": verified[f"{checkpoint_prefix}tensors.safetensors"],
        "manifest_sha256": verified[f"{checkpoint_prefix}manifest.json"],
        "metadata_sha256": verified[f"{checkpoint_prefix}metadata.json"],
        "role": manifest.get("role"),
        "mlx_imported": False,
    }
