from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from era100x.research.stage_2.baselines.conditional.outcome_run import _ingest_candidates
from era100x.research.stage_2.baselines.conditional.outcome_run import _local_sqlite_database
from era100x.research.stage_2.baselines.conditional.outcome_run import _produce_control_outcomes
from era100x.research.stage_2.baselines.conditional.v14_contracts import V14ControlCandidate

NS = 1_000_000_000


def _candidate_payload(price: Decimal = Decimal("9179.100000000000000000")) -> dict[str, object]:
    anchor = int(datetime(2025, 3, 1, 12, tzinfo=UTC).timestamp() * NS)
    candidate = V14ControlCandidate.seal(
        {
            "control_anchor_id": "1" * 64,
            "instrument": "BTCUSDT",
            "candidate_timestamp_ns": anchor,
            "high_timeframe_trend_state": "UP",
            "pre_registered_period": "P3",
            "evaluation_fold": "F2",
            "parameter_set_id": "G1-PRIMARY-V1",
            "time_combination_id": "T2",
            "label_contract_hash": "2" * 64,
            "control_entry_price": price,
            "entry_price_source_hash": "3" * 64,
            "outcome_contract_hash": "2" * 64,
            "volatility_quintile": 2,
            "activity_quintile": 3,
            "key_level_distance_quintile": 4,
            "utc_four_hour_bucket": 3,
            "utc_calendar_quarter": 1,
            "utc_calendar_year": 2025,
            "binning_snapshot_hash": "4" * 64,
            "information_span_start_ns": anchor - 3600 * NS,
            "information_span_end_ns": anchor + 600 * NS,
        }
    )
    return candidate.model_dump(mode="json")


def _write_selection(path: Path, payload: object) -> None:
    encoded = json.dumps([payload], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    pq.write_table(pa.table({"selected_candidates_json": [encoded]}), path)


def test_receiver_round_trips_canonical_decimal_string(tmp_path: Path) -> None:
    payload = _candidate_payload()
    assert payload["control_entry_price"] == "9179.100000000000000000"
    selection = tmp_path / "selection.parquet"
    _write_selection(selection, payload)
    database = sqlite3.connect(":memory:")
    try:
        assert _ingest_candidates(database, (selection,)) == 1
        stored = database.execute("SELECT payload_json,reference_price FROM candidates").fetchone()
    finally:
        database.close()

    assert stored is not None
    assert json.loads(stored[0])["control_entry_price"] == payload["control_entry_price"]
    assert stored[1] == payload["control_entry_price"]


@pytest.mark.parametrize(
    ("bad_value", "message"),
    [
        (9179, "canonical JSON decimal string"),
        ("9.1791E+3", "canonically formatted"),
        ("+9179.1", "canonically formatted"),
        ("NaN", "finite and positive"),
        ("0", "finite and positive"),
    ],
)
def test_receiver_rejects_noncanonical_or_invalid_decimal(
    tmp_path: Path, bad_value: object, message: str
) -> None:
    payload = _candidate_payload()
    payload["control_entry_price"] = bad_value
    selection = tmp_path / "selection.parquet"
    _write_selection(selection, payload)
    database = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match=message):
            _ingest_candidates(database, (selection,))
    finally:
        database.close()


def test_receiver_rejects_non_object_candidate(tmp_path: Path) -> None:
    selection = tmp_path / "selection.parquet"
    _write_selection(selection, "not-an-object")
    database = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="must be a JSON object"):
            _ingest_candidates(database, (selection,))
    finally:
        database.close()


def test_sqlite_work_database_uses_local_ephemeral_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("ERA_S2P13_LOCAL_SCRATCH_ROOT", str(scratch))
    with _local_sqlite_database() as database_path:
        assert database_path.is_relative_to(scratch)
        database = sqlite3.connect(database_path)
        database.execute("CREATE TABLE probe (value INTEGER NOT NULL)")
        database.execute("INSERT INTO probe VALUES (1)")
        database.commit()
        assert database.execute("SELECT COUNT(*) FROM probe").fetchone() == (1,)
        database.close()
        temporary_root = database_path.parent
        assert database_path.is_file()
    assert not temporary_root.exists()


def test_sqlite_work_database_rejects_external_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ERA_S2P13_LOCAL_SCRATCH_ROOT", "/Volumes/FuckingLife/t16-scratch")
    with pytest.raises(ValueError, match="cannot use an external volume"):
        with _local_sqlite_database():
            pass


def test_control_outcomes_batch_updates_and_report_fine_grained_progress(tmp_path: Path) -> None:
    payloads = [_candidate_payload(Decimal("100")), _candidate_payload(Decimal("101"))]
    payloads[1]["parameter_set_id"] = "SECONDARY"
    payloads[1]["control_entry_price"] = Decimal(str(payloads[1]["control_entry_price"]))
    second = V14ControlCandidate.seal(payloads[1]).model_dump(mode="json")
    selection = tmp_path / "selection.parquet"
    encoded = json.dumps(
        [payloads[0], second],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    pq.write_table(pa.table({"selected_candidates_json": [encoded]}), selection)
    database = sqlite3.connect(":memory:")

    class Reader:
        def read_window(
            self, *, instrument: str, start_ns: int, end_ns: int
        ) -> tuple[tuple[object, ...], tuple[object, ...], str]:
            assert instrument == "BTCUSDT"
            assert end_ns > start_ns
            return (), (), "8" * 64

        def metrics(self) -> dict[str, int]:
            return {"cache_hits": 7, "cache_misses": 2, "bytes_read": 123}

    updates: list[dict[str, object]] = []
    try:
        assert _ingest_candidates(database, (selection,)) == 2
        count, gap_matrices, gap_cells = _produce_control_outcomes(
            database,
            reader=Reader(),  # type: ignore[arg-type]
            output_path=tmp_path / "outcomes.parquet",
            total_count=2,
            progress_callback=updates.append,
        )
        stored = database.execute(
            "SELECT COUNT(*) FROM candidates WHERE matrix_id IS NOT NULL"
        ).fetchone()
    finally:
        database.close()

    assert (count, gap_matrices, gap_cells) == (2, 0, 0)
    assert stored == (2,)
    assert updates[-1] == {
        "phase": "POST_SELECTION_H2_OUTCOMES",
        "subphase": "CONTROL_OUTCOMES",
        "processed_units": 2,
        "total_units": 2,
        "physical_outcome_cache_hits": 0,
        "physical_outcome_cache_misses": 2,
        "cache_hits": 7,
        "cache_misses": 2,
        "bytes_read": 123,
    }


def test_physical_control_outcome_is_classified_once_for_reused_anchor(tmp_path: Path) -> None:
    first = _candidate_payload(Decimal("100"))
    second_payload = {**first, "control_anchor_id": "9" * 64}
    second_payload["control_entry_price"] = Decimal(str(second_payload["control_entry_price"]))
    second = V14ControlCandidate.seal(second_payload).model_dump(mode="json")
    assert first["control_candidate_id"] != second["control_candidate_id"]
    selection = tmp_path / "selection.parquet"
    encoded = json.dumps(
        [first, second],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    pq.write_table(pa.table({"selected_candidates_json": [encoded]}), selection)
    database = sqlite3.connect(":memory:")

    class Reader:
        calls = 0

        def read_window(
            self, *, instrument: str, start_ns: int, end_ns: int
        ) -> tuple[tuple[object, ...], tuple[object, ...], str]:
            self.calls += 1
            return (), (), "8" * 64

        def metrics(self) -> dict[str, int]:
            return {"cache_hits": 0, "cache_misses": 0, "bytes_read": 0}

    reader = Reader()
    progress: list[dict[str, object]] = []
    try:
        assert _ingest_candidates(database, (selection,)) == 2
        count, _, _ = _produce_control_outcomes(
            database,
            reader=reader,  # type: ignore[arg-type]
            output_path=tmp_path / "outcomes.parquet",
            total_count=2,
            progress_callback=progress.append,
        )
        matrix_ids = database.execute(
            "SELECT matrix_id FROM candidates ORDER BY control_candidate_id"
        ).fetchall()
    finally:
        database.close()

    assert count == 2
    assert reader.calls == 1
    assert len({row[0] for row in matrix_ids}) == 2
    assert progress[-1]["physical_outcome_cache_hits"] == 1
    assert progress[-1]["physical_outcome_cache_misses"] == 1
