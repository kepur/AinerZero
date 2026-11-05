"""Runtime identity verification for E1 Phase 2 (ainerzero.V9.P83).

Recomputes SHA256 digests of all declared E1 implementation sources and AWZ E0
generator sources, strictly comparing them against the frozen preregistration document.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from . import prereg, spec


class FrozenIdentityMismatchError(RuntimeError):
    """Raised when runtime source or generator digests do not match frozen document."""

    def __init__(self, mismatches: Mapping[str, Mapping[str, Any]]):
        self.mismatches = dict(mismatches)
        details = []
        for file_path, diff in sorted(self.mismatches.items()):
            doc_val = diff.get("document")
            curr_val = diff.get("current")
            details.append(f"  - {file_path}: document={doc_val!r}, current={curr_val!r}")
        message = (
            f"Frozen identity verification failed with {len(self.mismatches)} mismatch(es):\n"
            + "\n".join(details)
        )
        super().__init__(message)


def verify_frozen_identity(
    document: Mapping[str, Any],
    repo_root: Path | str | None = None,
    awz_root: Path | str | None = None,
) -> dict[str, Any]:
    """Verify that current repo and AWZ source digests strictly match frozen document.

    Args:
        document: Preregistration document dictionary.
        repo_root: Optional root directory of AinerZero repository.
        awz_root: Optional root directory of AnimeWorldZero repository.

    Returns:
        dict with status='passed', source_digests, and generator_digests.

    Raises:
        FrozenIdentityMismatchError: If any source or generator digest differs.
        FileNotFoundError: If any declared implementation or generator source is missing.
    """
    root = Path(repo_root) if repo_root is not None else spec.REPO_ROOT
    awz = Path(awz_root) if awz_root is not None else spec.AWZ_ROOT

    # Recompute current digests (raises FileNotFoundError if any declared file is missing)
    curr_source_digests = prereg.collect_source_digests(root)
    curr_gen_digests = prereg.collect_generator_digests(awz)

    doc_source_digests = document.get("source_digests")
    if not isinstance(doc_source_digests, Mapping):
        doc_source_digests = {}

    doc_gen_digests = document.get("generator_digests")
    if not isinstance(doc_gen_digests, Mapping):
        doc_gen_digests = {}

    mismatches: dict[str, dict[str, Any]] = {}

    # 1. Compare implementation source digests
    all_source_keys = set(spec.IMPLEMENTATION_SOURCES) | set(doc_source_digests.keys())
    for rel_path in sorted(all_source_keys):
        doc_val = doc_source_digests.get(rel_path)
        curr_val = curr_source_digests.get(rel_path)
        if doc_val != curr_val:
            mismatches[rel_path] = {
                "document": doc_val,
                "current": curr_val,
            }

    # 2. Compare generator source digests
    all_gen_keys = set(spec.GENERATOR_SOURCES) | set(doc_gen_digests.keys())
    for rel_path in sorted(all_gen_keys):
        doc_val = doc_gen_digests.get(rel_path)
        curr_val = curr_gen_digests.get(rel_path)
        if doc_val != curr_val:
            mismatches[rel_path] = {
                "document": doc_val,
                "current": curr_val,
            }

    # 3. Compare required velocity injection
    doc_vel = document.get("required_velocity_injection")
    curr_vel = spec.REQUIRED_VELOCITY_INJECTION
    if doc_vel != curr_vel:
        mismatches["required_velocity_injection"] = {
            "document": doc_vel,
            "current": curr_vel,
        }

    if mismatches:
        raise FrozenIdentityMismatchError(mismatches)

    return {
        "status": "passed",
        "source_digests": curr_source_digests,
        "generator_digests": curr_gen_digests,
        "required_velocity_injection": curr_vel,
    }
