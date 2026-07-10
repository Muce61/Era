from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal


@dataclass(frozen=True, slots=True)
class SizingResult:
    margin_used_usdt: Decimal
    notional_usdt: Decimal
    quantity_contracts: Decimal


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def calculate_contract_quantity(*, available_margin_usdt: Decimal, max_margin_usdt: Decimal, leverage: int, price_usdt: Decimal, contract_multiplier_base: Decimal, quantity_step: Decimal, minimum_quantity: Decimal) -> SizingResult:
    if available_margin_usdt <= 0 or max_margin_usdt <= 0:
        raise ValueError("margin must be positive")
    if leverage <= 0 or price_usdt <= 0 or contract_multiplier_base <= 0:
        raise ValueError("leverage, price and multiplier must be positive")
    margin = min(available_margin_usdt, max_margin_usdt)
    notional = margin * Decimal(leverage)
    quantity = floor_to_step(notional / (price_usdt * contract_multiplier_base), quantity_step)
    if quantity < minimum_quantity:
        raise ValueError("calculated quantity is below exchange minimum")
    return SizingResult(margin, notional, quantity)


def estimate_round_trip_cost_roe_pct(*, leverage: int, entry_fee_rate: Decimal, exit_fee_rate: Decimal, entry_slippage_bps: Decimal, exit_slippage_bps: Decimal) -> Decimal:
    if leverage <= 0:
        raise ValueError("leverage must be positive")
    if min(entry_fee_rate, exit_fee_rate, entry_slippage_bps, exit_slippage_bps) < 0:
        raise ValueError("cost assumptions cannot be negative")
    fee_fraction = entry_fee_rate + exit_fee_rate
    slippage_fraction = (entry_slippage_bps + exit_slippage_bps) / Decimal("10000")
    return (fee_fraction + slippage_fraction) * Decimal(leverage) * Decimal("100")
