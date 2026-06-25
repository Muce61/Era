"""Position sizing for fixed leverage and fixed risk modes."""

import math


def compute_quantity(
    equity: float,
    entry_price: float,
    stop_loss: float,
    leverage: float,
    risk_fraction: float,
    mode: str,
) -> dict:
    stop_distance = entry_price - stop_loss
    if (
        equity <= 0
        or entry_price <= 0
        or not math.isfinite(entry_price)
        or not math.isfinite(stop_loss)
        or stop_distance <= 0
        or not math.isfinite(stop_distance)
    ):
        return {
            "quantity": 0.0,
            "quantity_by_risk": 0.0,
            "quantity_by_leverage": 0.0,
            "risk_amount": 0.0,
            "stop_distance": stop_distance,
            "notional": 0.0,
            "effective_leverage": 0.0,
            "position_sizing_mode": mode,
            "risk_fraction": risk_fraction,
        }

    risk_amount = equity * risk_fraction
    quantity_by_risk = risk_amount / stop_distance
    quantity_by_leverage = (equity * leverage) / entry_price

    if mode == "fixed_risk":
        quantity = min(quantity_by_risk, quantity_by_leverage)
    else:
        quantity = quantity_by_leverage

    if not math.isfinite(quantity) or quantity <= 0:
        quantity = 0.0

    notional = quantity * entry_price
    effective_leverage = notional / equity if equity > 0 else 0.0

    return {
        "quantity": quantity,
        "quantity_by_risk": quantity_by_risk,
        "quantity_by_leverage": quantity_by_leverage,
        "risk_amount": risk_amount,
        "stop_distance": stop_distance,
        "notional": notional,
        "effective_leverage": effective_leverage,
        "position_sizing_mode": mode,
        "risk_fraction": risk_fraction,
    }
