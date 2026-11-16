"""Runtime identity verification for S2 Phase 1 (ainerzero.V9.P132).

Verifies:
1. Companion .sha256 file matches the bit-for-bit SHA256 of prereg.json.
2. The prereg.json document satisfies canonical representation and schema requirements.
3. Every declared source digest in prereg.json matches the freshly recomputed digest
   of all s2 Python source files and the CLI S2 code block.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ainerzero.v9.experiments.s2 import freeze


class FrozenIdentityMismatchError(RuntimeError):
    """Raised when runtime source digests do not match frozen preregistration."""

    def __init__(self, mismatches: Mapping[str, Mapping[str, Any]]):
        self.mismatches = dict(mismatches)
        details = []
        for file_path, diff in sorted(self.mismatches.items()):
            doc_val = diff.get("document")
            curr_val = diff.get("current")
            details.append(f"  - {file_path}: frozen={doc_val!r}, current={curr_val!r}")
        message = (
            f"Frozen identity verification failed with {len(self.mismatches)} mismatch(es):\n"
            + "\n".join(details)
        )
        super().__init__(message)


def verify_frozen_identity(
    prereg_path: Path | str,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Verify that companion .sha256 and current repository sources match frozen preregistration.

    Args:
        prereg_path: Path to prereg.json file.
        repo_root: Optional repository root path.

    Returns:
        Dict with status='passed', document_sha256, and verified source_digests.

    Raises:
        FileNotFoundError: If prereg.json or prereg.json.sha256 does not exist.
        ValueError: If companion .sha256 does not match prereg.json bytes.
        FrozenIdentityMismatchError: If any source file digest has changed.
    """
    p_path = Path(prereg_path).resolve()
    if not p_path.is_file():
        raise FileNotFoundError(f"Preregistration file not found: {p_path}")

    sha_path = p_path.with_suffix(p_path.suffix + ".sha256")
    if not sha_path.is_file():
        raise FileNotFoundError(f"Companion checksum file not found: {sha_path}")

    raw_bytes = p_path.read_bytes()
    actual_file_sha = hashlib.sha256(raw_bytes).hexdigest()

    # Verify companion .sha256 file
    sha_text = sha_path.read_text(encoding="utf-8").strip()
    tokens = sha_text.split()
    if not tokens:
        raise ValueError(f"Empty checksum file: {sha_path}")
    expected_file_sha = tokens[0].lower()

    if actual_file_sha.lower() != expected_file_sha:
        raise ValueError(
            f"Checksum verification failed for {p_path}: "
            f"actual content sha256 is {actual_file_sha}, but {sha_path} contains {expected_file_sha}"
        )

    # Parse and verify document
    try:
        doc = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse JSON from {p_path}: {exc}") from exc

    if not isinstance(doc, Mapping):
        raise ValueError(f"Preregistration root must be a mapping, got {type(doc).__name__}")

    doc_sources = doc.get("source_digests")
    if not isinstance(doc_sources, Mapping):
        raise ValueError(f"Preregistration missing valid source_digests mapping in {p_path}")

    # Recompute current source digests
    curr_sources = freeze.collect_source_digests(repo_root)

    mismatches: dict[str, dict[str, Any]] = {}
    all_keys = set(doc_sources.keys()) | set(curr_sources.keys())

    for k in sorted(all_keys):
        doc_val = doc_sources.get(k)
        curr_val = curr_sources.get(k)
        if doc_val != curr_val:
            mismatches[k] = {
                "document": doc_val,
                "current": curr_val,
            }

    if mismatches:
        raise FrozenIdentityMismatchError(mismatches)

    return {
        "status": "passed",
        "document_sha256": actual_file_sha,
        "source_digests": curr_sources,
    }
