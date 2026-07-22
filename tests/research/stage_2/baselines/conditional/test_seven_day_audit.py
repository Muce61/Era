from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from era100x.research.stage_2.baselines.conditional.seven_day_audit import (
    _safe_new_output_root,
    _validate_daily_anchor_grid,
    lifecycle_assessment,
    verify_seven_day_audit,
)
from era100x.research.stage_2.baselines.conditional.v14_contracts import canonical_hash


def test_lifecycle_audit_fails_closed_when_t4_survivors_exist() -> None:
    result = lifecycle_assessment(t4_primary_expired_count=19)

    assert result["status"] == "BLOCKED"
    assert result["can_run_to_theoretical_fully_flat"] is False
    assert result["scenario_net_exitable_pnl_computed"] is False
    assert result["position_flat_claimed"] is False
    assert "LIFECYCLE_PATH_SOURCE_STOPS_AT_T4_600S" in result["blockers"]


def test_lifecycle_audit_does_not_pass_when_window_has_no_survivor() -> None:
    result = lifecycle_assessment(t4_primary_expired_count=0)

    assert result["status"] == "BLOCKED"
    assert "SEVEN_DAY_WINDOW_DID_NOT_EXERCISE_SURVIVORS_AT_T4" in result["blockers"]


def test_daily_anchor_grid_allows_deterministic_offset_change_at_midnight() -> None:
    day_ns = 86_400_000_000_000
    minute_ns = 60_000_000_000
    start_ns = 1_577_836_800_000_000_000
    offsets = (9, 42, 3, 58, 11, 27, 35)
    anchors = [
        start_ns + day * day_ns + offset * 1_000_000_000 + minute * minute_ns
        for day, offset in enumerate(offsets)
        for minute in range(1_440)
    ]

    _validate_daily_anchor_grid(anchors=anchors, start_date=date(2020, 1, 1))


def test_output_root_must_be_new_named_private_tmp_child(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="named child of /private/tmp"):
        _safe_new_output_root(Path("/var/tmp/not-authorized"))


def test_verify_rejects_tampered_report(tmp_path: Path) -> None:
    report = {
        "schema_name": "stage2-cr031-cr032-seven-day-audit",
        "status": "BLOCKED",
    }
    report["report_hash"] = canonical_hash(report)
    report["status"] = "PASS"
    report_path = tmp_path / "seven-day-audit-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="report hash mismatch"):
        verify_seven_day_audit(report_path=report_path)
