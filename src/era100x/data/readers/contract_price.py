from __future__ import annotations
from decimal import Decimal
from datetime import UTC
from pathlib import Path
from typing import Literal
import polars as pl
from era100x.data.schema.models import ContractPrice1s


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def read_contract_price(
    path: Path, instrument: Literal["BTCUSDT", "ETHUSDT"]
) -> list[ContractPrice1s]:
    if path.suffix == ".csv":
        frame = pl.read_csv(path, try_parse_dates=False)
        ts_name = "ts_sec"
        encoding: Literal["DECIMAL_TEXT", "SOURCE_FLOAT64"] = "DECIMAL_TEXT"
    elif path.suffix == ".parquet":
        frame = pl.read_parquet(path)
        ts_name = "timestamp"
        encoding = "SOURCE_FLOAT64"
    else:
        raise ValueError("unsupported Contract Price format")
    required = {ts_name, "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError("missing Contract Price columns")
    rows = []
    previous = -1
    for raw in frame.iter_rows(named=True):
        ts = raw[ts_name]
        ts_ns = (
            int(ts) * 1_000_000
            if ts_name == "ts_sec"
            else int(ts.replace(tzinfo=UTC).timestamp() * 1_000_000_000)
        )
        if ts_ns <= previous:
            raise ValueError("timestamps must be strictly increasing")
        previous = ts_ns
        open_, high, low, close, volume = (
            _decimal(raw[n]) for n in ("open", "high", "low", "close", "volume")
        )
        if (
            min(open_, high, low, close) <= 0
            or volume < 0
            or high < max(open_, close)
            or low > min(open_, close)
        ):
            raise ValueError("invalid OHLCV")
        rows.append(
            ContractPrice1s(
                instrument=instrument,
                ts_event_ns=ts_ns,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                source_encoding=encoding,
            )
        )
    return rows


def rows_logically_equal(left: list[ContractPrice1s], right: list[ContractPrice1s]) -> bool:
    if len(left) != len(right):
        return False
    fields = ("ts_event_ns", "open", "high", "low", "close", "volume")
    return all(
        all(getattr(a, f) == getattr(b, f) for f in fields)
        for a, b in zip(left, right, strict=True)
    )
