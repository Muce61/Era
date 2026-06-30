"""Long/short portfolio comparison helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research_core.minimal_backtest_analysis import longest_drawdown_duration, max_drawdown
from research_core.p4_short_research.p4_short_accounting import INITIAL_BALANCE
from research_core.p4_short_research.p4_short_replay import summarize_trades


def monthly_returns_from_trades(trades: pd.DataFrame, label: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["month", label])
    out = trades.copy()
    out["exit_time"] = pd.to_datetime(out["exit_time"], utc=True)
    out["month"] = out["exit_time"].dt.to_period("M").astype(str)
    return out.groupby("month")["net_pnl"].sum().div(INITIAL_BALANCE).reset_index(name=label)


def compare_monthly(long_trades: pd.DataFrame, short_trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    long_m = monthly_returns_from_trades(long_trades, "p4_long_return")
    short_m = monthly_returns_from_trades(short_trades, "p4_short_return")
    merged = long_m.merge(short_m, on="month", how="outer").fillna(0.0)
    corr = merged["p4_long_return"].corr(merged["p4_short_return"]) if len(merged) >= 3 else np.nan
    summary = pd.DataFrame([{
        "monthly_return_correlation": corr,
        "p4_down_month_count": int((merged["p4_long_return"] < 0).sum()),
        "p4_down_month_short_positive_rate": float((merged.loc[merged["p4_long_return"] < 0, "p4_short_return"] > 0).mean()) if (merged["p4_long_return"] < 0).any() else np.nan,
    }])
    return merged, summary


def portfolio_summary(long_trades: pd.DataFrame, short_trades: pd.DataFrame, short_equity: pd.DataFrame) -> pd.DataFrame:
    rows = []
    rows.append({"portfolio_mode": "P4_SHORT_ONLY", **summarize_trades(short_trades, short_equity)})
    # Long-only values are a context placeholder unless caller supplies canonical P4 long trades.
    if long_trades.empty:
        rows.append({
            "portfolio_mode": "P4_LONG_ONLY_CONTEXT_UNAVAILABLE",
            "trade_count": 0,
            "total_return": np.nan,
            "max_drawdown": np.nan,
            "profit_factor": np.nan,
            "win_rate": np.nan,
            "final_equity": np.nan,
            "top1_profit_contribution": np.nan,
            "top3_profit_contribution": np.nan,
            "liquidation_count": np.nan,
            "longest_drawdown_duration": "",
        })
    return pd.DataFrame(rows)

