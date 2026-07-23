from __future__ import annotations

from decimal import Decimal

from era100x.data.schema.models import ContractBar, ContractPrice1s
from era100x.research.stage_2.contracts.identity import stable_id
from era100x.research.stage_2.contracts.models import HoldEvent, PriceTriggerFact

SECOND_NS = 1_000_000_000
HOUR_NS = 3_600 * SECOND_NS


def _context(hourly_bars: list[ContractBar], available_at: int) -> tuple[str, Decimal | None]:
    closed = sorted(
        (
            bar
            for bar in hourly_bars
            if bar.interval_seconds == 3600 and bar.bucket_start_ns + HOUR_NS <= available_at
        ),
        key=lambda bar: bar.bucket_start_ns,
    )
    if len(closed) < 20:
        return "UNAVAILABLE", None
    alpha = Decimal(2) / Decimal(21)
    ema = closed[0].close
    for bar in closed[1:]:
        ema = alpha * bar.close + (Decimal(1) - alpha) * ema
    latest = closed[-1].close
    if latest > ema:
        return "UP", latest
    if latest < ema:
        return "DOWN", latest
    return "FLAT", latest


def evaluate_price_trigger(
    hold: HoldEvent,
    hourly_bars: list[ContractBar],
    seconds: list[ContractPrice1s],
    *,
    structural_low_price: Decimal,
    trigger_window_seconds: int = 30,
) -> PriceTriggerFact:
    if hold.hold_result != "PASS":
        raise ValueError("Price Trigger requires a completed Hold")
    context_state, latest_hour_close = _context(hourly_bars, hold.available_at_ts)
    if context_state != "UP":
        return _result(
            hold,
            hold.available_at_ts,
            latest_hour_close or structural_low_price,
            context_state,
            "UNAVAILABLE" if context_state == "UNAVAILABLE" else "REJECTED",
            "G1_CONTEXT_NOT_UP",
        )
    by_ts = {row.ts_event_ns: row for row in seconds if row.instrument == hold.instrument}
    if len(by_ts) != sum(row.instrument == hold.instrument for row in seconds):
        raise ValueError("duplicate Contract Price second")
    deadline = hold.available_at_ts + trigger_window_seconds * SECOND_NS
    for ts in range(hold.available_at_ts, deadline, SECOND_NS):
        row = by_ts.get(ts)
        previous_1s = by_ts.get(ts - SECOND_NS)
        previous_5s = by_ts.get(ts - 5 * SECOND_NS)
        if row is None or previous_1s is None or previous_5s is None:
            return _result(
                hold,
                min(ts + SECOND_NS, deadline),
                latest_hour_close or structural_low_price,
                context_state,
                "UNAVAILABLE",
                "G0_PRICE_WINDOW_INCOMPLETE",
            )
        if row.low < structural_low_price:
            return _result(
                hold,
                ts + SECOND_NS,
                row.close,
                context_state,
                "REJECTED",
                "G3_NEW_STRUCTURAL_LOW",
            )
        if row.close > previous_1s.close and row.close > previous_5s.close:
            return _result(
                hold,
                ts + SECOND_NS,
                row.close,
                context_state,
                "PASS",
                "G3_PRICE_START_CONFIRMED",
            )
    return _result(
        hold,
        deadline,
        by_ts[deadline - SECOND_NS].close,
        context_state,
        "REJECTED",
        "G3_PRICE_START_TIMEOUT",
    )


def _result(
    hold: HoldEvent,
    detection_ts: int,
    price: Decimal,
    context_state: str,
    status: str,
    reason: str,
) -> PriceTriggerFact:
    trigger_id = stable_id(
        "price-trigger",
        "v1",
        hold.instrument,
        hold.hold_id,
        detection_ts,
        status,
        hold.parameter_set_id,
    )
    return PriceTriggerFact.model_validate(
        {
            "instrument": hold.instrument,
            "data_run_id": hold.data_run_id,
            "dataset_logical_hash": hold.dataset_logical_hash,
            "config_hash": hold.config_hash,
            "code_version": hold.code_version,
            "parameter_set_id": hold.parameter_set_id,
            "available_at_ts": detection_ts,
            "trigger_id": trigger_id,
            "hold_id": hold.hold_id,
            "sweep_id": hold.sweep_id,
            "trigger_version": "G1_G3_V1",
            "detection_ts": detection_ts,
            "reference_price": price,
            "context_state": context_state,
            "status": status,
            "reason_code": reason,
        }
    )
