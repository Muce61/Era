from __future__ import annotations

from decimal import Decimal

from era100x.data.schema.models import ContractPrice1s
from era100x.research.stage_2.contracts.identity import stable_id
from era100x.research.stage_2.contracts.models import CanonicalKeyLevel, HoldEvent, ReclaimEvent

SECOND_NS = 1_000_000_000


def detect_hold(
    reclaim: ReclaimEvent,
    level: CanonicalKeyLevel,
    prices: list[ContractPrice1s],
    *,
    hold_window_seconds: int,
    failure_buffer_bps: Decimal,
) -> HoldEvent:
    if reclaim.status != "RECLAIMED":
        raise ValueError("Hold requires a confirmed Reclaim")
    if reclaim.instrument != level.instrument or failure_buffer_bps < 0:
        raise ValueError("invalid Hold lineage or parameters")
    if hold_window_seconds <= 0:
        raise ValueError("Hold window must be positive")
    start = reclaim.available_at_ts
    end = start + hold_window_seconds * SECOND_NS
    failure_price = level.level_price * (Decimal(1) - failure_buffer_bps / Decimal(10_000))
    by_second: dict[int, ContractPrice1s] = {}
    for row in sorted(prices, key=lambda item: item.ts_event_ns):
        if row.instrument != reclaim.instrument:
            raise ValueError("mixed instruments")
        if start <= row.ts_event_ns < end:
            if row.ts_event_ns in by_second:
                raise ValueError("duplicate Contract Price second")
            by_second[row.ts_event_ns] = row
            if row.low < failure_price:
                return _result(
                    reclaim,
                    start,
                    row.ts_event_ns + SECOND_NS,
                    "FAIL",
                    "HOLD_FAILURE_BREAK",
                    failure_buffer_bps,
                )
    expected = {start + offset * SECOND_NS for offset in range(hold_window_seconds)}
    if set(by_second) != expected:
        return _result(
            reclaim,
            start,
            end,
            "INSUFFICIENT_WINDOW",
            "HOLD_WINDOW_INCOMPLETE",
            failure_buffer_bps,
        )
    return _result(
        reclaim,
        start,
        end,
        "PASS",
        "HOLD_CONFIRMED",
        failure_buffer_bps,
    )


def _result(
    reclaim: ReclaimEvent,
    start: int,
    end: int,
    result: str,
    reason: str,
    failure_buffer_bps: Decimal,
) -> HoldEvent:
    hold_id = stable_id(
        "hold-event",
        "v1",
        reclaim.instrument,
        reclaim.reclaim_id,
        start,
        end,
        failure_buffer_bps,
        reclaim.parameter_set_id,
    )
    return HoldEvent.model_validate(
        {
            "instrument": reclaim.instrument,
            "data_run_id": reclaim.data_run_id,
            "dataset_logical_hash": reclaim.dataset_logical_hash,
            "config_hash": reclaim.config_hash,
            "code_version": reclaim.code_version,
            "parameter_set_id": reclaim.parameter_set_id,
            "available_at_ts": end,
            "hold_id": hold_id,
            "reclaim_id": reclaim.reclaim_id,
            "sweep_id": reclaim.sweep_id,
            "hold_start_ts": start,
            "hold_end_ts": end,
            "hold_result": result,
            "failure_reason": None if result == "PASS" else reason,
        }
    )
