from __future__ import annotations

from decimal import Decimal

from era100x.data.schema.models import ContractPrice1s
from era100x.research.stage_2.contracts.identity import stable_id
from era100x.research.stage_2.contracts.models import CanonicalKeyLevel, SweepEpisode

SECOND_NS = 1_000_000_000


def _depth_bps(level_price: Decimal, extreme_price: Decimal) -> Decimal:
    return (level_price - extreme_price) / level_price * Decimal(10_000)


def detect_sweep(
    level: CanonicalKeyLevel,
    prices: list[ContractPrice1s],
    *,
    confirmation_bps: Decimal,
    maximum_depth_bps: Decimal = Decimal("25"),
) -> SweepEpisode | None:
    if confirmation_bps <= 0 or confirmation_bps > maximum_depth_bps:
        raise ValueError("invalid Sweep confirmation threshold")
    ordered = sorted(prices, key=lambda row: row.ts_event_ns)
    if any(row.instrument != level.instrument for row in ordered):
        raise ValueError("mixed instruments")
    previous_close: Decimal | None = None
    sweep_start: int | None = None
    pre_sweep_reference: Decimal | None = None
    for row in ordered:
        close_available_at = row.ts_event_ns + SECOND_NS
        if close_available_at < level.available_at_ts or row.ts_event_ns >= level.expires_at_ns:
            previous_close = row.close
            continue
        crossed = row.low < level.level_price and (
            previous_close is None or previous_close >= level.level_price
        )
        if sweep_start is None and crossed:
            sweep_start = row.ts_event_ns
            pre_sweep_reference = previous_close or level.level_price
        if sweep_start is not None:
            depth = _depth_bps(level.level_price, row.low)
            if depth > maximum_depth_bps:
                return _build(
                    level,
                    row,
                    sweep_start,
                    pre_sweep_reference or level.level_price,
                    depth,
                    confirmation_bps,
                    "INVALIDATED",
                    "SWEEP_DEPTH_EXCEEDED",
                )
            if depth >= confirmation_bps:
                return _build(
                    level,
                    row,
                    sweep_start,
                    pre_sweep_reference or level.level_price,
                    depth,
                    confirmation_bps,
                    "DETECTED",
                    "SWEEP_CONFIRMED",
                )
        previous_close = row.close
    return None


def _build(
    level: CanonicalKeyLevel,
    row: ContractPrice1s,
    sweep_start: int,
    pre_sweep_reference: Decimal,
    depth: Decimal,
    confirmation_bps: Decimal,
    status: str,
    reason: str,
) -> SweepEpisode:
    detection = row.ts_event_ns + SECOND_NS
    sweep_id = stable_id(
        "sweep-episode",
        "v1",
        level.instrument,
        level.key_level_id,
        sweep_start,
        confirmation_bps,
        level.parameter_set_id,
    )
    return SweepEpisode.model_validate(
        {
            "instrument": level.instrument,
            "data_run_id": level.data_run_id,
            "dataset_logical_hash": level.dataset_logical_hash,
            "config_hash": level.config_hash,
            "code_version": level.code_version,
            "parameter_set_id": level.parameter_set_id,
            "available_at_ts": detection,
            "sweep_id": sweep_id,
            "key_level_id": level.key_level_id,
            "direction": "LONG",
            "sweep_start_ts": sweep_start,
            "sweep_detection_ts": detection,
            "sweep_extreme_ts": row.ts_event_ns,
            "sweep_extreme_price": row.low,
            "sweep_depth": depth,
            "sweep_depth_unit": "BPS",
            "pre_sweep_reference": pre_sweep_reference,
            "status": status,
            "reason_code": reason,
            "metadata": {"confirmation_bps": format(confirmation_bps, "f")},
        }
    )
