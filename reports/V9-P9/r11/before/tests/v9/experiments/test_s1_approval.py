"""Coordinator approval credential tests (V9.P10 F1/F3 + V9.P9 r3 P-1/P-4).

The only approval credential is one bare line inside the registered section of
``RESEARCH_LOG.md``:

    APPROVED s1-phase1 prereg document_sha256=<64 lowercase hex>

and only when it sits between the ``## R20261021-P1-stageA-budget`` heading and
the next level-2 heading, outside fenced code, blockquotes and indented code.
Its SHA must equal the frozen document SHA256 exactly; the preregistration
``status`` field is *not* an approval, so a self-consistent forgery (status ->
``approved`` + recomputed document SHA + rewritten sidecar) is still refused.

The log path is not a knob: ``train`` reads ``spec.RESEARCH_LOG`` only, so every
case here monkeypatches ``spec.RESEARCH_LOG`` onto a temporary file instead of
passing ``--research-log``.  The real log is never read or written.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ainerzero.v9.experiments.s1 import commands, prereg, spec, worker

from s1_testkit import (
    SECTION_HEADING,
    frozen_document,
    research_log_text,
    write_frozen,
    write_raw_log,
    write_research_log,
)

DEADLINE = 450
SUPERVISION = 500


def _args(
    tmp_path: Path,
    prereg_path: Path,
    *,
    research_log: Path | None = None,
    arm: str = "arm2",
    seed: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        mode="train",
        output_root=tmp_path / "phase1",
        prereg=prereg_path,
        limits_file=None,
        wall_budget_seconds=None,
        research_log=research_log,
        arm=arm,
        seed=seed,
    )


def _forged_approved_document() -> dict:
    """A frozen document whose status claims approval and whose SHA is consistent."""
    document = frozen_document()
    document["status"] = prereg.STATUS_APPROVED
    return document


def _canonical_log(monkeypatch, path: Path) -> Path:
    """Point ``spec.RESEARCH_LOG`` at a temporary file (P-1: no CLI redirect)."""
    monkeypatch.setattr(spec, "RESEARCH_LOG", Path(path))
    return Path(path)


def _dataset_passes(monkeypatch) -> None:
    """Skip the P-3 dataset binding for cases about the approval credential."""
    monkeypatch.setattr(
        commands.data,
        "dataset_binding_state",
        lambda root, digest: {
            "status": "passed",
            "expected_dataset_digest": digest,
            "actual_dataset_digest": digest,
        },
    )


# --- F1: status is not an approval ---------------------------------------
def test_forged_status_with_recomputed_sha_is_refused(tmp_path, monkeypatch, canonical_root):
    path, digest, document = write_frozen(tmp_path / "pre_registration.json", document=_forged_approved_document())
    assert document["status"] == prereg.STATUS_APPROVED
    log = _canonical_log(monkeypatch, write_research_log(tmp_path / "RESEARCH_LOG.md"))

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("training started from a forged status field")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report = commands.mode_train(_args(tmp_path, path))
    assert report["status"] == "refused"
    assert report["stage"] == "preregistration_not_approved"
    assert report["preregistration_status"] == prereg.STATUS_APPROVED
    assert report["status_field_is_authoritative"] is False
    assert report["approval"]["approved"] is False
    assert any("approval line" in reason for reason in report["approval"]["reasons"])


def test_cli_exit_code_is_three_when_the_approval_line_is_missing(tmp_path, monkeypatch, canonical_root):
    path, _digest, _document = write_frozen(
        tmp_path / "pre_registration.json", document=_forged_approved_document()
    )
    _canonical_log(monkeypatch, write_research_log(tmp_path / "RESEARCH_LOG.md"))
    report, code = commands.s1_phase1_command(_args(tmp_path, path))
    assert code == commands.EXIT_REFUSED_APPROVAL == 3
    assert report["stage"] == "preregistration_not_approved"


def test_approval_line_with_one_hex_digit_off_is_refused(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    broken = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    assert broken != digest
    _canonical_log(monkeypatch, write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=broken))
    report = commands.mode_train(_args(tmp_path, path))
    assert report["status"] == "refused"
    assert report["approval"]["approved"] is False
    assert report["approval"]["detail"]["frozen_document_sha256"] == digest
    assert report["approval"]["detail"]["log_approval_sha256"] == [broken]


def test_approval_line_for_an_older_document_is_refused(tmp_path, monkeypatch, canonical_root):
    older = frozen_document()
    older["created_unix"] = 900.0  # an earlier freeze of the same numbers
    _old_path, old_digest, _old = write_frozen(tmp_path / "old_pre_registration.json", document=older)
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    assert old_digest != digest
    # The coordinator approved the *old* freeze; the re-frozen document moved on.
    _canonical_log(monkeypatch, write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=old_digest))
    report = commands.mode_train(_args(tmp_path, path))
    assert report["status"] == "refused"
    assert report["approval"]["detail"]["frozen_document_sha256"] == digest
    assert report["approval"]["detail"]["log_approval_sha256"] == [old_digest]


def test_the_documented_format_inside_a_paragraph_is_not_an_approval(tmp_path, monkeypatch, canonical_root):
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")
    log = write_research_log(
        tmp_path / "RESEARCH_LOG.md",
        extra_lines=(
            "- 批准机制：格式固定为「APPROVED s1-phase1 prereg document_sha256=<64位>」，"
            "由一级写入。",
        ),
    )
    _canonical_log(monkeypatch, log)
    report = commands.mode_train(_args(tmp_path, path))
    assert report["status"] == "refused"
    assert report["approval"]["detail"]["log_approval_sha256"] == []


# --- F1: the matching line approves, and only it -------------------------
def test_matching_approval_line_approves_and_uses_the_frozen_budget(tmp_path, monkeypatch, canonical_root):
    path, digest, document = write_frozen(tmp_path / "pre_registration.json")
    # Deliberately leave status at "awaiting_coordinator_approval": approval comes
    # from the log line alone, never from the status field.
    assert document["status"] == prereg.STATUS_FROZEN
    log = _canonical_log(monkeypatch, write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest))
    _dataset_passes(monkeypatch)
    captured: dict = {}

    def _capture(mode, **kwargs):
        assert mode == "train"
        captured.update(kwargs)
        return {"status": "completed", "mode": "train", "run_id": "stub"}

    monkeypatch.setattr(commands, "_supervised_worker", _capture)
    report = commands.mode_train(_args(tmp_path, path))
    assert report["status"] == "completed"
    assert captured["budget"] == float(document["timing"]["deadline_seconds"]) == DEADLINE
    assert captured["supervision_seconds"] == float(document["timing"]["supervision_seconds"]) == SUPERVISION
    assert Path(captured["research_log"]).resolve() == log.resolve()
    assert report["run_id"] == "stub"


def test_a_cli_wall_budget_cannot_shorten_or_extend_the_frozen_deadline(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    _canonical_log(monkeypatch, write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest))
    _dataset_passes(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(
        commands,
        "_supervised_worker",
        lambda mode, **kwargs: captured.update(kwargs) or {"status": "completed"},
    )
    args = _args(tmp_path, path)
    args.wall_budget_seconds = 5.0  # must be ignored by train mode
    commands.mode_train(args)
    assert captured["budget"] == DEADLINE
    assert captured["supervision_seconds"] == SUPERVISION


# --- F3: the worker refuses on its own, independently -------------------
def test_worker_refuses_train_without_an_approval_line(tmp_path, monkeypatch, canonical_root):
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")
    log = _canonical_log(monkeypatch, write_research_log(tmp_path / "RESEARCH_LOG.md"))  # no approval line
    (tmp_path / "phase1").mkdir(exist_ok=True)
    monkeypatch.setattr(worker, "_train", _must_not_train)
    report = worker.run_worker(
        "train",
        output_root=tmp_path / "phase1",
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=DEADLINE,
        prereg_path=path,
        research_log=None,
        arm="arm2",
        seed=0,
    )
    assert report["status"] == "refused"
    assert report["refused_stage"] == "preregistration_not_approved"
    assert report["approval"]["approved"] is False
    assert "run_id" not in report  # no run was opened in the ledger


def test_worker_records_the_approval_line_and_sha_in_the_runstore(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    log = _canonical_log(monkeypatch, write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest))
    _dataset_passes(monkeypatch)
    (tmp_path / "phase1").mkdir(exist_ok=True)
    monkeypatch.setattr(worker, "_train", lambda *a, **k: {"arm_runs": [], "stub": True})
    report = worker.run_worker(
        "train",
        output_root=tmp_path / "phase1",
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=DEADLINE,
        prereg_path=path,
        research_log=None,
        arm="arm2",
        seed=0,
    )
    assert report["status"] == "completed", report.get("error")
    run_id = report["run_id"]
    from ainerzero.runtime.lifecycle import RunStore

    with RunStore(tmp_path / "phase1" / "control.sqlite3") as store:
        record = store.get_run(run_id)
    approval = record.config_snapshot["approval"]
    expected_line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
    assert approval["line"] == expected_line
    assert approval["document_sha256"] == digest
    # The recorded line number must point at the approval line itself.
    assert log.read_text(encoding="utf-8").splitlines()[approval["line_number"] - 1].strip() == expected_line
    assert approval["research_log"] == str(log)
    assert approval["research_log_sha256"] == _sha256_file(log)
    assert approval["status_field_is_authoritative"] is False


def test_approval_requires_the_exact_document_sha(tmp_path):
    _path, digest, document = write_frozen(tmp_path / "pre_registration.json")
    log = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    record = prereg.require_coordinator_approval(document, digest, log_path=log)
    assert record["approved"] is True
    with pytest.raises(prereg.ApprovalRefused):
        prereg.require_coordinator_approval(document, "f" * 64, log_path=log)
    with pytest.raises(prereg.ApprovalRefused):
        prereg.require_coordinator_approval(document, digest, log_path=tmp_path / "missing.md")


# --- P-4: the approval is scoped to the registered section ---------------
def _log_with(body: str, *, tail: str = "") -> str:
    return f"# RESEARCH_LOG fixture\n\n{body}\n{tail}"


def _refused_reasons(tmp_path, monkeypatch, text: str, canonical_root) -> list[str]:
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    log = _canonical_log(monkeypatch, write_raw_log(tmp_path / "RESEARCH_LOG.md", text))
    report = commands.mode_train(_args(tmp_path, path))
    assert report["status"] == "refused"
    assert report["approval"]["approved"] is False
    reasons = report["approval"]["reasons"]
    assert reasons
    # The refusal must be about the approval credential, not about a later gate.
    assert report["stage"] == "preregistration_not_approved"
    return reasons


def test_approval_line_inside_a_fenced_code_block_is_not_an_approval(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
    text = _log_with(
        f"{SECTION_HEADING}\n\n格式示例：\n\n```\n{line}\n```\n\n- 本节到此。"
    )
    reasons = _refused_reasons(tmp_path, monkeypatch, text, canonical_root)
    assert any("no coordinator approval line" in reason for reason in reasons)


def test_approval_line_inside_a_blockquote_is_not_an_approval(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
    text = _log_with(f"{SECTION_HEADING}\n\n> 引用别人写过的行：\n> {line}\n\n- 本节到此。")
    reasons = _refused_reasons(tmp_path, monkeypatch, text, canonical_root)
    assert any("no coordinator approval line" in reason for reason in reasons)


def test_approval_line_indented_as_code_is_not_an_approval(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
    text = _log_with(f"{SECTION_HEADING}\n\n    {line}\n\n- 本节到此。")
    reasons = _refused_reasons(tmp_path, monkeypatch, text, canonical_root)
    assert any("no coordinator approval line" in reason for reason in reasons)


def test_approval_line_in_another_section_does_not_count(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
    text = _log_with(f"## D20261012-01：别的条目\n\n{line}\n\n- 与本任务无关。")
    reasons = _refused_reasons(tmp_path, monkeypatch, text, canonical_root)
    assert any("no '## R20261021-P1-stageA-budget' section" in reason for reason in reasons)


def test_a_line_after_the_next_level_two_heading_does_not_count(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
    text = _log_with(f"{SECTION_HEADING}\n\n- 本节先讲预算。\n\n## R20261021-push-delete-authorized\n\n{line}\n")
    reasons = _refused_reasons(tmp_path, monkeypatch, text, canonical_root)
    assert any("no coordinator approval line" in reason for reason in reasons)


def test_two_qualifying_lines_in_the_section_are_refused(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
    text = _log_with(f"{SECTION_HEADING}\n\n{line}\n\n{line}\n")
    reasons = _refused_reasons(tmp_path, monkeypatch, text, canonical_root)
    assert any("2 qualifying approval lines" in reason for reason in reasons)


def test_two_sections_with_the_same_heading_are_refused(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
    text = _log_with(f"{SECTION_HEADING}\n\n- 第一次登记。\n\n{SECTION_HEADING}\n\n{line}\n")
    reasons = _refused_reasons(tmp_path, monkeypatch, text, canonical_root)
    assert any("appears 2 times" in reason for reason in reasons)


def test_section_scan_reports_skipped_lines_for_the_audit_trail(tmp_path):
    digest = "a" * 64
    line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
    text = _log_with(
        f"{SECTION_HEADING}\n\n```\n{line}\n```\n\n> {line}\n\n    {line}\n\n{line}\n"
    )
    log = write_raw_log(tmp_path / "RESEARCH_LOG.md", text)
    scan = prereg.scan_approval_log(log)
    assert scan["section_count"] == 1
    assert len(scan["rows"]) == 1
    assert text.splitlines()[scan["rows"][0]["line_number"] - 1].strip() == line
    assert len(scan["skipped"]["fenced_code"]) == 1
    assert len(scan["skipped"]["blockquote"]) == 1
    assert len(scan["skipped"]["indented_code"]) == 1
    assert scan["problems"] == []


def test_section_heading_must_be_the_registered_id(tmp_path):
    digest = "a" * 64
    line = prereg.APPROVAL_TEMPLATE.format(document_sha256=digest)
    text = _log_with(f"## R20261021-P1-stageA-budget-v2：改了名的节\n\n{line}\n")
    log = write_raw_log(tmp_path / "RESEARCH_LOG.md", text)
    scan = prereg.scan_approval_log(log)
    assert scan["section_count"] == 0
    assert scan["rows"] == []


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _must_not_train(*_args, **_kwargs):  # pragma: no cover - tripwire
    raise AssertionError("worker started training without an approval line")
