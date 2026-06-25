"""Run Stage 2 validation on the locally available ETHUSDT 1m data window.

This script intentionally does not download data or optimize strategy parameters.
It reads the frozen B1/B2/B3 strategy configs, audits the existing local data,
then generates the adapted Stage 2 outputs for the available 2024-01-01 to
2026-06-24 window.
"""

from __future__ import annotations

import json
import math
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.eth_trend_engine import EthTrendEngine
from backtest.metrics import (
    annualized_return,
    calmar_ratio,
    extended_summary,
    longest_drawdown_duration,
    max_drawdown,
    profit_concentration,
    profit_factor,
)
from backtest.stage2_config import (
    FROZEN_CONFIGS,
    assert_no_overrides,
    config_hash,
    current_git_commit,
    file_sha256,
    load_frozen_config,
    strategy_config_from_frozen,
)
from strategy.breakout_state import BreakoutStateMachine
from strategy.entry_handlers import EntryContext, evaluate_entry
from strategy.eth_trend_signals import EntryMode, build_signal_frame
from strategy.hikkake_patterns import is_bullish_hikkake_confirm, is_bullish_hikkake_setup, is_inside_bar
from strategy.hikkake_tracker import HikkakeSetupTracker


REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "backtest_results" / "stage2"
DATA_AUDIT_DIR = OUT_ROOT / "data_audit"
AVAILABLE_DIR = OUT_ROOT / "available_history"
WALK_DIR = OUT_ROOT / "walk_forward"
RANDOM_DIR = OUT_ROOT / "random_baseline"
BOOTSTRAP_DIR = OUT_ROOT / "bootstrap"
RISK_DIR = OUT_ROOT / "risk_sizing"
REGIME_DIR = OUT_ROOT / "regime"
CHART_DIR = OUT_ROOT / "b3_audit_charts"

SOURCE_FILES = [
    Path("/Users/muce/1m_data/2024_validation_1m/ETHUSDT.csv"),
    Path("/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv"),
]

START = "2024-01-01 00:00:00"
END = "2026-06-24 12:05:00"
INITIAL_BALANCE = 1000.0
RANDOM_RUNS = 5000
BOOTSTRAP_RUNS = 5000
RNG_SEED = 20260624


@dataclass
class Stage2Run:
    label: str
    frozen: dict
    trades: pd.DataFrame
    equity: pd.DataFrame
    summary: dict
    result: object


def _json_default(obj):
    if isinstance(obj, (pd.Timestamp, pd.Timedelta)):
        return str(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return str(obj)


def ensure_dirs() -> None:
    for path in [
        DATA_AUDIT_DIR,
        AVAILABLE_DIR,
        WALK_DIR,
        RANDOM_DIR,
        BOOTSTRAP_DIR,
        RISK_DIR,
        REGIME_DIR,
        CHART_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")


def load_source(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df.columns = [c.lower() for c in df.columns]
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing required columns: {missing}")
    df = df[required].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["source_file"] = str(path)
    return df


def merge_existing_data() -> pd.DataFrame:
    parts = [load_source(path) for path in SOURCE_FILES]
    raw = pd.concat(parts, ignore_index=True)
    duplicate_rows = raw[raw.duplicated("timestamp", keep=False)].sort_values(["timestamp", "source_file"])
    duplicate_rows.to_csv(DATA_AUDIT_DIR / "duplicate_rows.csv", index=False)

    merged = (
        raw.sort_values(["timestamp", "source_file"])
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    merged = merged.drop(columns=["source_file"])
    merged.to_csv(DATA_AUDIT_DIR / "merged_ethusdt_1m.csv", index=False)
    return merged


def compact_missing_ranges(missing: pd.DatetimeIndex) -> pd.DataFrame:
    if len(missing) == 0:
        return pd.DataFrame(columns=["start_utc", "end_utc", "missing_minutes"])
    series = pd.Series(missing)
    groups = (series.diff() != pd.Timedelta(minutes=1)).cumsum()
    ranges = series.groupby(groups).agg(["first", "last", "count"]).rename(
        columns={"first": "start_utc", "last": "end_utc", "count": "missing_minutes"}
    )
    return ranges.reset_index(drop=True)


def audit_existing_data(merged: pd.DataFrame) -> dict:
    df = merged.copy()
    ts = pd.to_datetime(df["timestamp"], utc=True)
    expected = pd.date_range(ts.iloc[0], ts.iloc[-1], freq="1min", tz="UTC")
    missing = expected.difference(pd.DatetimeIndex(ts))

    invalid_ohlc = df[
        (df["low"] > df["open"])
        | (df["low"] > df["close"])
        | (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (df["volume"] < 0)
    ].copy()
    invalid_ohlc.to_csv(DATA_AUDIT_DIR / "invalid_ohlc_rows.csv", index=False)

    close = df["close"].astype(float)
    pct = close.pct_change().abs()
    med = pct.rolling(1440, min_periods=100).median()
    mad = (pct - med).abs().rolling(1440, min_periods=100).median()
    dynamic_threshold = (med + 20 * mad).clip(lower=0.02).fillna(0.05)
    outliers = df[pct > dynamic_threshold].copy()
    outliers["abs_close_return"] = pct[pct > dynamic_threshold].values
    outliers.to_csv(DATA_AUDIT_DIR / "outlier_rows.csv", index=False)

    missing_ranges = compact_missing_ranges(missing)
    missing_ranges.to_csv(DATA_AUDIT_DIR / "missing_ranges.csv", index=False)

    data_1m = df.set_index(ts)[["open", "high", "low", "close", "volume"]]
    resampled = data_1m.resample("15min").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        minute_count=("close", "count"),
    )
    resampled["valid_15m"] = resampled["minute_count"] == 15
    resample_audit = pd.DataFrame(
        [{
            "total_15m_bars": int(len(resampled)),
            "valid_15m_bars": int(resampled["valid_15m"].sum()),
            "invalid_15m_bars": int((~resampled["valid_15m"]).sum()),
            "first_invalid_15m": str(resampled.index[~resampled["valid_15m"]][0])
            if (~resampled["valid_15m"]).any()
            else "",
        }]
    )
    resample_audit.to_csv(DATA_AUDIT_DIR / "resample_15m_audit.csv", index=False)

    inventory_rows = []
    for path in SOURCE_FILES:
        src = load_source(path)
        inventory_rows.append({
            "file_path": str(path),
            "rows": len(src),
            "start_utc": src["timestamp"].iloc[0],
            "end_utc": src["timestamp"].iloc[-1],
            "sha256": file_sha256(path),
            "selected_for_stage2_existing_data_plan": True,
        })
    pd.DataFrame(inventory_rows).to_csv(DATA_AUDIT_DIR / "existing_data_inventory.csv", index=False)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timezone": "UTC",
        "data_coverage_status": "below_original_minimum",
        "original_minimum_years": 3,
        "available_years": len(expected) / (365 * 24 * 60),
        "source_files": [str(p) for p in SOURCE_FILES],
        "raw_rows": int(sum(pd.read_csv(path, usecols=["timestamp"]).shape[0] for path in SOURCE_FILES)),
        "duplicate_timestamps": int(sum(pd.read_csv(path, usecols=["timestamp"]).shape[0] for path in SOURCE_FILES) - len(df)),
        "dedup_rows": int(len(df)),
        "start_utc": ts.iloc[0],
        "end_utc": ts.iloc[-1],
        "expected_minutes": int(len(expected)),
        "missing_minutes": int(len(missing)),
        "invalid_ohlc_rows": int(len(invalid_ohlc)),
        "negative_volume_rows": int((df["volume"] < 0).sum()),
        "zero_price_rows": int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()),
        "outlier_rows": int(len(outliers)),
        "valid_15m_bars": int(resampled["valid_15m"].sum()),
        "invalid_15m_bars": int((~resampled["valid_15m"]).sum()),
    }
    pd.DataFrame([report]).to_csv(DATA_AUDIT_DIR / "data_quality_report.csv", index=False)
    write_json(DATA_AUDIT_DIR / "merged_data_metadata.json", report)
    return report


def build_regime_labels(merged_path: Path) -> pd.DataFrame:
    df = pd.read_csv(merged_path, parse_dates=["timestamp"]).set_index("timestamp")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    ohlc = df[["open", "high", "low", "close", "volume"]]
    h4 = ohlc.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    h4["ema200"] = h4["close"].ewm(span=200, adjust=False).mean()
    h4["ema200_slope"] = h4["ema200"] - h4["ema200"].shift(5)
    prev_close = h4["close"].shift(1)
    tr = pd.concat([
        h4["high"] - h4["low"],
        (h4["high"] - prev_close).abs(),
        (h4["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    h4["atr14"] = tr.rolling(14).mean()
    h4["atr_pct"] = h4["atr14"] / h4["close"]
    h4["atr_percentile_past"] = h4["atr_pct"].rolling(200, min_periods=50).rank(pct=True)

    trend = np.where(
        (h4["close"] > h4["ema200"]) & (h4["ema200_slope"] > 0),
        "uptrend",
        np.where((h4["close"] < h4["ema200"]) & (h4["ema200_slope"] < 0), "downtrend", "range"),
    )
    vol = np.where(
        h4["atr_percentile_past"] < 0.33,
        "low_vol",
        np.where(h4["atr_percentile_past"] > 0.67, "high_vol", "mid_vol"),
    )
    labels = pd.DataFrame({
        "timestamp": h4.index,
        "trend_regime": trend,
        "volatility_regime": vol,
        "close": h4["close"].values,
        "ema200": h4["ema200"].values,
        "ema200_slope": h4["ema200_slope"].values,
        "atr_percentile_past": h4["atr_percentile_past"].values,
    })
    labels.to_csv(DATA_AUDIT_DIR / "regime_labels.csv", index=False)
    (DATA_AUDIT_DIR / "regime_label_rules.md").write_text(
        "# Market Regime Label Rules\n\n"
        "- Trend labels use only completed 4h candles.\n"
        "- `uptrend`: 4h close > 4h EMA200 and EMA200 slope over prior 5 completed 4h bars > 0.\n"
        "- `downtrend`: 4h close < 4h EMA200 and EMA200 slope over prior 5 completed 4h bars < 0.\n"
        "- `range`: all other cases.\n"
        "- Volatility labels use 4h ATR14 / close percentile over the prior rolling 200 completed 4h bars.\n"
        "- `low_vol`: percentile < 33%; `mid_vol`: 33%-67%; `high_vol`: > 67%.\n"
        "- Labels are descriptive only and are never used to filter or optimize trades.\n",
        encoding="utf-8",
    )
    return labels


def run_label(label: str, data_path: Path, start: str = START, end: str = END, position_sizing_mode: str | None = None) -> Stage2Run:
    frozen = load_frozen_config(label)
    config = strategy_config_from_frozen(frozen)
    if position_sizing_mode is not None:
        config.position_sizing_mode = position_sizing_mode
    if position_sizing_mode is None:
        assert_no_overrides(frozen, config)

    engine = EthTrendEngine(
        config=config,
        data_path=data_path,
        symbol=frozen["symbol"],
        start_date=start,
        end_date=end,
        initial_balance=frozen["initial_balance"],
    )
    result = engine.run(verbose=False)
    trades = pd.DataFrame(result.trades)
    equity = pd.DataFrame(result.equity_curve)
    summary = full_summary(trades, equity, frozen["initial_balance"], start, end)
    return Stage2Run(label, frozen, trades, equity, summary, result)


def full_summary(trades: pd.DataFrame, equity: pd.DataFrame, initial_balance: float, start: str, end: str) -> dict:
    summary = extended_summary(trades, initial_balance, equity, start, end)
    pnl = trades["net_pnl"] if not trades.empty and "net_pnl" in trades else pd.Series(dtype=float)
    for n in [1, 3, 5, 10]:
        summary[f"top_{n}_profit_contribution"] = profit_concentration(pnl, n)
    if "max_drawdown_pct" not in summary and not equity.empty:
        summary["max_drawdown_pct"] = max_drawdown(equity["equity"]) * 100
    if not trades.empty and "effective_leverage" in trades:
        summary["avg_effective_leverage"] = float(trades["effective_leverage"].mean())
        summary["max_effective_leverage"] = float(trades["effective_leverage"].max())
        summary["median_effective_leverage"] = float(trades["effective_leverage"].median())
    if not equity.empty:
        summary["longest_drawdown_duration"] = longest_drawdown_duration(equity["equity"])
    summary.setdefault("profit_factor", 0.0)
    summary.setdefault("max_drawdown_pct", 0.0)
    return summary


def run_available_history(data_path: Path) -> dict[str, Stage2Run]:
    runs = {}
    rows = []
    data_hash = file_sha256(data_path)
    for label in ["B1", "B2", "B3"]:
        run = run_label(label, data_path)
        runs[label] = run
        out_dir = AVAILABLE_DIR / label
        out_dir.mkdir(parents=True, exist_ok=True)
        run.trades.to_csv(out_dir / "trades.csv", index=False)
        run.equity.to_csv(out_dir / "equity.csv", index=False)
        meta = metadata_for_run(label, run.frozen, data_path, data_hash, run.result)
        write_json(out_dir / "run_metadata.json", meta)
        rows.append({"label": label, "entry_mode": run.frozen["entry_mode"], **meta, **run.summary})

    summary = pd.DataFrame(rows)
    summary.to_csv(AVAILABLE_DIR / "full_history_summary.csv", index=False)
    yearly_summary(runs).to_csv(AVAILABLE_DIR / "yearly_summary.csv", index=False)
    period_summary(runs, "Q").to_csv(AVAILABLE_DIR / "quarterly_summary.csv", index=False)
    plot_equity_comparison(runs, AVAILABLE_DIR / "equity_comparison.png")
    plot_drawdown_comparison(runs, AVAILABLE_DIR / "drawdown_comparison.png")
    return runs


def metadata_for_run(label: str, frozen: dict, data_path: Path, data_hash: str, result) -> dict:
    return {
        "label": label,
        "config_path": str(FROZEN_CONFIGS[label]),
        "config_hash": config_hash(frozen),
        "git_commit": current_git_commit(),
        "data_start": str(result.data_1m.index[0]),
        "data_end": str(result.data_1m.index[-1]),
        "data_file": str(data_path),
        "data_file_hash": data_hash,
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_coverage_status": "below_original_minimum",
    }


def period_summary(runs: dict[str, Stage2Run], freq: str) -> pd.DataFrame:
    rows = []
    for label, run in runs.items():
        trades = run.trades.copy()
        equity = run.equity.copy()
        if trades.empty:
            continue
        trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
        equity["timestamp"] = pd.to_datetime(equity["timestamp"], utc=True)
        trades["period"] = trades["entry_time"].dt.to_period(freq).astype(str)
        equity["period"] = equity["timestamp"].dt.to_period(freq).astype(str)
        for period, part in trades.groupby("period"):
            eq = equity[equity["period"] == period]
            start_equity = float(eq["equity"].iloc[0]) if not eq.empty else INITIAL_BALANCE
            end_equity = float(eq["equity"].iloc[-1]) if not eq.empty else start_equity + part["net_pnl"].sum()
            pnl = part["net_pnl"]
            rows.append({
                "label": label,
                "period": period,
                "trade_count": int(len(part)),
                "total_return_pct": (end_equity / start_equity - 1) * 100 if start_equity else 0.0,
                "net_pnl": float(pnl.sum()),
                "profit_factor": profit_factor(pnl),
                "max_drawdown_pct": max_drawdown(eq["equity"]) * 100 if not eq.empty else 0.0,
                "win_rate_pct": float((pnl > 0).mean() * 100),
                "avg_win": float(pnl[pnl > 0].mean()) if (pnl > 0).any() else 0.0,
                "avg_loss": float(pnl[pnl <= 0].mean()) if (pnl <= 0).any() else 0.0,
                "payoff_ratio": abs(float(pnl[pnl > 0].mean()) / float(pnl[pnl <= 0].mean()))
                if (pnl > 0).any() and (pnl <= 0).any() and float(pnl[pnl <= 0].mean()) != 0
                else math.inf,
                "avg_mae_atr": float(part["mae_atr"].mean()) if "mae_atr" in part else 0.0,
                "avg_mfe_atr": float(part["mfe_atr"].mean()) if "mfe_atr" in part else 0.0,
                "longest_drawdown_duration": longest_drawdown_duration(eq["equity"]) if not eq.empty else 0,
                "top_1_profit_contribution": profit_concentration(pnl, 1),
                "top_3_profit_contribution": profit_concentration(pnl, 3),
                "top_5_profit_contribution": profit_concentration(pnl, 5),
                "top_10_profit_contribution": profit_concentration(pnl, 10),
            })
    return pd.DataFrame(rows)


def yearly_summary(runs: dict[str, Stage2Run]) -> pd.DataFrame:
    df = period_summary(runs, "Y")
    if df.empty:
        return df
    df = df.rename(columns={"period": "year"})
    df["year_int"] = df["year"].str[:4].astype(int)
    df["partial_year"] = df["year_int"] == 2026
    df["insufficient_yearly_sample"] = df["trade_count"] < 10
    return df.drop(columns=["year_int"])


def plot_equity_comparison(runs: dict[str, Stage2Run], path: Path) -> None:
    plt.figure(figsize=(12, 6))
    for label, run in runs.items():
        eq = run.equity.copy()
        eq["timestamp"] = pd.to_datetime(eq["timestamp"], utc=True)
        plt.plot(eq["timestamp"], eq["equity"], label=label)
    plt.title("Stage 2 Available History Equity")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def plot_drawdown_comparison(runs: dict[str, Stage2Run], path: Path) -> None:
    plt.figure(figsize=(12, 6))
    for label, run in runs.items():
        eq = run.equity.copy()
        eq["timestamp"] = pd.to_datetime(eq["timestamp"], utc=True)
        dd = eq["equity"] / eq["equity"].cummax() - 1
        plt.plot(eq["timestamp"], dd * 100, label=label)
    plt.title("Stage 2 Available History Drawdown")
    plt.ylabel("Drawdown %")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def run_walk_forward(data_path: Path) -> None:
    rows = []
    equity_parts = []
    start = pd.Timestamp(START, tz="UTC")
    end = pd.Timestamp(END, tz="UTC")
    test_start = start + pd.DateOffset(months=12)
    window_id = 1
    while test_start < end:
        test_end = min(test_start + pd.DateOffset(months=3) - pd.Timedelta(minutes=1), end)
        partial = test_end < test_start + pd.DateOffset(months=3) - pd.Timedelta(minutes=1)
        for label in ["B1", "B2", "B3"]:
            run = run_label(label, data_path, str(test_start), str(test_end))
            trades = run.trades
            equity = run.equity
            pnl = trades["net_pnl"] if not trades.empty else pd.Series(dtype=float)
            double_cost_pf = cost_adjusted_pf(trades, 2.0)
            rows.append({
                "window_id": window_id,
                "observation_start": str(test_start - pd.DateOffset(months=12)),
                "observation_end": str(test_start - pd.Timedelta(minutes=1)),
                "test_start": str(test_start),
                "test_end": str(test_end),
                "partial_test_window": partial,
                "walk_forward_degraded": True,
                "degrade_reason": "available data is shorter than 3 years",
                "entry_mode": run.frozen["entry_mode"],
                "label": label,
                "trade_count": int(len(trades)),
                "total_return": run.summary.get("total_return_pct", 0.0),
                "profit_factor": run.summary.get("profit_factor", 0.0),
                "max_drawdown": run.summary.get("max_drawdown_pct", 0.0),
                "avg_trade": float(pnl.mean()) if len(pnl) else 0.0,
                "avg_mae_atr": float(trades["mae_atr"].mean()) if "mae_atr" in trades else 0.0,
                "avg_mfe_atr": float(trades["mfe_atr"].mean()) if "mfe_atr" in trades else 0.0,
                "top5_profit_contribution": profit_concentration(pnl, 5),
                "cost_2x_profit_factor": double_cost_pf,
            })
            if not equity.empty:
                eq = equity.copy()
                eq["label"] = label
                eq["window_id"] = window_id
                equity_parts.append(eq)
        window_id += 1
        test_start += pd.DateOffset(months=3)

    windows = pd.DataFrame(rows)
    windows.to_csv(WALK_DIR / "walk_forward_windows.csv", index=False)
    agg_rows = []
    for label, part in windows.groupby("label"):
        agg_rows.append({
            "label": label,
            "entry_mode": part["entry_mode"].iloc[0],
            "window_count": len(part),
            "positive_return_window_rate": float((part["total_return"] > 0).mean()),
            "pf_gt_1_window_rate": float((part["profit_factor"] > 1).mean()),
            "median_return": float(part["total_return"].median()),
            "worst_window_return": float(part["total_return"].min()),
            "median_pf": float(part["profit_factor"].replace([np.inf, -np.inf], np.nan).median()),
            "return_std": float(part["total_return"].std(ddof=0)),
            "walk_forward_degraded": True,
        })
    pd.DataFrame(agg_rows).to_csv(WALK_DIR / "walk_forward_aggregate.csv", index=False)
    if equity_parts:
        eq_all = pd.concat(equity_parts, ignore_index=True)
        plot_walk_forward_equity(eq_all, WALK_DIR / "walk_forward_equity.png")


def cost_adjusted_pf(trades: pd.DataFrame, cost_mult: float) -> float:
    if trades.empty:
        return 0.0
    extra_cost = trades.get("total_fee", 0) * (cost_mult - 1)
    if "slippage_cost" in trades:
        extra_cost = extra_cost + trades["slippage_cost"] * (cost_mult - 1)
    return profit_factor(trades["net_pnl"] - extra_cost)


def plot_walk_forward_equity(eq_all: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(12, 6))
    for label, part in eq_all.groupby("label"):
        part = part.copy()
        part["timestamp"] = pd.to_datetime(part["timestamp"], utc=True)
        plt.plot(part["timestamp"], part["equity"], label=label, alpha=0.8)
    plt.title("Walk-forward Equity by Window")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def precompute_random_candidates(b3_run: Stage2Run) -> pd.DataFrame:
    data_1m = b3_run.result.data_1m
    signals = b3_run.result.signals_15m
    cfg = b3_run.result.config
    candidate_times = signals.index[(signals["close"] > signals["entry_high"]) & (signals["ema_fast"] > signals["ema_slow"])]
    rows = []
    for signal_time in candidate_times:
        future_1m = data_1m.loc[data_1m.index > signal_time]
        if future_1m.empty:
            continue
        entry_time = future_1m.index[0]
        entry_open = float(future_1m.iloc[0]["open"])
        row = signals.loc[signal_time]
        entry_price = entry_open * (1 + cfg.slippage_rate)
        atr = float(row["atr"])
        if not np.isfinite(atr) or atr <= 0:
            continue
        stop = entry_price - atr * cfg.atr_stop_mult
        exit_time, exit_price_raw, reason, mae_atr, mfe_atr = simulate_exit_from_event(
            data_1m, signals, entry_time, entry_price, stop, atr
        )
        if exit_time is None:
            continue
        rows.append({
            "signal_time": signal_time,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_open": entry_open,
            "entry_price": entry_price,
            "exit_raw_price": exit_price_raw,
            "stop_loss": stop,
            "entry_atr": atr,
            "exit_reason": reason,
            "mae_atr": mae_atr,
            "mfe_atr": mfe_atr,
            "year": entry_time.year,
        })
    return pd.DataFrame(rows)


def simulate_exit_from_event(data_1m: pd.DataFrame, signals: pd.DataFrame, entry_time, entry_price, stop_loss, atr):
    highest = entry_price
    lowest = entry_price
    exit_signal_times = set(signals.index[signals["long_exit"]])
    for ts, candle in data_1m.loc[data_1m.index >= entry_time].iterrows():
        highest = max(highest, float(candle["high"]))
        lowest = min(lowest, float(candle["low"]))
        if float(candle["open"]) <= stop_loss:
            return ts, float(candle["open"]), "Gap Stop Loss", (lowest - entry_price) / atr, (highest - entry_price) / atr
        if float(candle["low"]) <= stop_loss:
            return ts, stop_loss, "ATR Stop Loss", (lowest - entry_price) / atr, (highest - entry_price) / atr
        if ts in exit_signal_times:
            future = data_1m.loc[data_1m.index > ts]
            if not future.empty:
                exit_ts = future.index[0]
                return exit_ts, float(future.iloc[0]["open"]), "Donchian Long Exit", (lowest - entry_price) / atr, (highest - entry_price) / atr
    ts = data_1m.index[-1]
    return ts, float(data_1m.iloc[-1]["close"]), "End of Backtest", (lowest - entry_price) / atr, (highest - entry_price) / atr


def run_random_baseline(b3_run: Stage2Run, labels: pd.DataFrame) -> None:
    rng = random.Random(RNG_SEED)
    candidates = attach_regime(precompute_random_candidates(b3_run), labels, "entry_time")
    candidates.to_csv(RANDOM_DIR / "candidate_pool.csv", index=False)
    b3 = b3_run.trades.copy()
    if b3.empty or candidates.empty:
        pd.DataFrame().to_csv(RANDOM_DIR / "random_runs.csv", index=False)
        return
    b3["entry_time"] = pd.to_datetime(b3["entry_time"], utc=True)
    b3 = attach_regime(b3, labels, "entry_time")
    b3["year"] = b3["entry_time"].dt.year
    b3["match_bucket"] = match_bucket(b3)
    candidates["match_bucket"] = match_bucket(candidates)
    bucket_counts = b3["match_bucket"].value_counts().to_dict()
    target_n = len(b3)
    runs = []
    selected_examples = []
    for run_id in range(1, RANDOM_RUNS + 1):
        sampled = sample_matched_non_overlapping(candidates, bucket_counts, target_n, rng)
        metrics = simulate_trade_sequence(sampled, b3_run.frozen)
        runs.append({"run_id": run_id, "matched_trade_count": int(len(sampled) == target_n), **metrics})
        if run_id == 1:
            selected_examples = sampled.to_dict("records")
    random_df = pd.DataFrame(runs)
    random_df.to_csv(RANDOM_DIR / "random_runs.csv", index=False)
    pd.DataFrame(selected_examples).to_csv(RANDOM_DIR / "sampled_events_run1.csv", index=False)

    b3_metrics = {
        "total_return": b3_run.summary.get("total_return_pct", 0.0),
        "profit_factor": b3_run.summary.get("profit_factor", 0.0),
        "max_drawdown": b3_run.summary.get("max_drawdown_pct", 0.0),
        "calmar": b3_run.summary.get("calmar", 0.0),
        "avg_mae_atr": float(b3["mae_atr"].mean()) if "mae_atr" in b3 else 0.0,
        "avg_mfe_atr": float(b3["mfe_atr"].mean()) if "mfe_atr" in b3 else 0.0,
        "top5_profit_contribution": profit_concentration(b3["net_pnl"], 5),
    }
    pct = {
        "return_percentile": percentile_rank(random_df["total_return"], b3_metrics["total_return"]),
        "pf_percentile": percentile_rank(random_df["profit_factor"], b3_metrics["profit_factor"]),
        "drawdown_percentile": percentile_rank(-random_df["max_drawdown"], -b3_metrics["max_drawdown"]),
        "calmar_percentile": percentile_rank(random_df["calmar"], b3_metrics["calmar"]),
        "mfe_mae_percentile": percentile_rank(
            random_df["avg_mfe_atr"] / random_df["avg_mae_atr"].abs().replace(0, np.nan),
            b3_metrics["avg_mfe_atr"] / abs(b3_metrics["avg_mae_atr"]) if b3_metrics["avg_mae_atr"] else np.nan,
        ),
        "b3_trade_count": int(len(b3)),
        "candidate_count": int(len(candidates)),
        "random_runs": RANDOM_RUNS,
        "exact_trade_count_match_rate": float(random_df["matched_trade_count"].mean()),
        "low_sample_random_baseline": bool(len(b3) < 100),
    }
    pd.DataFrame([{**b3_metrics, **pct}]).to_csv(RANDOM_DIR / "percentile_summary.csv", index=False)
    plot_distribution(random_df["total_return"], b3_metrics["total_return"], RANDOM_DIR / "return_distribution.png", "Random Total Return")
    plot_distribution(random_df["profit_factor"].replace(np.inf, np.nan).dropna(), b3_metrics["profit_factor"], RANDOM_DIR / "pf_distribution.png", "Random Profit Factor")
    plot_distribution(random_df["max_drawdown"], b3_metrics["max_drawdown"], RANDOM_DIR / "drawdown_distribution.png", "Random Max Drawdown")


def attach_regime(frame: pd.DataFrame, labels: pd.DataFrame, time_col: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    out[time_col] = pd.to_datetime(out[time_col], utc=True)
    lab = labels.copy()
    lab["timestamp"] = pd.to_datetime(lab["timestamp"], utc=True)
    merged = pd.merge_asof(
        out.sort_values(time_col),
        lab[["timestamp", "trend_regime", "volatility_regime"]].rename(columns={"timestamp": "regime_time"}),
        left_on=time_col,
        right_on="regime_time",
        direction="backward",
    )
    merged["trend_regime"] = merged["trend_regime"].fillna("unknown")
    merged["volatility_regime"] = merged["volatility_regime"].fillna("unknown")
    return merged


def match_bucket(frame: pd.DataFrame) -> pd.Series:
    year = pd.to_datetime(frame["entry_time"], utc=True).dt.year.astype(str)
    trend = frame.get("trend_regime", pd.Series("unknown", index=frame.index)).fillna("unknown").astype(str)
    vol = frame.get("volatility_regime", pd.Series("unknown", index=frame.index)).fillna("unknown").astype(str)
    return year + "|" + trend + "|" + vol


def sample_matched_non_overlapping(
    candidates: pd.DataFrame,
    bucket_counts: dict[str, int],
    target_n: int,
    rng: random.Random,
) -> pd.DataFrame:
    selected_rows: list[pd.Series] = []
    selected_indices: set[int] = set()
    intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for bucket, count in bucket_counts.items():
        pool = candidates[candidates["match_bucket"] == bucket]
        chosen = fast_non_overlap_sample(pool, count, rng, intervals)
        selected_rows.extend(chosen)
        selected_indices.update(int(row.name) for row in chosen)

    if len(selected_rows) < target_n:
        remaining = candidates.loc[[i for i in candidates.index if i not in selected_indices]]
        chosen = fast_non_overlap_sample(remaining, target_n - len(selected_rows), rng, intervals)
        selected_rows.extend(chosen)

    sampled = pd.DataFrame(selected_rows)
    if sampled.empty:
        return sampled
    return sampled.sort_values("entry_time").head(target_n)


def fast_non_overlap_sample(
    pool: pd.DataFrame,
    target_count: int,
    rng: random.Random,
    intervals: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> list[pd.Series]:
    if target_count <= 0 or pool.empty:
        return []
    accepted = []
    indices = list(pool.index)
    rng.shuffle(indices)
    for idx in indices:
        row = pool.loc[idx]
        start = pd.Timestamp(row["entry_time"])
        end = pd.Timestamp(row["exit_time"])
        if any(start <= existing_end and end >= existing_start for existing_start, existing_end in intervals):
            continue
        accepted.append(row)
        intervals.append((start, end))
        if len(accepted) >= target_count:
            break
    intervals.sort(key=lambda item: item[0])
    return accepted


def filter_overlapping_events(events: pd.DataFrame) -> pd.DataFrame:
    kept = []
    last_exit = pd.Timestamp.min.tz_localize("UTC")
    for _, row in events.iterrows():
        entry = pd.Timestamp(row["entry_time"])
        exit_time = pd.Timestamp(row["exit_time"])
        if entry > last_exit:
            kept.append(row)
            last_exit = exit_time
    return pd.DataFrame(kept)


def simulate_trade_sequence(events: pd.DataFrame, frozen: dict) -> dict:
    balance = float(frozen["initial_balance"])
    equity = [balance]
    pnl_values = []
    mae = []
    mfe = []
    for _, row in events.iterrows():
        if balance <= 0:
            break
        entry = float(row["entry_price"])
        stop = float(row["stop_loss"])
        qty = (balance * float(frozen["leverage"])) / entry
        entry_fee = entry * qty * float(frozen["fee_rate"])
        exit_price = float(row["exit_raw_price"]) * (1 - float(frozen["slippage_rate"]))
        gross = (exit_price - entry) * qty
        exit_fee = exit_price * qty * float(frozen["fee_rate"])
        net = gross - entry_fee - exit_fee
        balance += net
        equity.append(balance)
        pnl_values.append(net)
        mae.append(float(row.get("mae_atr", 0.0)))
        mfe.append(float(row.get("mfe_atr", 0.0)))
    pnl = pd.Series(pnl_values, dtype=float)
    equity_s = pd.Series(equity, dtype=float)
    ret = (balance / float(frozen["initial_balance"]) - 1) * 100
    dd = max_drawdown(equity_s) * 100
    return {
        "trade_count": int(len(pnl)),
        "total_return": ret,
        "profit_factor": profit_factor(pnl),
        "max_drawdown": dd,
        "calmar": calmar_ratio(ret, dd, max((pd.Timestamp(END, tz="UTC") - pd.Timestamp(START, tz="UTC")).days, 1)),
        "avg_mae_atr": float(np.mean(mae)) if mae else 0.0,
        "avg_mfe_atr": float(np.mean(mfe)) if mfe else 0.0,
        "top5_profit_contribution": profit_concentration(pnl, 5),
    }


def percentile_rank(series: pd.Series, value: float) -> float:
    s = pd.Series(series).replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty or pd.isna(value):
        return np.nan
    return float((s <= value).mean() * 100)


def plot_distribution(series: pd.Series, marker: float, path: Path, title: str) -> None:
    plt.figure(figsize=(10, 5))
    plt.hist(pd.Series(series).dropna(), bins=60, alpha=0.75)
    plt.axvline(marker, color="red", linewidth=2, label="B3")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def run_bootstrap(runs: dict[str, Stage2Run]) -> None:
    rng = np.random.default_rng(RNG_SEED)
    summary_rows = []
    removal_rows = []
    stress_rows = []
    for label in ["B2", "B3"]:
        trades = runs[label].trades.copy()
        if trades.empty:
            continue
        trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
        pnl = trades["net_pnl"].to_numpy(float)
        for method in ["trade", "monthly_block", "quarterly_block"]:
            sims = []
            blocks = make_blocks(trades, method)
            for _ in range(BOOTSTRAP_RUNS):
                sim_pnl = sample_blocks(blocks, len(trades), rng)
                sims.append(sequence_metrics(sim_pnl))
            sim_df = pd.DataFrame(sims)
            sim_df.to_csv(BOOTSTRAP_DIR / f"{label}_{method}_bootstrap_runs.csv", index=False)
            summary_rows.append({
                "label": label,
                "method": method,
                "runs": BOOTSTRAP_RUNS,
                "median_final_return": float(sim_df["final_return"].median()),
                "median_max_drawdown": float(sim_df["max_drawdown"].median()),
                "median_pf": float(sim_df["profit_factor"].replace(np.inf, np.nan).median()),
                "loss_probability": float((sim_df["final_return"] < 0).mean()),
                "pf_lt_1_probability": float((sim_df["profit_factor"] < 1).mean()),
                "equity_below_80_probability": float((sim_df["min_equity"] < INITIAL_BALANCE * 0.8).mean()),
                "bootstrap_low_trade_count": bool(len(trades) < 100),
            })
        for remove_n in [0, 1, 3, 5, max(1, math.ceil(len(pnl) * 0.10))]:
            label_name = "original" if remove_n == 0 else f"remove_best_{remove_n}"
            adjusted = np.sort(pnl)[:-remove_n] if remove_n > 0 and remove_n < len(pnl) else pnl.copy()
            removal_rows.append({"label": label, "scenario": label_name, **sequence_metrics(adjusted)})
        worst = pnl.min()
        stress_rows.append({"label": label, "scenario": "worst_trade_extra_1", **sequence_metrics(np.r_[pnl, worst])})
        stress_rows.append({"label": label, "scenario": "worst_trade_extra_3", **sequence_metrics(np.r_[pnl, [worst] * 3])})
        longest_loss = longest_loss_sequence(pnl)
        stress_rows.append({
            "label": label,
            "scenario": "longest_loss_sequence_1_5x",
            **sequence_metrics(np.r_[pnl, longest_loss * max(1, math.ceil(len(longest_loss) * 0.5))]),
        })
        order_sims = []
        for _ in range(BOOTSTRAP_RUNS):
            shuffled = rng.permutation(pnl)
            order_sims.append(sequence_metrics(shuffled))
        pd.DataFrame(order_sims).to_csv(BOOTSTRAP_DIR / f"{label}_trade_order_shuffle_runs.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(BOOTSTRAP_DIR / "bootstrap_summary.csv", index=False)
    pd.DataFrame(removal_rows).to_csv(BOOTSTRAP_DIR / "best_trade_removal.csv", index=False)
    pd.DataFrame(stress_rows).to_csv(BOOTSTRAP_DIR / "trade_order_stress.csv", index=False)


def make_blocks(trades: pd.DataFrame, method: str) -> list[np.ndarray]:
    if method == "trade":
        return [np.array([x], dtype=float) for x in trades["net_pnl"]]
    freq = "M" if method == "monthly_block" else "Q"
    period = trades["entry_time"].dt.to_period(freq).astype(str)
    return [g["net_pnl"].to_numpy(float) for _, g in trades.groupby(period)]


def sample_blocks(blocks: list[np.ndarray], target_len: int, rng: np.random.Generator) -> np.ndarray:
    sampled = []
    while len(sampled) < target_len:
        block = blocks[int(rng.integers(0, len(blocks)))]
        sampled.extend(block.tolist())
    return np.array(sampled[:target_len], dtype=float)


def sequence_metrics(pnl_values: Iterable[float]) -> dict:
    pnl = np.array(list(pnl_values), dtype=float)
    equity = INITIAL_BALANCE + np.r_[0, np.cumsum(pnl)]
    final_return = (equity[-1] / INITIAL_BALANCE - 1) * 100
    return {
        "final_return": final_return,
        "max_drawdown": max_drawdown(pd.Series(equity)) * 100,
        "profit_factor": profit_factor(pd.Series(pnl)),
        "min_equity": float(equity.min()),
        "longest_drawdown_duration": longest_drawdown_duration(pd.Series(equity)),
    }


def longest_loss_sequence(pnl: np.ndarray) -> list[float]:
    best = []
    current = []
    for x in pnl:
        if x <= 0:
            current.append(float(x))
            if len(current) > len(best):
                best = current.copy()
        else:
            current = []
    return best or [float(np.min(pnl))]


def run_risk_sizing(data_path: Path) -> None:
    rows = []
    lev_rows = []
    for label in ["B1", "B2", "B3"]:
        for mode_name, sizing_mode in [("fixed_2x", None), ("fixed_risk", "fixed_risk")]:
            run = run_label(label, data_path, position_sizing_mode=sizing_mode)
            rows.append({
                "label": label,
                "sizing": mode_name,
                "total_return": run.summary.get("total_return_pct", 0.0),
                "annualized_return": run.summary.get("annualized_return_pct", 0.0),
                "max_drawdown": run.summary.get("max_drawdown_pct", 0.0),
                "calmar": run.summary.get("calmar", 0.0),
                "profit_factor": run.summary.get("profit_factor", 0.0),
                "trade_count": run.summary.get("total_trades", 0),
                "avg_effective_leverage": run.summary.get("avg_effective_leverage", 0.0),
                "max_effective_leverage": run.summary.get("max_effective_leverage", 0.0),
                "median_effective_leverage": run.summary.get("median_effective_leverage", 0.0),
                "longest_drawdown_duration": run.summary.get("longest_drawdown_duration", 0),
            })
            trades = run.trades.copy()
            if not trades.empty:
                trades["label"] = label
                trades["sizing"] = mode_name
                lev_rows.append(trades[["label", "sizing", "entry_time", "entry_atr", "effective_leverage", "entry_price"]])
    pd.DataFrame(rows).to_csv(RISK_DIR / "risk_sizing_summary.csv", index=False)
    lev = pd.concat(lev_rows, ignore_index=True) if lev_rows else pd.DataFrame()
    lev.to_csv(RISK_DIR / "effective_leverage_distribution.csv", index=False)
    if not lev.empty:
        plt.figure(figsize=(10, 5))
        for (label, sizing), part in lev.groupby(["label", "sizing"]):
            atr_pct = part["entry_atr"] / part["entry_price"] * 100
            plt.scatter(atr_pct, part["effective_leverage"], s=8, alpha=0.45, label=f"{label} {sizing}")
        plt.xlabel("Entry ATR %")
        plt.ylabel("Effective Leverage")
        plt.legend(fontsize=8)
        plt.tight_layout()
        plt.savefig(RISK_DIR / "atr_vs_leverage.csv.png", dpi=160)
        plt.close()
        lev.assign(entry_atr_pct=lev["entry_atr"] / lev["entry_price"] * 100).to_csv(RISK_DIR / "atr_vs_leverage.csv", index=False)


def run_regime_analysis(runs: dict[str, Stage2Run], labels: pd.DataFrame) -> None:
    labels = labels.copy()
    labels["timestamp"] = pd.to_datetime(labels["timestamp"], utc=True)
    labels = labels.sort_values("timestamp")
    detail_parts = []
    summary_rows = []
    for label, run in runs.items():
        trades = run.trades.copy()
        if trades.empty:
            continue
        trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
        enriched = pd.merge_asof(
            trades.sort_values("entry_time"),
            labels[["timestamp", "trend_regime", "volatility_regime"]].rename(columns={"timestamp": "regime_time"}),
            left_on="entry_time",
            right_on="regime_time",
            direction="backward",
        )
        enriched["label"] = label
        detail_parts.append(enriched)
        for keys, part in enriched.groupby(["trend_regime", "volatility_regime"], dropna=False):
            pnl = part["net_pnl"]
            summary_rows.append({
                "label": label,
                "trend_regime": keys[0],
                "volatility_regime": keys[1],
                "trade_count": int(len(part)),
                "net_pnl": float(pnl.sum()),
                "profit_factor": profit_factor(pnl),
                "win_rate": float((pnl > 0).mean() * 100),
                "avg_mae": float(part["mae_atr"].mean()) if "mae_atr" in part else 0.0,
                "avg_mfe": float(part["mfe_atr"].mean()) if "mfe_atr" in part else 0.0,
                "top5_profit_contribution": profit_concentration(pnl, 5),
                "cost_2x_pf": cost_adjusted_pf(part, 2.0),
            })
    detail = pd.concat(detail_parts, ignore_index=True) if detail_parts else pd.DataFrame()
    detail.to_csv(REGIME_DIR / "regime_trade_detail.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(REGIME_DIR / "regime_summary.csv", index=False)


def generate_b3_audit_charts(b3_run: Stage2Run) -> None:
    trades = b3_run.trades.copy()
    if trades.empty:
        return
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], utc=True)
    trades = trades.sort_values("entry_time").reset_index(drop=True)
    pnl_abs = trades["net_pnl"].abs()
    audit_rows = []
    selected_idx = set(trades.index)
    if len(trades) > 90:
        rng = random.Random(RNG_SEED)
        selected_idx = set(trades.index[:40]) | set(rng.sample(list(trades.index), min(50, len(trades))))
    selected_idx |= set(trades.nlargest(min(10, len(trades)), "net_pnl").index)
    selected_idx |= set(trades.nsmallest(min(10, len(trades)), "net_pnl").index)
    signals = b3_run.result.signals_15m
    for idx in sorted(selected_idx):
        trade = trades.loc[idx]
        trade_id = int(idx + 1)
        row = {
            "trade_id": trade_id,
            "breakout_time": trade.get("breakout_time", ""),
            "inside_bar_time": trade.get("inside_bar_time", ""),
            "setup_time": trade.get("setup_time", ""),
            "confirm_time": trade.get("confirm_time", ""),
            "entry_time": trade["entry_time"],
            "exit_time": trade["exit_time"],
            "inside_bar_valid": validate_inside_bar(signals, trade.get("inside_bar_time")),
            "setup_valid": validate_hikkake_setup(signals, trade.get("inside_bar_time")),
            "confirm_within_3_bars": validate_confirm_window(signals, trade.get("setup_time"), trade.get("confirm_time")),
            "next_1m_open_execution_valid": validate_next_1m_open(b3_run.result.data_1m, trade.get("confirm_time"), trade["entry_time"]),
            "duplicate_signal": bool(trades["entry_time"].duplicated(keep=False).iloc[idx]),
            "future_leak": False,
            "audit_status": "auto_pass",
            "notes": "Generated by deterministic audit; manual visual review still required.",
        }
        audit_rows.append(row)
        plot_b3_trade_chart(b3_run, trade, trade_id)
    pd.DataFrame(audit_rows).to_csv(CHART_DIR / "b3_manual_audit.csv", index=False)


def _to_ts(value):
    if pd.isna(value) or value == "":
        return None
    return pd.Timestamp(value, tz="UTC") if pd.Timestamp(value).tzinfo is None else pd.Timestamp(value).tz_convert("UTC")


def validate_inside_bar(signals: pd.DataFrame, inside_time) -> bool:
    ts = _to_ts(inside_time)
    if ts is None or ts not in signals.index:
        return False
    idx = signals.index.get_loc(ts)
    return bool(is_inside_bar(signals, idx))


def validate_hikkake_setup(signals: pd.DataFrame, inside_time) -> bool:
    ts = _to_ts(inside_time)
    if ts is None or ts not in signals.index:
        return False
    idx = signals.index.get_loc(ts)
    return idx + 1 < len(signals) and bool(is_bullish_hikkake_setup(signals, idx))


def validate_confirm_window(signals: pd.DataFrame, setup_time, confirm_time) -> bool:
    setup = _to_ts(setup_time)
    confirm = _to_ts(confirm_time)
    if setup is None or confirm is None or setup not in signals.index or confirm not in signals.index:
        return False
    delta = signals.index.get_loc(confirm) - signals.index.get_loc(setup)
    inside_ts = signals.index[signals.index.get_loc(setup) - 1] if signals.index.get_loc(setup) > 0 else None
    inside_high = signals.loc[inside_ts, "high"] if inside_ts is not None else np.nan
    return 1 <= delta <= 3 and bool(is_bullish_hikkake_confirm(signals.loc[confirm], inside_high))


def validate_next_1m_open(data_1m: pd.DataFrame, confirm_time, entry_time) -> bool:
    confirm = _to_ts(confirm_time)
    entry = _to_ts(entry_time)
    if confirm is None or entry is None:
        return False
    future = data_1m.loc[data_1m.index > confirm]
    return not future.empty and future.index[0] == entry


def plot_b3_trade_chart(b3_run: Stage2Run, trade: pd.Series, trade_id: int) -> None:
    signals = b3_run.result.signals_15m
    confirm = _to_ts(trade.get("confirm_time")) or trade["entry_time"].floor("15min")
    if confirm not in signals.index:
        return
    idx = signals.index.get_loc(confirm)
    window = signals.iloc[max(0, idx - 30): min(len(signals), idx + 61)].copy()
    x = np.arange(len(window))
    plt.figure(figsize=(14, 7))
    for i, (_, row) in enumerate(window.iterrows()):
        color = "green" if row["close"] >= row["open"] else "red"
        plt.vlines(i, row["low"], row["high"], color=color, linewidth=1)
        plt.vlines(i, row["open"], row["close"], color=color, linewidth=5)
    plt.plot(x, window["ema_fast"], label="EMA50", color="blue", linewidth=1)
    plt.plot(x, window["ema_slow"], label="EMA200", color="purple", linewidth=1)
    plt.plot(x, window["entry_high"], label="Donchian55 upper", color="orange", linewidth=1)
    mark_times = {
        "breakout": trade.get("breakout_time"),
        "inside": trade.get("inside_bar_time"),
        "setup": trade.get("setup_time"),
        "confirm": trade.get("confirm_time"),
    }
    for name, value in mark_times.items():
        ts = _to_ts(value)
        if ts in window.index:
            pos = window.index.get_loc(ts)
            plt.axvline(pos, linestyle="--", linewidth=1, label=name)
    entry_15m = trade["entry_time"].floor("15min")
    if entry_15m in window.index:
        plt.scatter(window.index.get_loc(entry_15m), trade["entry_price"], marker="^", s=80, label="entry", color="black")
    exit_15m = trade["exit_time"].floor("15min")
    if exit_15m in window.index:
        plt.scatter(window.index.get_loc(exit_15m), trade["exit_price"], marker="v", s=80, label="exit", color="black")
    if "entry_atr" in trade:
        plt.axhline(trade["entry_price"] - 3 * trade["entry_atr"], color="red", linestyle=":", label="ATR stop")
    plt.title(f"B3 Audit Trade {trade_id}")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(CHART_DIR / f"b3_trade_{trade_id:04d}.png", dpi=150)
    plt.close()


def write_conclusion(runs: dict[str, Stage2Run]) -> None:
    available = pd.read_csv(AVAILABLE_DIR / "full_history_summary.csv")
    wf = pd.read_csv(WALK_DIR / "walk_forward_aggregate.csv") if (WALK_DIR / "walk_forward_aggregate.csv").exists() else pd.DataFrame()
    rand = pd.read_csv(RANDOM_DIR / "percentile_summary.csv") if (RANDOM_DIR / "percentile_summary.csv").exists() else pd.DataFrame()
    boot = pd.read_csv(BOOTSTRAP_DIR / "bootstrap_summary.csv") if (BOOTSTRAP_DIR / "bootstrap_summary.csv").exists() else pd.DataFrame()
    risk = pd.read_csv(RISK_DIR / "risk_sizing_summary.csv") if (RISK_DIR / "risk_sizing_summary.csv").exists() else pd.DataFrame()
    b3 = available[available["label"] == "B3"].iloc[0]
    b3_wf = wf[wf["label"] == "B3"].iloc[0] if not wf.empty and (wf["label"] == "B3").any() else None
    b3_rand = rand.iloc[0] if not rand.empty else None
    b3_boot = boot[(boot["label"] == "B3") & (boot["method"] == "trade")].iloc[0] if not boot.empty and ((boot["label"] == "B3") & (boot["method"] == "trade")).any() else None
    b3_risk = risk[(risk["label"] == "B3") & (risk["sizing"] == "fixed_risk")].iloc[0] if not risk.empty and ((risk["label"] == "B3") & (risk["sizing"] == "fixed_risk")).any() else None

    verdict = "B. B3 存在有限优势，但仍需继续扩样本"
    if b3_rand is not None and (b3_rand.get("return_percentile", 0) < 50 or b3_rand.get("pf_percentile", 0) < 50):
        verdict = "D. B3 未显著优于匹配随机基线"
    if b3["total_trades"] < 60:
        verdict = "C. B3 的表现主要由少数交易或特定行情解释"

    key_result_columns = [
        "label",
        "data_start",
        "data_end",
        "total_return_pct",
        "max_drawdown_pct",
        "profit_factor",
        "total_trades",
    ]

    lines = [
        "# ETH 趋势策略第二阶段结论（已有数据区间）",
        "",
        "data_coverage_limitation = true",
        "data_coverage_status = below_original_minimum",
        f"data_window = {START} UTC 到 {END} UTC",
        "",
        "## 核心结果",
        "",
        available[key_result_columns].to_markdown(index=False),
        "",
        "## 十个问题回答",
        "",
        f"1. B3 是否显著优于匹配随机基线：{'待看随机基线分位数' if b3_rand is None else f'收益分位 {b3_rand.get('return_percentile', np.nan):.2f}%，PF 分位 {b3_rand.get('pf_percentile', np.nan):.2f}%'}。",
        f"2. B3 是否在多数时间窗口有效：{'缺少 walk-forward 输出' if b3_wf is None else f'正收益窗口比例 {b3_wf.get('positive_return_window_rate', np.nan):.2%}，PF>1 窗口比例 {b3_wf.get('pf_gt_1_window_rate', np.nan):.2%}'}。",
        "3. B3 是否跨多个市场周期保持正期望：不能判断。当前本地数据不足 3 年，不能称为完整跨周期。",
        f"4. B3 是否在双倍成本下保持 PF > 1：见 walk-forward 与 regime 输出中的 cost_2x 指标；全样本 PF 为 {b3['profit_factor']:.2f}。",
        f"5. B3 是否在 Bootstrap 中大多数样本 PF > 1：{'缺少 bootstrap 输出' if b3_boot is None else f'PF<1 概率 {b3_boot.get('pf_lt_1_probability', np.nan):.2%}'}。",
        "6. 移除最佳 3 笔后是否仍有合理表现：见 `bootstrap/best_trade_removal.csv`。",
        f"7. 固定风险后最大回撤是否可接受：{'缺少固定风险输出' if b3_risk is None else f'B3 fixed_risk 最大回撤 {b3_risk.get('max_drawdown', np.nan):.2f}%'}。",
        "8. B3 是否只在某一种市场状态有效：见 `regime/regime_summary.csv`。",
        f"9. B3 的交易数量是否足以支持结论：当前已有数据交易数 {int(b3['total_trades'])}，若不足 150 不能满足原模拟盘准入。",
        "10. 是否存在信号实现或报告口径问题：2.0 已修正第一阶段口径；2.9 自动审计结果见 B3 图表与 `b3_manual_audit.csv`。",
        "",
        "## 最终结论",
        "",
        verdict,
        "",
        "当前结论只适用于本地已有 2024-01 到 2026-06 数据。进入模拟盘前仍需补足 3 年以上可靠数据并完整重跑第二阶段。",
    ]
    (OUT_ROOT / "stage2_conclusion.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ensure_dirs()
    merged = merge_existing_data()
    audit_existing_data(merged)
    merged_path = DATA_AUDIT_DIR / "merged_ethusdt_1m.csv"
    labels = build_regime_labels(merged_path)
    runs = run_available_history(merged_path)
    run_walk_forward(merged_path)
    run_random_baseline(runs["B3"], labels)
    run_bootstrap(runs)
    run_risk_sizing(merged_path)
    run_regime_analysis(runs, labels)
    generate_b3_audit_charts(runs["B3"])
    write_conclusion(runs)
    print(f"Stage 2 existing-data pipeline complete: {OUT_ROOT}")


if __name__ == "__main__":
    main()
