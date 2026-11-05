"""Tests for T6 views quota override (64 -> 82) authorized in R20261027-T6-views-82."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ainerzero.v9.teachers.benchmark_protocol import (
    EXIT_REFUSED_RESOURCE,
    BenchmarkResourceRefused,
    T6_MAX_VIEWS,
)
from ainerzero.v9.teachers.da3_controlled import (
    check_t6_views_quota,
    get_effective_t6_max_views,
)


def test_baseline_max_views_remains_64():
    """Verify that default baseline remains 64 views when no override is present."""
    assert T6_MAX_VIEWS == 64
    assert get_effective_t6_max_views(None) == 64

    # Without override, 64 is accepted, 65 is refused
    res = check_t6_views_quota(64)
    assert res["status"] == "ok"
    assert res["max_views"] == 64

    with pytest.raises(BenchmarkResourceRefused):
        check_t6_views_quota(65)


def test_views_override_via_metadata(tmp_path: Path):
    """Verify that RunStore metadata override correctly raises ceiling to 82 views."""
    db_path = tmp_path / "runs.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
    
    meta_val = {
        "task": "ainerzero.V9.T35",
        "research_log_section": "R20261027-T6-views-82",
        "authorized_by": "user",
        "user_words": "批准 T6 视图配额从 64 加到 82，只用于一次冻结的 18 视图完整标定，由 L3 名单内的代理经中央入口持锁运行。",
        "old_max_views": 64,
        "new_max_views": 82,
        "views_requested": 18,
        "timestamp": "2026-10-27T01:44:00+03:00",
    }
    cur.execute(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        ("t6_views_override_20261027", json.dumps(meta_val, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

    effective_max = get_effective_t6_max_views(db_path)
    assert effective_max == 82

    # Under 82 ceiling:
    # 64 cumulative + 18 requested = 82 <= 82: OK
    res = check_t6_views_quota(18, cumulative_views=64, max_views=effective_max)
    assert res["status"] == "ok"
    assert res["views"] == 18
    assert res["cumulative_views"] == 64
    assert res["max_views"] == 82

    # 64 cumulative + 19 requested = 83 > 82: REFUSED
    with pytest.raises(BenchmarkResourceRefused) as exc:
        check_t6_views_quota(19, cumulative_views=64, max_views=effective_max)
    assert exc.value.exit_code == EXIT_REFUSED_RESOURCE
    assert "exceeds T6 lifetime quota of 82 views" in str(exc.value)
