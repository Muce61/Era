"""Strict 1m replay for high-leverage gate research.

This module replays accepted high-leverage events from raw 1m bars. It does not
reuse precomputed exit_time/exit_price/MAE to decide exits.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research_core.event_table import add_base_indicators, strict_resample_15m
from research_core.high_leverage_gate_analysis import downshift_leverage
from research_core.leverage_research_analysis import (
    FEE_RATE,
    INITIAL_BALANCE,
    MAINTENANCE_MARGIN_RATE,
    SLIPPAGE_RATE,
    adaptive_leverage_by_mode,
    fixed_leverage_for_mode,
    profit_factor,
    recent_loss_count,
    shifted_liquidation_price,
    summarize_leverage,
)
from research_core.minimal_backtest_analysis import max_drawdown


STRICT_LEVERAGE_MODES = [
    "fixed_20x",
    "adaptive_3x_8x_v1",
]


def downside_exit_from_bar(low: float, stop_loss: float, liquidation_price: float) -> tuple[str, float] | None:
    trigger = max(stop_loss, liquidation_price)
    if low > trigger:
        return None
    if liquidation_price >= stop_loss:
        return "liquidation_price", liquidation_price
    return "atr_stop", stop_loss


def _event_signal_time(event: pd.Series) -> pd.Timestamp:
    if "signal_time" in event and pd.notna(event["signal_time"]):
        return pd.to_datetime(event["signal_time"], utc=True)
    event_id = str(event.get("event_id", ""))
    if "_" in event_id:
        return pd.to_datetime(event_id.split("_", 1)[1], utc=True)
    return pd.to_datetime(event["entry_time"], utc=True) - pd.Timedelta(minutes=1)


def _event_entry_time(event: pd.Series) -> pd.Timestamp:
    if "execution_time" in event and pd.notna(event["execution_time"]):
        return pd.to_datetime(event["execution_time"], utc=True)
    return pd.to_datetime(event["entry_time"], utc=True)


def _event_atr(event: pd.Series) -> float:
    if "atr14" in event and pd.notna(event["atr14"]):
        return float(event["atr14"])
    return float(event["atr"])


def strict_replay_events(
    events: pd.DataFrame,
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
    symbol: str,
    prototype: str,
    gate: str,
    leverage_mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    index_1m_ns = data_1m.index.view("int64")
    open_1m = data_1m["open"].to_numpy(float)
    high_1m = data_1m["high"].to_numpy(float)
    low_1m = data_1m["low"].to_numpy(float)
    close_1m = data_1m["close"].to_numpy(float)
    index_15m_ns = data_15m.index.view("int64")
    close_15m = data_15m["close"].to_numpy(float)
    lower_15m = data_15m["donchian20_lower"].to_numpy(float)
    equity = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    next_available_time = pd.Timestamp.min.tz_localize("UTC")
    pnl_history: list[float] = []
    trades = []
    audit = []
    equity_rows = [{"time": data_1m.index[0], "equity": equity}]
    sorted_events = events.sort_values("execution_time" if "execution_time" in events.columns else "entry_time")

    for _, event in sorted_events.iterrows():
        entry_time = _event_entry_time(event)
        signal_time = _event_signal_time(event)
        entry_pos = int(np.searchsorted(index_1m_ns, entry_time.value, side="left"))
        if (
            entry_time <= next_available_time
            or entry_pos >= len(index_1m_ns)
            or index_1m_ns[entry_pos] != entry_time.value
        ):
            continue
        atr = _event_atr(event)
        if not np.isfinite(atr) or atr <= 0:
            continue
        equity_before = equity
        peak = max(peak, equity_before)
        drawdown_before = 1 - equity_before / peak if peak else 0.0
        losses = recent_loss_count(pnl_history)
        breakout_q = float(event.get("breakout_score_quantile", np.nan))
        atr_rank = float(event.get("atr_pct_rank", np.nan))
        if leverage_mode.startswith("adaptive_"):
            leverage, reason, base_leverage = adaptive_leverage_by_mode(
                leverage_mode,
                prototype,
                breakout_q,
                atr_rank,
                drawdown_before,
                losses,
            )
        else:
            leverage = fixed_leverage_for_mode(leverage_mode)
            reason = leverage_mode
            base_leverage = leverage
        if gate == "G4_RISK_MONITOR_DOWNSHIFT":
            leverage, gate_reason = downshift_leverage(leverage_mode, leverage, bool(event.get("gate_high_risk", False)))
            reason = f"{reason}|{gate_reason}"

        raw_entry = float(open_1m[entry_pos])
        entry_price = raw_entry * (1 + SLIPPAGE_RATE)
        quantity = equity_before * leverage / entry_price
        stop_loss = entry_price - 3.0 * atr
        liq_price = entry_price * (1 - 1 / leverage + MAINTENANCE_MARGIN_RATE)
        exit_time = entry_time
        exit_raw = raw_entry
        exit_price = entry_price
        exit_reason = "no_data"
        min_low = raw_entry
        max_high = raw_entry

        cursor = entry_pos
        start_15m = int(np.searchsorted(index_15m_ns, signal_time.value, side="right"))
        trigger = max(stop_loss, liq_price)
        downside_reason = "liquidation_price" if liq_price >= stop_loss else "atr_stop"
        downside_price = liq_price if downside_reason == "liquidation_price" else stop_loss
        for i in range(start_15m, len(index_15m_ns)):
            end_pos = int(np.searchsorted(index_1m_ns, index_15m_ns[i], side="right"))
            if end_pos > cursor:
                lows = low_1m[cursor:end_pos]
                highs = high_1m[cursor:end_pos]
                if len(lows):
                    min_low = min(min_low, float(np.nanmin(lows)))
                    max_high = max(max_high, float(np.nanmax(highs)))
                    hits = np.flatnonzero(lows <= trigger)
                    if len(hits):
                        hit_pos = cursor + int(hits[0])
                        exit_reason = downside_reason
                        raw_exit = downside_price
                        exit_time = pd.Timestamp(index_1m_ns[hit_pos], tz="UTC")
                        exit_price = raw_exit if exit_reason == "liquidation_price" else raw_exit * (1 - SLIPPAGE_RATE)
                        break
                cursor = end_pos
            if close_15m[i] < lower_15m[i]:
                exit_reason = "donchian20_exit"
                exit_time = pd.Timestamp(index_15m_ns[i], tz="UTC")
                exit_raw = float(close_15m[i])
                exit_price = exit_raw * (1 - SLIPPAGE_RATE)
                break
        else:
            if entry_pos < len(index_1m_ns):
                min_low = min(min_low, float(np.nanmin(low_1m[entry_pos:])))
                max_high = max(max_high, float(np.nanmax(high_1m[entry_pos:])))
                exit_reason = "end_of_backtest"
                exit_time = pd.Timestamp(index_1m_ns[-1], tz="UTC")
                exit_raw = float(close_1m[-1])
                exit_price = exit_raw * (1 - SLIPPAGE_RATE)

        if exit_reason == "liquidation_price":
            net_pnl = -equity_before * 0.95
            equity = equity_before * 0.05
            liquidation = True
            risk_event = "liquidation_price"
        else:
            gross = (exit_price - entry_price) * quantity
            entry_fee = equity_before * leverage * FEE_RATE
            exit_fee = quantity * exit_price * FEE_RATE
            net_pnl = gross - entry_fee - exit_fee
            projected = equity_before + net_pnl
            liquidation = False
            risk_event = ""
            if projected <= equity_before * 0.05:
                net_pnl = -equity_before * 0.95
                equity = equity_before * 0.05
                liquidation = True
                risk_event = "account_floor_after_costs"
            else:
                equity = projected
        pnl_history.append(net_pnl)
        next_available_time = exit_time
        mae_atr = (min_low / entry_price - 1.0) / (atr / entry_price)
        mfe_atr = (max_high / entry_price - 1.0) / (atr / entry_price)
        trades.append({
            "symbol": symbol,
            "prototype": prototype,
            "gate": gate,
            "leverage_mode": leverage_mode,
            "event_id": event.get("event_id", ""),
            "signal_time": signal_time,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "atr": atr,
            "stop_loss": stop_loss,
            "liquidation_price": liq_price,
            "min_low_1m": min_low,
            "max_high_1m": max_high,
            "mae_atr": mae_atr,
            "mfe_atr": mfe_atr,
            "leverage": leverage,
            "net_pnl": net_pnl,
            "trade_return": net_pnl / equity_before if equity_before else np.nan,
            "equity_before": equity_before,
            "equity_after": equity,
            "liquidation": liquidation,
            "risk_event": risk_event,
            "exit_reason": exit_reason,
            "reason": reason,
        })
        audit.append({
            "symbol": symbol,
            "prototype": prototype,
            "gate": gate,
            "leverage_mode": leverage_mode,
            "event_id": event.get("event_id", ""),
            "base_leverage": base_leverage,
            "final_leverage": leverage,
            "equity_drawdown_before_entry": drawdown_before,
            "recent_3_loss_count": losses,
            "gate_high_risk": bool(event.get("gate_high_risk", False)),
            "reason": reason,
        })
        equity_rows.append({"time": exit_time, "equity": equity})

    return pd.DataFrame(trades), pd.DataFrame(equity_rows), pd.DataFrame(audit)


def strict_summary(trades: pd.DataFrame, equity: pd.DataFrame) -> dict:
    summary = summarize_leverage(trades, equity)
    if not trades.empty:
        summary["atr_stop_count"] = int((trades["exit_reason"] == "atr_stop").sum())
        summary["donchian20_exit_count"] = int((trades["exit_reason"] == "donchian20_exit").sum())
        summary["end_of_backtest_count"] = int((trades["exit_reason"] == "end_of_backtest").sum())
    else:
        summary["atr_stop_count"] = 0
        summary["donchian20_exit_count"] = 0
        summary["end_of_backtest_count"] = 0
    return summary


def compare_proxy_to_strict(proxy: pd.DataFrame, strict: pd.DataFrame) -> pd.DataFrame:
    keys = ["symbol", "prototype", "gate", "leverage_mode"]
    rows = []
    proxy_index = proxy.set_index(keys)
    for _, row in strict.iterrows():
        key = tuple(row[k] for k in keys)
        base = proxy_index.loc[key] if key in proxy_index.index else pd.Series(dtype=object)
        rows.append({
            **{k: row[k] for k in keys},
            "proxy_trade_count": base.get("trade_count", np.nan),
            "strict_trade_count": row.get("trade_count", np.nan),
            "proxy_total_return": base.get("total_return", np.nan),
            "strict_total_return": row.get("total_return", np.nan),
            "proxy_profit_factor": base.get("profit_factor", np.nan),
            "strict_profit_factor": row.get("profit_factor", np.nan),
            "proxy_max_drawdown": base.get("max_drawdown", np.nan),
            "strict_max_drawdown": row.get("max_drawdown", np.nan),
            "proxy_liquidation_count": base.get("liquidation_count", np.nan),
            "strict_liquidation_count": row.get("liquidation_count", np.nan),
        })
    return pd.DataFrame(rows)


__all__ = [
    "STRICT_LEVERAGE_MODES",
    "downside_exit_from_bar",
    "strict_replay_events",
    "strict_summary",
    "compare_proxy_to_strict",
]
