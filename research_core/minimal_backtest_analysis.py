"""R8 minimal prototype backtest helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtest.accounting import execute_entry, execute_exit, gross_pnl, trade_net_pnl
from research_core.event_table import add_base_indicators, load_ohlcv_1m, strict_resample_15m
from research_core.family_validation_analysis import FAMILY_FACTORS, compute_family_score, fit_factor_params
from research_core.prototype_attribution_analysis import prototype_masks


R8_PROTOTYPES = [
    "P0_ALL_TREND_CONTEXT",
    "P1_C1_FIRST_BREAKOUT",
    "P2_STRONG_BREAKOUT",
    "P3_MOMENTUM_TOP20",
    "P4_BREAKOUT_TOP20",
    "P5_MOMENTUM_AND_BREAKOUT_TOP40",
    "P6_MOMENTUM_OR_BREAKOUT_TOP20",
]
SIZING_MODES = ["fixed_2x", "fixed_risk_0_5pct"]


@dataclass(frozen=True)
class BacktestParams:
    initial_balance: float = 1000.0
    leverage: float = 2.0
    fee_rate: float = 0.0005
    slippage_rate: float = 0.0002
    atr_stop_mult: float = 3.0
    risk_fraction: float = 0.005


@dataclass(frozen=True)
class MarketArrays:
    index_1m_ns: np.ndarray
    open_1m: np.ndarray
    low_1m: np.ndarray
    high_1m: np.ndarray
    close_1m: np.ndarray
    index_15m_ns: np.ndarray
    close_15m: np.ndarray
    lower_15m: np.ndarray


def load_params(frozen: dict) -> BacktestParams:
    return BacktestParams(
        initial_balance=float(frozen.get("initial_balance", 1000.0)),
        leverage=float(frozen.get("leverage", 2.0)),
        fee_rate=float(frozen.get("fee_rate", 0.0005)),
        slippage_rate=float(frozen.get("slippage_rate", 0.0002)),
        atr_stop_mult=float(frozen.get("atr_stop_mult", 3.0)),
        risk_fraction=float(frozen.get("risk_fraction", 0.005)),
    )


def prepare_market_data(data_path: Path | str) -> tuple[pd.DataFrame, pd.DataFrame]:
    data_1m = load_ohlcv_1m(data_path)
    data_15m = add_base_indicators(strict_resample_15m(data_1m))
    return data_1m, data_15m


def market_arrays(data_1m: pd.DataFrame, data_15m: pd.DataFrame) -> MarketArrays:
    return MarketArrays(
        index_1m_ns=data_1m.index.view("int64"),
        open_1m=data_1m["open"].to_numpy(float),
        low_1m=data_1m["low"].to_numpy(float),
        high_1m=data_1m["high"].to_numpy(float),
        close_1m=data_1m["close"].to_numpy(float),
        index_15m_ns=data_15m.index.view("int64"),
        close_15m=data_15m["close"].to_numpy(float),
        lower_15m=data_15m["donchian20_lower"].to_numpy(float),
    )


def fixed_2x_quantity(equity: float, entry_price: float, leverage: float) -> float:
    return equity * leverage / entry_price


def fixed_risk_quantity(equity: float, entry_price: float, stop_loss: float, leverage: float, risk_fraction: float) -> float:
    stop_distance = entry_price - stop_loss
    if stop_distance <= 0:
        return 0.0
    quantity_by_risk = equity * risk_fraction / stop_distance
    quantity_by_leverage = equity * leverage / entry_price
    return min(quantity_by_risk, quantity_by_leverage)


def prototype_event_frames(events: pd.DataFrame, scores: pd.DataFrame) -> dict[str, pd.DataFrame]:
    masks = prototype_masks(events.reset_index(drop=True), scores.reset_index(drop=True))
    return {
        name: events.reset_index(drop=True)[mask].sort_values("execution_time").reset_index(drop=True)
        for name, mask in masks.items()
        if name in R8_PROTOTYPES
    }


def simulate_exit(
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
    entry_time: pd.Timestamp,
    signal_time: pd.Timestamp,
    entry_price: float,
    stop_loss: float,
    atr: float,
) -> tuple[pd.Timestamp, float, str, float, float]:
    after_15m = data_15m.loc[data_15m.index > signal_time]
    mae = 0.0
    mfe = 0.0
    last_checked = entry_time
    for bar_time, bar in after_15m.iterrows():
        one_minute = data_1m.loc[(data_1m.index >= last_checked) & (data_1m.index < bar_time)]
        if not one_minute.empty:
            mae = min(mae, float(one_minute["low"].min()) / entry_price - 1.0)
            mfe = max(mfe, float(one_minute["high"].max()) / entry_price - 1.0)
            stop_hits = one_minute[one_minute["low"] <= stop_loss]
            if not stop_hits.empty:
                return stop_hits.index[0], stop_loss, "atr_stop", mae / (atr / entry_price), mfe / (atr / entry_price)
        last_checked = bar_time
        if float(bar["close"]) < float(bar["donchian20_lower"]):
            if bar_time in data_1m.index:
                return bar_time, float(data_1m.loc[bar_time, "open"]), "donchian20_exit", mae / (atr / entry_price), mfe / (atr / entry_price)
            return bar_time, float(bar["close"]), "end_of_backtest", mae / (atr / entry_price), mfe / (atr / entry_price)
    tail = data_1m.loc[data_1m.index >= entry_time]
    if tail.empty:
        return entry_time, entry_price, "no_data", 0.0, 0.0
    mae = min(mae, float(tail["low"].min()) / entry_price - 1.0)
    mfe = max(mfe, float(tail["high"].max()) / entry_price - 1.0)
    return tail.index[-1], float(tail.iloc[-1]["close"]), "end_of_backtest", mae / (atr / entry_price), mfe / (atr / entry_price)


def simulate_exit_arrays(
    arrays: MarketArrays,
    entry_time: pd.Timestamp,
    signal_time: pd.Timestamp,
    entry_price: float,
    stop_loss: float,
    atr: float,
) -> tuple[pd.Timestamp, float, str, float, float]:
    entry_ns = pd.Timestamp(entry_time).value
    signal_ns = pd.Timestamp(signal_time).value
    pos_1m = int(np.searchsorted(arrays.index_1m_ns, entry_ns, side="left"))
    pos_15m = int(np.searchsorted(arrays.index_15m_ns, signal_ns, side="right"))
    mae = 0.0
    mfe = 0.0
    cursor = pos_1m
    denom = atr / entry_price
    for i in range(pos_15m, len(arrays.index_15m_ns)):
        end_ns = arrays.index_15m_ns[i]
        end_1m = int(np.searchsorted(arrays.index_1m_ns, end_ns, side="left"))
        if end_1m > cursor:
            lows = arrays.low_1m[cursor:end_1m]
            highs = arrays.high_1m[cursor:end_1m]
            mae = min(mae, float(np.nanmin(lows)) / entry_price - 1.0)
            mfe = max(mfe, float(np.nanmax(highs)) / entry_price - 1.0)
            hits = np.flatnonzero(lows <= stop_loss)
            if len(hits):
                hit_pos = cursor + int(hits[0])
                return pd.Timestamp(arrays.index_1m_ns[hit_pos], tz="UTC"), stop_loss, "atr_stop", mae / denom, mfe / denom
            cursor = end_1m
        if arrays.close_15m[i] < arrays.lower_15m[i]:
            exit_pos = int(np.searchsorted(arrays.index_1m_ns, arrays.index_15m_ns[i], side="left"))
            if exit_pos >= len(arrays.index_1m_ns) or arrays.index_1m_ns[exit_pos] != arrays.index_15m_ns[i]:
                return pd.Timestamp(arrays.index_1m_ns[-1], tz="UTC"), float(arrays.close_1m[-1]), "end_of_backtest", mae / denom, mfe / denom
            return pd.Timestamp(arrays.index_1m_ns[exit_pos], tz="UTC"), float(arrays.open_1m[exit_pos]), "donchian20_exit", mae / denom, mfe / denom
    if pos_1m >= len(arrays.index_1m_ns):
        return pd.Timestamp(entry_ns, tz="UTC"), entry_price, "no_data", 0.0, 0.0
    lows = arrays.low_1m[pos_1m:]
    highs = arrays.high_1m[pos_1m:]
    mae = min(mae, float(np.nanmin(lows)) / entry_price - 1.0)
    mfe = max(mfe, float(np.nanmax(highs)) / entry_price - 1.0)
    return (
        pd.Timestamp(arrays.index_1m_ns[-1], tz="UTC"),
        float(arrays.close_1m[-1]),
        "end_of_backtest",
        mae / denom,
        mfe / denom,
    )


def enrich_events_with_exit_info(
    events: pd.DataFrame,
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
    params: BacktestParams,
) -> pd.DataFrame:
    arrays = market_arrays(data_1m, data_15m)
    rows = []
    for _, event in events.iterrows():
        raw_entry = float(event["execution_open"])
        entry_price = raw_entry * (1 + params.slippage_rate)
        atr = float(event["atr14"])
        stop_loss = entry_price - atr * params.atr_stop_mult
        exit_time, raw_exit, reason, mae_atr, mfe_atr = simulate_exit_arrays(
            arrays,
            pd.to_datetime(event["execution_time"], utc=True),
            pd.to_datetime(event["signal_time"], utc=True),
            entry_price,
            stop_loss,
            atr,
        )
        rows.append({
            "precomputed_exit_time": exit_time,
            "precomputed_exit_raw_price": raw_exit,
            "precomputed_exit_reason": reason,
            "precomputed_mae_atr": mae_atr,
            "precomputed_mfe_atr": mfe_atr,
        })
    extra = pd.DataFrame(rows, index=events.index)
    return pd.concat([events.reset_index(drop=True), extra.reset_index(drop=True)], axis=1)


def run_prototype_backtest(
    events: pd.DataFrame,
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
    params: BacktestParams,
    prototype: str,
    sizing_mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    equity = params.initial_balance
    trades = []
    equity_rows = [{"time": data_1m.index[0], "equity": equity, "prototype": prototype, "sizing_mode": sizing_mode}]
    next_available_time = pd.Timestamp.min.tz_localize("UTC")
    for _, event in events.sort_values("execution_time").iterrows():
        entry_time = pd.to_datetime(event["execution_time"], utc=True)
        signal_time = pd.to_datetime(event["signal_time"], utc=True)
        if entry_time <= next_available_time or entry_time not in data_1m.index:
            continue
        raw_entry = float(data_1m.loc[entry_time, "open"])
        atr = float(event["atr14"])
        if not np.isfinite(atr) or atr <= 0:
            continue
        preliminary_entry = raw_entry * (1 + params.slippage_rate)
        stop_loss = preliminary_entry - atr * params.atr_stop_mult
        if sizing_mode == "fixed_2x":
            quantity = fixed_2x_quantity(equity, preliminary_entry, params.leverage)
        elif sizing_mode == "fixed_risk_0_5pct":
            quantity = fixed_risk_quantity(equity, preliminary_entry, stop_loss, params.leverage, params.risk_fraction)
        else:
            raise ValueError(f"Unknown sizing mode: {sizing_mode}")
        if quantity <= 0:
            continue
        entry_fill = execute_entry(raw_entry, quantity, "LONG", params.fee_rate, params.slippage_rate)
        stop_loss = entry_fill.executed_price - atr * params.atr_stop_mult
        if "precomputed_exit_time" in event:
            exit_time = pd.to_datetime(event["precomputed_exit_time"], utc=True)
            raw_exit = float(event["precomputed_exit_raw_price"])
            exit_reason = str(event["precomputed_exit_reason"])
            mae_atr = float(event["precomputed_mae_atr"])
            mfe_atr = float(event["precomputed_mfe_atr"])
        else:
            exit_time, raw_exit, exit_reason, mae_atr, mfe_atr = simulate_exit(
                data_1m, data_15m, entry_time, signal_time, entry_fill.executed_price, stop_loss, atr
            )
        exit_fill = execute_exit(raw_exit, quantity, "LONG", params.fee_rate, params.slippage_rate)
        gross = gross_pnl(entry_fill.executed_price, exit_fill.executed_price, quantity, "LONG")
        net = trade_net_pnl(gross, entry_fill.fee, exit_fill.fee)
        equity_before = equity
        equity += net
        next_available_time = exit_time
        trades.append({
            "prototype": prototype,
            "sizing_mode": sizing_mode,
            "event_id": event.get("event_id", ""),
            "signal_time": signal_time,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_raw_price": raw_entry,
            "entry_price": entry_fill.executed_price,
            "exit_raw_price": raw_exit,
            "exit_price": exit_fill.executed_price,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "atr": atr,
            "gross_pnl": gross,
            "entry_fee": entry_fill.fee,
            "exit_fee": exit_fill.fee,
            "total_fee": entry_fill.fee + exit_fill.fee,
            "net_pnl": net,
            "trade_return": net / equity_before if equity_before else np.nan,
            "equity_before": equity_before,
            "equity_after": equity,
            "mae_atr": mae_atr,
            "mfe_atr": mfe_atr,
            "exit_reason": exit_reason,
        })
        equity_rows.append({"time": exit_time, "equity": equity, "prototype": prototype, "sizing_mode": sizing_mode})
    return pd.DataFrame(trades), pd.DataFrame(equity_rows)


def profit_factor(pnl: pd.Series) -> float:
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    if losses == 0:
        return np.inf if wins > 0 else np.nan
    return float(wins / losses)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return np.nan
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def longest_drawdown_duration(equity_df: pd.DataFrame) -> str:
    if equity_df.empty:
        return ""
    frame = equity_df.sort_values("time").copy()
    peak = frame["equity"].cummax()
    in_dd = frame["equity"] < peak
    start = None
    longest = pd.Timedelta(0)
    for t, dd in zip(pd.to_datetime(frame["time"], utc=True), in_dd):
        if dd and start is None:
            start = t
        if not dd and start is not None:
            longest = max(longest, t - start)
            start = None
    if start is not None:
        longest = max(longest, pd.to_datetime(frame["time"], utc=True).iloc[-1] - start)
    return str(longest)


def top_profit_contribution(pnl: pd.Series, n: int) -> float:
    positive = pnl[pnl > 0].sort_values(ascending=False)
    total = pnl.sum()
    if total <= 0 or positive.empty:
        return np.nan
    return float(positive.head(n).sum() / total)


def summarize_backtest(
    prototype: str,
    sizing_mode: str,
    trades: pd.DataFrame,
    equity: pd.DataFrame,
    initial_balance: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict:
    final_equity = float(equity["equity"].iloc[-1]) if not equity.empty else initial_balance
    total_return = final_equity / initial_balance - 1.0
    years = max((end - start).total_seconds() / (365.25 * 24 * 3600), 1e-9)
    annualized = (final_equity / initial_balance) ** (1 / years) - 1 if final_equity > 0 else -1.0
    pnl = trades["net_pnl"] if not trades.empty else pd.Series(dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    mdd = max_drawdown(equity["equity"]) if not equity.empty else np.nan
    return {
        "prototype": prototype,
        "sizing_mode": sizing_mode,
        "trade_count": int(len(trades)),
        "total_return": total_return,
        "annualized_return": annualized,
        "max_drawdown": mdd,
        "calmar": annualized / abs(mdd) if mdd and pd.notna(mdd) and mdd < 0 else np.nan,
        "profit_factor": profit_factor(pnl),
        "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
        "avg_win": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss": float(losses.mean()) if len(losses) else np.nan,
        "payoff_ratio": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else np.nan,
        "avg_mae_atr": float(trades["mae_atr"].mean()) if not trades.empty else np.nan,
        "avg_mfe_atr": float(trades["mfe_atr"].mean()) if not trades.empty else np.nan,
        "longest_drawdown_duration": longest_drawdown_duration(equity),
        "top1_profit_contribution": top_profit_contribution(pnl, 1),
        "top3_profit_contribution": top_profit_contribution(pnl, 3),
        "top5_profit_contribution": top_profit_contribution(pnl, 5),
        "top10_profit_contribution": top_profit_contribution(pnl, 10),
        "final_equity": final_equity,
    }


def period_trade_summary(trades: pd.DataFrame, period: str, initial_balance: float) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["prototype", "sizing_mode", "period", "trade_count", "net_pnl", "return", "profit_factor", "max_drawdown", "win_rate"])
    data = trades.copy()
    ts = pd.to_datetime(data["exit_time"], utc=True)
    data["period"] = ts.dt.strftime("%Y-%m") if period == "month" else ts.dt.year.astype(str) + "Q" + ts.dt.quarter.astype(str)
    rows = []
    for (prototype, sizing_mode, period_value), part in data.groupby(["prototype", "sizing_mode", "period"]):
        pnl = part["net_pnl"]
        eq = initial_balance + pnl.cumsum()
        rows.append({
            "prototype": prototype,
            "sizing_mode": sizing_mode,
            "period": period_value,
            "trade_count": int(len(part)),
            "net_pnl": float(pnl.sum()),
            "return": float(pnl.sum() / initial_balance),
            "profit_factor": profit_factor(pnl),
            "max_drawdown": max_drawdown(eq),
            "win_rate": float((pnl > 0).mean()),
        })
    return pd.DataFrame(rows)


def trade_stability_summary(monthly: pd.DataFrame, quarterly: pd.DataFrame, min_trades: int = 3) -> pd.DataFrame:
    rows = []
    keys = pd.concat([monthly[["prototype", "sizing_mode"]], quarterly[["prototype", "sizing_mode"]]]).drop_duplicates()
    for _, key in keys.iterrows():
        m = monthly[(monthly["prototype"] == key["prototype"]) & (monthly["sizing_mode"] == key["sizing_mode"])]
        q = quarterly[(quarterly["prototype"] == key["prototype"]) & (quarterly["sizing_mode"] == key["sizing_mode"])]
        valid_m = m[m["trade_count"] >= min_trades]
        valid_q = q[q["trade_count"] >= min_trades]
        month_rate = float((valid_m["return"] > 0).mean()) if not valid_m.empty else np.nan
        quarter_rate = float((valid_q["return"] > 0).mean()) if not valid_q.empty else np.nan
        if len(valid_m) < 3 or len(valid_q) < 2:
            status = "insufficient_sample"
        elif month_rate >= 0.60 and quarter_rate >= 0.60:
            status = "stable"
        elif month_rate < 0.60:
            status = "month_fragile"
        else:
            status = "quarter_fragile"
        rows.append({
            "prototype": key["prototype"],
            "sizing_mode": key["sizing_mode"],
            "valid_month_count": int(len(valid_m)),
            "positive_month_rate": month_rate,
            "valid_quarter_count": int(len(valid_q)),
            "positive_quarter_rate": quarter_rate,
            "worst_month_return": float(valid_m["return"].min()) if not valid_m.empty else np.nan,
            "worst_quarter_return": float(valid_q["return"].min()) if not valid_q.empty else np.nan,
            "stability_status": status,
        })
    return pd.DataFrame(rows)


def total_return_from_pnl(pnl: pd.Series, initial_balance: float) -> float:
    return float(pnl.sum() / initial_balance)


def trade_tail_dependence(trades: pd.DataFrame, initial_balance: float) -> pd.DataFrame:
    rows = []
    if trades.empty:
        return pd.DataFrame()
    data = trades.copy()
    ts = pd.to_datetime(data["exit_time"], utc=True)
    data["month_group"] = ts.dt.strftime("%Y-%m")
    data["quarter_group"] = ts.dt.year.astype(str) + "Q" + ts.dt.quarter.astype(str)
    for (prototype, sizing_mode), part in data.groupby(["prototype", "sizing_mode"]):
        pnl = part["net_pnl"].sort_values(ascending=False)
        positive = pnl[pnl > 0]
        original = total_return_from_pnl(part["net_pnl"], initial_balance)
        values = {
            "remove_best_1_trade_return": total_return_from_pnl(pnl.iloc[1:], initial_balance) if len(pnl) > 1 else np.nan,
            "remove_best_3_trades_return": total_return_from_pnl(pnl.iloc[3:], initial_balance) if len(pnl) > 3 else np.nan,
            "remove_best_5_trades_return": total_return_from_pnl(pnl.iloc[5:], initial_balance) if len(pnl) > 5 else np.nan,
        }
        n_remove = int(math.ceil(len(positive) * 0.10))
        remove_idx = positive.head(n_remove).index if n_remove > 0 else []
        values["remove_best_10pct_winners_return"] = total_return_from_pnl(part.drop(index=remove_idx)["net_pnl"], initial_balance)
        month_pnl = part.groupby("month_group")["net_pnl"].sum()
        quarter_pnl = part.groupby("quarter_group")["net_pnl"].sum()
        values["remove_best_month_return"] = total_return_from_pnl(part[part["month_group"] != month_pnl.idxmax()]["net_pnl"], initial_balance) if len(month_pnl) else np.nan
        values["remove_best_quarter_return"] = total_return_from_pnl(part[part["quarter_group"] != quarter_pnl.idxmax()]["net_pnl"], initial_balance) if len(quarter_pnl) else np.nan
        if len(part) < 30:
            status = "insufficient_sample"
        elif values["remove_best_1_trade_return"] <= 0:
            status = "single_trade_dependent"
        elif values["remove_best_3_trades_return"] <= 0:
            status = "top3_trade_dependent"
        elif values["remove_best_5_trades_return"] <= 0:
            status = "top5_trade_dependent"
        elif values["remove_best_10pct_winners_return"] <= 0:
            status = "top10pct_dependent"
        elif values["remove_best_month_return"] <= 0:
            status = "best_month_dependent"
        elif values["remove_best_quarter_return"] <= 0:
            status = "best_quarter_dependent"
        else:
            status = "not_tail_dependent"
        rows.append({
            "prototype": prototype,
            "sizing_mode": sizing_mode,
            "original_total_return": original,
            **values,
            "tail_dependence_status": status,
        })
    return pd.DataFrame(rows)


def event_to_trade_consistency(
    r7_event_summary: pd.DataFrame,
    trade_summary: pd.DataFrame,
    monthly: pd.DataFrame,
    r7_decision_summary: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows = []
    r7 = r7_event_summary[r7_event_summary["horizon"] == 16].set_index("prototype")
    fixed = trade_summary[trade_summary["sizing_mode"] == "fixed_2x"].set_index("prototype")
    r7_decision = r7_decision_summary.set_index("prototype") if r7_decision_summary is not None and not r7_decision_summary.empty else pd.DataFrame()
    for prototype in R8_PROTOTYPES:
        if prototype not in r7.index or prototype not in fixed.index:
            continue
        m = monthly[(monthly["prototype"] == prototype) & (monthly["sizing_mode"] == "fixed_2x")]
        positive_month_rate = float((m["return"] > 0).mean()) if not m.empty else np.nan
        event_count = int(r7.loc[prototype, "event_count"])
        trade_count = int(fixed.loc[prototype, "trade_count"])
        avg_trade = float(fixed.loc[prototype, "total_return"] / trade_count) if trade_count else np.nan
        r7_mean = float(r7.loc[prototype, "mean_fwd_ret"])
        if trade_count < 30:
            status = "insufficient_trades"
        elif avg_trade <= 0 < r7_mean:
            status = "reversed_after_execution"
        elif avg_trade < r7_mean * 0.5:
            status = "weakened_by_execution"
        else:
            status = "consistent"
        rows.append({
            "prototype": prototype,
            "r7_event_count_h16": event_count,
            "r8_trade_count": trade_count,
            "signal_to_trade_conversion_rate": trade_count / event_count if event_count else np.nan,
            "r7_mean_ret_h16": r7_mean,
            "r8_avg_trade_return": avg_trade,
            "r7_positive_month_rate_h16": float(r7_decision.loc[prototype, "positive_month_rate_h16"]) if prototype in r7_decision.index else np.nan,
            "r8_positive_month_rate": positive_month_rate,
            "consistency_status": status,
        })
    return pd.DataFrame(rows)


def recompute_walk_forward_scores(train: pd.DataFrame, test: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    directions = {row["factor"]: int(row["direction"]) for _, row in metadata.iterrows()}
    scores = pd.DataFrame(index=test.index)
    for family, factors in FAMILY_FACTORS.items():
        available = [f for f in factors if f in train.columns and f in test.columns]
        params = fit_factor_params(train, available, directions)
        score = compute_family_score(test, available, params)
        short = "momentum" if family == "momentum_continuation" else "breakout"
        scores[f"{short}_score_quantile"] = score.rank(pct=True, method="first")
    return scores


def walk_forward_backtest(
    events: pd.DataFrame,
    metadata: pd.DataFrame,
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
    params: BacktestParams,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = events.copy()
    data["signal_time"] = pd.to_datetime(data["signal_time"], utc=True)
    start = data["signal_time"].min().normalize()
    end = data["signal_time"].max()
    rows = []
    window_id = 0
    train_start = start
    while train_start + pd.DateOffset(months=15) <= end + pd.Timedelta(days=1):
        train_end = train_start + pd.DateOffset(months=12)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=3)
        train = data[(data["signal_time"] >= train_start) & (data["signal_time"] < train_end)].copy()
        test = data[(data["signal_time"] >= test_start) & (data["signal_time"] < test_end)].copy()
        scores = recompute_walk_forward_scores(train, test, metadata) if not train.empty and not test.empty else pd.DataFrame(index=test.index)
        frames = prototype_event_frames(test.reset_index(drop=True), scores.reset_index(drop=True)) if not test.empty else {p: test for p in R8_PROTOTYPES}
        for prototype in R8_PROTOTYPES:
            for sizing_mode in SIZING_MODES:
                trades, equity = run_prototype_backtest(frames.get(prototype, test.iloc[0:0]), data_1m, data_15m, params, prototype, sizing_mode)
                summary = summarize_backtest(prototype, sizing_mode, trades, equity, params.initial_balance, test_start, min(test_end, end))
                pf = summary["profit_factor"]
                rows.append({
                    "window_id": window_id,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "prototype": prototype,
                    "sizing_mode": sizing_mode,
                    "trade_count": summary["trade_count"],
                    "total_return": summary["total_return"],
                    "profit_factor": pf,
                    "max_drawdown": summary["max_drawdown"],
                    "avg_trade_return": summary["total_return"] / summary["trade_count"] if summary["trade_count"] else np.nan,
                    "sample_status": "valid" if summary["trade_count"] >= 5 else "insufficient_sample",
                })
        train_start = train_start + pd.DateOffset(months=3)
        window_id += 1
    windows = pd.DataFrame(rows)
    if windows.empty:
        summary_rows = []
        for prototype in R8_PROTOTYPES:
            for sizing_mode in SIZING_MODES:
                summary_rows.append({
                    "prototype": prototype,
                    "sizing_mode": sizing_mode,
                    "window_count": 0,
                    "valid_window_count": 0,
                    "positive_window_rate": np.nan,
                    "pf_gt_1_window_rate": np.nan,
                    "median_return": np.nan,
                    "worst_return": np.nan,
                    "median_pf": np.nan,
                    "walk_forward_status": "insufficient_sample",
                })
        return windows, pd.DataFrame(summary_rows)
    summary_rows = []
    for (prototype, sizing_mode), part in windows.groupby(["prototype", "sizing_mode"]):
        valid = part[part["sample_status"] == "valid"]
        positive_rate = float((valid["total_return"] > 0).mean()) if not valid.empty else np.nan
        pf_rate = float((valid["profit_factor"] > 1).mean()) if not valid.empty else np.nan
        if valid.empty:
            status = "insufficient_sample"
        elif positive_rate >= 0.60 and pf_rate >= 0.60:
            status = "wf_pass"
        elif positive_rate >= 0.50 or pf_rate >= 0.50:
            status = "wf_weak"
        else:
            status = "wf_fail"
        summary_rows.append({
            "prototype": prototype,
            "sizing_mode": sizing_mode,
            "window_count": int(len(part)),
            "valid_window_count": int(len(valid)),
            "positive_window_rate": positive_rate,
            "pf_gt_1_window_rate": pf_rate,
            "median_return": float(valid["total_return"].median()) if not valid.empty else np.nan,
            "worst_return": float(valid["total_return"].min()) if not valid.empty else np.nan,
            "median_pf": float(valid["profit_factor"].replace(np.inf, np.nan).median()) if not valid.empty else np.nan,
            "walk_forward_status": status,
        })
    return windows, pd.DataFrame(summary_rows)


def r8_decision_summary(backtest_summary: pd.DataFrame, wf_summary: pd.DataFrame, tail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    fixed = backtest_summary.pivot(index="prototype", columns="sizing_mode")
    wf_fixed = wf_summary[wf_summary["sizing_mode"] == "fixed_2x"].set_index("prototype")
    tail_fixed = tail[tail["sizing_mode"] == "fixed_2x"].set_index("prototype")
    for prototype in R8_PROTOTYPES:
        f2 = backtest_summary[(backtest_summary["prototype"] == prototype) & (backtest_summary["sizing_mode"] == "fixed_2x")].iloc[0]
        fr = backtest_summary[(backtest_summary["prototype"] == prototype) & (backtest_summary["sizing_mode"] == "fixed_risk_0_5pct")].iloc[0]
        wf = wf_fixed.loc[prototype] if prototype in wf_fixed.index else pd.Series(dtype=object)
        tail_status = tail_fixed.loc[prototype, "tail_dependence_status"] if prototype in tail_fixed.index else "insufficient_sample"
        top1 = float(f2["top1_profit_contribution"]) if pd.notna(f2["top1_profit_contribution"]) else np.inf
        if f2["trade_count"] < 50:
            decision = "insufficient_sample"
            step = "needs_more_data"
        elif prototype in {"P0_ALL_TREND_CONTEXT", "P1_C1_FIRST_BREAKOUT", "P2_STRONG_BREAKOUT"}:
            decision = "explanatory_only"
            step = "keep_as_explanation"
        elif (
            f2["profit_factor"] > 1.10
            and fr["max_drawdown"] >= -0.25
            and float(wf.get("positive_window_rate", np.nan)) >= 0.60
            and float(wf.get("pf_gt_1_window_rate", np.nan)) >= 0.60
            and tail_status == "not_tail_dependent"
            and top1 <= 0.30
        ):
            decision = "candidate_for_R9_oos_validation"
            step = "R9_new_data_validation"
        elif f2["profit_factor"] > 1.0:
            decision = "weak_candidate"
            step = "needs_more_data"
        else:
            decision = "discard_for_now"
            step = "discard"
        rows.append({
            "prototype": prototype,
            "fixed_2x_trade_count": int(f2["trade_count"]),
            "fixed_2x_total_return": float(f2["total_return"]),
            "fixed_2x_max_drawdown": float(f2["max_drawdown"]),
            "fixed_2x_profit_factor": float(f2["profit_factor"]),
            "fixed_risk_trade_count": int(fr["trade_count"]),
            "fixed_risk_total_return": float(fr["total_return"]),
            "fixed_risk_max_drawdown": float(fr["max_drawdown"]),
            "fixed_risk_profit_factor": float(fr["profit_factor"]),
            "walk_forward_positive_window_rate": float(wf.get("positive_window_rate", np.nan)),
            "walk_forward_pf_gt_1_rate": float(wf.get("pf_gt_1_window_rate", np.nan)),
            "tail_dependence_status": tail_status,
            "decision_status": decision,
            "allowed_next_step": step,
        })
    return pd.DataFrame(rows)


def plot_equity_curves(equity_frames: list[pd.DataFrame], path: Path) -> None:
    plt.figure(figsize=(12, 6))
    for frame in equity_frames:
        if frame.empty or frame["sizing_mode"].iloc[0] != "fixed_2x":
            continue
        plt.plot(pd.to_datetime(frame["time"], utc=True), frame["equity"], label=frame["prototype"].iloc[0])
    plt.legend(fontsize=8)
    plt.title("R8 Prototype Equity Comparison (fixed_2x)")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def plot_drawdown_curves(equity_frames: list[pd.DataFrame], path: Path) -> None:
    plt.figure(figsize=(12, 6))
    for frame in equity_frames:
        if frame.empty or frame["sizing_mode"].iloc[0] != "fixed_2x":
            continue
        eq = frame["equity"]
        dd = eq / eq.cummax() - 1.0
        plt.plot(pd.to_datetime(frame["time"], utc=True), dd, label=frame["prototype"].iloc[0])
    plt.legend(fontsize=8)
    plt.title("R8 Prototype Drawdown Comparison (fixed_2x)")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
