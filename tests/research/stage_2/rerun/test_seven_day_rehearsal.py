from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from era100x.research.stage_2.rerun import seven_day_rehearsal as subject
from era100x.research.stage_2.rerun.orchestrator import TASKS


@dataclass(frozen=True)
class _ResultFixture:
    value: Decimal


def _report(path: Path) -> dict[str, object]:
    scope_hash = subject.ExecutionScope.seal(
        mode="SEVEN_DAY",
        start_date="2020-01-01",
        end_date_exclusive="2020-01-08",
    ).execution_scope_hash
    handoffs = [
        subject._handoff(
            task,
            "fixture-rehearsal",
            {"task": task},
            1,
            root=path.parent,
            execution_scope_hash=scope_hash,
        ).payload()
        for task in TASKS
    ]
    payload: dict[str, object] = {
        "schema_name": "stage2-plan-v13-seven-day-rehearsal-report-v1",
        "status": "PASS",
        "day_count": 7,
        "code_commit": "a" * 40,
        "handoffs": handoffs,
        "authority_created": False,
        "formal_binning_snapshot_created": False,
        "formal_run_id_created": False,
        "later_tasks_executed": False,
        "stage3_locked": True,
        "ui_projection": "PENDING_EXTERNAL_BROWSER_CHECK",
        "simulated_acceptance_criteria": {
            "all_six_tasks_use_successor_core": True,
            "t12_reads_t10_and_only_binds_t11_gate": True,
            "t13_t14_share_t12_but_are_independent": True,
            "declared_gap_is_right_censored_not_win_loss": True,
            "all_handoffs_strict_readback": True,
            "all_counts_reconcile": True,
            "ui_must_observe_exact_commit": True,
            "formal_authority_bins_run_created": False,
            "stage3_locked": True,
        },
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
    assert receipt_path.name == f"seven-day-rehearsal-receipt.{'a' * 40}.json"
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


def test_canonical_hash_accepts_strict_result_objects() -> None:
    assert subject._canonical_hash(_ResultFixture(Decimal("1.230"))) == subject._canonical_hash(
        {"value": "1.230"}
    )
