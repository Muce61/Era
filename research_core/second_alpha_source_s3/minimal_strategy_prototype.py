"""S3 minimal strategy prototype for exit-window IDLE_MR1 events."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.accounting import execute_entry, execute_exit, gross_pnl, trade_net_pnl
from research_core.common import RESEARCH_ROOT
from research_core.event_table import add_base_indicators, load_ohlcv_1m, strict_resample_15m
from research_core.leverage_research_analysis import FEE_RATE, INITIAL_BALANCE, SLIPPAGE_RATE
from research_core.minimal_backtest_analysis import longest_drawdown_duration, max_drawdown, profit_factor, top_profit_contribution


S28_EVENTS = RESEARCH_ROOT / "second_alpha_source_s28" / "long_history_exit_window_events.parquet"
S29_DIR = RESEARCH_ROOT / "second_alpha_source_s29"
S3_DIR = RESEARCH_ROOT / "second_alpha_source_s3"
LONG_HISTORY_ROOT = Path("/Users/muce/1m_data/long_history_1m/merged")
SYMBOLS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
CANDIDATE = "IDLE_MR1_P4_IDLE_REVERSION"
EXIT_BUCKET = "after_p4_exit_5_16_bars"
PROTOTYPE = "S3_EXIT_WINDOW_IDLE_MR1"
SIZING_MODES = ["fixed_1x", "fixed_risk_0_5pct"]
SIDE_SCOPES = ["both", "long_only", "short_only"]
MAX_HOLD_MINUTES = 240


@dataclass(frozen=True)
class S3Params:
    initial_balance: float = INITIAL_BALANCE
    fee_rate: float = FEE_RATE
    slippage_rate: float = SLIPPAGE_RATE
    risk_fraction: float = 0.005
    max_leverage: float = 1.0
    atr_stop_mult: float = 1.0


def input_validation() -> pd.DataFrame:
    s29_decision_path = S29_DIR / "s29_decision_summary.csv"
    s29_exists = s29_decision_path.exists()
    s29_decision = ""
    if s29_exists:
        s29 = pd.read_csv(s29_decision_path)
        s29_decision = str(s29.get("decision_letter", pd.Series([""])).iloc[0])
    events_available = S28_EVENTS.exists()
    event_count = 0
    if events_available:
        try:
            event_count = int(len(pd.read_parquet(S28_EVENTS, columns=["event_id"])))
        except Exception:
            events_available = False
    data_symbols = [s for s in SYMBOLS if (LONG_HISTORY_ROOT / f"{s}.csv").exists()]
    ok = s29_exists and s29_decision == "A" and events_available and event_count >= 1000 and len(data_symbols) >= 3
    return pd.DataFrame([{
        "s29_exists": bool(s29_exists),
        "s29_decision": s29_decision,
        "events_available": bool(events_available),
        "event_count": event_count,
        "symbols_available": ",".join(data_symbols),
        "symbol_count": len(data_symbols),
        "candidate": CANDIDATE,
        "p4_state_bucket": EXIT_BUCKET,
        "input_validation_status": "pass" if ok else "blocked",
        "data_layer": "expanded_discovery_long_history",
        "oos_status": "not_oos",
    }])


def load_events() -> pd.DataFrame:
    events = pd.read_parquet(S28_EVENTS)
    out = events[
        (events["candidate"] == CANDIDATE)
        & (events["p4_state_bucket"] == EXIT_BUCKET)
        & (events["symbol"].isin(SYMBOLS))
    ].copy()
    out["signal_time"] = pd.to_datetime(out["signal_time"], utc=True)
    out["execution_time"] = pd.to_datetime(out["execution_time"], utc=True)
    return out.sort_values(["symbol", "execution_time", "event_id"]).reset_index(drop=True)


def load_symbol_data(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    data_1m = load_ohlcv_1m(LONG_HISTORY_ROOT / f"{symbol}.csv")
    data_15m = add_base_indicators(strict_resample_15m(data_1m))
    return data_1m, data_15m


def build_p4_restart_times(data_15m: pd.DataFrame) -> set[pd.Timestamp]:
    cond = (
        (data_15m["close"] > data_15m["donchian55_upper"])
        & (data_15m["ema50"] > data_15m["ema200"])
        & data_15m["atr14"].notna()
    )
    return set(data_15m.index[cond.fillna(False)])


def market_arrays(data_1m: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "index_ns": data_1m.index.view("int64"),
        "open": data_1m["open"].to_numpy(float),
        "high": data_1m["high"].to_numpy(float),
        "low": data_1m["low"].to_numpy(float),
        "close": data_1m["close"].to_numpy(float),
    }


def quantity_for_sizing(equity: float, entry_price: float, atr: float, sizing_mode: str, params: S3Params) -> float:
    if sizing_mode == "fixed_1x":
        return equity * params.max_leverage / entry_price
    if sizing_mode == "fixed_risk_0_5pct":
        stop_distance = atr * params.atr_stop_mult
        if stop_distance <= 0:
            return 0.0
        by_risk = equity * params.risk_fraction / stop_distance
        by_leverage = equity * params.max_leverage / entry_price
        return min(by_risk, by_leverage)
    raise ValueError(f"Unknown sizing mode: {sizing_mode}")


def _mean_target(row: pd.Series, side: str) -> float:
    values = [float(row.get("ema20", np.nan)), float(row.get("range_mid", np.nan))]
    values = [v for v in values if np.isfinite(v)]
    if not values:
        return np.nan
    entry = float(row.get("execution_open", np.nan))
    if side == "long":
        above = [v for v in values if v >= entry]
        return min(above) if above else max(values)
    below = [v for v in values if v <= entry]
    return max(below) if below else min(values)


def replay_exit(
    event: pd.Series,
    data_1m: pd.DataFrame,
    p4_restart_times: set[pd.Timestamp],
    side: str,
    entry_time: pd.Timestamp,
    entry_price: float,
    atr: float,
) -> tuple[pd.Timestamp, float, str, float, float, int]:
    max_exit_time = entry_time + pd.Timedelta(minutes=MAX_HOLD_MINUTES)
    stop_price = entry_price - atr if side == "long" else entry_price + atr
    target = _mean_target(event, side)
    window = data_1m.loc[(data_1m.index >= entry_time) & (data_1m.index <= max_exit_time)]
    mae = 0.0
    mfe = 0.0
    for ts, bar in window.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        open_price = float(bar["open"])
        if side == "long":
            mae = min(mae, low / entry_price - 1.0)
            mfe = max(mfe, high / entry_price - 1.0)
            hit_stop = open_price <= stop_price or low <= stop_price
            hit_mean = np.isfinite(target) and (open_price >= target or high >= target)
            if hit_stop and hit_mean:
                return ts, min(stop_price, target), "stop_and_mean_conservative", mae / (atr / entry_price), mfe / (atr / entry_price), int((ts - entry_time).total_seconds() // 60)
            if hit_stop:
                return ts, open_price if open_price <= stop_price else stop_price, "atr_stop", mae / (atr / entry_price), mfe / (atr / entry_price), int((ts - entry_time).total_seconds() // 60)
            if hit_mean:
                return ts, open_price if open_price >= target else target, "mean_exit", mae / (atr / entry_price), mfe / (atr / entry_price), int((ts - entry_time).total_seconds() // 60)
        else:
            mae = min(mae, entry_price / high - 1.0)
            mfe = max(mfe, entry_price / low - 1.0)
            hit_stop = open_price >= stop_price or high >= stop_price
            hit_mean = np.isfinite(target) and (open_price <= target or low <= target)
            if hit_stop and hit_mean:
                return ts, max(stop_price, target), "stop_and_mean_conservative", mae / (atr / entry_price), mfe / (atr / entry_price), int((ts - entry_time).total_seconds() // 60)
            if hit_stop:
                return ts, open_price if open_price >= stop_price else stop_price, "atr_stop", mae / (atr / entry_price), mfe / (atr / entry_price), int((ts - entry_time).total_seconds() // 60)
            if hit_mean:
                return ts, open_price if open_price <= target else target, "mean_exit", mae / (atr / entry_price), mfe / (atr / entry_price), int((ts - entry_time).total_seconds() // 60)
        if ts in p4_restart_times:
            # P4 is long-only. It is opposite only to short mean-reversion trades.
            if side == "short":
                return ts, open_price, "trend_restart_exit", mae / (atr / entry_price), mfe / (atr / entry_price), int((ts - entry_time).total_seconds() // 60)
        if ts >= max_exit_time:
            return ts, open_price, "time_stop", mae / (atr / entry_price), mfe / (atr / entry_price), int((ts - entry_time).total_seconds() // 60)
    if window.empty:
        return entry_time, entry_price, "missing_exit_data", 0.0, 0.0, 0
    last = window.iloc[-1]
    return window.index[-1], float(last["close"]), "end_of_data", mae / (atr / entry_price), mfe / (atr / entry_price), int((window.index[-1] - entry_time).total_seconds() // 60)


def replay_exit_arrays(
    event: pd.Series,
    arrays: dict[str, np.ndarray],
    p4_restart_ns: set[int],
    side: str,
    entry_time: pd.Timestamp,
    entry_price: float,
    atr: float,
) -> tuple[pd.Timestamp, float, str, float, float, int]:
    idx = arrays["index_ns"]
    start = int(np.searchsorted(idx, pd.Timestamp(entry_time).value, side="left"))
    if start >= len(idx):
        return entry_time, entry_price, "missing_exit_data", 0.0, 0.0, 0
    end_time = entry_time + pd.Timedelta(minutes=MAX_HOLD_MINUTES)
    end = int(np.searchsorted(idx, pd.Timestamp(end_time).value, side="right"))
    end = min(end, len(idx))
    stop_price = entry_price - atr if side == "long" else entry_price + atr
    target = _mean_target(event, side)
    mae = 0.0
    mfe = 0.0
    denom = atr / entry_price
    for pos in range(start, end):
        ts_ns = int(idx[pos])
        open_price = float(arrays["open"][pos])
        high = float(arrays["high"][pos])
        low = float(arrays["low"][pos])
        if side == "long":
            mae = min(mae, low / entry_price - 1.0)
            mfe = max(mfe, high / entry_price - 1.0)
            hit_stop = open_price <= stop_price or low <= stop_price
            hit_mean = np.isfinite(target) and (open_price >= target or high >= target)
            if hit_stop and hit_mean:
                return pd.Timestamp(ts_ns, tz="UTC"), min(stop_price, target), "stop_and_mean_conservative", mae / denom, mfe / denom, int((ts_ns - pd.Timestamp(entry_time).value) // 60_000_000_000)
            if hit_stop:
                return pd.Timestamp(ts_ns, tz="UTC"), open_price if open_price <= stop_price else stop_price, "atr_stop", mae / denom, mfe / denom, int((ts_ns - pd.Timestamp(entry_time).value) // 60_000_000_000)
            if hit_mean:
                return pd.Timestamp(ts_ns, tz="UTC"), open_price if open_price >= target else target, "mean_exit", mae / denom, mfe / denom, int((ts_ns - pd.Timestamp(entry_time).value) // 60_000_000_000)
        else:
            mae = min(mae, entry_price / high - 1.0)
            mfe = max(mfe, entry_price / low - 1.0)
            hit_stop = open_price >= stop_price or high >= stop_price
            hit_mean = np.isfinite(target) and (open_price <= target or low <= target)
            if hit_stop and hit_mean:
                return pd.Timestamp(ts_ns, tz="UTC"), max(stop_price, target), "stop_and_mean_conservative", mae / denom, mfe / denom, int((ts_ns - pd.Timestamp(entry_time).value) // 60_000_000_000)
            if hit_stop:
                return pd.Timestamp(ts_ns, tz="UTC"), open_price if open_price >= stop_price else stop_price, "atr_stop", mae / denom, mfe / denom, int((ts_ns - pd.Timestamp(entry_time).value) // 60_000_000_000)
            if hit_mean:
                return pd.Timestamp(ts_ns, tz="UTC"), open_price if open_price <= target else target, "mean_exit", mae / denom, mfe / denom, int((ts_ns - pd.Timestamp(entry_time).value) // 60_000_000_000)
        if ts_ns in p4_restart_ns and side == "short":
            return pd.Timestamp(ts_ns, tz="UTC"), open_price, "trend_restart_exit", mae / denom, mfe / denom, int((ts_ns - pd.Timestamp(entry_time).value) // 60_000_000_000)
        if ts_ns >= pd.Timestamp(end_time).value:
            return pd.Timestamp(ts_ns, tz="UTC"), open_price, "time_stop", mae / denom, mfe / denom, int((ts_ns - pd.Timestamp(entry_time).value) // 60_000_000_000)
    last = max(start, end - 1)
    return pd.Timestamp(idx[last], tz="UTC"), float(arrays["close"][last]), "end_of_data", mae / denom, mfe / denom, int((idx[last] - pd.Timestamp(entry_time).value) // 60_000_000_000)


def run_backtest_for_symbol(
    events: pd.DataFrame,
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
    symbol: str,
    sizing_mode: str,
    side_scope: str = "both",
    params: S3Params = S3Params(),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if side_scope == "long_only":
        events = events[events["side"] == "long"].copy()
    elif side_scope == "short_only":
        events = events[events["side"] == "short"].copy()
    p4_restart = build_p4_restart_times(data_15m)
    p4_restart_ns = {pd.Timestamp(ts).value for ts in p4_restart}
    arrays = market_arrays(data_1m)
    equity = params.initial_balance
    trades = []
    conversion_rows = []
    next_available = pd.Timestamp.min.tz_localize("UTC")
    equity_rows = [{"time": data_1m.index.min(), "equity": equity, "symbol": symbol, "sizing_mode": sizing_mode, "side_scope": side_scope}]
    for _, event in events.sort_values("execution_time").iterrows():
        entry_time = pd.to_datetime(event["execution_time"], utc=True)
        side = str(event["side"])
        if entry_time not in data_1m.index:
            conversion_rows.append({"event_id": event.get("event_id", ""), "symbol": symbol, "side": side, "status": "missing_execution", "bars_held": np.nan})
            continue
        if entry_time <= next_available:
            conversion_rows.append({"event_id": event.get("event_id", ""), "symbol": symbol, "side": side, "status": "ignored_due_to_position", "bars_held": np.nan})
            continue
        atr = float(event["atr14"])
        if not np.isfinite(atr) or atr <= 0:
            conversion_rows.append({"event_id": event.get("event_id", ""), "symbol": symbol, "side": side, "status": "invalid_atr", "bars_held": np.nan})
            continue
        raw_entry = float(data_1m.loc[entry_time, "open"])
        trade_side = "LONG" if side == "long" else "SHORT"
        preliminary = raw_entry * (1 + params.slippage_rate if side == "long" else 1 - params.slippage_rate)
        qty = quantity_for_sizing(equity, preliminary, atr, sizing_mode, params)
        if qty <= 0:
            conversion_rows.append({"event_id": event.get("event_id", ""), "symbol": symbol, "side": side, "status": "invalid_quantity", "bars_held": np.nan})
            continue
        entry_fill = execute_entry(raw_entry, qty, trade_side, params.fee_rate, params.slippage_rate)
        exit_time, raw_exit, exit_reason, mae_atr, mfe_atr, minutes_held = replay_exit_arrays(
            event, arrays, p4_restart_ns, side, entry_time, entry_fill.executed_price, atr
        )
        exit_fill = execute_exit(raw_exit, qty, trade_side, params.fee_rate, params.slippage_rate)
        gross = gross_pnl(entry_fill.executed_price, exit_fill.executed_price, qty, trade_side)
        net = trade_net_pnl(gross, entry_fill.fee, exit_fill.fee)
        before = equity
        equity += net
        next_available = exit_time
        bars_held = minutes_held / 15.0
        trades.append({
            "prototype": PROTOTYPE,
            "symbol": symbol,
            "side": side,
            "side_scope": side_scope,
            "sizing_mode": sizing_mode,
            "event_id": event.get("event_id", ""),
            "signal_time": event["signal_time"],
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_raw_price": raw_entry,
            "entry_price": entry_fill.executed_price,
            "exit_raw_price": raw_exit,
            "exit_price": exit_fill.executed_price,
            "quantity": qty,
            "atr": atr,
            "gross_pnl": gross,
            "entry_fee": entry_fill.fee,
            "exit_fee": exit_fill.fee,
            "total_fee": entry_fill.fee + exit_fill.fee,
            "funding_fee": 0.0,
            "funding_status": "unavailable",
            "net_pnl": net,
            "trade_return": net / before if before else np.nan,
            "equity_before": before,
            "equity_after": equity,
            "mae_atr": mae_atr,
            "mfe_atr": mfe_atr,
            "bars_held": bars_held,
            "exit_reason": exit_reason,
        })
        conversion_rows.append({"event_id": event.get("event_id", ""), "symbol": symbol, "side": side, "status": "traded", "bars_held": bars_held})
        equity_rows.append({"time": exit_time, "equity": equity, "symbol": symbol, "sizing_mode": sizing_mode, "side_scope": side_scope})
    return pd.DataFrame(trades), pd.DataFrame(equity_rows), pd.DataFrame(conversion_rows)


def annualized_return(final_equity: float, start: pd.Timestamp, end: pd.Timestamp, initial: float = INITIAL_BALANCE) -> float:
    years = max((end - start).total_seconds() / (365.25 * 24 * 3600), 1e-9)
    return (final_equity / initial) ** (1 / years) - 1 if final_equity > 0 else -1.0


def summarize_trades(symbol: str, side_scope: str, sizing_mode: str, trades: pd.DataFrame, equity: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    pnl = trades["net_pnl"] if not trades.empty else pd.Series(dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    final = float(equity["equity"].iloc[-1]) if not equity.empty else INITIAL_BALANCE
    gross_profit = float(trades.loc[trades["gross_pnl"] > 0, "gross_pnl"].sum()) if not trades.empty else 0.0
    fees = float(trades["total_fee"].sum()) if not trades.empty else 0.0
    return {
        "symbol": symbol,
        "side_scope": side_scope,
        "sizing_mode": sizing_mode,
        "trade_count": int(len(trades)),
        "total_return": final / INITIAL_BALANCE - 1,
        "annualized_return": annualized_return(final, start, end),
        "max_drawdown": max_drawdown(equity["equity"]) if not equity.empty else np.nan,
        "profit_factor": profit_factor(pnl),
        "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
        "avg_win": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss": float(losses.mean()) if len(losses) else np.nan,
        "payoff_ratio": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else np.nan,
        "avg_bars_held": float(trades["bars_held"].mean()) if not trades.empty else np.nan,
        "median_bars_held": float(trades["bars_held"].median()) if not trades.empty else np.nan,
        "fee_to_gross_profit_ratio": fees / gross_profit if gross_profit > 0 else np.nan,
        "funding_status": "unavailable",
        "final_equity": final,
        "top1_profit_contribution": top_profit_contribution(pnl, 1),
        "top3_profit_contribution": top_profit_contribution(pnl, 3),
        "top5_profit_contribution": top_profit_contribution(pnl, 5),
        "longest_drawdown_duration": longest_drawdown_duration(equity),
        "sample_status": "valid" if len(trades) >= 30 else "insufficient_sample",
    }


def event_to_trade_conversion(conversions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if conversions.empty:
        return pd.DataFrame(columns=[
            "symbol", "side", "event_count", "trade_count", "conversion_rate",
            "ignored_due_to_position_count", "missing_execution_count", "avg_bars_held", "median_bars_held",
        ])
    for (symbol, side), part in conversions.groupby(["symbol", "side"], dropna=False):
        traded = part[part["status"] == "traded"]
        rows.append({
            "symbol": symbol,
            "side": side,
            "event_count": int(len(part)),
            "trade_count": int(len(traded)),
            "conversion_rate": float(len(traded) / len(part)) if len(part) else np.nan,
            "ignored_due_to_position_count": int((part["status"] == "ignored_due_to_position").sum()),
            "missing_execution_count": int((part["status"] == "missing_execution").sum()),
            "avg_bars_held": float(traded["bars_held"].mean()) if len(traded) else np.nan,
            "median_bars_held": float(traded["bars_held"].median()) if len(traded) else np.nan,
        })
    return pd.DataFrame(rows)


def period_summary(trades: pd.DataFrame, freq: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    work = trades.copy()
    ts = pd.to_datetime(work["exit_time"], utc=True)
    if freq == "M":
        work["period"] = ts.dt.strftime("%Y-%m")
    elif freq == "Q":
        work["period"] = ts.dt.year.astype(str) + "Q" + ts.dt.quarter.astype(str)
    else:
        work["period"] = ts.dt.year.astype(str)
    rows = []
    for (period, symbol, sizing_mode), part in work.groupby(["period", "symbol", "sizing_mode"], dropna=False):
        pnl = part["net_pnl"]
        eq = pd.Series(INITIAL_BALANCE + pnl.cumsum())
        sample = "valid" if len(part) >= 10 else "insufficient_sample"
        if freq == "Y" and str(period) == "2026":
            sample = "partial_year"
        rows.append({
            "period": period,
            "symbol": symbol,
            "sizing_mode": sizing_mode,
            "trade_count": int(len(part)),
            "return": float(pnl.sum() / INITIAL_BALANCE),
            "profit_factor": profit_factor(pnl),
            "max_drawdown": max_drawdown(eq),
            "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
            "sample_status": sample,
        })
    return pd.DataFrame(rows)


def symbol_side_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if trades.empty:
        return pd.DataFrame()
    for (symbol, side, sizing_mode), part in trades.groupby(["symbol", "side", "sizing_mode"], dropna=False):
        pnl = part["net_pnl"]
        eq = pd.Series(INITIAL_BALANCE + pnl.cumsum())
        rows.append({
            "symbol": symbol,
            "side": side,
            "sizing_mode": sizing_mode,
            "trade_count": int(len(part)),
            "total_return": float(pnl.sum() / INITIAL_BALANCE),
            "profit_factor": profit_factor(pnl),
            "max_drawdown": max_drawdown(eq),
            "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
            "avg_trade_return": float(part["trade_return"].mean()) if len(part) else np.nan,
            "top1_profit_contribution": top_profit_contribution(pnl, 1),
            "sample_status": "valid" if len(part) >= 30 else "insufficient_sample",
        })
    return pd.DataFrame(rows)


def _total_return_from_trades(part: pd.DataFrame) -> float:
    return float(part["net_pnl"].sum() / INITIAL_BALANCE) if not part.empty else np.nan


def tail_dependency(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if trades.empty:
        return pd.DataFrame()
    work = trades.copy()
    ts = pd.to_datetime(work["exit_time"], utc=True)
    work["month"] = ts.dt.strftime("%Y-%m")
    work["quarter"] = ts.dt.year.astype(str) + "Q" + ts.dt.quarter.astype(str)
    work["year"] = ts.dt.year.astype(str)
    for (symbol, sizing_mode), part in work.groupby(["symbol", "sizing_mode"], dropna=False):
        ordered = part.sort_values("net_pnl", ascending=False)
        vals = {
            "original_total_return": _total_return_from_trades(part),
            "remove_best_1_trade_return": _total_return_from_trades(ordered.iloc[1:]) if len(ordered) > 1 else np.nan,
            "remove_best_3_trades_return": _total_return_from_trades(ordered.iloc[3:]) if len(ordered) > 3 else np.nan,
            "remove_best_5_trades_return": _total_return_from_trades(ordered.iloc[5:]) if len(ordered) > 5 else np.nan,
        }
        for col, out_col in [("month", "remove_best_month_return"), ("quarter", "remove_best_quarter_return"), ("year", "remove_best_year_return")]:
            by = part.groupby(col)["net_pnl"].sum()
            vals[out_col] = _total_return_from_trades(part[part[col] != by.idxmax()]) if len(by) else np.nan
        if len(part) < 30:
            status = "insufficient_sample"
        elif vals["remove_best_1_trade_return"] <= 0:
            status = "single_trade_dependent"
        elif vals["remove_best_3_trades_return"] <= 0:
            status = "top3_trade_dependent"
        elif vals["remove_best_month_return"] <= 0:
            status = "month_dependent"
        elif vals["remove_best_quarter_return"] <= 0:
            status = "quarter_dependent"
        elif vals["remove_best_year_return"] <= 0:
            status = "year_dependent"
        else:
            status = "not_tail_dependent"
        rows.append({"symbol": symbol, "sizing_mode": sizing_mode, **vals, "tail_dependency_status": status})
    return pd.DataFrame(rows)


def monthly_trade_proxy(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["symbol", "month", "s3_return"])
    work = trades.copy()
    work["month"] = pd.to_datetime(work["exit_time"], utc=True).dt.strftime("%Y-%m")
    return work.groupby(["symbol", "month"], dropna=False)["net_pnl"].sum().reset_index(name="s3_pnl").assign(
        s3_return=lambda x: x["s3_pnl"] / INITIAL_BALANCE
    )


def p4_complement_summary(trades: pd.DataFrame, p4_proxy: pd.DataFrame) -> pd.DataFrame:
    s3 = monthly_trade_proxy(trades)
    rows = []
    for symbol in sorted(set(s3["symbol"]) | set(p4_proxy["symbol"])):
        merged = s3[s3["symbol"] == symbol].merge(p4_proxy[p4_proxy["symbol"] == symbol], on=["symbol", "month"], how="inner")
        corr = np.nan
        if len(merged) >= 12 and merged["s3_return"].std() > 0 and merged["p4_proxy_return"].std() > 0:
            corr = float(np.corrcoef(merged["s3_return"], merged["p4_proxy_return"])[0, 1])
        neg = merged[merged["p4_negative_month"] == True]  # noqa: E712
        weak = merged[merged["p4_weak_month"] == True]  # noqa: E712
        pos_neg = float((neg["s3_return"] > 0).mean()) if len(neg) else np.nan
        pos_weak = float((weak["s3_return"] > 0).mean()) if len(weak) else np.nan
        both_neg = int(((merged["s3_return"] < 0) & (merged["p4_proxy_return"] < 0)).sum()) if len(merged) else 0
        if len(merged) < 12:
            status = "insufficient_overlap"
        elif abs(corr) >= 0.7:
            status = "not_complementary"
        elif (np.isnan(pos_neg) or pos_neg >= 0.40) and pos_weak >= 0.45:
            status = "complementary"
        elif pos_weak >= 0.35:
            status = "weak_complementary"
        else:
            status = "not_complementary"
        rows.append({
            "symbol": symbol,
            "overlap_month_count": int(len(merged)),
            "monthly_corr_with_p4": corr,
            "p4_negative_month_count": int(len(neg)),
            "s3_positive_in_p4_negative_month_rate": pos_neg,
            "p4_weak_month_count": int(len(weak)),
            "s3_positive_in_p4_weak_month_rate": pos_weak,
            "both_negative_month_count": both_neg,
            "complement_status": status,
        })
    # ALL proxy
    all_s3 = s3.groupby("month")["s3_return"].mean().reset_index()
    all_p4 = p4_proxy.groupby("month").agg(
        p4_proxy_return=("p4_proxy_return", "mean"),
        p4_negative_month=("p4_negative_month", "any"),
        p4_weak_month=("p4_weak_month", "any"),
    ).reset_index()
    merged = all_s3.merge(all_p4, on="month", how="inner")
    corr = float(np.corrcoef(merged["s3_return"], merged["p4_proxy_return"])[0, 1]) if len(merged) >= 12 and merged["s3_return"].std() > 0 and merged["p4_proxy_return"].std() > 0 else np.nan
    weak = merged[merged["p4_weak_month"] == True]  # noqa: E712
    neg = merged[merged["p4_negative_month"] == True]  # noqa: E712
    pos_weak = float((weak["s3_return"] > 0).mean()) if len(weak) else np.nan
    pos_neg = float((neg["s3_return"] > 0).mean()) if len(neg) else np.nan
    rows.append({
        "symbol": "ALL",
        "overlap_month_count": int(len(merged)),
        "monthly_corr_with_p4": corr,
        "p4_negative_month_count": int(len(neg)),
        "s3_positive_in_p4_negative_month_rate": pos_neg,
        "p4_weak_month_count": int(len(weak)),
        "s3_positive_in_p4_weak_month_rate": pos_weak,
        "both_negative_month_count": int(((merged["s3_return"] < 0) & (merged["p4_proxy_return"] < 0)).sum()) if len(merged) else 0,
        "complement_status": "complementary" if len(merged) >= 12 and (np.isnan(corr) or abs(corr) < 0.7) and (np.isnan(pos_neg) or pos_neg >= 0.40) and pos_weak >= 0.45 else "not_complementary",
    })
    return pd.DataFrame(rows)


def combine_equity_curves(equities: list[pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for i, eq in enumerate(equities):
        if eq.empty:
            continue
        part = eq[["time", "equity"]].copy()
        part["time"] = pd.to_datetime(part["time"], utc=True)
        part = part.drop_duplicates("time").set_index("time").sort_index()
        part[f"c{i}"] = part["equity"] / INITIAL_BALANCE
        frames.append(part[[f"c{i}"]])
    if not frames:
        return pd.DataFrame(columns=["time", "equity"])
    union = frames[0]
    for frame in frames[1:]:
        union = union.join(frame, how="outer")
    union = union.sort_index().ffill().fillna(1.0)
    return pd.DataFrame({"time": union.index, "equity": union.mean(axis=1) * INITIAL_BALANCE}).reset_index(drop=True)


def portfolio_comparison(s3_trades: pd.DataFrame, s3_equity: pd.DataFrame, p4_proxy: pd.DataFrame) -> pd.DataFrame:
    s3_pnl = s3_trades["net_pnl"] if not s3_trades.empty else pd.Series(dtype=float)
    s3_pf = profit_factor(s3_pnl)
    s3_final = float(s3_equity["equity"].iloc[-1]) if not s3_equity.empty else INITIAL_BALANCE
    p4_month_ret = p4_proxy.groupby("month")["p4_proxy_return"].mean()
    p4_final = INITIAL_BALANCE * (1 + p4_month_ret.sum())
    s3_month = monthly_trade_proxy(s3_trades).groupby("month")["s3_return"].mean()
    merged = pd.concat([p4_month_ret.rename("p4"), s3_month.rename("s3")], axis=1).fillna(0)
    corr = float(merged["p4"].corr(merged["s3"])) if len(merged) >= 2 and merged["p4"].std() > 0 and merged["s3"].std() > 0 else np.nan
    weak = merged[merged["p4"] <= 0.005]
    improvement = float((weak["s3"] > 0).mean()) if len(weak) else np.nan
    rows = [
        {
            "portfolio_mode": "A_P4_only_proxy",
            "trade_count": int(p4_proxy["p4_trade_count"].sum()) if "p4_trade_count" in p4_proxy else 0,
            "total_return": float(p4_final / INITIAL_BALANCE - 1),
            "annualized_return": np.nan,
            "max_drawdown": np.nan,
            "profit_factor": np.nan,
            "win_rate": np.nan,
            "longest_drawdown_duration": "",
            "top1_profit_contribution": np.nan,
            "monthly_corr_between_components": corr,
            "p4_weak_month_improvement_rate": improvement,
            "decision_note": "P4 monthly proxy only",
        },
        {
            "portfolio_mode": "B_S3_only",
            "trade_count": int(len(s3_trades)),
            "total_return": float(s3_final / INITIAL_BALANCE - 1),
            "annualized_return": np.nan,
            "max_drawdown": max_drawdown(s3_equity["equity"]) if not s3_equity.empty else np.nan,
            "profit_factor": s3_pf,
            "win_rate": float((s3_pnl > 0).mean()) if len(s3_pnl) else np.nan,
            "longest_drawdown_duration": longest_drawdown_duration(s3_equity),
            "top1_profit_contribution": top_profit_contribution(s3_pnl, 1),
            "monthly_corr_between_components": corr,
            "p4_weak_month_improvement_rate": improvement,
            "decision_note": "S3 standalone realized trades",
        },
        {
            "portfolio_mode": "C_P4_priority_proxy",
            "trade_count": int(len(s3_trades)),
            "total_return": float((p4_month_ret.sum() + s3_month.sum()) / 2),
            "annualized_return": np.nan,
            "max_drawdown": np.nan,
            "profit_factor": np.nan,
            "win_rate": np.nan,
            "longest_drawdown_duration": "",
            "top1_profit_contribution": np.nan,
            "monthly_corr_between_components": corr,
            "p4_weak_month_improvement_rate": improvement,
            "decision_note": "Proxy: P4 priority approximated by monthly component blend",
        },
        {
            "portfolio_mode": "D_P4_S3_independent_equal_risk_proxy",
            "trade_count": int(len(s3_trades)),
            "total_return": float((p4_month_ret.sum() + s3_month.sum()) / 2),
            "annualized_return": np.nan,
            "max_drawdown": np.nan,
            "profit_factor": np.nan,
            "win_rate": np.nan,
            "longest_drawdown_duration": "",
            "top1_profit_contribution": np.nan,
            "monthly_corr_between_components": corr,
            "p4_weak_month_improvement_rate": improvement,
            "decision_note": "Proxy: no position-level P4 replay generated in S3",
        },
    ]
    return pd.DataFrame(rows)


def decision_summary(summary: pd.DataFrame, tail: pd.DataFrame, complement: pd.DataFrame) -> pd.DataFrame:
    focus = summary[(summary["symbol"] == "ALL") & (summary["side_scope"] == "both") & (summary["sizing_mode"] == "fixed_1x")]
    if focus.empty:
        letter = "E"
        row = {}
    else:
        row = focus.iloc[0].to_dict()
        all_pf = float(row["profit_factor"]) if pd.notna(row["profit_factor"]) else np.nan
        all_mdd = float(row["max_drawdown"]) if pd.notna(row["max_drawdown"]) else np.nan
        all_trades = int(row["trade_count"])
        top1 = float(row["top1_profit_contribution"]) if pd.notna(row["top1_profit_contribution"]) else np.nan
        fixed_tail = tail[(tail["symbol"] == "ALL") & (tail["sizing_mode"] == "fixed_1x")]
        remove3 = float(fixed_tail["remove_best_3_trades_return"].iloc[0]) if not fixed_tail.empty else np.nan
        symbol_pf = summary[(summary["symbol"].isin(SYMBOLS)) & (summary["side_scope"] == "both") & (summary["sizing_mode"] == "fixed_1x")]
        pf_symbols = int((symbol_pf["profit_factor"] > 1).sum())
        comp_all = complement[complement["symbol"] == "ALL"]
        weak_rate = float(comp_all["s3_positive_in_p4_weak_month_rate"].iloc[0]) if not comp_all.empty else np.nan
        high_corr = bool((comp_all["monthly_corr_with_p4"].abs() >= 0.7).any()) if not comp_all.empty else False
        if (
            all_pf > 1.05
            and all_mdd >= -0.20
            and all_trades >= 200
            and (np.isnan(top1) or top1 <= 0.20)
            and remove3 >= 0
            and pf_symbols >= 2
            and weak_rate >= 0.45
            and not high_corr
        ):
            letter = "A"
        elif all_pf > 1.0 and all_trades >= 100:
            letter = "B"
        elif all_pf <= 1.0:
            letter = "C"
        else:
            letter = "D"
    return pd.DataFrame([{
        "decision_letter": letter,
        "decision_status": {
            "A": "candidate_for_S4_oos_or_shadow_preparation",
            "B": "weak_positive_expectancy_needs_conservative_portfolio_validation",
            "C": "event_edge_consumed_by_execution_cost_or_exits",
            "D": "depends_on_few_symbols_or_trades_not_strategy_ready",
            "E": "input_or_implementation_problem",
        }[letter],
        "all_fixed_1x_profit_factor": row.get("profit_factor", np.nan),
        "all_fixed_1x_max_drawdown": row.get("max_drawdown", np.nan),
        "all_fixed_1x_trade_count": row.get("trade_count", 0),
        "funding_status": "unavailable",
        "strategy_backtest_generated": True,
        "data_layer": "expanded_discovery_long_history",
        "oos_status": "not_oos",
    }])
