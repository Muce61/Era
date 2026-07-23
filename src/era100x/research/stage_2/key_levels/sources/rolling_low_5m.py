from __future__ import annotations

from era100x.data.schema.models import ContractBar
from era100x.research.stage_2.contracts.identity import stable_id
from era100x.research.stage_2.contracts.models import RawKeyLevel

from .common import SourceLineage

WINDOW = 12
INTERVAL_SECONDS = 300


def generate_rolling_lows_5m(bars: list[ContractBar], lineage: SourceLineage) -> list[RawKeyLevel]:
    ordered = sorted(bars, key=lambda bar: bar.bucket_start_ns)
    if any(bar.interval_seconds != INTERVAL_SECONDS for bar in ordered):
        raise ValueError("rolling_low_5m requires closed five-minute bars")
    results: list[RawKeyLevel] = []
    for end_index in range(WINDOW - 1, len(ordered)):
        window = ordered[end_index - WINDOW + 1 : end_index + 1]
        instrument = window[0].instrument
        if any(bar.instrument != instrument for bar in window):
            raise ValueError("mixed instruments")
        source_start = window[0].bucket_start_ns
        source_end = window[-1].bucket_start_ns + INTERVAL_SECONDS * 1_000_000_000
        price = min(bar.low for bar in window)
        source_id = stable_id(
            "key-source", "v1", instrument, "rolling_low_5m", source_start, source_end
        )
        raw_id = stable_id(
            "raw-key-level", "v1", instrument, source_id, price, lineage.parameter_set_id
        )
        results.append(
            RawKeyLevel(
                instrument=instrument,
                data_run_id=lineage.data_run_id,
                dataset_logical_hash=lineage.dataset_logical_hash,
                config_hash=lineage.config_hash,
                code_version=lineage.code_version,
                parameter_set_id=lineage.parameter_set_id,
                available_at_ts=source_end,
                raw_key_level_id=raw_id,
                source_type="rolling_low_5m",
                source_id=source_id,
                source_timeframe="5m",
                source_start_ts=source_start,
                source_end_ts=source_end,
                level_price=price,
                priority=5,
                quality_status="ACCEPTED",
                metadata={"closed_bar_count": WINDOW},
            )
        )
    return results
