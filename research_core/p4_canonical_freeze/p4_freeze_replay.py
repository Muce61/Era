"""Strict P4 Long fixed-1x replay for canonical freeze candidates."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research_core.leverage_research_analysis import INITIAL_BALANCE, profit_factor
from research_core.minimal_backtest_analysis import longest_drawdown_duration, max_drawdown, top_profit_contribution
from research_core.p4_canonical_freeze.p4_freeze_accounting import BASE_COST, CostScenario, long_net_pnl


def replay_long_fixed_1x(
    events: pd.DataFrame,
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
    symbol: str,
    candidate_id: str,
    gate: str,
    cost: CostScenario = BASE_COST,
    initial_balance: float = INITIAL_BALANCE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if data_1m.empty:
        return pd.DataFrame(), pd.DataFrame([{"time": pd.NaT, "equity": initial_balance}])
    index_1m_ns = data_1m.index.view("int64")
    open_1m = data_1m["open"].to_numpy(float)
    low_1m = data_1m["low"].to_numpy(float)
    high_1m = data_1m["high"].to_numpy(float)
    close_1m = data_1m["close"].to_numpy(float)
    index_15m_ns = data_15m.index.view("int64")
    close_15m = data_15m["close"].to_numpy(float)
    lower_15m = data_15m["donchian20_lower"].to_numpy(float)

    equity = float(initial_balance)
    next_available_time = pd.Timestamp.min.tz_localize("UTC")
    trades: list[dict] = []
    equity_rows = [{"time": data_1m.index[0], "equity": equity}]
    sorted_events = events.sort_values("execution_time")

    for _, event in sorted_events.iterrows():
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
        entry_price_for_stop = raw_entry * (1.0 + cost.entry_slippage_rate)
        stop_loss = entry_price_for_stop - 3.0 * atr
        exit_time = entry_time
        raw_exit = raw_entry
        exit_reason = "no_data"
        min_low = raw_entry
        max_high = raw_entry
        cursor = entry_pos
        start_15m = int(np.searchsorted(index_15m_ns, signal_time.value, side="right"))

        for i in range(start_15m, len(index_15m_ns)):
            end_pos = int(np.searchsorted(index_1m_ns, index_15m_ns[i], side="left"))
            if end_pos > cursor:
                lows = low_1m[cursor:end_pos]
                highs = high_1m[cursor:end_pos]
                if len(lows):
                    min_low = min(min_low, float(np.nanmin(lows)))
                    max_high = max(max_high, float(np.nanmax(highs)))
                    hits = np.flatnonzero(lows <= stop_loss)
                    if len(hits):
                        hit_pos = cursor + int(hits[0])
                        exit_time = pd.Timestamp(index_1m_ns[hit_pos], tz="UTC")
                        raw_exit = stop_loss
                        exit_reason = "atr_stop"
                        break
                cursor = end_pos
            if close_15m[i] < lower_15m[i]:
                exit_pos = int(np.searchsorted(index_1m_ns, index_15m_ns[i], side="left"))
                if exit_pos >= len(index_1m_ns) or index_1m_ns[exit_pos] != index_15m_ns[i]:
                    exit_time = pd.Timestamp(index_1m_ns[-1], tz="UTC")
                    raw_exit = float(close_1m[-1])
                    exit_reason = "end_of_backtest"
                else:
                    exit_time = pd.Timestamp(index_1m_ns[exit_pos], tz="UTC")
                    raw_exit = float(open_1m[exit_pos])
                    if raw_exit <= stop_loss:
                        raw_exit = stop_loss
                        exit_reason = "atr_stop"
                    else:
                        exit_reason = "donchian20_exit"
                break
        else:
            if entry_pos < len(index_1m_ns):
                min_low = min(min_low, float(np.nanmin(low_1m[entry_pos:])))
                max_high = max(max_high, float(np.nanmax(high_1m[entry_pos:])))
            exit_time = pd.Timestamp(index_1m_ns[-1], tz="UTC")
            raw_exit = float(close_1m[-1])
            exit_reason = "end_of_backtest"

        acct = long_net_pnl(equity_before, raw_entry, raw_exit, 1.0, cost)
        equity = equity_before + acct["net_pnl"]
        denom = atr / acct["entry_price"] if acct["entry_price"] else np.nan
        trades.append({
            "candidate_id": candidate_id,
            "symbol": symbol,
            "prototype": "P4_BREAKOUT_TOP20",
            "gate": gate,
            "leverage_mode": "fixed_1x",
            "cost_scenario": cost.name,
            "event_id": event.get("event_id", ""),
            "signal_time": signal_time,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "raw_entry_price": raw_entry,
            "raw_exit_price": raw_exit,
            "entry_price": acct["entry_price"],
            "exit_price": acct["exit_price"],
            "quantity": acct["quantity"],
            "entry_notional": acct["entry_notional"],
            "atr": atr,
            "stop_loss": stop_loss,
            "gross_pnl": acct["gross_pnl"],
            "entry_fee": acct["entry_fee"],
            "exit_fee": acct["exit_fee"],
            "slippage": acct["slippage"],
            "funding_paid": acct["funding_paid"],
            "funding_received": acct["funding_received"],
            "net_pnl": acct["net_pnl"],
            "accounting_error": acct["accounting_error"],
            "trade_return": acct["net_pnl"] / equity_before if equity_before else np.nan,
            "equity_before": equity_before,
            "equity_after": equity,
            "min_low_1m": min_low,
            "max_high_1m": max_high,
            "mae_atr": (min_low / acct["entry_price"] - 1.0) / denom if np.isfinite(denom) and denom else np.nan,
            "mfe_atr": (max_high / acct["entry_price"] - 1.0) / denom if np.isfinite(denom) and denom else np.nan,
            "exit_reason": exit_reason,
            "liquidation": False,
        })
        next_available_time = exit_time
        equity_rows.append({"time": exit_time, "equity": equity})
    return pd.DataFrame(trades), pd.DataFrame(equity_rows)


def summarize_trades(trades: pd.DataFrame, equity: pd.DataFrame, candidate_id: str) -> dict:
    pnl = trades["net_pnl"] if not trades.empty else pd.Series(dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    final_equity = float(equity["equity"].iloc[-1]) if not equity.empty else INITIAL_BALANCE
    return {
        "candidate_id": candidate_id,
        "trade_count": int(len(trades)),
        "base_cost_total_return": final_equity / INITIAL_BALANCE - 1.0,
        "total_return": final_equity / INITIAL_BALANCE - 1.0,
        "base_cost_profit_factor": profit_factor(pnl),
        "profit_factor": profit_factor(pnl),
        "base_cost_max_drawdown": max_drawdown(equity["equity"] if "equity" in equity else pd.Series(dtype=float)),
        "max_drawdown": max_drawdown(equity["equity"] if "equity" in equity else pd.Series(dtype=float)),
        "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
        "avg_win": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss": float(losses.mean()) if len(losses) else np.nan,
        "payoff_ratio": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else np.nan,
        "final_equity": final_equity,
        "liquidation_count": int(trades["liquidation"].sum()) if "liquidation" in trades else 0,
        "top1_profit_contribution": top_profit_contribution(pnl, 1),
        "top3_profit_contribution": top_profit_contribution(pnl, 3),
        "top5_profit_contribution": top_profit_contribution(pnl, 5),
        "longest_drawdown_duration": longest_drawdown_duration(equity),
        "longest_drawdown_seconds": _duration_seconds(longest_drawdown_duration(equity)),
        "accounting_identity_max_abs_error": float(trades["accounting_error"].abs().max()) if not trades.empty else 0.0,
    }


def _duration_seconds(value: object) -> float:
    try:
        return float(pd.Timedelta(value).total_seconds())
    except Exception:
        return 0.0


def combine_equal_weight(equities: dict[str, pd.DataFrame], candidate_id: str = "C3") -> pd.DataFrame:
    frames = []
    for symbol, eq in equities.items():
        part = eq[["time", "equity"]].copy()
        part["time"] = pd.to_datetime(part["time"], utc=True)
        part = part.drop_duplicates("time").set_index("time").sort_index()
        part[symbol] = part["equity"] / INITIAL_BALANCE
        frames.append(part[[symbol]])
    if not frames:
        return pd.DataFrame()
    joined = frames[0]
    for frame in frames[1:]:
        joined = joined.join(frame, how="outer")
    joined = joined.sort_index().ffill().fillna(1.0)
    out = pd.DataFrame({"time": joined.index, "equity": joined.mean(axis=1) * INITIAL_BALANCE})
    out["candidate_id"] = candidate_id
    return out.reset_index(drop=True)


def combine_trade_pnls(trades_by_symbol: dict[str, pd.DataFrame], candidate_id: str = "C3") -> pd.DataFrame:
    frames = []
    for symbol, trades in trades_by_symbol.items():
        if trades.empty:
            continue
        part = trades.copy()
        part["candidate_id"] = candidate_id
        # C3 uses 50/50 initial capital. Scaling PnL by 0.5 matches the equity-combination return path.
        for col in ["net_pnl", "gross_pnl", "entry_fee", "exit_fee", "slippage", "funding_paid", "funding_received"]:
            if col in part.columns:
                part[col] = part[col] * 0.5
        frames.append(part)
    return pd.concat(frames, ignore_index=True).sort_values("exit_time").reset_index(drop=True) if frames else pd.DataFrame()


def compare_trades_to_rb2(current: pd.DataFrame, rb2_path: str | None) -> dict:
    if not rb2_path:
        return {"reproduction_status": "no_rb2_reference", "rb2_trade_count": np.nan, "current_trade_count": len(current), "mismatch_count": 0}
    try:
        rb2 = pd.read_csv(rb2_path)
    except Exception:
        return {"reproduction_status": "no_rb2_reference", "rb2_trade_count": np.nan, "current_trade_count": len(current), "mismatch_count": 0}
    cols = ["entry_time", "exit_time"]
    cur = current[cols].astype(str).reset_index(drop=True) if not current.empty else pd.DataFrame(columns=cols)
    old = rb2[cols].astype(str).reset_index(drop=True) if not rb2.empty and set(cols).issubset(rb2.columns) else pd.DataFrame(columns=cols)
    count_match = len(cur) == len(old)
    mismatch = 0
    if count_match and len(cur):
        mismatch = int((cur != old).any(axis=1).sum())
    else:
        mismatch = abs(len(cur) - len(old))
    return {
        "reproduction_status": "matched" if count_match and mismatch == 0 else "mismatch",
        "rb2_trade_count": int(len(old)),
        "current_trade_count": int(len(cur)),
        "mismatch_count": int(mismatch),
    }
