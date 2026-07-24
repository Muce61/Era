from __future__ import annotations

import hashlib
import json
from datetime import date
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

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


def test_t16_supplement_coverage_excludes_declared_gaps_without_controls(
    tmp_path: Path,
) -> None:
    for instrument in ("BTCUSDT", "ETHUSDT"):
        target = tmp_path / instrument / "first_passage.parquet"
        target.parent.mkdir()
        pq.write_table(
            pa.Table.from_pylist(
                [
                    {
                        "instrument": instrument,
                        "market_episode_id": f"episode-{instrument}",
                        "evidence_level": "H2",
                        "parameter_set_id": subject.PRIMARY_PARAMETER_SET,
                        "timing_id": subject.PRIMARY_TIMING,
                        "primary_eligible": True,
                        "variant_id": "V1_PRICE",
                        "source_quality_status": "WITH_GAPS",
                        "source_gap_codes": ["H2_VENUE_TRADE_ID_GAP"],
                    }
                ]
            ),
            target,
        )
    payload = subject.produce_scoped_conditional_baseline(
        source_first_passage_root=tmp_path,
        coverage_mode="EXCLUDE_DECLARED_GAP",
    )
    assert payload["row_count"] == 2
    assert payload["coverage_mode"] == "EXCLUDE_DECLARED_GAP"
    assert all(item["match_level"] == "EXCLUDED_SOURCE_GAP" for item in payload["probes"])
    assert all(item["selected_control_ids"] == [] for item in payload["probes"])


def test_trade_receipt_accepts_accounted_input_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_date = date(2022, 4, 15)
    root = tmp_path / "stage1"
    partition_root = root / "BTCUSDT" / "archive=2022-04" / "date=2022-04-15"
    partition_root.mkdir(parents=True)
    parquet_path = partition_root / "part-000.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ts_event_ns": 1,
                    "venue_trade_id": 1,
                    "canonical_trade_id": "a",
                    "price": "1",
                },
                {
                    "ts_event_ns": 2,
                    "venue_trade_id": 2,
                    "canonical_trade_id": "b",
                    "price": "2",
                },
            ]
        ),
        parquet_path,
    )
    receipt = {
        "instrument": "BTCUSDT",
        "date": owner_date.isoformat(),
        "byte_sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
        "input_rows": 5,
        "rows": 2,
        "duplicate_exact_count": 3,
        "venue_trade_id_gap_count": 0,
        "venue_trade_id_reversal_count": 0,
    }
    (partition_root / "partition.json").write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(subject, "STAGE1_ROOT", root)
    subject._verified_trade_receipt_day.cache_clear()

    resolved_path, partition_hash, gap = subject._verified_trade_receipt_day("BTCUSDT", owner_date)

    assert resolved_path == parquet_path
    assert partition_hash == receipt["byte_sha256"]
    assert gap is None


def test_trade_receipt_rejects_unreconciled_duplicate_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_date = date(2022, 4, 15)
    root = tmp_path / "stage1"
    partition_root = root / "BTCUSDT" / "archive=2022-04" / "date=2022-04-15"
    partition_root.mkdir(parents=True)
    parquet_path = partition_root / "part-000.parquet"
    pq.write_table(pa.Table.from_pylist([{"value": 1}, {"value": 2}]), parquet_path)
    receipt = {
        "instrument": "BTCUSDT",
        "date": owner_date.isoformat(),
        "byte_sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
        "input_rows": 6,
        "rows": 2,
        "duplicate_exact_count": 3,
        "venue_trade_id_gap_count": 0,
        "venue_trade_id_reversal_count": 0,
    }
    (partition_root / "partition.json").write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(subject, "STAGE1_ROOT", root)
    subject._verified_trade_receipt_day.cache_clear()

    with pytest.raises(ValueError, match="Stage 1 Trade partition Verify failed"):
        subject._verified_trade_receipt_day("BTCUSDT", owner_date)
