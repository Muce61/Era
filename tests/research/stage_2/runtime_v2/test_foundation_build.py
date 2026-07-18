from __future__ import annotations

from decimal import Decimal
import inspect
from pathlib import Path

import polars as pl
import pyarrow as pa
import pytest

from era100x.research.stage_2.runtime_v2.foundation_build import (
    CONTRACT_PRICE_SCHEMA,
    PRICE_BAR_SCHEMA,
    TRADE_PRIMITIVE_SCHEMA,
    aggregate_price_bars,
    aggregate_trade_seconds,
    normalize_contract_price_day,
)

H = "a" * 64


def test_trade_seconds_are_half_open_and_decimal_exact(tmp_path: Path) -> None:
    source = tmp_path / "trades.parquet"
    pl.DataFrame(
        {
            "ts_event_ns": [0, 999_999_999, 1_000_000_000],
            "quantity": [
                Decimal("1.250000000000000000"),
                Decimal("0.500000000000000000"),
                Decimal("2.000000000000000000"),
            ],
            "aggressor_side": ["BUY", "SELL", "BUY"],
        },
        schema={
            "ts_event_ns": pl.Int64,
            "quantity": pl.Decimal(38, 18),
            "aggressor_side": pl.String,
        },
    ).write_parquet(source)

    table = aggregate_trade_seconds(
        path=source,
        instrument="BTCUSDT",
        source_logical_hash=H,
        expected_source_rows=3,
    )

    assert table.schema == TRADE_PRIMITIVE_SCHEMA
    assert table.column("event_ts_ns").to_pylist() == [0, 1_000_000_000]
    assert table.column("available_at_ns").to_pylist() == [1_000_000_000, 2_000_000_000]
    assert table.column("trade_count").to_pylist() == [2, 1]
    assert table.column("aggressor_buy_qty").to_pylist() == [
        Decimal("1.250000000000000000"),
        Decimal("2.000000000000000000"),
    ]
    assert table.column("signed_qty").to_pylist() == [
        Decimal("0.750000000000000000"),
        Decimal("2.000000000000000000"),
    ]


def test_trade_seconds_merge_row_groups_without_changing_semantics(tmp_path: Path) -> None:
    source = tmp_path / "multi-row-group-trades.parquet"
    pl.DataFrame(
        {
            "ts_event_ns": [
                0,
                500_000_000,
                999_999_999,
                1_000_000_000,
                1_500_000_000,
                2_000_000_000,
            ],
            "quantity": [
                Decimal("1"),
                Decimal("2"),
                Decimal("3"),
                Decimal("4"),
                Decimal("5"),
                Decimal("6"),
            ],
            "aggressor_side": ["BUY", "SELL", "BUY", "SELL", "BUY", "SELL"],
        },
        schema={
            "ts_event_ns": pl.Int64,
            "quantity": pl.Decimal(38, 18),
            "aggressor_side": pl.String,
        },
    ).write_parquet(source, row_group_size=2)

    table = aggregate_trade_seconds(
        path=source,
        instrument="ETHUSDT",
        source_logical_hash=H,
        expected_source_rows=6,
    )

    assert table.column("event_ts_ns").to_pylist() == [0, 1_000_000_000, 2_000_000_000]
    assert table.column("trade_count").to_pylist() == [3, 2, 1]
    assert table.column("aggressor_buy_qty").to_pylist() == [
        Decimal("4.000000000000000000"),
        Decimal("5.000000000000000000"),
        Decimal("0E-18"),
    ]
    assert table.column("aggressor_sell_qty").to_pylist() == [
        Decimal("2.000000000000000000"),
        Decimal("4.000000000000000000"),
        Decimal("6.000000000000000000"),
    ]
    assert table.column("signed_qty").to_pylist() == [
        Decimal("2.000000000000000000"),
        Decimal("1.000000000000000000"),
        Decimal("-6.000000000000000000"),
    ]


def test_trade_seconds_reject_source_row_count_drift_across_row_groups(tmp_path: Path) -> None:
    source = tmp_path / "row-count-drift.parquet"
    pl.DataFrame(
        {
            "ts_event_ns": [0, 1_000_000_000, 2_000_000_000],
            "quantity": [Decimal("1"), Decimal("1"), Decimal("1")],
            "aggressor_side": ["BUY", "BUY", "BUY"],
        },
        schema={
            "ts_event_ns": pl.Int64,
            "quantity": pl.Decimal(38, 18),
            "aggressor_side": pl.String,
        },
    ).write_parquet(source, row_group_size=1)

    with pytest.raises(ValueError, match="source row mismatch"):
        aggregate_trade_seconds(
            path=source,
            instrument="BTCUSDT",
            source_logical_hash=H,
            expected_source_rows=4,
        )


def test_trade_seconds_production_path_is_explicit_row_group_streaming() -> None:
    source = inspect.getsource(aggregate_trade_seconds)

    assert "ParquetFile" in source
    assert "read_row_group" in source
    assert "scan_parquet" not in source
    assert "read_table" not in source


def test_trade_seconds_fail_on_unknown_aggressor_side(tmp_path: Path) -> None:
    source = tmp_path / "trades.parquet"
    pl.DataFrame(
        {
            "ts_event_ns": [0],
            "quantity": [Decimal("1")],
            "aggressor_side": ["UNKNOWN"],
        },
        schema={
            "ts_event_ns": pl.Int64,
            "quantity": pl.Decimal(38, 18),
            "aggressor_side": pl.String,
        },
    ).write_parquet(source)
    with pytest.raises(ValueError, match="unsupported aggressor side"):
        aggregate_trade_seconds(
            path=source,
            instrument="ETHUSDT",
            source_logical_hash=H,
        )


def test_contract_price_normalization_eliminates_binary_float_fields(tmp_path: Path) -> None:
    source = tmp_path / "BTCUSDT_1s_20200101.csv"
    source.write_text(
        "ts_sec,open,high,low,close,volume\n"
        "1000,1.1,1.2,1.0,1.15,3.5\n"
        "2000,1.15,1.25,1.1,1.2,2.0\n",
        encoding="utf-8",
    )
    table = normalize_contract_price_day(path=source, instrument="BTCUSDT")

    assert table.schema == CONTRACT_PRICE_SCHEMA
    assert table.column("event_ts_ns").to_pylist() == [1_000_000_000, 2_000_000_000]
    assert table.column("available_at_ns").to_pylist() == [2_000_000_000, 3_000_000_000]
    assert table.column("open").to_pylist() == [
        Decimal("1.100000000000000000"),
        Decimal("1.150000000000000000"),
    ]
    assert all(
        pa.types.is_decimal(table.schema.field(name).type)
        for name in ("open", "high", "low", "close", "volume")
    )


def test_price_bars_are_utc_aligned_and_only_available_at_close(tmp_path: Path) -> None:
    source = tmp_path / "BTCUSDT_1s_20200101.csv"
    source.write_text(
        "ts_sec,open,high,low,close,volume\n"
        "0,1.0,1.1,0.9,1.0,2\n"
        "1000,1.0,1.2,0.8,1.1,3\n"
        "60000,1.1,1.3,1.0,1.2,4\n",
        encoding="utf-8",
    )
    prices = normalize_contract_price_day(path=source, instrument="BTCUSDT")

    bars = aggregate_price_bars(prices, intervals=(60, 300))

    assert bars.schema == PRICE_BAR_SCHEMA
    assert bars.column("interval_seconds").to_pylist() == [60, 60, 300]
    assert bars.column("event_ts_ns").to_pylist() == [0, 60_000_000_000, 0]
    assert bars.column("available_at_ns").to_pylist() == [
        60_000_000_000,
        120_000_000_000,
        300_000_000_000,
    ]
    assert bars.column("low").to_pylist() == [
        Decimal("0.800000000000000000"),
        Decimal("1.000000000000000000"),
        Decimal("0.800000000000000000"),
    ]
