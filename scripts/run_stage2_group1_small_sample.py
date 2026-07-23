"""Read-only controlled real-window validation for Stage 2 Group 1."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl

from era100x.data.schema.models import ContractBar
from era100x.research.stage_2.key_levels.sources.common import SourceLineage
from era100x.research.stage_2.key_levels.sources.range_low import (
    RangeTimeframe,
    generate_range_lows,
)
from era100x.research.stage_2.key_levels.sources.rolling_low_1m import generate_rolling_lows_1m
from era100x.research.stage_2.key_levels.sources.rolling_low_5m import generate_rolling_lows_5m
from era100x.research.stage_2.manifests.models import canonical_json

Instrument = Literal["BTCUSDT", "ETHUSDT"]
WINDOWS = (
    ("P1", date(2020, 1, 5), date(2020, 1, 13)),
    ("P2", date(2022, 1, 2), date(2022, 1, 10)),
    ("P3", date(2023, 12, 31), date(2024, 1, 8)),
)


def _daily_paths(root: Path, instrument: Instrument, start: date, end: date) -> list[Path]:
    directory = root / f"{instrument}_1s_agg"
    result = []
    current = start
    while current < end:
        stamp = current.strftime("%Y%m%d")
        csv_path = directory / f"{instrument}_1s_{stamp}.csv"
        parquet_path = directory / f"{instrument}_1s_{stamp}.parquet"
        path = csv_path if csv_path.exists() else parquet_path
        if not path.exists():
            raise FileNotFoundError(f"missing Contract Price date: {instrument} {current}")
        result.append(path)
        current += timedelta(days=1)
    return result


def _frame(paths: list[Path]) -> pl.DataFrame:
    frames = []
    for path in paths:
        if path.suffix == ".csv":
            item = pl.read_csv(path).with_columns(
                (pl.col("ts_sec") * 1_000_000).alias("ts_event_ns")
            )
        else:
            item = pl.read_parquet(path).with_columns(
                pl.col("timestamp").dt.epoch("ns").alias("ts_event_ns")
            )
        frames.append(item.select("ts_event_ns", "open", "high", "low", "close", "volume"))
    return pl.concat(frames)


def _bars(frame: pl.DataFrame, instrument: Instrument, seconds: int) -> list[ContractBar]:
    width = seconds * 1_000_000_000
    aggregated = (
        frame.sort("ts_event_ns")
        .with_columns(((pl.col("ts_event_ns") // width) * width).alias("bucket"))
        .group_by("bucket", maintain_order=True)
        .agg(
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
        )
    )
    return [
        ContractBar(
            instrument=instrument,
            source_type="CONTRACT",
            interval_seconds=seconds,
            bucket_start_ns=int(row["bucket"]),
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=Decimal(str(row["volume"])),
        )
        for row in aggregated.iter_rows(named=True)
    ]


def validate(root: Path, code_version: str) -> dict[str, Any]:
    lineage = SourceLineage(
        "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682",
        "1" * 64,
        "2" * 64,
        code_version,
        "G1-PRIMARY-V1",
    )
    rows: list[dict[str, Any]] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for period, start, end in WINDOWS:
            paths = _daily_paths(root, instrument, start, end)
            frame = _frame(paths)
            if frame.height != 8 * 86_400:
                raise ValueError("controlled window is not complete")
            one = _bars(frame, instrument, 60)
            five = _bars(frame, instrument, 300)
            counts = {
                "rolling_low_1m": len(generate_rolling_lows_1m(one, lineage)),
                "rolling_low_5m": len(generate_rolling_lows_5m(five, lineage)),
            }
            for timeframe, seconds in (("15m", 900), ("1H", 3600), ("4H", 14400), ("1D", 86400)):
                counts[f"range_low_{timeframe}"] = len(
                    generate_range_lows(
                        _bars(frame, instrument, seconds),
                        cast(RangeTimeframe, timeframe),
                        lineage,
                    )
                )
            rows.append(
                {
                    "instrument": instrument,
                    "period": period,
                    "warmup_start": str(start),
                    "end_exclusive": str(end),
                    "rows": frame.height,
                    "counts": counts,
                }
            )
    payload = {"schema": "stage2-group1-small-sample-v1", "windows": rows}
    payload["logical_hash"] = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-price-root", type=Path, required=True)
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.contract_price_root, args.code_version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    print(payload["logical_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
