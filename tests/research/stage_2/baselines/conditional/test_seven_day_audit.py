from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.baselines.conditional.seven_day_audit import (
    _safe_new_output_root,
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
