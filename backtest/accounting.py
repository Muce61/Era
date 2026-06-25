from dataclasses import dataclass


@dataclass(frozen=True)
class Fill:
    raw_price: float
    executed_price: float
    fee: float
    notional: float
    slippage_cost: float


def execute_entry(raw_price, quantity, side, fee_rate, slippage_rate):
    side = side.upper()
    if side == "LONG":
        executed_price = raw_price * (1 + slippage_rate)
        slippage_cost = (executed_price - raw_price) * quantity
    elif side == "SHORT":
        executed_price = raw_price * (1 - slippage_rate)
        slippage_cost = (raw_price - executed_price) * quantity
    else:
        raise ValueError(f"Unsupported side: {side}")
    notional = executed_price * quantity
    return Fill(raw_price, executed_price, notional * fee_rate, notional, slippage_cost)


def execute_exit(raw_price, quantity, side, fee_rate, slippage_rate):
    side = side.upper()
    if side == "LONG":
        executed_price = raw_price * (1 - slippage_rate)
        slippage_cost = (raw_price - executed_price) * quantity
    elif side == "SHORT":
        executed_price = raw_price * (1 + slippage_rate)
        slippage_cost = (executed_price - raw_price) * quantity
    else:
        raise ValueError(f"Unsupported side: {side}")
    notional = executed_price * quantity
    return Fill(raw_price, executed_price, notional * fee_rate, notional, slippage_cost)


def gross_pnl(entry_price, exit_price, quantity, side):
    side = side.upper()
    if side == "LONG":
        return (exit_price - entry_price) * quantity
    if side == "SHORT":
        return (entry_price - exit_price) * quantity
    raise ValueError(f"Unsupported side: {side}")


def trade_net_pnl(gross, entry_fee, exit_fee, funding_fee=0.0):
    return gross - entry_fee - exit_fee - funding_fee
