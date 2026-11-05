"""Build, freeze and verify the E1 Phase 2 preregistration document (ainerzero.V9.P71).

Provides:
- build_draft(): Constructs draft dictionary from spec.py and source digests.
- freeze(): Validates and seals document into canonical bytes, computing SHA256.
- validate(): Strict validator checking schemas, arm parameters, thresholds, and budget arithmetic.
- approval_line(): Formats standard approval line for RESEARCH_LOG.md.
- find_approval(): Scans RESEARCH_LOG.md section ## R20261029-E1-approval for exactly one approval line,
  rejecting fenced code, blockquotes, indented code, duplicate sections, or multiple lines.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from . import spec

SCHEMA = "ainerzero.v9.e1.preregistration.v1"
STATUS_DRAFT = "draft_awaiting_approval"
STATUS_FROZEN = "awaiting_coordinator_approval"
STATUS_APPROVED = "approved"  # informational only; never an approval

# --- Coordinator Approval Line Format ---
APPROVAL_PREFIX = "APPROVED e1-phase2 prereg document_sha256="
APPROVAL_TEMPLATE = APPROVAL_PREFIX + "{document_sha256}"
_APPROVAL_RE = re.compile(r"^APPROVED e1-phase2 prereg document_sha256=([0-9a-f]{64})$")

# Scoped section in RESEARCH_LOG.md (coordinator write-scope only)
APPROVAL_SECTION = "R20261029-E1-approval"
_SECTION_HEADING_RE = re.compile(
    r"^##\s+" + re.escape(APPROVAL_SECTION) + r"(?=$|[\s：:（(])"
)
_ANY_H2_RE = re.compile(r"^##\s")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


class ApprovalRefused(RuntimeError):
    """No coordinator approval line for this exact frozen document."""

    def __init__(self, reasons: list[str], *, detail: Mapping[str, Any] | None = None):
        self.reasons = list(reasons)
        self.detail = dict(detail or {})
        super().__init__("; ".join(self.reasons))


class SpecValidationError(ValueError):
    """Preregistration document violates frozen specification contracts."""


def canonical_bytes(document: Mapping[str, Any]) -> bytes:
    """Format dictionary into canonical deterministic JSON bytes."""
    return spec.canonical_json(document)


def document_sha256(document: Mapping[str, Any]) -> str:
    """Compute 64-char lowercase SHA256 hex digest of canonical JSON bytes."""
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def write_sha256_file(path: Path | str, digest: str) -> Path:
    """Write companion .sha256 file for a document."""
    file_path = Path(path)
    checksum_path = file_path.with_suffix(file_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {file_path.name}\n", encoding="utf-8")
    return checksum_path


def collect_source_digests(repo_root: Path | str | None = None) -> dict[str, str]:
    """Compute SHA256 digests for all declared implementation source files."""
    root = Path(repo_root) if repo_root is not None else spec.REPO_ROOT
    digests: dict[str, str] = {}
    for rel_path in spec.IMPLEMENTATION_SOURCES:
        full_path = root / rel_path
        if not full_path.is_file():
            raise FileNotFoundError(f"Implementation source file missing: {full_path}")
        content = full_path.read_bytes()
        digests[rel_path] = hashlib.sha256(content).hexdigest()
    return digests


def collect_generator_digests(awz_root: Path | str | None = None) -> dict[str, str]:
    """Compute SHA256 digests for all declared generator source files in AWZ."""
    root = Path(awz_root) if awz_root is not None else spec.AWZ_ROOT
    digests: dict[str, str] = {}
    for rel_path in spec.GENERATOR_SOURCES:
        full_path = root / rel_path
        if not full_path.is_file():
            raise FileNotFoundError(f"Generator source file missing: {full_path}")
        content = full_path.read_bytes()
        digests[rel_path] = hashlib.sha256(content).hexdigest()
    return digests


def build_draft(
    *,
    repo_root: Path | str | None = None,
    awz_root: Path | str | None = None,
    draft_time_utc: str | None = None,
) -> dict[str, Any]:
    """Build the complete preregistration draft dictionary from frozen spec constants."""
    root = Path(repo_root) if repo_root is not None else spec.REPO_ROOT
    awz = Path(awz_root) if awz_root is not None else spec.AWZ_ROOT
    timestamp = draft_time_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "spec_name": spec.SPEC_NAME,
        "experiment_id": spec.EXPERIMENT_ID,
        "task_id": spec.TASK_ID,
        "prereg_draft_ref": {
            "path": spec.PREREG_DRAFT_PATH,
            "sha256": spec.PREREG_DRAFT_SHA256,
            "sha256_prefix": spec.PREREG_DRAFT_SHA256_PREFIX,
        },
        "status": STATUS_DRAFT,
        "created_utc": timestamp,
        "arms": [arm.to_dict() for arm in spec.ARM_SPECS],
        "parameter_equality": {
            "trainable_arms": list(spec.TRAINABLE_ARM_IDS),
            "registered_parameter_count": spec.REGISTERED_NET_PARAMETER_COUNT,
        },
        "families": {
            "names": list(spec.FAMILIES),
            "descriptions": spec.FAMILY_DESCRIPTIONS,
        },
        "partitions": {
            "names": list(spec.PARTITIONS),
            "train_worlds_per_family": spec.TRAIN_WORLDS_PER_FAMILY,
            "dev_worlds_per_family": spec.DEV_WORLDS_PER_FAMILY,
            "final_worlds_per_family": spec.FINAL_WORLDS_PER_FAMILY,
            "total_experiment_worlds": spec.TOTAL_EXPERIMENT_WORLDS,
            "data_seed": spec.DATA_SEED,
        },
        "training_seeds": list(spec.TRAINING_SEEDS),
        "simulation": {
            "fps_simulation": spec.FPS_SIMULATION,
            "physics_ticks_per_sec": spec.PHYSICS_TICKS_PER_SEC,
            "substeps_per_frame": spec.SUBSTEPS_PER_FRAME,
            "substep_delta_t": spec.SUBSTEP_DELTA_T,
            "ticks_per_frame_ratio": spec.TICKS_PER_FRAME_RATIO,
            "coordinate_system": spec.COORDINATE_SYSTEM,
            "gravity_vector": list(spec.GRAVITY_VECTOR),
            "prior_median_parameters": spec.PRIOR_MEDIAN_PARAMETERS,
            "jacobian_rel_step": spec.JACOBIAN_REL_STEP,
            "svd_rel_tolerance": spec.SVD_REL_TOLERANCE,
        },
        "metrics": {
            "eval_k_steps": list(spec.EVAL_K_STEPS),
            "eval_primary_k": spec.EVAL_PRIMARY_K,
            "surface_contact_tolerance_m": spec.SURFACE_CONTACT_TOLERANCE_M,
            "collision_rel_velocity_threshold_mps": spec.COLLISION_REL_VELOCITY_THRESHOLD_MPS,
            "collision_debounce_frames": spec.COLLISION_DEBOUNCE_FRAMES_COUNT,
            "collision_match_tolerance_frames": spec.COLLISION_MATCH_TOLERANCE_FRAMES_COUNT,
            "ballistic_min_frames": spec.BALLISTIC_MIN_FRAMES_COUNT,
            "bootstrap_resamples": spec.BOOTSTRAP_RESAMPLES_COUNT,
            "bootstrap_rng_seed": spec.BOOTSTRAP_RNG_SEED,
            "bootstrap_confidence_level": spec.BOOTSTRAP_CONFIDENCE_LEVEL,
        },
        "hypotheses": {
            "primary_gate": spec.PRIMARY_GATE_NAME,
            "primary_error_reduction_min": spec.PRIMARY_ERROR_REDUCTION_MIN,
            "collision_f1_non_decreasing": spec.COLLISION_F1_NON_DECREASING,
            "exploratory_hypotheses": list(spec.EXPLORATORY_HYPOTHESES),
            "h_p_similarity_max_width_ratio": spec.H_P_SIMILARITY_MAX_WIDTH_RATIO,
        },
        "budget_caps": dict(spec.BUDGET_CAPS),
        "resource_limits": dict(spec.RESOURCE_LIMITS),
        "source_digests": collect_source_digests(root),
        "generator_digests": collect_generator_digests(awz),
        "required_velocity_injection": spec.REQUIRED_VELOCITY_INJECTION,
    }
    return doc


def validate(document: Mapping[str, Any]) -> None:
    """Validate a preregistration document against frozen specification rules.

    Raises:
        SpecValidationError: If any required rule, arm parameter, threshold,
                             or budget math constraint is violated.
    """
    if not isinstance(document, Mapping):
        raise SpecValidationError(f"Document must be a mapping, got {type(document).__name__}")

    # Schema & identity
    if document.get("schema") != SCHEMA:
        raise SpecValidationError(
            f"Invalid schema: expected {SCHEMA}, got {document.get('schema')}"
        )
    if document.get("spec_name") != spec.SPEC_NAME:
        raise SpecValidationError(
            f"Invalid spec_name: expected {spec.SPEC_NAME}, got {document.get('spec_name')}"
        )
    if document.get("experiment_id") != spec.EXPERIMENT_ID:
        raise SpecValidationError(
            f"Invalid experiment_id: expected {spec.EXPERIMENT_ID}, got {document.get('experiment_id')}"
        )

    # Draft reference check
    draft_ref = document.get("prereg_draft_ref")
    if not isinstance(draft_ref, Mapping):
        raise SpecValidationError("Missing or invalid prereg_draft_ref mapping")
    if not str(draft_ref.get("sha256", "")).startswith(spec.PREREG_DRAFT_SHA256_PREFIX):
        raise SpecValidationError(
            f"Draft SHA256 must start with prefix {spec.PREREG_DRAFT_SHA256_PREFIX}"
        )

    # Arms validation
    arms = document.get("arms")
    if not isinstance(arms, (list, tuple)) or len(arms) != 7:
        raise SpecValidationError(f"Expected exactly 7 arms, got {len(arms) if arms else 0}")

    arm_ids_seen = set()
    for arm in arms:
        if not isinstance(arm, Mapping):
            raise SpecValidationError(f"Arm entry must be mapping, got {type(arm).__name__}")
        arm_id = arm.get("arm_id")
        if arm_id is None or arm_id in arm_ids_seen:
            raise SpecValidationError(f"Invalid or duplicate arm_id: {arm_id}")
        arm_ids_seen.add(arm_id)

        trainable = arm.get("trainable")
        params = arm.get("parameter_count")

        if arm_id in spec.TRAINABLE_ARM_IDS:
            if not trainable:
                raise SpecValidationError(f"Arm {arm_id} must be trainable")
            if params != spec.REGISTERED_NET_PARAMETER_COUNT:
                raise SpecValidationError(
                    f"Trainable Arm {arm_id} parameter count must equal registered "
                    f"{spec.REGISTERED_NET_PARAMETER_COUNT}, got {params}"
                )
        else:
            if trainable:
                raise SpecValidationError(f"Arm {arm_id} must not be trainable")
            if params != 0:
                raise SpecValidationError(
                    f"Non-trainable Arm {arm_id} parameter count must be 0, got {params}"
                )

        if arm_id == 4 and arm.get("tag") != "diagnostic":
            raise SpecValidationError("Arm 4 must have tag 'diagnostic'")

    if arm_ids_seen != set(range(1, 8)):
        raise SpecValidationError(f"Arm IDs must span 1 to 7, got {sorted(arm_ids_seen)}")

    # Parameter equality declaration check
    param_eq = document.get("parameter_equality")
    if not isinstance(param_eq, Mapping):
        raise SpecValidationError("Missing parameter_equality declaration")
    if tuple(param_eq.get("trainable_arms", ())) != spec.TRAINABLE_ARM_IDS:
        raise SpecValidationError("parameter_equality trainable_arms mismatch")
    if param_eq.get("registered_parameter_count") != spec.REGISTERED_NET_PARAMETER_COUNT:
        raise SpecValidationError("parameter_equality registered_parameter_count mismatch")

    # Partitions validation
    partitions = document.get("partitions")
    if not isinstance(partitions, Mapping):
        raise SpecValidationError("Missing partitions mapping")
    if partitions.get("train_worlds_per_family") != spec.TRAIN_WORLDS_PER_FAMILY:
        raise SpecValidationError("train_worlds_per_family mismatch")
    if partitions.get("dev_worlds_per_family") != spec.DEV_WORLDS_PER_FAMILY:
        raise SpecValidationError("dev_worlds_per_family mismatch")
    if partitions.get("final_worlds_per_family") != spec.FINAL_WORLDS_PER_FAMILY:
        raise SpecValidationError("final_worlds_per_family mismatch")
    if partitions.get("total_experiment_worlds") != spec.TOTAL_EXPERIMENT_WORLDS:
        raise SpecValidationError("total_experiment_worlds mismatch")

    # Training seeds validation
    seeds = document.get("training_seeds")
    if not isinstance(seeds, (list, tuple)) or len(seeds) != 3 or len(set(seeds)) != 3:
        raise SpecValidationError(f"training_seeds must be 3 unique seeds, got {seeds}")

    # Primary gate & hypotheses validation
    hypo = document.get("hypotheses")
    if not isinstance(hypo, Mapping):
        raise SpecValidationError("Missing hypotheses mapping")
    if hypo.get("primary_gate") != spec.PRIMARY_GATE_NAME:
        raise SpecValidationError(f"primary_gate must be {spec.PRIMARY_GATE_NAME}")
    if hypo.get("primary_error_reduction_min") != spec.PRIMARY_ERROR_REDUCTION_MIN:
        raise SpecValidationError(
            f"primary_error_reduction_min must be {spec.PRIMARY_ERROR_REDUCTION_MIN}, "
            f"got {hypo.get('primary_error_reduction_min')}"
        )
    if hypo.get("collision_f1_non_decreasing") is not True:
        raise SpecValidationError("collision_f1_non_decreasing must be True")

    # Metrics validation
    metrics = document.get("metrics")
    if not isinstance(metrics, Mapping):
        raise SpecValidationError("Missing metrics mapping")
    if metrics.get("eval_primary_k") != spec.EVAL_PRIMARY_K:
        raise SpecValidationError(f"eval_primary_k must be {spec.EVAL_PRIMARY_K}")
    if metrics.get("surface_contact_tolerance_m") != spec.SURFACE_CONTACT_TOLERANCE_M:
        raise SpecValidationError("surface_contact_tolerance_m mismatch")
    if metrics.get("collision_rel_velocity_threshold_mps") != spec.COLLISION_REL_VELOCITY_THRESHOLD_MPS:
        raise SpecValidationError("collision_rel_velocity_threshold_mps mismatch")

    # Budget caps arithmetic validation
    budget = document.get("budget_caps")
    if not isinstance(budget, Mapping):
        raise SpecValidationError("Missing budget_caps mapping")

    required_budget_keys = (
        "data_generation_max_seconds",
        "train_cell_compute_max_seconds",
        "training_duty_cycle",
        "train_cell_wall_max_seconds",
        "train_cells_count",
        "train_total_wall_max_seconds",
        "dev_eval_train_cell_max_seconds",
        "dev_eval_nontrain_cell_max_seconds",
        "dev_eval_total_max_seconds",
        "final_eval_max_seconds",
        "phase_total_wall_ceiling_seconds",
    )
    for key in required_budget_keys:
        val = budget.get(key)
        if val is None or not isinstance(val, (int, float)) or val <= 0:
            raise SpecValidationError(f"Budget cap '{key}' must be positive number, got {val}")

    # Duty cycle math
    data_gen = float(budget["data_generation_max_seconds"])
    train_wall = float(budget["train_total_wall_max_seconds"])
    dev_eval = float(budget["dev_eval_total_max_seconds"])
    final_eval = float(budget["final_eval_max_seconds"])
    total_ceiling = float(budget["phase_total_wall_ceiling_seconds"])

    cell_wall = float(budget["train_cell_wall_max_seconds"])
    cell_compute = float(budget["train_cell_compute_max_seconds"])
    duty = float(budget["training_duty_cycle"])
    cells_count = float(budget["train_cells_count"])
    max_train_wall = cells_count * cell_wall

    if abs(cell_wall * duty - cell_compute) > 1e-3:
        raise SpecValidationError(
            f"train_cell_compute_max_seconds ({cell_compute}) does not equal "
            f"train_cell_wall_max_seconds * training_duty_cycle ({cell_wall * duty})"
        )

    if train_wall < cell_wall or train_wall > max_train_wall:
        raise SpecValidationError(
            f"train_total_wall_max_seconds ({train_wall}) out of bounds: "
            f"must satisfy train_cell_wall_max_seconds ({cell_wall}) <= train_total_wall_max_seconds <= "
            f"train_cells_count * train_cell_wall_max_seconds ({max_train_wall})"
        )

    component_sum = data_gen + train_wall + dev_eval + final_eval
    if component_sum > total_ceiling:
        raise SpecValidationError(
            f"Budget components sum ({component_sum:.1f} s) exceeds total ceiling "
            f"phase_total_wall_ceiling_seconds ({total_ceiling:.1f} s)"
        )

    # Source digests, generator digests and velocity injection validation
    source_digests = document.get("source_digests")
    if not isinstance(source_digests, Mapping):
        raise SpecValidationError("Missing source_digests mapping")
    for src in spec.IMPLEMENTATION_SOURCES:
        if src not in source_digests:
            raise SpecValidationError(f"Missing source digest for: {src}")

    gen_digests = document.get("generator_digests")
    if not isinstance(gen_digests, Mapping):
        raise SpecValidationError("Missing generator_digests mapping")
    for gen in spec.GENERATOR_SOURCES:
        if gen not in gen_digests:
            raise SpecValidationError(f"Missing generator digest for: {gen}")

    req_vel = document.get("required_velocity_injection")
    if req_vel is None:
        raise SpecValidationError("Missing required_velocity_injection field")
    if req_vel != spec.REQUIRED_VELOCITY_INJECTION:
        raise SpecValidationError(
            f"required_velocity_injection mismatch: expected {spec.REQUIRED_VELOCITY_INJECTION}, got {req_vel}"
        )


def freeze(
    document: Mapping[str, Any],
    *,
    output_path: Path | str | None = None,
) -> tuple[dict[str, Any], str]:
    """Validate and freeze a preregistration document into canonical JSON bytes.

    Returns:
        (frozen_document, document_sha256)
    """
    frozen_doc = copy.deepcopy(dict(document))
    frozen_doc["status"] = STATUS_FROZEN

    # Validate before hashing
    validate(frozen_doc)

    raw_bytes = canonical_bytes(frozen_doc)
    digest = hashlib.sha256(raw_bytes).hexdigest()

    if output_path is not None:
        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(raw_bytes)
        write_sha256_file(target_path, digest)

    return frozen_doc, digest


def approval_line(document_sha256_hex: str) -> str:
    """Format the standard approval line for the coordinator's RESEARCH_LOG entry."""
    return f"{APPROVAL_PREFIX}{document_sha256_hex}"


def scan_approval_log(log_path: Path | str | None = None) -> dict[str, Any]:
    """Read the research log and return candidate approval lines within ## R20261029-E1-approval.

    Rules:
    - Must be within a level-2 heading matching '## R20261029-E1-approval'.
    - If multiple sections with this heading exist, refuses (ambiguous).
    - Lines inside fenced code (``` or ~~~) are ignored.
    - Lines inside blockquotes ('>') are ignored.
    - Lines indented by 4 spaces or tabs (indented code) are ignored.
    - Candidate lines must strictly match the regex: APPROVED e1-phase2 prereg document_sha256=<64hex>.
    """
    path = Path(log_path) if log_path is not None else spec.RESEARCH_LOG
    if not path.is_file():
        raise ApprovalRefused(
            [f"research log is missing: {path}"], detail={"research_log": str(path)}
        )

    text = path.read_text(encoding="utf-8")
    log_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

    rows: list[dict[str, Any]] = []
    spans: list[list[int | None]] = []
    skipped: dict[str, list[int]] = {"fenced_code": [], "blockquote": [], "indented_code": []}
    in_fence = False
    in_section = False

    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            if in_section:
                skipped["fenced_code"].append(number)
            continue

        if _ANY_H2_RE.match(stripped):
            if _SECTION_HEADING_RE.match(stripped):
                if in_section and spans:
                    spans[-1][1] = number - 1
                spans.append([number, None])
                in_section = True
            else:
                if in_section and spans:
                    spans[-1][1] = number - 1
                in_section = False
            continue

        if not in_section:
            continue

        if stripped.startswith(">"):
            skipped["blockquote"].append(number)
            continue
        if raw.startswith("    ") or raw.startswith("\t"):
            skipped["indented_code"].append(number)
            continue

        match = _APPROVAL_RE.match(stripped)
        if not match:
            continue

        rows.append(
            {
                "line": stripped,
                "line_number": number,
                "document_sha256": match.group(1),
            }
        )

    if in_section and spans and spans[-1][1] is None:
        spans[-1][1] = len(text.splitlines())

    return {
        "path": str(path),
        "log_sha256": log_sha256,
        "section": APPROVAL_SECTION,
        "section_spans": spans,
        "rows": rows,
        "skipped": skipped,
    }


def find_approval(
    log_path: Path | str | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Find and verify the single qualifying approval line in RESEARCH_LOG.md.

    Raises:
        ApprovalRefused: If the section is missing, multiple sections exist,
                         0 lines or >1 lines exist, or SHA256 does not match.
    """
    scan = scan_approval_log(log_path)
    spans = scan["section_spans"]
    rows = scan["rows"]

    if len(spans) == 0:
        raise ApprovalRefused(
            [f"approval section '## {APPROVAL_SECTION}' not found in {scan['path']}"],
            detail=scan,
        )
    if len(spans) > 1:
        raise ApprovalRefused(
            [f"multiple '## {APPROVAL_SECTION}' sections found in {scan['path']} (ambiguous)"],
            detail=scan,
        )

    if len(rows) == 0:
        raise ApprovalRefused(
            [f"no qualifying approval line found in section '## {APPROVAL_SECTION}' in {scan['path']}"],
            detail=scan,
        )
    if len(rows) > 1:
        raise ApprovalRefused(
            [
                f"multiple ({len(rows)}) qualifying approval lines found in section "
                f"'## {APPROVAL_SECTION}' in {scan['path']} (ambiguous)"
            ],
            detail=scan,
        )

    match_row = rows[0]
    found_sha256 = match_row["document_sha256"]

    if expected_sha256 is not None and found_sha256 != expected_sha256:
        raise ApprovalRefused(
            [
                f"document SHA256 mismatch in approval line: expected {expected_sha256}, "
                f"got {found_sha256}"
            ],
            detail={"expected": expected_sha256, "found": match_row},
        )

    return {
        "status": STATUS_APPROVED,
        "line": match_row["line"],
        "line_number": match_row["line_number"],
        "document_sha256": found_sha256,
        "log_path": scan["path"],
        "log_sha256": scan["log_sha256"],
    }
