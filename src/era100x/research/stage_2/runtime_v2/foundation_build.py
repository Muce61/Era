"""Vectorized builders for immutable Runtime V2 foundation primitives."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import polars as pl
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

Instrument = Literal["BTCUSDT", "ETHUSDT"]
SECOND_NS = 1_000_000_000
DECIMAL = pl.Decimal(precision=38, scale=18)
TRADE_PRIMITIVE_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("event_ts_ns", pa.int64(), nullable=False),
        pa.field("second_end_ns", pa.int64(), nullable=False),
        pa.field("available_at_ns", pa.int64(), nullable=False),
        pa.field("trade_count", pa.uint64(), nullable=False),
        pa.field("aggressor_buy_count", pa.uint64(), nullable=False),
        pa.field("aggressor_sell_count", pa.uint64(), nullable=False),
        pa.field("aggressor_buy_qty", pa.decimal128(38, 18), nullable=False),
        pa.field("aggressor_sell_qty", pa.decimal128(38, 18), nullable=False),
        pa.field("signed_qty", pa.decimal128(38, 18), nullable=False),
        pa.field("source_logical_hash", pa.string(), nullable=False),
    ]
)
CONTRACT_PRICE_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("event_ts_ns", pa.int64(), nullable=False),
        pa.field("available_at_ns", pa.int64(), nullable=False),
        pa.field("open", pa.decimal128(38, 18), nullable=False),
        pa.field("high", pa.decimal128(38, 18), nullable=False),
        pa.field("low", pa.decimal128(38, 18), nullable=False),
        pa.field("close", pa.decimal128(38, 18), nullable=False),
        pa.field("volume", pa.decimal128(38, 18), nullable=False),
        pa.field("source_file_sha256", pa.string(), nullable=False),
    ]
)
PRICE_BAR_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("interval_seconds", pa.int32(), nullable=False),
        pa.field("event_ts_ns", pa.int64(), nullable=False),
        pa.field("available_at_ns", pa.int64(), nullable=False),
        pa.field("open", pa.decimal128(38, 18), nullable=False),
        pa.field("high", pa.decimal128(38, 18), nullable=False),
        pa.field("low", pa.decimal128(38, 18), nullable=False),
        pa.field("close", pa.decimal128(38, 18), nullable=False),
        pa.field("volume", pa.decimal128(38, 18), nullable=False),
        pa.field("source_file_sha256", pa.string(), nullable=False),
    ]
)
APPROVED_BAR_INTERVALS: tuple[int, ...] = (60, 300, 900, 3600, 14_400, 86_400)


def aggregate_trade_seconds(
    *,
    path: Path,
    instrument: Instrument,
    source_logical_hash: str,
    expected_source_rows: int | None = None,
) -> pa.Table:
    """Aggregate one authoritative Trades day one Parquet row group at a time."""

    _require_hash(source_logical_hash, "source_logical_hash")
    parquet = pq.ParquetFile(path)
    partials: list[pl.DataFrame] = []
    actual_source_rows = 0
    for ordinal in range(parquet.metadata.num_row_groups):
        batch = parquet.read_row_group(
            ordinal,
            columns=("ts_event_ns", "quantity", "aggressor_side"),
            use_threads=False,
        )
        actual_source_rows += batch.num_rows
        partials.append(_aggregate_trade_frame(cast(pl.DataFrame, pl.from_arrow(batch)).lazy()))
        del batch
        # Keep the list bounded even for exceptional high-volume days while
        # preserving exact Decimal sums and second ownership.
        if len(partials) == 32:
            partials = [_merge_trade_partials(partials)]
    grouped = _merge_trade_partials(partials)
    grouped = (
        grouped.with_columns(
            pl.lit(instrument).alias("instrument"),
            (pl.col("event_ts_ns") + SECOND_NS).alias("second_end_ns"),
            (pl.col("event_ts_ns") + SECOND_NS).alias("available_at_ns"),
            (pl.col("aggressor_buy_qty") - pl.col("aggressor_sell_qty")).alias("signed_qty"),
            pl.lit(source_logical_hash).alias("source_logical_hash"),
        )
        .select(TRADE_PRIMITIVE_SCHEMA.names)
        .sort("event_ts_ns")
    )
    if expected_source_rows is not None:
        if actual_source_rows != expected_source_rows:
            raise ValueError(
                f"Trade primitive source row mismatch: {actual_source_rows} != "
                f"{expected_source_rows}"
            )
    invalid_sides = grouped.filter(
        pl.col("trade_count") != pl.col("aggressor_buy_count") + pl.col("aggressor_sell_count")
    )
    if invalid_sides.height:
        raise ValueError("Stage 1 Trades contain an unsupported aggressor side")
    return grouped.to_arrow().cast(TRADE_PRIMITIVE_SCHEMA)


def _aggregate_trade_frame(source: pl.LazyFrame) -> pl.DataFrame:
    zero = pl.lit(Decimal("0"), dtype=DECIMAL)
    return (
        source.select("ts_event_ns", "quantity", "aggressor_side")
        .with_columns(pl.col("quantity").cast(DECIMAL))
        .with_columns(
            ((pl.col("ts_event_ns") // SECOND_NS) * SECOND_NS).alias("event_ts_ns"),
            pl.when(pl.col("aggressor_side") == "BUY")
            .then(pl.col("quantity"))
            .otherwise(zero)
            .alias("_buy_qty"),
            pl.when(pl.col("aggressor_side") == "SELL")
            .then(pl.col("quantity"))
            .otherwise(zero)
            .alias("_sell_qty"),
            (pl.col("aggressor_side") == "BUY").cast(pl.UInt64).alias("_buy_count"),
            (pl.col("aggressor_side") == "SELL").cast(pl.UInt64).alias("_sell_count"),
        )
        .group_by("event_ts_ns")
        .agg(
            pl.len().cast(pl.UInt64).alias("trade_count"),
            pl.col("_buy_count").sum().alias("aggressor_buy_count"),
            pl.col("_sell_count").sum().alias("aggressor_sell_count"),
            pl.col("_buy_qty").sum().alias("aggressor_buy_qty"),
            pl.col("_sell_qty").sum().alias("aggressor_sell_qty"),
        )
        .collect(engine="streaming")
    )


def _merge_trade_partials(partials: list[pl.DataFrame]) -> pl.DataFrame:
    if not partials:
        return pl.DataFrame(
            schema={
                "event_ts_ns": pl.Int64,
                "trade_count": pl.UInt64,
                "aggressor_buy_count": pl.UInt64,
                "aggressor_sell_count": pl.UInt64,
                "aggressor_buy_qty": DECIMAL,
                "aggressor_sell_qty": DECIMAL,
            }
        )
    return (
        pl.concat(partials, how="vertical", rechunk=False)
        .lazy()
        .group_by("event_ts_ns")
        .agg(
            pl.col("trade_count").sum(),
            pl.col("aggressor_buy_count").sum(),
            pl.col("aggressor_sell_count").sum(),
            pl.col("aggressor_buy_qty").sum(),
            pl.col("aggressor_sell_qty").sum(),
        )
        .sort("event_ts_ns")
        .collect(engine="streaming")
    )


def normalize_contract_price_day(
    *,
    path: Path,
    instrument: Instrument,
    expected_source_sha256: str | None = None,
) -> pa.Table:
    """Normalize one frozen Contract Price day without binary floats in V2 output."""

    if expected_source_sha256 is None:
        source_hash = sha256_file(path)
    else:
        _require_hash(expected_source_sha256, "expected_source_sha256")
        # The single-reader FoundationSourceReader has authenticated this file
        # exactly once immediately before calling the decoder.  Reuse that
        # sealed binding here so normalization does not perform a second hash
        # pass over the same source bytes.
        source_hash = expected_source_sha256
    if path.suffix == ".csv":
        frame = pl.scan_csv(path).select(
            (pl.col("ts_sec") * 1_000_000).cast(pl.Int64).alias("event_ts_ns"),
            *(pl.col(name).cast(pl.String).cast(DECIMAL).alias(name) for name in _PRICE_FIELDS),
        )
    elif path.suffix == ".parquet":
        frame = pl.scan_parquet(path).select(
            pl.col("timestamp").dt.epoch("ns").cast(pl.Int64).alias("event_ts_ns"),
            *(pl.col(name).cast(pl.String).cast(DECIMAL).alias(name) for name in _PRICE_FIELDS),
        )
    else:
        raise ValueError(f"unsupported Contract Price file: {path}")
    normalized = (
        frame.with_columns(
            pl.lit(instrument).alias("instrument"),
            (pl.col("event_ts_ns") + SECOND_NS).alias("available_at_ns"),
            pl.lit(source_hash).alias("source_file_sha256"),
        )
        .select(CONTRACT_PRICE_SCHEMA.names)
        .sort("event_ts_ns")
        .collect(engine="streaming")
    )
    if normalized["event_ts_ns"].n_unique() != normalized.height:
        raise ValueError("Contract Price day contains duplicate event timestamps")
    if not normalized["event_ts_ns"].is_sorted():
        raise ValueError("Contract Price day is not monotonic")
    return normalized.to_arrow().cast(CONTRACT_PRICE_SCHEMA)


def aggregate_price_bars(
    prices: pa.Table,
    *,
    intervals: tuple[int, ...] = APPROVED_BAR_INTERVALS,
) -> pa.Table:
    """Build approved UTC-aligned closed bars from one complete price partition."""

    if not prices.schema.equals(CONTRACT_PRICE_SCHEMA, check_metadata=False):
        raise ValueError("Contract Price input does not use the frozen foundation schema")
    if tuple(sorted(set(intervals))) != intervals or any(
        interval not in APPROVED_BAR_INTERVALS for interval in intervals
    ):
        raise ValueError("bar intervals must be unique, ordered, and preregistered")
    if prices.num_rows == 0:
        return pa.Table.from_batches([], schema=PRICE_BAR_SCHEMA)
    source = cast(pl.DataFrame, pl.from_arrow(prices)).lazy()
    outputs: list[pl.DataFrame] = []
    for interval in intervals:
        width_ns = interval * SECOND_NS
        outputs.append(
            source.with_columns(
                ((pl.col("event_ts_ns") // width_ns) * width_ns).alias("event_ts_ns")
            )
            .group_by("instrument", "event_ts_ns", maintain_order=True)
            .agg(
                pl.col("open").first(),
                pl.col("high").max(),
                pl.col("low").min(),
                pl.col("close").last(),
                pl.col("volume").sum(),
                pl.col("source_file_sha256").first(),
            )
            .with_columns(
                pl.lit(interval, dtype=pl.Int32).alias("interval_seconds"),
                (pl.col("event_ts_ns") + width_ns).alias("available_at_ns"),
            )
            .select(PRICE_BAR_SCHEMA.names)
            .collect(engine="streaming")
        )
    combined = pl.concat(outputs).sort(["interval_seconds", "event_ts_ns"])
    return combined.to_arrow().cast(PRICE_BAR_SCHEMA)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_PRICE_FIELDS = ("open", "high", "low", "close", "volume")


def _require_hash(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be lowercase SHA-256")
