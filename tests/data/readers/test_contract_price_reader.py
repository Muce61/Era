from pathlib import Path
from decimal import Decimal
import polars as pl
import pytest
from era100x.data.readers import read_contract_price, rows_logically_equal

FIXTURE = Path(__file__).parents[2] / "fixtures/stage_1/contract_price.csv"


def test_csv_reader_uses_decimal_text_and_utc_ns() -> None:
    rows = read_contract_price(FIXTURE, "BTCUSDT")
    assert rows[0].open == Decimal("100.0") and rows[0].ts_event_ns == 1577836800000000000
    assert rows[0].source_encoding == "DECIMAL_TEXT"


def test_parquet_is_float_labeled_and_logically_equal(tmp_path: Path) -> None:
    rows = read_contract_price(FIXTURE, "BTCUSDT")
    pl.DataFrame(
        {
            "timestamp": [1577836800000000000, 1577836801000000000],
            "open": [100.0, 100.5],
            "high": [101.0, 100.5],
            "low": [99.0, 100.25],
            "close": [100.5, 100.25],
            "volume": [1.25, 0.0],
        }
    ).with_columns(pl.col("timestamp").cast(pl.Datetime("ns"))).write_parquet(
        tmp_path / "x.parquet"
    )
    pq = read_contract_price(tmp_path / "x.parquet", "BTCUSDT")
    assert pq[0].source_encoding == "SOURCE_FLOAT64" and rows_logically_equal(rows, pq)


def test_invalid_and_nonmonotonic_fail(tmp_path: Path) -> None:
    p = tmp_path / "bad.csv"
    p.write_text("ts_sec,open,high,low,close,volume\n2,1,1,1,1,0\n1,1,1,1,1,0\n")
    with pytest.raises(ValueError, match="strictly increasing"):
        read_contract_price(p, "ETHUSDT")
