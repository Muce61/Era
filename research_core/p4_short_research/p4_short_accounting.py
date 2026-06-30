"""Accounting helpers for P4 short mirror research."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostScenario:
    name: str
    fee_rate: float
    slippage_rate: float
    funding_rate_source: str = "binance_usdt_m_funding"
    borrow_cost_rate: float = 0.0
    liquidation_fee_rate: float = 0.0


INITIAL_BALANCE = 1000.0
MAINTENANCE_MARGIN_RATE = 0.005
BASE_COST = CostScenario("base_cost", fee_rate=0.0005, slippage_rate=0.0002)
HIGH_COST = CostScenario("high_cost", fee_rate=0.0010, slippage_rate=0.0004)
STRESS_COST = CostScenario("stress_cost", fee_rate=0.0015, slippage_rate=0.0008)
COST_SCENARIOS = [BASE_COST, HIGH_COST, STRESS_COST]


def short_entry_price(raw_open: float, slippage_rate: float) -> float:
    return float(raw_open) * (1.0 - float(slippage_rate))


def short_exit_price(raw_price: float, slippage_rate: float) -> float:
    return float(raw_price) * (1.0 + float(slippage_rate))


def short_quantity(notional: float, entry_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return float(notional) / float(entry_price)


def short_gross_pnl(quantity: float, entry_price: float, exit_price: float) -> float:
    return float(quantity) * (float(entry_price) - float(exit_price))


def short_liquidation_price(entry_price: float, leverage: float, maintenance_margin_rate: float = MAINTENANCE_MARGIN_RATE) -> float:
    return float(entry_price) * (1.0 + 1.0 / float(leverage) - float(maintenance_margin_rate))


def short_net_pnl(
    quantity: float,
    entry_price: float,
    exit_price: float,
    fee_rate: float,
    slippage_cost: float = 0.0,
    funding_paid: float = 0.0,
    funding_received: float = 0.0,
    liquidation_fee: float = 0.0,
) -> dict:
    gross = short_gross_pnl(quantity, entry_price, exit_price)
    entry_fee = abs(quantity * entry_price) * fee_rate
    exit_fee = abs(quantity * exit_price) * fee_rate
    net = gross + funding_received - funding_paid - entry_fee - exit_fee - slippage_cost - liquidation_fee
    return {
        "gross_pnl": gross,
        "entry_fee": entry_fee,
        "exit_fee": exit_fee,
        "slippage": slippage_cost,
        "funding_paid": funding_paid,
        "funding_received": funding_received,
        "liquidation_fee": liquidation_fee,
        "net_pnl": net,
        "accounting_error": net - (gross + funding_received - funding_paid - entry_fee - exit_fee - slippage_cost - liquidation_fee),
    }

