from __future__ import annotations

from typing import Literal

from era100x.data.schema.models import ContractBar
from era100x.research.stage_2.contracts.identity import stable_id
from era100x.research.stage_2.contracts.models import RawKeyLevel

from .common import SourceLineage

RangeTimeframe = Literal["15m", "1H", "4H", "1D"]
SECONDS: dict[RangeTimeframe, int] = {"15m": 900, "1H": 3600, "4H": 14400, "1D": 86400}
PRIORITY: dict[RangeTimeframe, int] = {"1D": 1, "4H": 2, "1H": 3, "15m": 4}


def generate_range_lows(
    bars: list[ContractBar], timeframe: RangeTimeframe, lineage: SourceLineage
) -> list[RawKeyLevel]:
    interval = SECONDS[timeframe]
    ordered = sorted(bars, key=lambda bar: bar.bucket_start_ns)
    if any(bar.interval_seconds != interval for bar in ordered):
        raise ValueError("range_low interval does not match timeframe")
    results: list[RawKeyLevel] = []
    for bar in ordered:
        source_end = bar.bucket_start_ns + interval * 1_000_000_000
        source_id = stable_id(
            "key-source",
            "v1",
            bar.instrument,
            "range_low",
            timeframe,
            bar.bucket_start_ns,
            source_end,
        )
        raw_id = stable_id(
            "raw-key-level", "v1", bar.instrument, source_id, bar.low, lineage.parameter_set_id
        )
        results.append(
            RawKeyLevel(
                instrument=bar.instrument,
                data_run_id=lineage.data_run_id,
                dataset_logical_hash=lineage.dataset_logical_hash,
                config_hash=lineage.config_hash,
                code_version=lineage.code_version,
                parameter_set_id=lineage.parameter_set_id,
                available_at_ts=source_end,
                raw_key_level_id=raw_id,
                source_type="range_low",
                source_id=source_id,
                source_timeframe=timeframe,
                source_start_ts=bar.bucket_start_ns,
                source_end_ts=source_end,
                level_price=bar.low,
                priority=PRIORITY[timeframe],
                quality_status="ACCEPTED",
                metadata={"closed_bar_count": 1},
            )
        )
    return results
