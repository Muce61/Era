from decimal import Decimal

from era100x.data.schema.models import NormalizedTrade
from era100x.research.stage_2.contracts.models import PriceTriggerFact
from era100x.research.stage_2.gates.flow import evaluate_flow_gate

S = 1_000_000_000


def trigger() -> PriceTriggerFact:
    return PriceTriggerFact(
        instrument="BTCUSDT",
        data_run_id="stage1",
        dataset_logical_hash="1" * 64,
        config_hash="2" * 64,
        code_version="abcdef0",
        parameter_set_id="G1-PRIMARY-V1",
        available_at_ts=10 * S,
        trigger_id="3" * 64,
        hold_id="4" * 64,
        sweep_id="5" * 64,
        trigger_version="G1_G3_V1",
        detection_ts=10 * S,
        reference_price=Decimal("100"),
        context_state="UP",
        status="PASS",
        reason_code="G3_PRICE_START_CONFIRMED",
    )


def trade(identifier: int, ts: int, side: str, quantity: str = "1") -> NormalizedTrade:
    return NormalizedTrade.model_validate(
        {
            "instrument": "BTCUSDT",
            "venue_trade_id": identifier,
            "canonical_trade_id": f"{identifier:064x}",
            "identity_status": "UNIQUE_VENUE_ID",
            "price": Decimal("100"),
            "quantity": Decimal(quantity),
            "quote_quantity": Decimal(quantity) * Decimal("100"),
            "ts_event_ns": ts,
            "is_buyer_maker": side == "SELL",
            "aggressor_side": side,
            "source_sha256": "a" * 64,
        }
    )


def test_flow_passes_and_excludes_right_boundary() -> None:
    rows = [
        trade(1, 5 * S, "SELL"),
        trade(2, 9 * S, "BUY", "2"),
        trade(3, 9 * S + 1, "BUY", "2"),
        trade(4, 10 * S, "SELL", "100"),
    ]
    fact = evaluate_flow_gate(trigger(), rows)
    assert fact.status == "PASS"
    assert fact.feature_values["signed_quantity_imbalance"] == Decimal("0.6")
    assert "bid" in fact.unavailable_fields


def test_missing_trades_are_unavailable_not_zero_flow() -> None:
    fact = evaluate_flow_gate(trigger(), [])
    assert fact.status == "UNAVAILABLE"
    assert fact.feature_values["signed_quantity_imbalance"] is None


def test_future_trade_cannot_change_flow() -> None:
    rows = [trade(1, 9 * S, "BUY")]
    assert evaluate_flow_gate(trigger(), rows) == evaluate_flow_gate(
        trigger(), rows + [trade(2, 11 * S, "SELL", "100")]
    )
