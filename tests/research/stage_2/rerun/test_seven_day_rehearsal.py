from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.rerun import seven_day_rehearsal as subject
from era100x.research.stage_2.rerun.orchestrator import TASKS


def _report(path: Path) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_name": "stage2-plan-v13-seven-day-rehearsal-report-v1",
        "status": "PASS",
        "day_count": 7,
        "code_commit": "a" * 40,
        "handoffs": [
            {
                "task_id": task,
                "consumer_readback": "PASS",
                "reconciliation": "PASS",
                "verify_status": "PASS",
            }
            for task in TASKS
        ],
        "authority_created": False,
        "formal_binning_snapshot_created": False,
        "formal_run_id_created": False,
        "later_tasks_executed": False,
        "stage3_locked": True,
        "ui_projection": "PENDING_EXTERNAL_BROWSER_CHECK",
    }
    payload["report_hash"] = subject.canonical_hash(payload)
    path.write_bytes(subject._encoded(payload))
    return payload


def test_verify_and_finalize_are_append_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "seven-day-rehearsal-report.json"
    report = _report(report_path)
    operations = tmp_path / "operations"
    operations.mkdir()
    monkeypatch.setattr(subject, "OPERATIONS_ROOT", operations)

    verified = subject.verify_final_code_rehearsal(report_path)
    assert verified["report_hash"] == report["report_hash"]
    receipt_path = subject.finalize_ui_projection(
        report_path=report_path,
        observed_repo_commit="a" * 40,
        observed_gate="PENDING",
    )
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "PASS"
    assert receipt["authority_created"] is False
    assert receipt["formal_binning_snapshot_created"] is False
    assert receipt["formal_run_id_created"] is False

    with pytest.raises(FileExistsError):
        subject.finalize_ui_projection(
            report_path=report_path,
            observed_repo_commit="a" * 40,
            observed_gate="PENDING",
        )


def test_verify_rejects_missing_task_handoff(tmp_path: Path) -> None:
    report_path = tmp_path / "seven-day-rehearsal-report.json"
    report = _report(report_path)
    handoffs = list(report["handoffs"])  # type: ignore[arg-type]
    report["handoffs"] = handoffs[:-1]
    report["report_hash"] = subject.canonical_hash(
        {key: value for key, value in report.items() if key != "report_hash"}
    )
    report_path.write_bytes(subject._encoded(report))

    with pytest.raises(ValueError, match="reconciliation"):
        subject.verify_final_code_rehearsal(report_path)
