import math

import numpy as np
import pandas as pd


def profit_factor(pnl):
    pnl = pd.Series(pnl).dropna()
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = pnl[pnl <= 0].sum()
    if gross_loss == 0:
        return math.inf if gross_profit > 0 else 0.0
    return gross_profit / abs(gross_loss)


def longest_losing_streak(pnl):
    longest = 0
    current = 0
    for value in pnl:
        if value <= 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def max_drawdown(equity):
    equity = pd.Series(equity).dropna()
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return (equity / peak - 1).min()


def geometric_mean_return(returns):
    returns = pd.Series(returns).dropna()
    returns = returns[returns > -1]
    if returns.empty:
        return 0.0
    return float(np.exp(np.log1p(returns).mean()) - 1)


def longest_drawdown_duration(equity):
    equity = pd.Series(equity).dropna()
    if equity.empty:
        return 0
    peak = equity.cummax()
    in_dd = equity < peak
    max_dur = 0
    current = 0
    for v in in_dd:
        if v:
            current += 1
            max_dur = max(max_dur, current)
        else:
            current = 0
    return int(max_dur)


def annualized_return(total_return_pct, days):
    if days <= 0:
        return 0.0
    growth = 1 + total_return_pct / 100
    if growth <= 0:
        return -100.0
    return float((growth ** (365.25 / days) - 1) * 100)


def calmar_ratio(total_return_pct, max_drawdown_pct, days):
    ann = annualized_return(total_return_pct, days)
    if max_drawdown_pct == 0:
        return float("inf") if ann > 0 else 0.0
    return ann / abs(max_drawdown_pct)


def profit_concentration(pnl, top_n):
    pnl = pd.Series(pnl).dropna()
    wins = pnl[pnl > 0].sort_values(ascending=False)
    total_net = pnl.sum()
    if total_net <= 0 or wins.empty:
        return 0.0
    return float(wins.head(top_n).sum() / total_net * 100)


def summarize_trades(trades, initial_balance=1000.0, equity_curve=None):
    trades = trades.copy()
    if trades.empty:
        return {
            "initial_balance": initial_balance,
            "final_balance": initial_balance,
            "total_return_pct": 0.0,
            "total_trades": 0,
        }

    pnl = trades["net_pnl"]
    final_balance = float(trades["balance_after"].iloc[-1])
    returns = trades["return_on_equity"] / 100.0 if "return_on_equity" in trades else pnl / initial_balance
    summary = {
        "initial_balance": float(initial_balance),
        "final_balance": final_balance,
        "total_return_pct": (final_balance / initial_balance - 1) * 100,
        "total_trades": int(len(trades)),
        "win_rate_pct": float((pnl > 0).mean() * 100),
        "gross_profit": float(pnl[pnl > 0].sum()),
        "gross_loss": float(pnl[pnl <= 0].sum()),
        "net_profit": float(pnl.sum()),
        "profit_factor": float(profit_factor(pnl)),
        "average_trade": float(pnl.mean()),
        "median_trade": float(pnl.median()),
        "geometric_mean_trade_return_pct": float(geometric_mean_return(returns) * 100),
        "longest_losing_streak": int(longest_losing_streak(pnl)),
        "total_fee": float(trades.get("total_fee", pd.Series(0, index=trades.index)).sum()),
        "total_slippage_cost": float(trades.get("slippage_cost", pd.Series(0, index=trades.index)).sum()),
        "gross_profit_before_cost": float(trades.get("gross_pnl", pnl).clip(lower=0).sum()),
        "gross_loss_before_cost": float(trades.get("gross_pnl", pnl).clip(upper=0).sum()),
    }
    if equity_curve is not None and not equity_curve.empty:
        summary["max_drawdown_pct"] = float(max_drawdown(equity_curve["equity"]) * 100)
    return summary


def extended_summary(trades, initial_balance, equity_curve, start_date, end_date):
    summary = summarize_trades(trades, initial_balance, equity_curve)
    if trades.empty:
        return summary

    days = max((pd.Timestamp(end_date) - pd.Timestamp(start_date)).days, 1)
    pnl = trades["net_pnl"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    summary["annualized_return_pct"] = annualized_return(summary["total_return_pct"], days)
    summary["calmar"] = calmar_ratio(
        summary["total_return_pct"],
        summary.get("max_drawdown_pct", 0),
        days,
    )
    summary["avg_win"] = float(wins.mean()) if len(wins) else 0.0
    summary["avg_loss"] = float(losses.mean()) if len(losses) else 0.0
    summary["payoff_ratio"] = (
        abs(summary["avg_win"] / summary["avg_loss"]) if summary["avg_loss"] != 0 else float("inf")
    )
    summary["top_5_profit_contribution"] = profit_concentration(pnl, 5)
    summary["top_10_profit_contribution"] = profit_concentration(pnl, 10)

    if "mae_atr" in trades.columns:
        summary["avg_mae_atr"] = float(trades["mae_atr"].mean())
        summary["avg_mfe_atr"] = float(trades["mfe_atr"].mean())

    if equity_curve is not None and not equity_curve.empty:
        summary["longest_drawdown_duration_bars"] = longest_drawdown_duration(equity_curve["equity"])

    return summary
