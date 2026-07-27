from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from era100x.research.stage_2.baselines.conditional import binning_run
from era100x.research.stage_2.baselines.conditional.h2_control_reader import H2ControlReader
from era100x.research.stage_2.baselines.conditional.outcomes import H2_COVERAGE_CONTRACT_ID
from era100x.research.stage_2.baselines.conditional.v14_contracts import canonical_hash
from era100x.research.stage_2.paths.extraction.full_run import H2RowGroup

NS = 1_000_000_000


def _timestamp(day: int) -> int:
    return int(datetime(2020, 1, day, tzinfo=UTC).timestamp() * NS)


def _reader_for_overlay(path: Path, digest: str) -> H2ControlReader:
    reader = object.__new__(H2ControlReader)
    reader._overlays = {  # type: ignore[attr-defined]
        "sealed/trades.parquet": {
            "overlay_path": str(path),
            "overlay_sha256": digest,
        }
    }
    reader._verified = set()  # type: ignore[attr-defined]
    reader._cache = OrderedDict()  # type: ignore[attr-defined]
    reader._cache_hits = 0  # type: ignore[attr-defined]
    reader._cache_misses = 0  # type: ignore[attr-defined]
    reader._bytes_read = 0  # type: ignore[attr-defined]
    return reader


def test_h2_row_group_is_decoded_once_into_immutable_typed_cache(tmp_path: Path) -> None:
    path = tmp_path / "trades.parquet"
    timestamps = [_timestamp(1), _timestamp(1) + NS, _timestamp(1) + 2 * NS]
    pq.write_table(
        pa.table(
            {
                "ts_event_ns": timestamps,
                "venue_trade_id": [10, 11, 12],
                "canonical_trade_id": ["a", "b", "c"],
                "price": [Decimal("100"), Decimal("101"), Decimal("102")],
            }
        ),
        path,
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    reader = _reader_for_overlay(path, digest)
    group = H2RowGroup(
        owner_date=date(2020, 1, 1),
        source_relative_path="sealed/trades.parquet",
        source_byte_sha256="0" * 64,
        source_logical_sha256="1" * 64,
        ordinal=0,
        row_count=3,
        start_ns=timestamps[0],
        end_ns=timestamps[-1] + 1,
    )

    first = reader._group_rows(group)  # type: ignore[attr-defined]
    second = reader._group_rows(group)  # type: ignore[attr-defined]

    assert first is second
    assert first.timestamps == tuple(timestamps)
    assert tuple(row.canonical_trade_id for row in first.trades) == ("a", "b", "c")
    assert reader.metrics() == {
        "cache_hits": 1,
        "cache_misses": 1,
        "bytes_read": path.stat().st_size,
    }


def test_h2_row_group_still_fails_closed_on_stable_order_drift(tmp_path: Path) -> None:
    path = tmp_path / "unordered.parquet"
    timestamps = [_timestamp(1) + NS, _timestamp(1)]
    pq.write_table(
        pa.table(
            {
                "ts_event_ns": timestamps,
                "venue_trade_id": [11, 10],
                "canonical_trade_id": ["b", "a"],
                "price": [Decimal("101"), Decimal("100")],
            }
        ),
        path,
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    reader = _reader_for_overlay(path, digest)
    group = H2RowGroup(
        owner_date=date(2020, 1, 1),
        source_relative_path="sealed/trades.parquet",
        source_byte_sha256="0" * 64,
        source_logical_sha256="1" * 64,
        ordinal=0,
        row_count=2,
        start_ns=min(timestamps),
        end_ns=max(timestamps) + 1,
    )

    with pytest.raises(ValueError, match="frozen stable order"):
        reader._group_rows(group)  # type: ignore[attr-defined]


def test_optimized_h2_window_preserves_frozen_rows_gaps_and_source_hash(tmp_path: Path) -> None:
    path = tmp_path / "trades.parquet"
    timestamps = [_timestamp(1), _timestamp(1) + NS, _timestamp(1) + 2 * NS]
    pq.write_table(
        pa.table(
            {
                "ts_event_ns": timestamps,
                "venue_trade_id": [10, 11, 12],
                "canonical_trade_id": ["a", "b", "c"],
                "price": [Decimal("100"), Decimal("101"), Decimal("102")],
            }
        ),
        path,
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    reader = _reader_for_overlay(path, digest)
    owner_date = date(2020, 1, 1)
    group = H2RowGroup(
        owner_date=owner_date,
        source_relative_path="sealed/trades.parquet",
        source_byte_sha256="0" * 64,
        source_logical_sha256="1" * 64,
        ordinal=0,
        row_count=3,
        start_ns=timestamps[0],
        end_ns=timestamps[-1] + 1,
    )
    reader._groups = {("BTCUSDT", owner_date): (group,)}  # type: ignore[attr-defined]
    reader._quality = {("BTCUSDT", owner_date): {}}  # type: ignore[attr-defined]
    start_ns = timestamps[0]
    end_ns = timestamps[-1] + 1

    trades, gaps, source_hash = reader.read_window(
        instrument="BTCUSDT",
        start_ns=start_ns,
        end_ns=end_ns,
    )

    assert tuple(
        (trade.ts_event_ns, trade.venue_trade_id, trade.canonical_trade_id, trade.price)
        for trade in trades
    ) == (
        (timestamps[0], 10, "a", Decimal("100")),
        (timestamps[1], 11, "b", Decimal("101")),
        (timestamps[2], 12, "c", Decimal("102")),
    )
    assert gaps == ()
    assert source_hash == canonical_hash(
        {
            "instrument": "BTCUSDT",
            "start_ns": start_ns,
            "end_ns": end_ns,
            "bindings": [
                {
                    "relative_path": "sealed/trades.parquet",
                    "source_byte_sha256": "0" * 64,
                    "source_logical_sha256": "1" * 64,
                    "row_group_ordinal": 0,
                }
            ],
            "coverage_contract_id": H2_COVERAGE_CONTRACT_ID,
            "gaps": [],
        }
    )


def test_train_boundary_columns_share_one_parquet_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "features.parquet"
    pq.write_table(
        pa.table(
            {
                "anchor_ns": [3600 * NS, 3601 * NS, 9401 * NS],
                "volatility_rms_bps": [
                    Decimal("1"),
                    Decimal("2"),
                    Decimal("3"),
                ],
                "activity_count_60s": [10, 20, 30],
                "distance": [Decimal("4"), None, Decimal("6")],
            }
        ),
        path,
    )
    original = binning_run.pq.ParquetFile
    reads: list[Path] = []

    def counted_parquet_file(source: Path, **kwargs: object) -> pq.ParquetFile:
        reads.append(source)
        return original(source, **kwargs)

    monkeypatch.setattr(binning_run.pq, "ParquetFile", counted_parquet_file)
    values, source_count = binning_run._boundary_value_sets(  # type: ignore[attr-defined]
        (path,),
        columns=("volatility_rms_bps", "activity_count_60s", "distance"),
        train_start_ns=0,
        train_end_ns=10_000 * NS,
    )

    assert reads == [path]
    assert source_count == 2
    assert values == {
        "volatility_rms_bps": (Decimal("1"), Decimal("2")),
        "activity_count_60s": (Decimal("10"), Decimal("20")),
        "distance": (Decimal("4"),),
    }
