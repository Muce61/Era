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
