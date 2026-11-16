"""S2 Phase 1 preregistration freeze and approval line generator (ainerzero.V9.P132).

Provides:
- canonical_bytes(): deterministic canonical JSON bytes (sorted keys, compact separators, UTF-8).
- document_sha256(): SHA-256 hex digest of canonical JSON bytes.
- collect_source_digests(): collects digests for all s2 Python modules and the S2 CLI snippet in cli.py.
- approval_line(): formats exact approval line expected by s2/commands.py scan_approval_log.
- freeze(): validates draft, injects source_digests, writes prereg.json and prereg.json.sha256,
  refusing overwrite if target files already exist.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from ainerzero.v9.experiments.s2 import prereg

APPROVAL_PREFIX = "APPROVED s2-phase1 prereg document_sha256="
STATUS_FROZEN = "awaiting_coordinator_approval"


def canonical_bytes(doc: Mapping[str, Any]) -> bytes:
    """Format dictionary into deterministic canonical JSON bytes.

    Uses sorted keys, compact separators (',', ':'), and UTF-8 encoding.
    """
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def document_sha256(doc: Mapping[str, Any]) -> str:
    """Compute 64-char lowercase SHA256 hex digest of canonical JSON bytes."""
    return hashlib.sha256(canonical_bytes(doc)).hexdigest()


def approval_line(sha: str) -> str:
    """Format the coordinator approval line for RESEARCH_LOG.md.

    Strictly matches the scanning regex in ainerzero.v9.experiments.s2.commands:
    r"^APPROVED\\s+s2-phase1\\s+prereg\\s+document_sha256=([0-9a-f]{64})$"

    Raises:
        ValueError: If sha is not exactly 64 hexadecimal characters.
    """
    cleaned = str(sha).strip().lower()
    if len(cleaned) != 64 or not re.fullmatch(r"[0-9a-f]{64}", cleaned):
        raise ValueError(
            f"document_sha256 must be exactly 64 lowercase hexadecimal characters, got {sha!r}"
        )
    return f"{APPROVAL_PREFIX}{cleaned}"


def find_repo_root(start_path: Path | None = None) -> Path:
    """Find repository root containing pyproject.toml."""
    current = (start_path or Path(__file__)).resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return current.parents[4]


def extract_cli_s2_snippet(cli_path: Path) -> str:
    """Extract S2 CLI parser and dispatch blocks from cli.py.

    Extraction rule:
    1. Parser block: from 's2 = commands.add_parser("s2-phase1"' up to the next command parser or def.
    2. Dispatch block: from 'if args.command == "s2-phase1":' up to the next if/return branch.
    """
    text = cli_path.read_text(encoding="utf-8")
    p_match = re.search(
        r'(\s+s2 = commands\.add_parser\(\s*"s2-phase1".*?)(?=\n\s+\w+ = commands\.add_parser|\n\s+def )',
        text,
        re.DOTALL,
    )
    d_match = re.search(
        r'(\s+if args\.command == "s2-phase1":.*?)(?=\n\s+if args\.command|\n\s+return )',
        text,
        re.DOTALL,
    )
    if not p_match or not d_match:
        raise ValueError(f"Could not locate S2 CLI parser and dispatch blocks in {cli_path}")

    return (
        "# --- S2 CLI Parser ---\n"
        + p_match.group(1).strip()
        + "\n# --- S2 CLI Dispatch ---\n"
        + d_match.group(1).strip()
        + "\n"
    )


def collect_source_digests(repo_root: Path | str | None = None) -> dict[str, str]:
    """Compute SHA256 digests for all Python source files in s2 and the s2 CLI code block."""
    root = Path(repo_root) if repo_root is not None else find_repo_root()
    s2_dir = root / "src" / "ainerzero" / "v9" / "experiments" / "s2"
    if not s2_dir.is_dir():
        s2_dir = Path(__file__).resolve().parent
        root = find_repo_root(s2_dir)

    digests: dict[str, str] = {}
    for py_file in sorted(s2_dir.glob("*.py")):
        if py_file.is_file() and not py_file.name.startswith("."):
            try:
                rel_path = str(py_file.relative_to(root))
            except ValueError:
                rel_path = f"src/ainerzero/v9/experiments/s2/{py_file.name}"
            digests[rel_path] = hashlib.sha256(py_file.read_bytes()).hexdigest()

    cli_path = root / "src" / "ainerzero" / "cli.py"
    if cli_path.is_file():
        snippet = extract_cli_s2_snippet(cli_path)
        digests["src/ainerzero/cli.py:s2-phase1"] = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
    else:
        raise FileNotFoundError(f"CLI file missing: {cli_path}")

    return digests


def freeze(
    draft_doc: Mapping[str, Any],
    out_dir: Path | str,
    repo_root: Path | str | None = None,
) -> str:
    """Validate and freeze a preregistration document.

    Steps:
    1. Validate input draft via prereg.validate.
    2. Check target files (prereg.json, prereg.json.sha256); refuse overwrite if exists.
    3. Update status to awaiting_coordinator_approval.
    4. Inject fresh source_digests from repo_root.
    5. Re-validate complete frozen document.
    6. Write prereg.json and companion prereg.json.sha256.
    7. Return 64-hex document_sha256.

    Raises:
        FileExistsError: If prereg.json or prereg.json.sha256 already exists in out_dir.
        SpecValidationError: If draft or frozen document fails specification validation.
    """
    # 1. Pre-validation of draft
    prereg.validate(draft_doc)

    out_path = Path(out_dir).resolve()
    target_json = out_path / "prereg.json"
    target_sha = out_path / "prereg.json.sha256"

    # 2. Refuse overwrite
    if target_json.exists() or target_sha.exists():
        raise FileExistsError(f"Target preregistration file already exists in {out_path}")

    # 3 & 4. Clone and enrich
    frozen_doc = copy.deepcopy(dict(draft_doc))
    frozen_doc["status"] = STATUS_FROZEN
    frozen_doc["source_digests"] = collect_source_digests(repo_root)

    # 5. Re-validate complete frozen document
    prereg.validate(frozen_doc)

    # 6. Compute canonical bytes and hash
    raw_bytes = canonical_bytes(frozen_doc)
    doc_sha = hashlib.sha256(raw_bytes).hexdigest()

    # Write files
    out_path.mkdir(parents=True, exist_ok=True)
    target_json.write_bytes(raw_bytes)
    target_sha.write_text(f"{doc_sha}  prereg.json\n", encoding="utf-8")

    return doc_sha
