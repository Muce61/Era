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


def _write_stage1_catalog_fixture(
    *,
    root: Path,
    catalog_root: Path,
    instrument: str,
    owner_date: date,
    parquet_hash: str,
    gap_count: int = 0,
    reversal_count: int = 0,
    conflict_count: int = 0,
) -> None:
    entry = {
        "instrument": instrument,
        "date": owner_date.isoformat(),
        "relative_path": f"date={owner_date.isoformat()}/part-000.parquet",
        "byte_sha256": parquet_hash,
        "venue_trade_id_gap_count": gap_count,
        "venue_trade_id_reversal_count": reversal_count,
        "venue_trade_id_conflict_count": conflict_count,
    }
    catalog = {"logical_data_hash": "fixture-logical-hash", "entries": [entry]}
    catalog_root.mkdir(parents=True, exist_ok=True)
    (catalog_root / f"{instrument}.catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    manifest = {
        "run_id": root.name,
        "symbols": {
            instrument: {
                "logical_data_hash": "fixture-logical-hash",
                "entries": [entry],
            }
        },
    }
    manifest["manifest_sha256"] = subject._canonical_hash(manifest)
    (catalog_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_trade_partition(
    *,
    root: Path,
    instrument: str,
    owner_date: date,
    archive: str,
    rows: list[dict[str, object]],
    input_rows: int | None = None,
    duplicate_exact_count: int = 0,
    gap_count: int = 0,
    reversal_count: int = 0,
) -> tuple[Path, dict[str, object]]:
    partition_root = root / instrument / f"archive={archive}" / f"date={owner_date.isoformat()}"
    partition_root.mkdir(parents=True)
    parquet_path = partition_root / "part-000.parquet"
    pq.write_table(pa.Table.from_pylist(rows), parquet_path)
    receipt: dict[str, object] = {
        "instrument": instrument,
        "date": owner_date.isoformat(),
        "byte_sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
        "input_rows": len(rows) if input_rows is None else input_rows,
        "rows": len(rows),
        "duplicate_exact_count": duplicate_exact_count,
        "venue_trade_id_gap_count": gap_count,
        "venue_trade_id_reversal_count": reversal_count,
    }
    (partition_root / "partition.json").write_text(json.dumps(receipt), encoding="utf-8")
    return parquet_path, receipt


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


def test_nanosecond_before_midnight_stays_on_previous_utc_date() -> None:
    midnight_ns = 1_783_123_200_000_000_000

    assert subject._date_from_ns(midnight_ns - 1) == date(2026, 7, 3)
    assert subject._date_from_ns(midnight_ns) == date(2026, 7, 4)


def test_archive_layout_boundary_rehearsal_scope_is_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subject, "_git_clean", lambda: True)

    with pytest.raises(ValueError, match="archive-layout boundary"):
        subject.run_final_code_rehearsal(
            output_root=tmp_path / "not-created",
            start_date=date(2026, 6, 26),
            purpose="ARCHIVE_LAYOUT_BOUNDARY_COVERAGE",
        )

    assert not (tmp_path / "not-created").exists()


def test_archive_layout_boundary_receipt_has_distinct_schema() -> None:
    assert (
        subject._rehearsal_receipt_schema("ARCHIVE_LAYOUT_BOUNDARY_COVERAGE")
        == "stage2-archive-layout-boundary-rehearsal-v1"
    )


def test_rehearsal_progress_checkpoint_is_atomic_hashed_and_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations = tmp_path / "operations"
    monkeypatch.setattr(subject, "OPERATIONS_ROOT", operations)
    progress = subject._RehearsalProgress(
        code_commit="a" * 40,
        output_root=tmp_path / "rehearsal",
        start_date=date(2020, 1, 1),
        end_date_exclusive=date(2020, 1, 8),
        purpose="FINAL_CODE_RELEASE_GATE",
    )

    progress.update_task(
        "S2P13-T11",
        completed_units=3,
        total_units=12,
        row_count=12,
        current_instrument="ETHUSDT",
        current_date="2020-01-03",
    )
    payload = json.loads(progress.path.read_text())
    claimed_hash = payload.pop("checkpoint_hash")

    assert claimed_hash == subject._canonical_hash(payload)
    assert payload["status"] == "IN_PROGRESS"
    assert payload["overall_progress_percent"] == "4.17"
    assert payload["tasks"]["S2P13-T11"]["progress_percent"] == "25.00"
    assert payload["tasks"]["S2P13-T11"]["current_instrument"] == "ETHUSDT"
    assert payload["tasks"]["S2P13-T11"]["current_date"] == "2020-01-03"
    assert not list(operations.glob(".*.tmp"))


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
    root = tmp_path / "stage1-run"
    rows = [
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
    parquet_path, receipt = _write_trade_partition(
        root=root,
        instrument="BTCUSDT",
        owner_date=owner_date,
        archive="2022-04",
        rows=rows,
        input_rows=5,
        duplicate_exact_count=3,
    )
    catalog_root = tmp_path / "catalog"
    _write_stage1_catalog_fixture(
        root=root,
        catalog_root=catalog_root,
        instrument="BTCUSDT",
        owner_date=owner_date,
        parquet_hash=str(receipt["byte_sha256"]),
    )
    monkeypatch.setattr(subject, "STAGE1_ROOT", root)
    monkeypatch.setattr(subject, "STAGE1_CATALOG_ROOT", catalog_root)
    subject._sealed_trade_catalog_entries.cache_clear()
    subject._verified_trade_receipt_day.cache_clear()

    resolved_path, partition_hash, gap = subject._verified_trade_receipt_day("BTCUSDT", owner_date)

    assert resolved_path == parquet_path
    assert partition_hash == receipt["byte_sha256"]
    assert gap is None


def test_trade_receipt_rejects_unreconciled_duplicate_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_date = date(2022, 4, 15)
    root = tmp_path / "stage1-run"
    _, receipt = _write_trade_partition(
        root=root,
        instrument="BTCUSDT",
        owner_date=owner_date,
        archive="2022-04",
        rows=[{"value": 1}, {"value": 2}],
        input_rows=6,
        duplicate_exact_count=3,
    )
    catalog_root = tmp_path / "catalog"
    _write_stage1_catalog_fixture(
        root=root,
        catalog_root=catalog_root,
        instrument="BTCUSDT",
        owner_date=owner_date,
        parquet_hash=str(receipt["byte_sha256"]),
    )
    monkeypatch.setattr(subject, "STAGE1_ROOT", root)
    monkeypatch.setattr(subject, "STAGE1_CATALOG_ROOT", catalog_root)
    subject._sealed_trade_catalog_entries.cache_clear()
    subject._verified_trade_receipt_day.cache_clear()

    with pytest.raises(ValueError, match="Stage 1 Trade partition Verify failed"):
        subject._verified_trade_receipt_day("BTCUSDT", owner_date)


def test_trade_receipt_retains_catalog_bound_reversal_and_conflict_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_date = date(2025, 8, 29)
    root = tmp_path / "stage1-run"
    parquet_path, receipt = _write_trade_partition(
        root=root,
        instrument="ETHUSDT",
        owner_date=owner_date,
        archive="2025-08",
        rows=[{"value": 1}],
        gap_count=3,
        reversal_count=1,
    )
    catalog_root = tmp_path / "catalog"
    _write_stage1_catalog_fixture(
        root=root,
        catalog_root=catalog_root,
        instrument="ETHUSDT",
        owner_date=owner_date,
        parquet_hash=str(receipt["byte_sha256"]),
        gap_count=3,
        reversal_count=1,
        conflict_count=3,
    )
    monkeypatch.setattr(subject, "STAGE1_ROOT", root)
    monkeypatch.setattr(subject, "STAGE1_CATALOG_ROOT", catalog_root)
    subject._sealed_trade_catalog_entries.cache_clear()
    subject._verified_trade_receipt_day.cache_clear()

    resolved_path, _, quality = subject._verified_trade_receipt_day("ETHUSDT", owner_date)

    assert resolved_path == parquet_path
    assert quality is not None
    assert quality["venue_trade_id_gap_count"] == 3
    assert quality["venue_trade_id_reversal_count"] == 1
    assert quality["venue_trade_id_conflict_count"] == 3


def test_trade_receipt_rejects_reversal_count_drift_from_sealed_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_date = date(2025, 8, 29)
    root = tmp_path / "stage1-run"
    _, receipt = _write_trade_partition(
        root=root,
        instrument="ETHUSDT",
        owner_date=owner_date,
        archive="2025-08",
        rows=[{"value": 1}],
        reversal_count=1,
    )
    catalog_root = tmp_path / "catalog"
    _write_stage1_catalog_fixture(
        root=root,
        catalog_root=catalog_root,
        instrument="ETHUSDT",
        owner_date=owner_date,
        parquet_hash=str(receipt["byte_sha256"]),
        reversal_count=0,
    )
    monkeypatch.setattr(subject, "STAGE1_ROOT", root)
    monkeypatch.setattr(subject, "STAGE1_CATALOG_ROOT", catalog_root)
    subject._sealed_trade_catalog_entries.cache_clear()
    subject._verified_trade_receipt_day.cache_clear()

    with pytest.raises(ValueError, match="Stage 1 Trade partition Verify failed"):
        subject._verified_trade_receipt_day("ETHUSDT", owner_date)


@pytest.mark.parametrize(
    ("archive", "owner_date"),
    [
        ("2026-06", date(2026, 6, 30)),
        ("2026-07-01", date(2026, 7, 1)),
    ],
)
def test_trade_partition_resolver_accepts_catalog_bound_monthly_or_daily_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    archive: str,
    owner_date: date,
) -> None:
    root = tmp_path / "stage1-run"
    parquet_path, receipt = _write_trade_partition(
        root=root,
        instrument="BTCUSDT",
        owner_date=owner_date,
        archive=archive,
        rows=[{"value": 1}],
    )
    catalog_root = tmp_path / "catalog"
    _write_stage1_catalog_fixture(
        root=root,
        catalog_root=catalog_root,
        instrument="BTCUSDT",
        owner_date=owner_date,
        parquet_hash=str(receipt["byte_sha256"]),
    )
    monkeypatch.setattr(subject, "STAGE1_ROOT", root)
    monkeypatch.setattr(subject, "STAGE1_CATALOG_ROOT", catalog_root)
    subject._sealed_trade_catalog_entries.cache_clear()

    resolved, _ = subject._partition_paths("BTCUSDT", owner_date)

    assert resolved == parquet_path


def test_trade_partition_resolver_rejects_conflicting_monthly_and_daily_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_date = date(2026, 7, 1)
    root = tmp_path / "stage1-run"
    _, monthly_receipt = _write_trade_partition(
        root=root,
        instrument="BTCUSDT",
        owner_date=owner_date,
        archive="2026-07",
        rows=[{"value": 1}],
    )
    _write_trade_partition(
        root=root,
        instrument="BTCUSDT",
        owner_date=owner_date,
        archive="2026-07-01",
        rows=[{"value": 2}],
    )
    catalog_root = tmp_path / "catalog"
    _write_stage1_catalog_fixture(
        root=root,
        catalog_root=catalog_root,
        instrument="BTCUSDT",
        owner_date=owner_date,
        parquet_hash=str(monthly_receipt["byte_sha256"]),
    )
    monkeypatch.setattr(subject, "STAGE1_ROOT", root)
    monkeypatch.setattr(subject, "STAGE1_CATALOG_ROOT", catalog_root)
    subject._sealed_trade_catalog_entries.cache_clear()

    with pytest.raises(ValueError, match="conflicting Stage 1 Trade partition binding"):
        subject._partition_paths("BTCUSDT", owner_date)


def test_lifecycle_source_end_is_right_censored_at_sealed_catalog_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_ns = 1_783_036_800_000_000_000  # 2026-07-03T00:00:00Z
    data_end_ns = 1_783_123_200_000_000_000  # 2026-07-04T00:00:00Z
    monkeypatch.setattr(subject, "_sealed_trade_data_end_ns", lambda _: data_end_ns)

    end_ns, coverage = subject._bounded_lifecycle_source_end(
        instrument="BTCUSDT",
        start_ns=start_ns,
    )

    assert end_ns == data_end_ns
    assert coverage is subject.SourceCoverage.DATA_END


def test_lifecycle_source_end_keeps_complete_seven_day_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_ns = 1_577_836_800_000_000_000
    monkeypatch.setattr(
        subject,
        "_sealed_trade_data_end_ns",
        lambda _: start_ns + 8 * subject.DAY_NS,
    )

    end_ns, coverage = subject._bounded_lifecycle_source_end(
        instrument="ETHUSDT",
        start_ns=start_ns,
    )

    assert end_ns == start_ns + 7 * subject.DAY_NS
    assert coverage is subject.SourceCoverage.COMPLETE
