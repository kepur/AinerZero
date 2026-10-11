from __future__ import annotations

import json
from datetime import datetime

from ainerzero.core.logging import configure_logging


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_logging_produces_utc_utf8_structured_records(tmp_path):
    path = tmp_path / "logs" / "run.jsonl"
    logger = configure_logging(path, run_id="run-17")
    logger.info(
        "训练第 %d 步完成",
        17,
        extra={"event": "training.step", "fields": {"step": 17, "loss": 0.125}},
    )
    (record,) = _records(path)
    assert record["level"] == "INFO"
    assert record["event"] == "training.step"
    assert record["message"] == "训练第 17 步完成"
    assert record["run_id"] == "run-17"
    assert record["fields"] == {"step": 17, "loss": 0.125}
    assert record["timestamp"].endswith("Z")
    assert datetime.fromisoformat(record["timestamp"]).utcoffset().total_seconds() == 0


def test_reconfiguration_does_not_duplicate_records_or_cross_write(tmp_path):
    path = tmp_path / "run.jsonl"
    first = configure_logging(path, run_id="run-1")
    first.info("before")
    second = configure_logging(path, run_id="run-2")
    second.info("after")
    separate_path = tmp_path / "other.jsonl"
    separate = configure_logging(separate_path, run_id="run-3")
    separate.info("separate")
    assert first is second
    assert len(second.handlers) == 1
    assert [record["message"] for record in _records(path)] == ["before", "after"]
    assert [record["run_id"] for record in _records(path)] == ["run-1", "run-2"]
    assert [record["message"] for record in _records(separate_path)] == ["separate"]


def test_nested_secret_fields_are_redacted_without_mutating_caller(tmp_path):
    path = tmp_path / "run.jsonl"
    logger = configure_logging(path)
    fields = {
        "api_key": "private-value-a",
        "accessToken": "private-value-b",
        "nested": [{"PASSWORD": "private-value-c", "step": 7}],
        "client_secret": "private-value-d",
        "Authorization": "private-value-e",
        "loss": 0.25,
    }
    logger.info("configuration checked", extra={"fields": fields})
    raw = path.read_text()
    assert "private-value-" not in raw
    stored = _records(path)[0]["fields"]
    assert stored["nested"] == [{"PASSWORD": "[REDACTED]", "step": 7}]
    assert stored["loss"] == 0.25
    assert fields["api_key"] == "private-value-a"
    assert fields["nested"][0]["PASSWORD"] == "private-value-c"


def test_non_finite_metric_and_exception_remain_valid_json(tmp_path):
    path = tmp_path / "run.jsonl"
    logger = configure_logging(path)
    try:
        raise RuntimeError("training stopped")
    except RuntimeError:
        logger.exception("failure", extra={"fields": {"loss": float("nan")}})
    (record,) = _records(path)
    assert record["fields"]["loss"] is None
    assert "RuntimeError: training stopped" in record["exception"]
    assert "Traceback" in record["exception"]


def test_rotation_is_bounded_and_retains_complete_json_records(tmp_path):
    path = tmp_path / "run.jsonl"
    logger = configure_logging(path)
    (handler,) = logger.handlers
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3
    # Exercise rotation without writing megabytes during a CPU correctness test.
    handler.maxBytes = 700
    for step in range(40):
        logger.info("step completed", extra={"fields": {"step": step}})
    files = list(tmp_path.glob("run.jsonl*"))
    assert len(files) == 4
    for file in files:
        assert _records(file)
    assert _records(path)[-1]["fields"]["step"] == 39
