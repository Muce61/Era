"""Decimal-only formulas from V1.3.4 Appendix F; no trading behavior."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal


ZERO = Decimal("0")
BPS = Decimal("10000")


def _decimal(name: str, value: Decimal, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite() or value < ZERO or (positive and value == ZERO):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return value


def proxy_long_pnl(
    *,
    reference_entry: Decimal,
    reference_exit: Decimal,
    quantity: Decimal,
    entry_scenario_bps: Decimal,
    exit_scenario_bps: Decimal,
    entry_fee: Decimal,
    exit_fee: Decimal,
    funding: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return proxy entry, proxy exit, and proxy net PnL with scenario slippage once."""
    entry = _decimal("reference_entry", reference_entry, positive=True) * (
        Decimal("1") + _decimal("entry_scenario_bps", entry_scenario_bps) / BPS
    )
    exit_ = _decimal("reference_exit", reference_exit, positive=True) * (
        Decimal("1") - _decimal("exit_scenario_bps", exit_scenario_bps) / BPS
    )
    if exit_ < ZERO:
        raise ValueError("exit scenario cannot produce a negative price")
    gross = _decimal("quantity", quantity, positive=True) * (exit_ - entry)
    net = gross - _decimal("entry_fee", entry_fee) - _decimal("exit_fee", exit_fee)
    net -= _decimal("funding", funding)
    return entry, exit_, net


def realized_long_pnl(
    *,
    entry_fills: Iterable[tuple[Decimal, Decimal]],
    exit_fills: Iterable[tuple[Decimal, Decimal]],
    actual_commission: Decimal,
    actual_funding: Decimal,
) -> Decimal:
    """Use actual fill prices; no slippage argument exists, preventing double deduction."""
    entry_value = sum(
        (
            _decimal("entry_price", price, positive=True)
            * _decimal("entry_qty", qty, positive=True)
            for price, qty in entry_fills
        ),
        ZERO,
    )
    exit_value = sum(
        (
            _decimal("exit_price", price, positive=True) * _decimal("exit_qty", qty, positive=True)
            for price, qty in exit_fills
        ),
        ZERO,
    )
    return (
        exit_value
        - entry_value
        - _decimal("actual_commission", actual_commission)
        - _decimal("actual_funding", actual_funding)
    )


def estimated_ticket_equity_if_flat(
    *,
    starting_ticket_equity: Decimal,
    current_realized_net_pnl: Decimal,
    estimated_remaining_exit_net_pnl: Decimal,
    external_cash_flow_since_round_start: Decimal,
) -> Decimal:
    if external_cash_flow_since_round_start != ZERO:
        raise ValueError("external cash flow since round start must be zero")
    return starting_ticket_equity + current_realized_net_pnl + estimated_remaining_exit_net_pnl


def final_realized_ticket_equity(
    *,
    starting_ticket_equity: Decimal,
    cumulative_realized_net_pnl: Decimal,
    position_flat: bool,
    cleanup_complete: bool,
    external_cash_flow_since_round_start: Decimal,
) -> Decimal:
    if external_cash_flow_since_round_start != ZERO:
        raise ValueError("external cash flow since round start must be zero")
    if not position_flat or not cleanup_complete:
        raise ValueError("final equity requires POSITION_FLAT and cleanup_complete")
    return starting_ticket_equity + cumulative_realized_net_pnl


def target_exit_price(
    *,
    remaining_net_profit: Decimal,
    quantity: Decimal,
    entry_price: Decimal,
    entry_fee_rate: Decimal,
    exit_fee_rate: Decimal,
    funding: Decimal,
) -> Decimal:
    q = _decimal("quantity", quantity, positive=True)
    denominator = q * (Decimal("1") - _decimal("exit_fee_rate", exit_fee_rate))
    if denominator <= ZERO:
        raise ValueError("exit fee rate must be below one")
    numerator = _decimal("remaining_net_profit", remaining_net_profit)
    numerator += (
        q
        * _decimal("entry_price", entry_price, positive=True)
        * (Decimal("1") + _decimal("entry_fee_rate", entry_fee_rate))
    )
    numerator += _decimal("funding", funding)
    return numerator / denominator


def required_target_bps(
    *,
    remaining_net_profit_target: Decimal,
    estimated_remaining_cost: Decimal,
    actual_position_notional: Decimal,
) -> Decimal:
    numerator = _decimal("remaining_net_profit_target", remaining_net_profit_target)
    numerator += _decimal("estimated_remaining_cost", estimated_remaining_cost)
    return (
        numerator
        / _decimal("actual_position_notional", actual_position_notional, positive=True)
        * BPS
    )
