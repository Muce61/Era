from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import polars as pl

from era100x.data.schema.models import ContractBar, ContractPrice1s
from era100x.research.stage_2.contracts.models import RawKeyLevel
from era100x.research.stage_2.episodes.hold import detect_hold
from era100x.research.stage_2.episodes.identity import build_market_episode
from era100x.research.stage_2.episodes.reclaim import detect_reclaim
from era100x.research.stage_2.episodes.sweep import detect_sweep
from era100x.research.stage_2.gates.price import evaluate_price_trigger
from era100x.research.stage_2.key_levels.arbitration import arbitrate_key_levels
from era100x.research.stage_2.key_levels.sources.common import SourceLineage
from era100x.research.stage_2.key_levels.sources.range_low import generate_range_lows
from era100x.research.stage_2.key_levels.sources.rolling_low_1m import generate_rolling_lows_1m
from era100x.research.stage_2.key_levels.sources.rolling_low_5m import generate_rolling_lows_5m
from era100x.research.stage_2.manifests.configuration import parameter_sets, timing_configurations

Instrument = Literal["BTCUSDT", "ETHUSDT"]
SECOND_NS = 1_000_000_000
DAY_NS = 86_400 * SECOND_NS
MINUTE_NS = 60 * SECOND_NS


def owns_sweep_start(minute_start_ns: int, sweep_start_ns: int) -> bool:
    """Return whether this UTC minute seed uniquely owns the Sweep start fact."""

    return minute_start_ns <= sweep_start_ns < minute_start_ns + MINUTE_NS


def _path(root: Path, instrument: Instrument, day: date) -> Path:
    directory = root / f"{instrument}_1s_agg"
    stamp = day.strftime("%Y%m%d")
    csv_path = directory / f"{instrument}_1s_{stamp}.csv"
    parquet_path = directory / f"{instrument}_1s_{stamp}.parquet"
    path = csv_path if csv_path.exists() else parquet_path
    if not path.exists():
        raise FileNotFoundError(f"missing Contract Price: {instrument} {day}")
    return path


def _read(path: Path) -> pl.DataFrame:
    if path.suffix == ".csv":
        return pl.read_csv(path).select(
            (pl.col("ts_sec") * 1_000_000).alias("ts_event_ns"),
            "open",
            "high",
            "low",
            "close",
            "volume",
        )
    return pl.read_parquet(path).select(
        pl.col("timestamp").dt.epoch("ns").alias("ts_event_ns"),
        "open",
        "high",
        "low",
        "close",
        "volume",
    )


def _bars(frame: pl.DataFrame, instrument: Instrument, seconds: int) -> list[ContractBar]:
    width = seconds * SECOND_NS
    grouped = (
        frame.sort("ts_event_ns")
        .with_columns(((pl.col("ts_event_ns") // width) * width).alias("bucket"))
        .group_by("bucket", maintain_order=True)
        .agg(
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
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
        for row in grouped.iter_rows(named=True)
    ]


def _price_rows(frame: pl.DataFrame, instrument: Instrument) -> list[ContractPrice1s]:
    return [
        ContractPrice1s(
            instrument=instrument,
            ts_event_ns=int(row["ts_event_ns"]),
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=Decimal(str(row["volume"])),
            source_encoding="DECIMAL_TEXT"
            if frame.schema["open"] == pl.String
            else "SOURCE_FLOAT64",
        )
        for row in frame.iter_rows(named=True)
    ]


def _raw_levels(
    frame: pl.DataFrame, instrument: Instrument, lineage: SourceLineage
) -> list[RawKeyLevel]:
    levels = generate_rolling_lows_1m(_bars(frame, instrument, 60), lineage)
    levels += generate_rolling_lows_5m(_bars(frame, instrument, 300), lineage)
    for timeframe, seconds in (("15m", 900), ("1H", 3600), ("4H", 14400), ("1D", 86400)):
        levels += generate_range_lows(_bars(frame, instrument, seconds), timeframe, lineage)  # type: ignore[arg-type]
    return sorted(levels, key=lambda item: (item.available_at_ts, item.raw_key_level_id))


def build_price_day(
    *,
    contract_root: Path,
    instrument: Instrument,
    day: date,
    data_run_id: str,
    dataset_logical_hash: str,
    config_hash: str,
    code_version: str,
) -> dict[str, list[dict[str, Any]]]:
    previous = day - timedelta(days=1)
    following = day + timedelta(days=1)
    frames = []
    if previous >= date(2020, 1, 1):
        frames.append(_read(_path(contract_root, instrument, previous)))
    frames.append(_read(_path(contract_root, instrument, day)))
    if following < date(2026, 7, 4):
        frames.append(_read(_path(contract_root, instrument, following)).head(180))
    frame = pl.concat(frames).sort("ts_event_ns")
    day_start = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * SECOND_NS)
    day_end = day_start + DAY_NS
    lineage = SourceLineage(
        data_run_id, dataset_logical_hash, config_hash, code_version, "KEYLEVEL-BASE-V1"
    )
    raw_all = _raw_levels(frame, instrument, lineage)
    raw = [item for item in raw_all if day_start <= item.available_at_ts < day_end]
    by_available: dict[int, list[RawKeyLevel]] = {}
    for item in raw_all:
        by_available.setdefault(item.available_at_ts, []).append(item)
    minute_bars = _bars(frame, instrument, 60)
    minute_by_start = {bar.bucket_start_ns: bar for bar in minute_bars}
    hourly = _bars(frame, instrument, 3600)
    second_frame = frame.filter(
        (pl.col("ts_event_ns") >= day_start - 5 * SECOND_NS)
        & (pl.col("ts_event_ns") < day_end + 180 * SECOND_NS)
    )
    second_rows = _price_rows(second_frame, instrument)
    seconds_by_ts = {row.ts_event_ns: row for row in second_rows}
    active: dict[tuple[str, str], RawKeyLevel] = {}
    output: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "raw_key_levels",
            "canonical_key_levels",
            "arbitration",
            "sweeps",
            "reclaims",
            "holds",
            "price_triggers",
            "candidate_attempts",
        )
    }
    output["raw_key_levels"] = [item.model_dump(mode="json") for item in raw]
    timings = {item.timing_id: item for item in timing_configurations()}
    parameter_family = parameter_sets()
    for minute_start in range(day_start, day_end, 60 * SECOND_NS):
        available = minute_start + 60 * SECOND_NS
        for item in by_available.get(available, []):
            active[(item.source_type, item.source_timeframe)] = item
        current_minute = minute_by_start.get(minute_start)
        previous_minute = minute_by_start.get(minute_start - 60 * SECOND_NS)
        if current_minute is None or previous_minute is None or not active:
            continue
        canonical_by_merge: dict[Decimal, list[Any]] = {}
        for tolerance in (Decimal("5"), Decimal("10"), Decimal("15")):
            canonical_by_merge[tolerance] = arbitrate_key_levels(
                list(active.values()),
                merge_tolerance_bps=tolerance,
                expires_at_ns=available + 60 * SECOND_NS,
            )
        for parameter in parameter_family:
            canonical_levels = canonical_by_merge[parameter.merge_tolerance_bps]
            for canonical in canonical_levels:
                output["canonical_key_levels"].append(
                    {
                        **canonical.model_dump(mode="json"),
                        "event_parameter_set_id": parameter.parameter_set_id,
                    }
                )
                if not (
                    current_minute.low < canonical.level_price
                    and previous_minute.close >= canonical.level_price
                ):
                    continue
                window = [
                    seconds_by_ts[ts]
                    for ts in range(minute_start, minute_start + 121 * SECOND_NS, SECOND_NS)
                    if ts in seconds_by_ts
                ]
                sweep = detect_sweep(
                    canonical, window, confirmation_bps=parameter.sweep_confirmation_bps
                )
                if sweep is None:
                    continue
                if not owns_sweep_start(minute_start, sweep.sweep_start_ts):
                    continue
                output["sweeps"].append(
                    {
                        **sweep.model_dump(mode="json"),
                        "event_parameter_set_id": parameter.parameter_set_id,
                    }
                )
                if sweep.status != "DETECTED":
                    continue
                timing = timings[parameter.timing_id]
                reclaim = detect_reclaim(
                    sweep,
                    canonical,
                    window,
                    reclaim_buffer_bps=parameter.reclaim_buffer_bps,
                    timeout_seconds=timing.reclaim_timeout_seconds,
                )
                output["reclaims"].append(
                    {
                        **reclaim.model_dump(mode="json"),
                        "event_parameter_set_id": parameter.parameter_set_id,
                    }
                )
                if reclaim.status != "RECLAIMED":
                    continue
                hold = detect_hold(
                    reclaim,
                    canonical,
                    window,
                    hold_window_seconds=timing.hold_window_seconds,
                    failure_buffer_bps=parameter.hold_failure_buffer_bps,
                )
                output["holds"].append(
                    {
                        **hold.model_dump(mode="json"),
                        "event_parameter_set_id": parameter.parameter_set_id,
                    }
                )
                if hold.hold_result != "PASS":
                    continue
                trigger = evaluate_price_trigger(
                    hold, hourly, window, structural_low_price=sweep.sweep_extreme_price
                )
                output["price_triggers"].append(
                    {
                        **trigger.model_dump(mode="json"),
                        "event_parameter_set_id": parameter.parameter_set_id,
                    }
                )
                if trigger.status != "PASS":
                    continue
                episode = build_market_episode(
                    canonical,
                    sweep,
                    reclaim,
                    hold,
                    trigger,
                    None,
                    variant="V1_PRICE",
                    event_parameter_set_id=parameter.parameter_set_id,
                    time_combination_id=parameter.timing_id,
                )
                episode_record = {
                    **episode.model_dump(mode="json"),
                    "event_parameter_set_id": parameter.parameter_set_id,
                }
                ordinal = len(output["candidate_attempts"])
                output["candidate_attempts"].append(
                    {
                        **episode_record,
                        "trigger_available_at_ts": trigger.available_at_ts,
                        "window_start_ts": trigger.available_at_ts - 5 * SECOND_NS,
                        "window_end_ts": trigger.available_at_ts,
                        "source_processing_partition": day.isoformat(),
                        "source_row_ordinal": ordinal,
                        "source_file_logical_path": (
                            f"instrument={instrument}/variant=V1_PRICE/"
                            f"candidate_attempts/date={day.isoformat()}/part-000.parquet"
                        ),
                    }
                )
    output["arbitration"] = [
        {
            "key_level_id": row["key_level_id"],
            "normalization_group": row["normalization_group"],
            "member_key_level_ids": row["member_key_level_ids"],
            "reason_code": row["reason_code"],
            "event_parameter_set_id": row["event_parameter_set_id"],
        }
        for row in output["canonical_key_levels"]
    ]
    return output
