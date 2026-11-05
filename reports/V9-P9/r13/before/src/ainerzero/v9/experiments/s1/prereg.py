"""Build, freeze and verify the S1 phase-1 preregistration document.

Two stages:

1. ``draft`` -- everything that does not depend on measurement (arms, data
   identity, resource limits, metric definitions, stop rules).
2. ``freeze`` -- consumes the no-update smoke measurements, applies the frozen
   budget rule (estimate x 1.25 deadline, supervision = deadline + 50 s, per-run
   <= 20 min, phase <= 4 h) and writes ``pre_registration.json`` plus its SHA256.

The CLI never accepts a command-line override of the deadline, the supervision
timeout or the update counts: they are read from the frozen file and re-checked
by :func:`validate`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Any, Mapping

from . import spec

SCHEMA = "ainerzero.v9.s1.preregistration.v1"
TRAINABLE_ARMS = ("arm2", "arm3", "arm4")
ALL_ARMS = ("arm1", "arm2", "arm3", "arm4")
STATUS_DRAFT = "draft_awaiting_smoke"
STATUS_FROZEN = "awaiting_coordinator_approval"
STATUS_APPROVED = "approved"  # informational only; never an approval (V9.P10 F1)


def canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return spec.canonical_json(document)


def document_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def write_sha256_file(path: Path, digest: str) -> Path:
    checksum = Path(path).with_suffix(Path(path).suffix + ".sha256")
    checksum.write_text(f"{digest}  {Path(path).name}\n", encoding="utf-8")
    return checksum


# --- coordinator approval (V9.P10 F1) -------------------------------------
# The only approval credential is a bare line written by the coordinator into
# RESEARCH_LOG.md:
#
#     APPROVED s1-phase1 prereg document_sha256=<64 lowercase hex>
#
# The ``status`` field inside the frozen document is *not* an approval: whoever
# can edit the document can also rewrite status and the companion SHA256 file,
# so a self-consistent forgery would otherwise walk into the training branch.
# The log is outside the executor's write scope.
APPROVAL_PREFIX = "APPROVED s1-phase1 prereg document_sha256="
APPROVAL_TEMPLATE = APPROVAL_PREFIX + "{document_sha256}"
_APPROVAL_RE = re.compile(r"^APPROVED s1-phase1 prereg document_sha256=([0-9a-f]{64})$")

# --- the approval is scoped to one section (V9.P9 r3 / P-4) ---------------
# Only lines *inside* the ``## R20261021-P1-stageA-budget`` section count, i.e.
# from that heading to the next level-2 heading.  This closes the r2 hole where
# any line anywhere in the file approved a run: a line quoted in another entry,
# a fenced example, a blockquote, or a second competing approval line in the
# same section must not be able to decide the gate.
APPROVAL_SECTION = "R20261021-P1-stageA-budget"

# r8 (S1-R8-DECISION F6): implementation files the frozen document must carry in
# its source identity.  They are read-only additions to the identity list (the
# generic lifecycle, the D candidate loaders and the A2 trust-root manifest);
# adding a file's digest does not modify it and does not change any scientific
# value.  The real ones are bound at freeze time and re-hashed at train/verify.
IMPLEMENTATION_SOURCES = (
    "src/ainerzero/runtime/lifecycle.py",
    "src/ainerzero/core/pilot.py",
    "src/ainerzero/learning/pilot_model.py",
    "src/ainerzero/runtime/checkpoints.py",
    "reports/V9-baseline/r3/baseline_manifest.json",
)
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


def scan_approval_log(log_path: Path | str | None = None) -> dict:
    """Read the log and return only the approval lines inside the frozen section.

    Rules (V9.P9 r3, P-4):

    * the section starts at a level-2 heading whose text is
      ``R20261021-P1-stageA-budget`` and ends at the next level-2 heading;
    * lines inside a fenced code block (``` / ~~~) never count;
    * lines inside a blockquote (``>``) never count;
    * a line indented by four spaces (Markdown indented code) never counts;
    * more than one qualifying line inside the section refuses the gate;
    * more than one section with that heading refuses the gate (ambiguous).
    """
    path = Path(log_path) if log_path is not None else spec.RESEARCH_LOG
    if not path.is_file():
        raise ApprovalRefused(
            [f"research log is missing: {path}"], detail={"research_log": str(path)}
        )
    text = path.read_text(encoding="utf-8")
    log_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    rows: list[dict] = []
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
                "research_log": str(path),
                "research_log_sha256": log_sha256,
            }
        )
    if spans and spans[-1][1] is None:
        spans[-1][1] = len(text.splitlines())
    problems: list[str] = []
    if not spans:
        problems.append(
            f"no '## {APPROVAL_SECTION}' section in {path}; approval lines are only read "
            "inside that section"
        )
    elif len(spans) > 1:
        problems.append(
            f"the '## {APPROVAL_SECTION}' heading appears {len(spans)} times in {path}; "
            "an ambiguous section cannot approve a run"
        )
    if len(rows) > 1:
        problems.append(
            f"{len(rows)} qualifying approval lines inside the '## {APPROVAL_SECTION}' "
            f"section of {path} (lines {[row['line_number'] for row in rows]}); exactly one "
            "is allowed"
        )
    return {
        "research_log": str(path),
        "research_log_sha256": log_sha256,
        "approval_section": APPROVAL_SECTION,
        "section_spans": spans,
        "section_count": len(spans),
        "rows": rows,
        "skipped": skipped,
        "problems": problems,
    }


def read_approval_lines(log_path: Path | str | None = None) -> list[dict]:
    """Every qualifying approval line inside the section, in file order."""
    return scan_approval_log(log_path)["rows"]


def require_coordinator_approval(
    document: Mapping[str, Any],
    document_sha256: str,
    *,
    log_path: Path | str | None = None,
) -> dict:
    """Return the approval record, or raise ``ApprovalRefused``.

    ``document["status"]`` is recorded for the audit trail but never decides:
    only a single log line, inside the registered section, whose SHA equals the
    frozen document SHA approves a run.
    """
    path = Path(log_path) if log_path is not None else spec.RESEARCH_LOG
    scan = scan_approval_log(path)
    rows = scan["rows"]
    detail = {
        "research_log": str(path),
        "research_log_sha256": scan["research_log_sha256"],
        "approval_section": APPROVAL_SECTION,
        "section_spans": scan["section_spans"],
        "frozen_document_sha256": document_sha256,
        "log_approval_sha256": [row["document_sha256"] for row in rows],
        "log_approval_line_numbers": [row["line_number"] for row in rows],
        "skipped_lines": scan["skipped"],
        "status_field": document.get("status"),
        "status_field_is_authoritative": False,
        "expected_line": APPROVAL_TEMPLATE.format(document_sha256=document_sha256),
    }
    if scan["problems"]:
        raise ApprovalRefused(scan["problems"], detail=detail)
    if not rows:
        raise ApprovalRefused(
            [
                f"no coordinator approval line inside the '## {APPROVAL_SECTION}' section of "
                f"{path}; expected a bare line "
                f"'{APPROVAL_TEMPLATE.format(document_sha256=document_sha256)}'"
            ],
            detail=detail,
        )
    matching = [row for row in rows if row["document_sha256"] == document_sha256]
    if not matching:
        raise ApprovalRefused(
            [
                "coordinator approval line does not cover this frozen document: "
                f"{len(rows)} approval line(s) point at another document SHA256, frozen "
                f"document is {document_sha256}"
            ],
            detail=detail,
        )
    record = dict(matching[0])
    record["approved"] = True
    record["status_field"] = document.get("status")
    record["status_field_is_authoritative"] = False
    return record


def _source_identity() -> dict:
    import hashlib as _hashlib

    files = {}
    package = Path(__file__).resolve().parent
    for path in sorted(package.glob("*.py")):
        files[f"src/ainerzero/v9/experiments/s1/{path.name}"] = _hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    # The CLI entry point is part of the run entry: bind the exact file that
    # dispatches ``s1-phase1`` too, so the frozen document names the whole path.
    cli_path = spec.REPO_ROOT / "src" / "ainerzero" / "cli.py"
    if cli_path.is_file():
        files["src/ainerzero/cli.py"] = _hashlib.sha256(cli_path.read_bytes()).hexdigest()
    # r8 (S1-R8-DECISION F6): the *actual* control/load dependencies are part of
    # the frozen identity, not just the S1 adapter files.  These are read-only
    # additions to the identity list -- no scientific value changes -- so a
    # mutated generic RunStore, D-candidate loader or trust-root manifest shows up
    # as source drift instead of silently controlling a "frozen" run.
    for rel in IMPLEMENTATION_SOURCES:
        path = spec.REPO_ROOT / rel
        if path.is_file():
            files[rel] = _hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "spec": spec.spec_source_digest(),
        "package_files": files,
        "package_map_digest": _hashlib.sha256(spec.canonical_json(files)).hexdigest(),
        "repo_worktree_note": "working tree may carry other cards' changes; the prereg binds the "
        "files above, the data source map and the A2 baseline manifest, not the whole tree",
    }



def source_binding_state(document: Mapping[str, Any]) -> dict:
    """Re-hash every source file the frozen document binds (P-2).

    Shared by ``verify`` and by the ``train`` gate: a mismatch means the code
    that would run is not the code that was frozen, so a run must not start.
    """
    bound = ((document.get("source_identity") or {}).get("package_files")) or {}
    rows: dict[str, dict] = {}
    ok = bool(bound)
    for rel, expected in sorted(bound.items()):
        path = spec.REPO_ROOT / rel
        if not path.is_file():
            rows[rel] = {"present": False, "expected": expected, "match": False}
            ok = False
            continue
        actual = spec.sha256_file(path)
        match = actual == expected
        ok = ok and match
        rows[rel] = {"present": True, "expected": expected, "actual": actual, "match": match}
    drifted = sorted(rel for rel, row in rows.items() if not row["match"])
    return {
        "status": "passed" if ok else "failed",
        "rule": "re-hash the bound files at train/verify time; any drift means the frozen "
        "document no longer describes the code on disk",
        "drifted": drifted,
        "files": rows,
    }


def _arm_rows(parameter_counts: Mapping[str, Any] | None) -> dict:
    counts = dict(parameter_counts or {})
    rows = {}
    for arm_id in ALL_ARMS:
        source = dict(spec.ARM_SPECS[arm_id])
        row = {
            "arm_id": arm_id,
            "name": source["name"],
            "kind": source["kind"],
            "architecture": source["architecture"],
            "training_updates": source.get("training_updates") if arm_id == "arm1" else None,
            "seeds": list(source.get("seeds", ())),
            "incomparable": list(source.get("incomparable", ())),
        }
        if "dims" in source:
            row["dims"] = dict(source["dims"])
        if "identity" in source:
            row["identity"] = dict(source["identity"])
        count = counts.get(arm_id)
        row["parameter_count"] = int(count) if isinstance(count, int) else count
        rows[arm_id] = row
    return rows


def build_draft(
    *,
    data_identity: Mapping[str, Any],
    parameter_counts: Mapping[str, Any] | None = None,
    created_unix: float | None = None,
    experiment_id: str | None = None,
    budget_registration: str | None = None,
) -> dict:
    """Static preregistration (no smoke numbers yet).

    ``experiment_id`` / ``budget_registration`` default to the registered r1-r10
    identity.  The registered re-freeze (RESEARCH_LOG
    R20261023-S1-phase1-r11-budget, user-approved option A) registers a new
    experiment ID so the phase-1 attempt guards and phase wall budget start
    from zero for the new registration while the old experiment's rows stay
    untouched; the registration also switches the timing rule to the registered
    (non-derived) deadline.  r11 froze that registration first and r12 repeats
    it under a fresh identity after the P31 ledger incident consumed r11
    (P31-LEDGER-INCIDENT-RULING); both ids are accepted as history, the default
    is the current one.  Anything else is refused by ``build_frozen``.
    """
    registered_r11 = budget_registration == spec.R11_BUDGET_REGISTRATION
    draft = {
        "schema": SCHEMA,
        "spec": spec.SPEC_NAME,
        "task": spec.TASK_ID,
        "experiment_id": (
            experiment_id
            or (spec.CURRENT_EXPERIMENT_ID if registered_r11 else spec.EXPERIMENT_ID)
        ),
        "budget_registration": budget_registration or "RESEARCH_LOG R20261021-P1-stageA-budget",
        "status": STATUS_DRAFT,
        "created_unix": time.time() if created_unix is None else float(created_unix),
        "phase": "S1 phase 1 (structured restricted observation arms; no visual-teacher arm)",
        "arms": _arm_rows(parameter_counts),
        "training_protocol": {
            **{key: value for key, value in spec.TRAIN_COMMON.items() if key != "target_estimate_seconds"},
            "updates": None,
            "target_estimate_seconds": spec.TRAIN_COMMON["target_estimate_seconds"],
            "update_rule": "updates = floor(((target_estimate * duty / overhead) - eval_cost) / "
            "(update_cost_factor * measured_forward_loss_step_seconds)), clamped to "
            "[updates_min, updates_cap]; shrink until the frozen deadline fits the per-run cap",
        },
        "data_identity": json.loads(json.dumps(data_identity)),
        "resource_limits": dict(spec.RESOURCE_LIMITS),
        "resource_limit_sources": dict(spec.RESOURCE_LIMIT_SOURCES),
        "effective_metadata": {
            "optimizer": "AdamW",
            "single_step_prediction": True,
            "equivariant_source": "analytic normalisation (G3 estimated pose + covariance-injected "
            "error); truth-pose normalisation is upper-bound diagnostic only and is never scored",
            "forbidden": "multi-step rollout, Muon, equivariant-network/no-equivariance arms, E1 "
            "physics prior: all reserved for phase 2",
            "final_partition": "sealed; P1 全程不读 final；final 由之后单独的评测卡经封存通道读一次",
        },
        "timing": {
            "rule": "deadline = ceil(1.25 * measured_estimate); supervision = deadline + 50 s; "
            "per-run wall <= 20 min; phase-1 total wall <= 4 h",
            "deadline_factor": spec.TIMING["deadline_factor"],
            "supervision_extra_seconds": spec.TIMING["supervision_extra_seconds"],
            "per_run_wall_max_seconds": spec.TIMING["per_run_wall_max_seconds"],
            "phase_wall_max_seconds": spec.TIMING["phase_wall_max_seconds"],
            "smoke": None,
            "estimate_seconds": None,
            "deadline_seconds": None,
            "supervision_seconds": None,
            "arm1_estimate_seconds": None,
            "arm1_deadline_seconds": None,
            "arm1_supervision_seconds": None,
            "phase_wall_seconds": None,
            "phase_wall_headroom_seconds": None,
        },
        "metrics": [dict(row) for row in spec.METRIC_DEFINITIONS],
        "evaluation": {
            "query_limit": int(spec.EVALUATION["query_limit"]),
            "reporting_notes": list(spec.EVALUATION["reporting_notes"]),
        },
        "stop_rules": list(spec.STOP_RULES),
        "source_identity": _source_identity(),
        "approval_rule": {
            "credential": "one bare line inside the '## " + APPROVAL_SECTION + "' section of "
            "RESEARCH_LOG.md: " + APPROVAL_TEMPLATE,
            "document_sha256_must_equal": "the frozen document SHA256 (canonical JSON)",
            "section_scope": "only lines between the '## " + APPROVAL_SECTION + "' heading and "
            "the next level-2 heading count; fenced code, blockquotes and indented code never "
            "count; two qualifying lines in that section, or two such sections, refuse the gate",
            "log_location": "the repository RESEARCH_LOG.md only (spec.RESEARCH_LOG); a "
            "command-line path that resolves elsewhere is refused with exit 3",
            "status_field": "informational only; rewriting status and the sidecar SHA256 "
            "does not approve a run (V9.P10 F1)",
            "written_by": "coordinator (level 1); the executor never writes approval lines",
            "recorded_in": "RunStore run config_snapshot.approval (line text, line number, "
            "log SHA256, document SHA256); level 1 also sends a relay notice with the same "
            "document SHA and line number, and the reviewer compares the two (R-6)",
        },
        "commands": {
            "generate_data": "ainerzero s1-phase1 --mode data --output-root "
            "artifacts/v9/s1/phase1",
            "smoke": "ainerzero s1-phase1 --mode smoke --output-root artifacts/v9/s1/phase1",
            "freeze": "ainerzero s1-phase1 --mode freeze --output-root artifacts/v9/s1/phase1",
            "verify": "ainerzero s1-phase1 --mode verify --output-root artifacts/v9/s1/phase1",
            "eval": "ainerzero s1-phase1 --mode eval --arm {arm1,arm2,arm3,arm4} [--seed {0,1,2}] "
            "--output-root artifacts/v9/s1/phase1",
            "run_refused_here": "ainerzero s1-phase1 --mode train --arm <arm2|arm3|arm4> --seed <0|1|2> --prereg "
            "artifacts/v9/s1/phase1/pre_registration.json (refused, exit 3, unless the single "
            "approval line inside the registered RESEARCH_LOG.md section covers this document "
            "SHA256, the bound sources still match, and the dataset digest equals "
            "data_identity.dataset_digest)",
        },
        "storage": {
            "ledger_output_root": "artifacts/v9/s1/phase1/",
            "datasets": "artifacts/v9/s1/datasets/<dataset_digest>/",
            "reports": "reports/V9-P9/ holds only manifests and their SHA256",
        },
    }
    if registered_r11:
        # r11 (option A): the deadline is a user-approved registered value, not a
        # derived one; the derivation rule would compute ceil(1.25 x 993 s) =
        # 1242 s at the slowest measured P1 throughput, trip the per-run cap and
        # shrink the update count below the approved 3510.  ``registered_budget``
        # fail-closes on this path; ``validate`` refuses any document whose
        # registered deadline is not 1200 s or whose update count was reduced.
        draft["timing"].update(
            {
                "rule": "deadline is the user-approved registered value "
                f"{spec.R11_REGISTERED_DEADLINE_SECONDS} s "
                "(RESEARCH_LOG R20261023-S1-phase1-r11-budget), not ceil(1.25 x "
                "estimate); supervision = deadline + 50 s; per-run wall <= 20 min; "
                "phase-1 total wall <= 4 h",
                "deadline_source": spec.R11_DEADLINE_SOURCE,
                "registered_updates": int(spec.R11_REGISTERED_UPDATES),
                "registered_deadline_seconds": int(spec.R11_REGISTERED_DEADLINE_SECONDS),
                "registered_supervision_seconds": int(spec.R11_SUPERVISION_SECONDS),
            }
        )
        draft["training_protocol"]["update_rule"] = (
            "updates = 3510 (user-approved registered value, RESEARCH_LOG "
            "R20261023-S1-phase1-r11-budget); the derivation rule and its "
            "shrink loop do not apply to this registration"
        )
    return draft


def estimate_budget(smoke: Mapping[str, Any]) -> dict:
    """Apply the frozen rule to the smoke measurements (no command-line input)."""
    protocol = spec.TRAIN_COMMON
    timing = spec.TIMING
    per_arm = smoke["trainable_arms"]
    step_seconds = max(
        float(per_arm[arm_id]["forward_loss_step_seconds"]) for arm_id in TRAINABLE_ARMS
    )
    if not math.isfinite(step_seconds) or step_seconds <= 0:
        raise ValueError("smoke step time must be positive and finite")
    d_step = float(smoke["d_candidate"]["forward_loss_step_seconds"])
    if not math.isfinite(d_step) or d_step <= 0:
        raise ValueError("D candidate smoke step time must be positive and finite")
    duty = float(spec.RESOURCE_LIMITS["training_duty_cycle"])
    overhead = float(timing["estimate_eval_overhead_factor"])
    update_cost = float(timing["update_cost_factor"]) * step_seconds
    eval_cost = float(timing["eval_batches"]) * step_seconds * len(
        protocol["checkpoint_fractions"]
    )
    target = float(protocol["target_estimate_seconds"])
    active_budget = target * duty / overhead
    raw_updates = math.floor((active_budget - eval_cost) / update_cost)
    updates = max(int(protocol["updates_min"]), min(int(protocol["updates_cap"]), raw_updates))

    def wall_estimate(candidate: int) -> float:
        active = candidate * update_cost + eval_cost
        return (active / duty) * overhead

    estimate = wall_estimate(updates)
    deadline = math.ceil(estimate * float(timing["deadline_factor"]))
    per_run_cap = float(timing["per_run_wall_max_seconds"])
    while deadline > per_run_cap and updates > int(protocol["updates_min"]):
        updates = max(int(protocol["updates_min"]), int(updates * 0.9))
        estimate = wall_estimate(updates)
        deadline = math.ceil(estimate * float(timing["deadline_factor"]))
    if deadline > per_run_cap:
        raise ValueError(
            "measured cost cannot fit the 20 min per-run cap even at the minimum update count; "
            "the card forbids raising the cap, so the run must be re-scoped"
        )
    supervision = deadline + float(timing["supervision_extra_seconds"])
    arm1_active = float(timing["eval_batches"]) * d_step * len(protocol["checkpoint_fractions"])
    arm1_estimate = (arm1_active / duty) * overhead
    arm1_deadline = math.ceil(arm1_estimate * float(timing["deadline_factor"]))
    arm1_supervision = arm1_deadline + float(timing["supervision_extra_seconds"])
    total = (
        int(timing["trainable_runs"]) * deadline
        + int(timing["d_candidate_eval_runs"]) * arm1_deadline
        + float(smoke.get("data_generation_seconds") or 0.0)
    )
    phase_cap = float(timing["phase_wall_max_seconds"])
    return {
        "measured_forward_loss_step_seconds": step_seconds,
        "estimated_update_cost_seconds": update_cost,
        "estimated_eval_cost_seconds": eval_cost,
        "updates": int(updates),
        "target_estimate_seconds": target,
        "estimate_seconds": estimate,
        "deadline_seconds": int(deadline),
        "supervision_seconds": supervision,
        "arm1_step_seconds": d_step,
        "arm1_estimate_seconds": arm1_estimate,
        "arm1_deadline_seconds": int(arm1_deadline),
        "arm1_supervision_seconds": arm1_supervision,
        "phase_wall_seconds": float(total),
        "phase_wall_cap_seconds": phase_cap,
        "phase_wall_headroom_seconds": phase_cap - float(total),
        "fits_per_run_cap": deadline <= per_run_cap,
        "fits_phase_cap": total <= phase_cap,
    }


def registered_budget(smoke: Mapping[str, Any]) -> dict:
    """The r11 registered budget (RESEARCH_LOG R20261023-S1-phase1-r11-budget).

    Option A freezes the update count (3510) and the single-run deadline
    (1200 s) as *user-approved registered values*: they are not derived from
    the smoke estimate, and the "shrink until the deadline fits the cap" loop
    of :func:`estimate_budget` never runs on this path.  Everything else (the
    honest smoke-derived estimate at the registered update count, the arm1
    D-candidate deadline, the phase wall total) is derived by the frozen
    formulas and recorded as measured.

    Fail-closed contract (the task card's "值不是 1200、或步数被缩减，都要拒绝"):

    * the registered update count must equal ``spec.R11_REGISTERED_UPDATES``
      (3510) -- the derivation with ``eval_batches=175`` yields ~3299, so a
      caller that runs the derived path and re-labels the result as the
      registered one is refused;
    * the registered deadline must equal
      ``spec.R11_REGISTERED_DEADLINE_SECONDS`` (1200) and fit the per-run cap;
    * the smoke-derived estimate at the registered update count must not have
      been shrunk: when ceil(1.25 x estimate) exceeds the per-run cap the old
      code would cut the update count, so this path refuses instead of
      freezing a registration the measurement cannot support;
    * the phase wall total (9 x registered deadline + arm1 deadline + data
      generation) must fit the registered phase cap.
    """
    protocol = spec.TRAIN_COMMON
    timing = spec.TIMING
    updates = int(spec.R11_REGISTERED_UPDATES)
    deadline = int(spec.R11_REGISTERED_DEADLINE_SECONDS)
    per_run_cap = float(timing["per_run_wall_max_seconds"])
    phase_cap = float(timing["phase_wall_max_seconds"])

    if not int(protocol["updates_min"]) <= updates <= int(protocol["updates_cap"]):
        raise ValueError(
            f"registered update count {updates} is outside the frozen "
            f"[{protocol['updates_min']}, {protocol['updates_cap']}] range"
        )
    if deadline <= 0 or deadline > per_run_cap:
        raise ValueError(
            f"registered deadline {deadline} s does not fit the registered per-run "
            f"cap {per_run_cap} s"
        )

    per_arm = smoke["trainable_arms"]
    step_seconds = max(
        float(per_arm[arm_id]["forward_loss_step_seconds"]) for arm_id in TRAINABLE_ARMS
    )
    if not math.isfinite(step_seconds) or step_seconds <= 0:
        raise ValueError("smoke step time must be positive and finite")
    d_step = float(smoke["d_candidate"]["forward_loss_step_seconds"])
    if not math.isfinite(d_step) or d_step <= 0:
        raise ValueError("D candidate smoke step time must be positive and finite")
    duty = float(spec.RESOURCE_LIMITS["training_duty_cycle"])
    overhead = float(timing["estimate_eval_overhead_factor"])
    update_cost = float(timing["update_cost_factor"]) * step_seconds
    eval_cost = float(timing["eval_batches"]) * step_seconds * len(
        protocol["checkpoint_fractions"]
    )

    def wall_estimate(candidate: int) -> float:
        active = candidate * update_cost + eval_cost
        return (active / duty) * overhead

    estimate = wall_estimate(updates)
    derived_deadline = math.ceil(estimate * float(timing["deadline_factor"]))
    if derived_deadline > per_run_cap:
        # The derivation path would enter its shrink loop here and cut the
        # update count; the registered value must never ride on a shrunk count.
        raise ValueError(
            f"the smoke-derived deadline at {updates} updates would be "
            f"{derived_deadline} s > the {per_run_cap} s per-run cap, so the "
            "derivation path would shrink the update count; the registered "
            "budget refuses instead of freezing a reduced count"
        )
    arm1_active = float(timing["eval_batches"]) * d_step * len(protocol["checkpoint_fractions"])
    arm1_estimate = (arm1_active / duty) * overhead
    arm1_deadline = math.ceil(arm1_estimate * float(timing["deadline_factor"]))
    total = (
        int(timing["trainable_runs"]) * deadline
        + int(timing["d_candidate_eval_runs"]) * arm1_deadline
        + float(smoke.get("data_generation_seconds") or 0.0)
    )
    return {
        "measured_forward_loss_step_seconds": step_seconds,
        "estimated_update_cost_seconds": update_cost,
        "estimated_eval_cost_seconds": eval_cost,
        "updates": updates,
        "deadline_seconds": deadline,
        "supervision_seconds": int(spec.R11_SUPERVISION_SECONDS),
        "registered_deadline_seconds": deadline,
        "registered_supervision_seconds": int(spec.R11_SUPERVISION_SECONDS),
        "target_estimate_seconds": float(protocol["target_estimate_seconds"]),
        "estimate_seconds": estimate,
        "derived_deadline_seconds": int(derived_deadline),
        "deadline_source": spec.R11_DEADLINE_SOURCE,
        "arm1_step_seconds": d_step,
        "arm1_estimate_seconds": arm1_estimate,
        "arm1_deadline_seconds": int(arm1_deadline),
        "arm1_supervision_seconds": int(arm1_deadline)
        + int(timing["supervision_extra_seconds"]),
        "phase_wall_seconds": float(total),
        "phase_wall_cap_seconds": phase_cap,
        "phase_wall_headroom_seconds": phase_cap - float(total),
        "fits_per_run_cap": deadline <= per_run_cap,
        "fits_phase_cap": total <= phase_cap,
        # deep copy: the frozen document must own its measurement block, never
        # share the nested dicts with the spec constant (a shared nested dict
        # would let a document edit silently rewrite the registration).
        "measured_throughput": copy.deepcopy(spec.R11_MEASURED_THROUGHPUT),
    }


def build_frozen(
    draft: Mapping[str, Any],
    *,
    smoke: Mapping[str, Any],
    data_identity: Mapping[str, Any] | None = None,
    created_unix: float | None = None,
) -> dict:
    """Freeze the draft with the smoke-based budget (no overrides accepted).

    The r11 registration (``budget_registration`` =
    ``spec.R11_BUDGET_REGISTRATION``) takes the registered-budget path of
    :func:`registered_budget`; every other draft keeps the derived rule of
    :func:`estimate_budget`.  The branch is decided by the registration the
    draft itself declares, and both paths refuse a budget that does not fit
    the registered caps.
    """
    frozen = json.loads(json.dumps(draft))
    if frozen.get("status") not in (STATUS_DRAFT, STATUS_FROZEN):
        raise ValueError(f"cannot freeze a preregistration in status {frozen.get('status')!r}")
    registered = frozen.get("budget_registration") == spec.R11_BUDGET_REGISTRATION
    if registered:
        # r12: a freeze may only carry a *registered* identity (r11 as archived
        # history, r12 as the current re-freeze).  Any other id would give an
        # unregistered experiment a fresh attempt count and phase budget.
        if frozen.get("experiment_id") not in spec.REGISTERED_EXPERIMENT_IDS:
            raise ValueError(
                "the registered budget must carry a registered experiment id "
                f"{spec.REGISTERED_EXPERIMENT_IDS}, got {frozen.get('experiment_id')!r}"
            )
        # Fail-closed at the draft boundary: the registration the draft declares
        # must be the user-approved one.  A draft that declares the derived
        # update count (3299 with eval_batches=175) or any other deadline is a
        # reduced/moved registration and is refused before it can be frozen.
        declared = frozen.get("timing") or {}
        declared_updates = declared.get("registered_updates")
        if declared_updates is not None and int(declared_updates) != int(
            spec.R11_REGISTERED_UPDATES
        ):
            raise ValueError(
                f"draft declares registered_updates={declared_updates}, not the "
                f"user-approved {spec.R11_REGISTERED_UPDATES}; a reduced update "
                "count is refused"
            )
        declared_deadline = declared.get("registered_deadline_seconds")
        if declared_deadline is not None and int(declared_deadline) != int(
            spec.R11_REGISTERED_DEADLINE_SECONDS
        ):
            raise ValueError(
                f"draft declares registered_deadline_seconds={declared_deadline}, "
                f"not the user-approved {spec.R11_REGISTERED_DEADLINE_SECONDS} s"
            )
    budget = registered_budget(smoke) if registered else estimate_budget(smoke)
    if not budget["fits_per_run_cap"] or not budget["fits_phase_cap"]:
        raise ValueError(
            "measured budget does not fit the registered caps: "
            f"per_run={budget['fits_per_run_cap']} phase={budget['fits_phase_cap']}"
        )
    for arm_id in TRAINABLE_ARMS:
        frozen["arms"][arm_id]["training_updates"] = budget["updates"]
        frozen["arms"][arm_id]["seeds"] = list(spec.TRAIN_COMMON["seeds"])
    frozen["training_protocol"]["updates"] = budget["updates"]
    frozen["training_protocol"]["checkpoint_updates"] = [
        int(round(fraction * budget["updates"]))
        for fraction in spec.TRAIN_COMMON["checkpoint_fractions"]
    ]
    timing_update = {
        "smoke": dict(smoke),
        "estimate_seconds": budget["estimate_seconds"],
        "deadline_seconds": budget["deadline_seconds"],
        "supervision_seconds": budget["supervision_seconds"],
        "arm1_estimate_seconds": budget["arm1_estimate_seconds"],
        "arm1_deadline_seconds": budget["arm1_deadline_seconds"],
        "arm1_supervision_seconds": budget["arm1_supervision_seconds"],
        "phase_wall_seconds": budget["phase_wall_seconds"],
        "phase_wall_headroom_seconds": budget["phase_wall_headroom_seconds"],
        "measured_step_seconds": budget["measured_forward_loss_step_seconds"],
        "estimated_update_cost_seconds": budget["estimated_update_cost_seconds"],
    }
    if registered:
        # The registered path records the registration itself and the P1
        # measurement that motivated it; ``deadline_seconds`` is the approved
        # 1200 s value, never the derived one.
        timing_update.update(
            {
                "deadline_source": budget["deadline_source"],
                "registered_updates": budget["updates"],
                "registered_deadline_seconds": budget["registered_deadline_seconds"],
                "registered_supervision_seconds": budget["registered_supervision_seconds"],
                "derived_deadline_seconds": budget["derived_deadline_seconds"],
                "measured_throughput": budget["measured_throughput"],
            }
        )
    frozen["timing"].update(timing_update)
    frozen["budget_estimate"] = budget
    if data_identity is not None:
        frozen["data_identity"] = json.loads(json.dumps(data_identity))
    frozen["status"] = STATUS_FROZEN
    frozen["created_unix"] = time.time() if created_unix is None else float(created_unix)
    frozen["preregistration_sha256"] = document_sha256(frozen) if False else None
    del frozen["preregistration_sha256"]
    reasons = validate(frozen)
    if reasons:
        raise ValueError("frozen preregistration failed validation: " + "; ".join(reasons))
    return frozen


def freeze_file(
    draft_path: Path,
    *,
    out_path: Path,
    smoke: Mapping[str, Any],
    data_identity: Mapping[str, Any] | None = None,
) -> dict:
    draft = json.loads(Path(draft_path).read_text(encoding="utf-8"))
    frozen = build_frozen(draft, smoke=smoke, data_identity=data_identity)
    out_path = Path(out_path)
    out_path.write_text(
        json.dumps(frozen, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    digest = document_sha256(frozen)
    write_sha256_file(out_path, digest)
    return {"document": frozen, "sha256": digest, "path": str(out_path)}


# --- validation -----------------------------------------------------------
def validate(document: Mapping[str, Any]) -> list[str]:
    """Fail-closed structural + budget checks; returns every problem found."""
    reasons: list[str] = []
    if document.get("schema") != SCHEMA:
        reasons.append(f"preregistration schema must be {SCHEMA}")
    if document.get("task") != spec.TASK_ID:
        reasons.append("preregistration task id mismatch")
    status = document.get("status")
    if status not in (STATUS_FROZEN, STATUS_APPROVED):
        reasons.append(f"preregistration status {status!r} is not frozen/approved")
    arms = document.get("arms") or {}
    if set(arms) != set(ALL_ARMS):
        reasons.append(f"preregistration must contain exactly the four arms {ALL_ARMS}")
        return reasons
    protocol = document.get("training_protocol") or {}
    updates = protocol.get("updates")
    if not isinstance(updates, int) or updates < int(spec.TRAIN_COMMON["updates_min"]):
        reasons.append("training_protocol.updates must be a frozen integer")
    elif updates > int(spec.TRAIN_COMMON["updates_cap"]):
        reasons.append("training_protocol.updates exceeds the frozen cap")
    # r11: the registered evaluation call budget is fail-closed too.  r10
    # registered 48 while the frozen window probe needs 5 x 35 = 175 batches,
    # and every trainable-arm eval was refused; the registered value must
    # equal the frozen spec value.
    if protocol.get("eval_batches") != int(spec.TIMING["eval_batches"]):
        reasons.append(
            f"training_protocol.eval_batches {protocol.get('eval_batches')!r} differs "
            f"from the registered {spec.TIMING['eval_batches']}"
        )
    for arm_id in TRAINABLE_ARMS:
        row = arms[arm_id]
        if row.get("kind") != "trainable":
            reasons.append(f"{arm_id} must be a trainable arm")
        if row.get("training_updates") != updates:
            reasons.append(f"{arm_id} training budget differs from the shared budget")
        if list(row.get("seeds") or []) != list(spec.TRAIN_COMMON["seeds"]):
            reasons.append(f"{arm_id} seeds differ from the frozen seed set")
        count = row.get("parameter_count")
        if not isinstance(count, int) or not 100_000 <= count <= 2_000_000:
            reasons.append(f"{arm_id} parameter count {count!r} outside the registered 0.1M-2M")
        for key, expected in (
            ("optimizer", spec.TRAIN_COMMON["optimizer"]),
            ("batch_size", spec.TRAIN_COMMON["batch_size"]),
            ("sequence_steps", spec.TRAIN_COMMON["sequence_steps"]),
            ("learning_rate", spec.TRAIN_COMMON["learning_rate"]),
        ):
            if protocol.get(key) != expected:
                reasons.append(f"training_protocol.{key} differs from the frozen value")
    arm1 = arms["arm1"]
    if arm1.get("kind") != "frozen_candidate":
        reasons.append("arm1 must stay a frozen candidate (evaluate only)")
    if arm1.get("training_updates") not in (0, None):
        reasons.append("arm1 must not receive training updates")
    arm1_count = arm1.get("parameter_count")
    if not isinstance(arm1_count, int) or not 100_000 <= arm1_count <= 2_000_000:
        reasons.append("arm1 parameter count outside the registered 0.1M-2M")
    if not arm1.get("incomparable"):
        reasons.append("arm1 must record its incomparable items explicitly")

    # data identity / caps
    data = document.get("data_identity") or {}
    plan = data.get("plan") or {}
    try:
        train_worlds = int(plan["train"]["worlds"])
        dev_worlds = int(plan["development"]["worlds"])
        rounds = int(plan["train"]["rounds_per_world"])
    except (KeyError, TypeError, ValueError):
        reasons.append("data identity plan is malformed")
    else:
        caps = spec.DATA_CAPS
        if not 1 <= train_worlds <= caps["train_worlds_max"]:
            reasons.append("train world count outside the registered cap")
        if not 1 <= dev_worlds <= caps["development_worlds_max"]:
            reasons.append("development world count outside the registered cap")
        if not 1 <= rounds <= caps["rounds_per_world_max"]:
            reasons.append("rounds per world outside the registered cap")
        if plan.get("final_partition") != "not_generated_not_read":
            reasons.append("data plan does not seal the final partition")
        if "final" in (plan.get("partitions") or ()):
            reasons.append("data plan lists the sealed final partition")
    if not data.get("dataset_digest") or len(str(data.get("dataset_digest"))) != 64:
        reasons.append("data identity must carry a frozen dataset SHA256")
    if not ((data.get("source_identity") or {}).get("source_map_digest")):
        reasons.append("data identity must carry the generator source map digest")

    # resources: exact registered values (tightening only outside the frozen file)
    limits = document.get("resource_limits") or {}
    from . import resource_gate

    if resource_gate.validate_limits(limits):
        reasons.extend(resource_gate.validate_limits(limits))
    for key, value in spec.RESOURCE_LIMITS.items():
        if limits.get(key) != value:
            reasons.append(f"resource limit {key} differs from the registered {value}")

    # timing rule consistency
    timing = document.get("timing") or {}
    estimate = timing.get("estimate_seconds")
    deadline = timing.get("deadline_seconds")
    supervision = timing.get("supervision_seconds")
    registered_deadline_source = timing.get("deadline_source") == spec.R11_DEADLINE_SOURCE
    if registered_deadline_source:
        # r11 option A: the deadline is the user-approved registered value, not
        # ceil(1.25 x estimate).  Fail closed on any document that carries the
        # registration but a different deadline, a reduced update count, a
        # missing/tampered P1 measurement, or a supervision that is not
        # deadline + 50 s.
        if document.get("budget_registration") != spec.R11_BUDGET_REGISTRATION:
            reasons.append("registered deadline source without the r11 budget registration")
        if document.get("experiment_id") not in spec.REGISTERED_EXPERIMENT_IDS:
            reasons.append(
                "the registered budget must carry a registered experiment id "
                f"{spec.REGISTERED_EXPERIMENT_IDS}"
            )
        if updates != int(spec.R11_REGISTERED_UPDATES):
            reasons.append(
                f"registered updates {updates!r} is not the user-approved "
                f"{spec.R11_REGISTERED_UPDATES}; a reduced update count is refused"
            )
        if deadline != int(spec.R11_REGISTERED_DEADLINE_SECONDS):
            reasons.append(
                f"registered deadline {deadline!r} is not the user-approved "
                f"{spec.R11_REGISTERED_DEADLINE_SECONDS} s"
            )
        if supervision != int(spec.R11_SUPERVISION_SECONDS):
            reasons.append(
                f"registered supervision {supervision!r} is not deadline + "
                f"{spec.TIMING['supervision_extra_seconds']} s = "
                f"{spec.R11_SUPERVISION_SECONDS} s"
            )
        if not isinstance(estimate, (int, float)) or estimate <= 0:
            reasons.append("timing.estimate_seconds is missing")
        else:
            derived = math.ceil(float(estimate) * float(spec.TIMING["deadline_factor"]))
            if derived > spec.TIMING["per_run_wall_max_seconds"]:
                reasons.append(
                    "the smoke-derived deadline at the registered update count "
                    f"({derived} s) exceeds the per-run cap; the derivation path "
                    "would have shrunk the update count"
                )
            if timing.get("derived_deadline_seconds") != derived:
                reasons.append("derived_deadline_seconds is not ceil(1.25 x estimate)")
        throughput = timing.get("measured_throughput") or {}
        if throughput != dict(spec.R11_MEASURED_THROUGHPUT):
            reasons.append(
                "the registered P1 measured throughput block is missing or differs "
                "from the registered measurement"
            )
    elif not isinstance(estimate, (int, float)) or estimate <= 0:
        reasons.append("timing.estimate_seconds is missing")
    else:
        expected_deadline = math.ceil(float(estimate) * float(spec.TIMING["deadline_factor"]))
        if deadline != expected_deadline:
            reasons.append(
                f"deadline {deadline!r} differs from ceil(estimate x 1.25) = {expected_deadline}"
            )
        expected_supervision = expected_deadline + spec.TIMING["supervision_extra_seconds"]
        if supervision != expected_supervision:
            reasons.append("supervision is not deadline + 50 s")
        if expected_deadline > spec.TIMING["per_run_wall_max_seconds"]:
            reasons.append("per-run deadline exceeds the 20 min cap")
    arm1_deadline = timing.get("arm1_deadline_seconds")
    if not isinstance(arm1_deadline, int) or arm1_deadline <= 0:
        reasons.append("arm1 deadline is missing")
    phase = timing.get("phase_wall_seconds")
    if not isinstance(phase, (int, float)) or phase <= 0:
        reasons.append("phase wall estimate is missing")
    elif phase > spec.TIMING["phase_wall_max_seconds"]:
        reasons.append("phase wall estimate exceeds the 4 h cap")
    if isinstance(deadline, int) and isinstance(arm1_deadline, int) and isinstance(phase, (int, float)):
        recomputed = (
            spec.TIMING["trainable_runs"] * deadline
            + spec.TIMING["d_candidate_eval_runs"] * arm1_deadline
            + float((timing.get("smoke") or {}).get("data_generation_seconds") or 0.0)
        )
        if abs(recomputed - float(phase)) > 1e-6:
            reasons.append("phase wall time is not 9 x deadline + 1 x arm1 deadline + data generation")

    smoke = timing.get("smoke") or {}
    if not smoke:
        reasons.append("timing.smoke measurements are missing")
    else:
        if smoke.get("parameters_unchanged") is not True:
            reasons.append("smoke must prove parameters were unchanged")
        if smoke.get("updated_parameters") not in (False, None):
            reasons.append("smoke must not update parameters")
        measured = float(timing.get("measured_step_seconds") or 0.0)
        if measured <= 0:
            reasons.append("smoke step time is missing")
        peak = float(smoke.get("peak_process_rss_gib") or 0.0)
        if peak > spec.RESOURCE_LIMITS["process_memory_gib"]:
            reasons.append("smoke peak process memory exceeds 8 GiB")
        if float(smoke.get("peak_mlx_gib") or 0.0) > spec.RESOURCE_LIMITS["mlx_memory_gib"]:
            reasons.append("smoke peak MLX memory exceeds 4 GiB")

    metric_ids = tuple(row.get("id") for row in document.get("metrics") or ())
    expected_metrics = tuple(row["id"] for row in spec.METRIC_DEFINITIONS)
    if metric_ids != expected_metrics:
        reasons.append("metric definitions differ from the frozen S1 set")
    evaluation = document.get("evaluation")
    if not isinstance(evaluation, Mapping):
        reasons.append("evaluation.query_limit is missing")
    else:
        if "query_limit" not in evaluation:
            reasons.append("evaluation.query_limit is missing")
        elif evaluation.get("query_limit") != spec.EVALUATION["query_limit"]:
            reasons.append(
                f"evaluation.query_limit {evaluation.get('query_limit')!r} differs from "
                f"the registered {spec.EVALUATION['query_limit']}"
            )
        notes = evaluation.get("reporting_notes")
        if list(notes or ()) != list(spec.EVALUATION["reporting_notes"]):
            reasons.append("evaluation.reporting_notes differ from the registered option-A notes")
    if not document.get("stop_rules"):
        reasons.append("stop rules are missing")
    return reasons


def verify_frozen_file(path: Path) -> dict:
    """Load a frozen file, verify its companion SHA256 and re-run validation."""
    path = Path(path)
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    if not checksum_path.is_file():
        raise FileNotFoundError(f"preregistration checksum file is missing: {checksum_path}")
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    document = json.loads(path.read_text(encoding="utf-8"))
    actual = document_sha256(document)
    if actual != expected:
        raise ValueError(
            f"preregistration SHA256 mismatch: file says {expected}, document hashes to {actual}"
        )
    reasons = validate(document)
    if reasons:
        raise ValueError("preregistration failed validation: " + "; ".join(reasons))
    return {"path": str(path), "sha256": actual, "document": document}
