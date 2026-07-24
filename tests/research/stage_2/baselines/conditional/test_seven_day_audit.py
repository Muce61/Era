from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from era100x.research.stage_2.baselines.conditional.seven_day_audit import (
    _expected_typed_exclusions,
    _safe_new_output_root,
    _validate_audit_scope,
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


def test_trade_supplement_scope_is_explicit_and_does_not_relax_source_boundary() -> None:
    _validate_audit_scope(
        start_date=date(2022, 2, 27),
        audit_mode="TRADE_SUPPLEMENT_COVERAGE",
    )
    with pytest.raises(ValueError, match="2020-01-01"):
        _validate_audit_scope(
            start_date=date(2022, 2, 27),
            audit_mode="SOURCE_BOUNDARY",
        )
    with pytest.raises(ValueError, match="must contain"):
        _validate_audit_scope(
            start_date=date(2022, 3, 2),
            audit_mode="TRADE_SUPPLEMENT_COVERAGE",
        )


def test_trade_supplement_mid_history_allows_fully_warmed_feature_grid() -> None:
    assert _expected_typed_exclusions("TRADE_SUPPLEMENT_COVERAGE") == {}
    assert _expected_typed_exclusions("SEALED_RECEIPT_COVERAGE") == {}
    assert _expected_typed_exclusions("ARCHIVE_LAYOUT_BOUNDARY_COVERAGE") == {}
    assert _expected_typed_exclusions("SOURCE_BOUNDARY") == {"BOUNDARY_WARMUP_UNAVAILABLE": 61}


def test_sealed_receipt_scope_must_cover_duplicate_input_partition() -> None:
    _validate_audit_scope(
        start_date=date(2022, 4, 12),
        audit_mode="SEALED_RECEIPT_COVERAGE",
    )
    with pytest.raises(ValueError, match="must contain"):
        _validate_audit_scope(
            start_date=date(2022, 4, 16),
            audit_mode="SEALED_RECEIPT_COVERAGE",
        )


def test_archive_layout_boundary_audit_scope_is_frozen() -> None:
    _validate_audit_scope(
        start_date=date(2026, 6, 27),
        audit_mode="ARCHIVE_LAYOUT_BOUNDARY_COVERAGE",
    )
    with pytest.raises(ValueError, match="must start on 2026-06-27"):
        _validate_audit_scope(
            start_date=date(2026, 6, 26),
            audit_mode="ARCHIVE_LAYOUT_BOUNDARY_COVERAGE",
        )


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
