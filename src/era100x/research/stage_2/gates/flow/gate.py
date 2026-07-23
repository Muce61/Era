from __future__ import annotations

from decimal import Decimal

from era100x.data.schema.models import NormalizedTrade
from era100x.research.stage_2.contracts.identity import stable_id
from era100x.research.stage_2.contracts.models import FlowFeatureSet, PriceTriggerFact

SECOND_NS = 1_000_000_000
UNAVAILABLE_EXECUTION_FIELDS = (
    "bid",
    "ask",
    "spread",
    "ts_recv",
    "l2_depth",
    "queue_position",
    "actual_partial_fill",
    "actual_slippage",
    "private_order_flow",
)


def evaluate_flow_gate(trigger: PriceTriggerFact, trades: list[NormalizedTrade]) -> FlowFeatureSet:
    end = trigger.available_at_ts
    start = end - 5 * SECOND_NS
    selected = sorted(
        (
            trade
            for trade in trades
            if trade.instrument == trigger.instrument and start <= trade.ts_event_ns < end
        ),
        key=lambda trade: (trade.ts_event_ns, trade.venue_trade_id, trade.canonical_trade_id),
    )
    buy_qty = sum(
        (trade.quantity for trade in selected if trade.aggressor_side == "BUY"), Decimal(0)
    )
    sell_qty = sum(
        (trade.quantity for trade in selected if trade.aggressor_side == "SELL"), Decimal(0)
    )
    total_qty = buy_qty + sell_qty
    latest_count = sum(trade.ts_event_ns >= end - SECOND_NS for trade in selected)
    previous_count = len(selected) - latest_count
    previous_mean = Decimal(previous_count) / Decimal(4)
    if not selected or total_qty == 0:
        return _result(
            trigger,
            start,
            end,
            buy_qty,
            sell_qty,
            None,
            latest_count,
            previous_mean,
            "UNAVAILABLE",
            "FLOW_TRADES_UNAVAILABLE",
        )
    imbalance = (buy_qty - sell_qty) / total_qty
    passed = imbalance > 0 and Decimal(latest_count) > previous_mean
    return _result(
        trigger,
        start,
        end,
        buy_qty,
        sell_qty,
        imbalance,
        latest_count,
        previous_mean,
        "PASS" if passed else "REJECTED",
        "FLOW_CONFIRMED" if passed else "FLOW_THRESHOLD_NOT_MET",
    )


def _result(
    trigger: PriceTriggerFact,
    start: int,
    end: int,
    buy_qty: Decimal,
    sell_qty: Decimal,
    imbalance: Decimal | None,
    latest_count: int,
    previous_mean: Decimal,
    status: str,
    reason: str,
) -> FlowFeatureSet:
    feature_id = stable_id(
        "flow-feature-set",
        "v1",
        trigger.instrument,
        trigger.trigger_id,
        start,
        end,
        trigger.parameter_set_id,
    )
    return FlowFeatureSet.model_validate(
        {
            "instrument": trigger.instrument,
            "data_run_id": trigger.data_run_id,
            "dataset_logical_hash": trigger.dataset_logical_hash,
            "config_hash": trigger.config_hash,
            "code_version": trigger.code_version,
            "parameter_set_id": trigger.parameter_set_id,
            "available_at_ts": end,
            "flow_feature_set_id": feature_id,
            "flow_feature_version": "G4_TRADES_V1",
            "window_start_ts": start,
            "window_end_ts": end,
            "feature_values": {
                "buy_quantity": buy_qty,
                "sell_quantity": sell_qty,
                "signed_quantity_imbalance": imbalance,
                "latest_1s_trade_count": latest_count,
                "previous_4s_per_second_mean": previous_mean,
            },
            "status": status,
            "unavailable_fields": UNAVAILABLE_EXECUTION_FIELDS,
            "reason_code": reason,
        }
    )
