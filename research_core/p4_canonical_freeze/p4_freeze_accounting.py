"""Accounting helpers for P4 canonical freeze replay."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CostScenario:
    name: str
    entry_fee_rate: float
    exit_fee_rate: float
    entry_slippage_rate: float
    exit_slippage_rate: float
    funding_rate_source: str = "unavailable"
    liquidation_fee_rate: float = 0.0


BASE_COST = CostScenario("base_cost", 0.0005, 0.0005, 0.0002, 0.0002)
HIGH_COST = CostScenario("high_cost", 0.0010, 0.0010, 0.0004, 0.0004)
STRESS_COST = CostScenario("stress_cost", 0.0015, 0.0015, 0.0008, 0.0008)
COST_SCENARIOS = [BASE_COST, HIGH_COST, STRESS_COST]


def long_quantity(equity: float, leverage: float, entry_price: float) -> float:
    if entry_price <= 0 or not np.isfinite(entry_price):
        return 0.0
    return equity * leverage / entry_price


def long_net_pnl(
    equity_before: float,
    raw_entry: float,
    raw_exit: float,
    leverage: float,
    cost: CostScenario = BASE_COST,
    funding_paid: float = 0.0,
    funding_received: float = 0.0,
    liquidation_fee: float = 0.0,
) -> dict:
    entry_price = raw_entry * (1.0 + cost.entry_slippage_rate)
    exit_price = raw_exit * (1.0 - cost.exit_slippage_rate)
    quantity = long_quantity(equity_before, leverage, entry_price)
    gross_pnl = (exit_price - entry_price) * quantity
    entry_fee = quantity * entry_price * cost.entry_fee_rate
    exit_fee = quantity * exit_price * cost.exit_fee_rate
    slippage_cost = quantity * ((entry_price - raw_entry) + (raw_exit - exit_price))
    net_pnl = gross_pnl + funding_received - funding_paid - entry_fee - exit_fee - liquidation_fee
    accounting_error = net_pnl - (
        gross_pnl + funding_received - funding_paid - entry_fee - exit_fee - liquidation_fee
    )
    return {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "entry_notional": quantity * entry_price,
        "gross_pnl": gross_pnl,
        "entry_fee": entry_fee,
        "exit_fee": exit_fee,
        "slippage": slippage_cost,
        "funding_paid": funding_paid,
        "funding_received": funding_received,
        "liquidation_fee": liquidation_fee,
        "net_pnl": net_pnl,
        "accounting_error": accounting_error,
    }


def cost_assumptions_rows() -> list[dict]:
    rows = []
    for c in COST_SCENARIOS:
        rows.append({
            "scenario": c.name,
            "entry_fee_rate": c.entry_fee_rate,
            "exit_fee_rate": c.exit_fee_rate,
            "entry_slippage_rate": c.entry_slippage_rate,
            "exit_slippage_rate": c.exit_slippage_rate,
            "funding_rate_source": c.funding_rate_source,
            "liquidation_fee_rate": c.liquidation_fee_rate,
        })
    return rows

