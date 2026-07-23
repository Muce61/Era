from __future__ import annotations

from decimal import Decimal

from era100x.data.schema.models import ContractPrice1s
from era100x.research.stage_2.contracts.identity import stable_id
from era100x.research.stage_2.contracts.models import (
    CanonicalKeyLevel,
    ReclaimEvent,
    SweepEpisode,
)

SECOND_NS = 1_000_000_000


def detect_reclaim(
    sweep: SweepEpisode,
    level: CanonicalKeyLevel,
    prices: list[ContractPrice1s],
    *,
    reclaim_buffer_bps: Decimal,
    timeout_seconds: int,
) -> ReclaimEvent:
    if sweep.status != "DETECTED":
        raise ValueError("Reclaim requires a confirmed Sweep")
    if sweep.key_level_id != level.key_level_id or sweep.instrument != level.instrument:
        raise ValueError("Sweep/key-level lineage mismatch")
    if reclaim_buffer_bps < 0 or timeout_seconds <= 0:
        raise ValueError("invalid Reclaim parameters")
    threshold = level.level_price * (Decimal(1) + reclaim_buffer_bps / Decimal(10_000))
    deadline = sweep.sweep_detection_ts + timeout_seconds * SECOND_NS
    ordered = sorted(prices, key=lambda row: row.ts_event_ns)
    last_price = level.level_price
    for row in ordered:
        if row.instrument != sweep.instrument:
            raise ValueError("mixed instruments")
        fact_available_at = row.ts_event_ns + SECOND_NS
        if fact_available_at < sweep.sweep_detection_ts:
            continue
        if fact_available_at >= deadline:
            break
        last_price = row.close
        if row.close >= threshold:
            return _result(
                sweep,
                row.ts_event_ns,
                fact_available_at,
                row.close,
                reclaim_buffer_bps,
                "RECLAIMED",
                "RECLAIM_CONFIRMED",
            )
    return _result(
        sweep,
        deadline,
        deadline,
        last_price,
        reclaim_buffer_bps,
        "TIMED_OUT",
        "RECLAIM_TIMEOUT",
    )


def _result(
    sweep: SweepEpisode,
    reclaim_ts: int,
    available_at: int,
    price: Decimal,
    buffer_bps: Decimal,
    status: str,
    reason: str,
) -> ReclaimEvent:
    reclaim_id = stable_id(
        "reclaim-event",
        "v1",
        sweep.instrument,
        sweep.sweep_id,
        reclaim_ts,
        buffer_bps,
        sweep.parameter_set_id,
    )
    return ReclaimEvent.model_validate(
        {
            "instrument": sweep.instrument,
            "data_run_id": sweep.data_run_id,
            "dataset_logical_hash": sweep.dataset_logical_hash,
            "config_hash": sweep.config_hash,
            "code_version": sweep.code_version,
            "parameter_set_id": sweep.parameter_set_id,
            "available_at_ts": available_at,
            "reclaim_id": reclaim_id,
            "sweep_id": sweep.sweep_id,
            "reclaim_ts": reclaim_ts,
            "reclaim_price": price,
            "status": status,
            "reason_code": reason,
        }
    )
