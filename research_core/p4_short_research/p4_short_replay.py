"""Strict 1m short replay for P4 short mirror research."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research_core.leverage_research_analysis import profit_factor
from research_core.minimal_backtest_analysis import longest_drawdown_duration, max_drawdown, top_profit_contribution
from research_core.p4_short_research.p4_short_accounting import (
    INITIAL_BALANCE,
    CostScenario,
    short_entry_price,
    short_exit_price,
    short_liquidation_price,
    short_net_pnl,
    short_quantity,
)


def conservative_short_exit_from_bar(high: float, stop_loss: float, liquidation_price: float | None = None) -> tuple[str, float] | None:
    liq = liquidation_price if liquidation_price is not None else np.inf
    trigger = min(stop_loss, liq)
    if high < trigger:
        return None
    if liquidation_price is not None and high >= liquidation_price:
        return "liquidation_price", float(liquidation_price)
    if high >= stop_loss:
        return "atr_stop", float(stop_loss)
    return None


def _funding_for_trade(funding: pd.DataFrame | None, entry_time: pd.Timestamp, exit_time: pd.Timestamp, notional: float) -> tuple[float, float, str]:
    if funding is None or funding.empty:
        return 0.0, 0.0, "unavailable"
    frame = funding.copy()
    frame["funding_time"] = pd.to_datetime(frame["funding_time"], utc=True)
    part = frame[(frame["funding_time"] > entry_time) & (frame["funding_time"] <= exit_time)]
    if part.empty:
        return 0.0, 0.0, "available_no_events"
    # Binance fundingRate is paid by longs when positive; shorts receive it.
    amount = float((part["funding_rate"].astype(float) * notional).sum())
    if amount >= 0:
        return 0.0, amount, "available"
    return abs(amount), 0.0, "available"


def replay_short_events(
    events: pd.DataFrame,
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
    symbol: str,
    scenario: CostScenario,
    funding: pd.DataFrame | None = None,
    leverage: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    index_1m_ns = data_1m.index.view("int64")
    open_1m = data_1m["open"].to_numpy(float)
    high_1m = data_1m["high"].to_numpy(float)
    low_1m = data_1m["low"].to_numpy(float)
    close_1m = data_1m["close"].to_numpy(float)
    index_15m_ns = data_15m.index.view("int64")
    close_15m = data_15m["close"].to_numpy(float)
    upper_15m = data_15m["donchian20_upper"].to_numpy(float)
    equity = INITIAL_BALANCE
    next_available_time = pd.Timestamp.min.tz_localize("UTC")
    trades = []
    equity_rows = [{"time": data_1m.index[0], "equity": equity}]
    for _, event in events.sort_values("execution_time").iterrows():
        entry_time = pd.to_datetime(event["execution_time"], utc=True)
        signal_time = pd.to_datetime(event["signal_time"], utc=True)
        if entry_time <= next_available_time:
            continue
        entry_pos = int(np.searchsorted(index_1m_ns, entry_time.value, side="left"))
        if entry_pos >= len(index_1m_ns) or index_1m_ns[entry_pos] != entry_time.value:
            continue
        atr = float(event["atr14"])
        if not np.isfinite(atr) or atr <= 0:
            continue
        equity_before = equity
        raw_entry = float(open_1m[entry_pos])
        entry_price = short_entry_price(raw_entry, scenario.slippage_rate)
        notional = equity_before * leverage
        quantity = short_quantity(notional, entry_price)
        stop_loss = entry_price + 3.0 * atr
        liquidation_price = short_liquidation_price(entry_price, leverage) if leverage > 1 else np.inf
        exit_reason = "end_of_backtest"
        exit_time = data_1m.index[-1]
        exit_raw = float(close_1m[-1])
        min_low = raw_entry
        max_high = raw_entry
        start_15m = int(np.searchsorted(index_15m_ns, signal_time.value, side="right"))
        cursor = entry_pos
        for i in range(start_15m, len(index_15m_ns)):
            end_pos = int(np.searchsorted(index_1m_ns, index_15m_ns[i], side="left"))
            if end_pos > cursor:
                highs = high_1m[cursor:end_pos]
                lows = low_1m[cursor:end_pos]
                if len(highs):
                    max_high = max(max_high, float(np.nanmax(highs)))
                    min_low = min(min_low, float(np.nanmin(lows)))
                    hits = np.flatnonzero(highs >= min(stop_loss, liquidation_price))
                    if len(hits):
                        hit_pos = cursor + int(hits[0])
                        downside = conservative_short_exit_from_bar(float(highs[int(hits[0])]), stop_loss, liquidation_price)
                        if downside:
                            exit_reason, exit_raw = downside
                            exit_time = pd.Timestamp(index_1m_ns[hit_pos], tz="UTC")
                            break
                cursor = end_pos
            if close_15m[i] > upper_15m[i]:
                exit_pos = int(np.searchsorted(index_1m_ns, index_15m_ns[i], side="left"))
                if exit_pos >= len(index_1m_ns) or index_1m_ns[exit_pos] != index_15m_ns[i]:
                    exit_reason = "end_of_backtest"
                    exit_time = pd.Timestamp(index_1m_ns[-1], tz="UTC")
                    exit_raw = float(close_1m[-1])
                    break
                exit_raw = float(open_1m[exit_pos])
                if exit_raw >= min(stop_loss, liquidation_price):
                    downside = conservative_short_exit_from_bar(exit_raw, stop_loss, liquidation_price)
                    if downside:
                        exit_reason, exit_raw = downside
                    else:
                        exit_reason = "donchian20_exit"
                else:
                    exit_reason = "donchian20_exit"
                exit_time = pd.Timestamp(index_1m_ns[exit_pos], tz="UTC")
                break
        if exit_reason != "liquidation_price":
            exit_price = short_exit_price(exit_raw, scenario.slippage_rate)
            funding_paid, funding_received, funding_status = _funding_for_trade(funding, entry_time, exit_time, notional)
            acct = short_net_pnl(quantity, entry_price, exit_price, scenario.fee_rate, funding_paid=funding_paid, funding_received=funding_received)
            net_pnl = float(acct["net_pnl"])
            equity = equity_before + net_pnl
            liquidation = False
        else:
            exit_price = float(exit_raw)
            funding_paid, funding_received, funding_status = _funding_for_trade(funding, entry_time, exit_time, notional)
            liquidation_fee = notional * scenario.liquidation_fee_rate
            acct = short_net_pnl(quantity, entry_price, exit_price, scenario.fee_rate, funding_paid=funding_paid, funding_received=funding_received, liquidation_fee=liquidation_fee)
            net_pnl = max(float(acct["net_pnl"]), -equity_before)
            equity = max(equity_before + net_pnl, 0.0)
            liquidation = True
        next_available_time = exit_time
        mae_atr = (max_high - entry_price) / atr
        mfe_atr = (entry_price - min_low) / atr
        row = {
            "symbol": symbol,
            "prototype": "P4_SHORT_MIRROR_V1",
            "cost_scenario": scenario.name,
            "event_id": event.get("event_id", ""),
            "signal_time": signal_time,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "entry_notional": notional,
            "atr": atr,
            "stop_loss": stop_loss,
            "liquidation_price": liquidation_price,
            "gross_pnl": acct["gross_pnl"],
            "entry_fee": acct["entry_fee"],
            "exit_fee": acct["exit_fee"],
            "slippage": acct["slippage"],
            "funding_paid": acct["funding_paid"],
            "funding_received": acct["funding_received"],
            "liquidation_fee": acct["liquidation_fee"],
            "net_pnl": net_pnl,
            "accounting_error": acct["accounting_error"],
            "equity_before": equity_before,
            "equity_after": equity,
            "trade_return": net_pnl / equity_before if equity_before else np.nan,
            "exit_reason": exit_reason,
            "liquidation": liquidation,
            "funding_status": funding_status,
            "min_low_1m": min_low,
            "max_high_1m": max_high,
            "mae_atr": mae_atr,
            "mfe_atr": mfe_atr,
        }
        trades.append(row)
        equity_rows.append({"time": exit_time, "equity": equity})
    return pd.DataFrame(trades), pd.DataFrame(equity_rows)


def summarize_trades(trades: pd.DataFrame, equity: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "trade_count": 0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": np.nan,
            "win_rate": np.nan,
            "final_equity": INITIAL_BALANCE,
            "top1_profit_contribution": np.nan,
            "top3_profit_contribution": np.nan,
            "liquidation_count": 0,
            "longest_drawdown_duration": "",
        }
    pnl = trades["net_pnl"].astype(float)
    return {
        "trade_count": int(len(trades)),
        "total_return": float(equity["equity"].iloc[-1] / INITIAL_BALANCE - 1.0),
        "max_drawdown": max_drawdown(equity),
        "profit_factor": profit_factor(pnl),
        "win_rate": float((pnl > 0).mean()),
        "final_equity": float(equity["equity"].iloc[-1]),
        "top1_profit_contribution": top_profit_contribution(pnl, 1),
        "top3_profit_contribution": top_profit_contribution(pnl, 3),
        "top5_profit_contribution": top_profit_contribution(pnl, 5),
        "liquidation_count": int(trades["liquidation"].sum()),
        "longest_drawdown_duration": longest_drawdown_duration(equity),
    }

