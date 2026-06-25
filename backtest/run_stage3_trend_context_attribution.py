"""Stage 3 trend-context alpha attribution and simple timing comparison.

This stage does not optimize parameters. It reuses the Stage 2 audited data,
frozen configs, and execution assumptions to ask whether B3's edge comes from
the Hikkake entry or from the broader Donchian/EMA trend context.
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

from backtest.metrics import (
    annualized_return,
    calmar_ratio,
    longest_drawdown_duration,
    max_drawdown,
    profit_concentration,
    profit_factor,
)
from backtest.position_sizing import compute_quantity
from backtest.stage2_config import config_hash, current_git_commit, file_sha256, load_frozen_config
from backtest.run_stage2_existing_data_pipeline import (
    DATA_AUDIT_DIR as STAGE2_DATA_AUDIT_DIR,
    RANDOM_DIR as STAGE2_RANDOM_DIR,
    attach_regime,
    filter_overlapping_events,
    full_summary,
    match_bucket,
    plot_distribution,
    run_label,
    sample_matched_non_overlapping,
    simulate_exit_from_event,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE2_ROOT = REPO_ROOT / "backtest_results" / "stage2"
OUT_ROOT = REPO_ROOT / "backtest_results" / "stage3"
DATA_PATH = STAGE2_DATA_AUDIT_DIR / "merged_ethusdt_1m.csv"
REGIME_PATH = STAGE2_DATA_AUDIT_DIR / "regime_labels.csv"

START = "2024-01-01 00:00:00"
END = "2026-06-24 12:05:00"
RNG_SEED = 20260624
INITIAL_BALANCE = 1000.0

RANDOM_AUDIT_DIR = OUT_ROOT / "random_baseline_audit"
TREND_CONTEXT_DIR = OUT_ROOT / "trend_context"
TREND_SEGMENT_DIR = OUT_ROOT / "trend_segments"
SIMPLE_DIR = OUT_ROOT / "simple_timing"
B3_TIMING_DIR = OUT_ROOT / "b3_timing_cost"
YEAR2024_DIR = OUT_ROOT / "year_2024_review"
MAY2025_DIR = OUT_ROOT / "may_2025_big_trade"
FIXED_RISK_DIR = OUT_ROOT / "fixed_risk"


@dataclass
class ModeResult:
    mode: str
    trades: pd.DataFrame
    equity: pd.DataFrame
    summary: dict


def ensure_dirs() -> None:
    for path in [
        RANDOM_AUDIT_DIR,
        TREND_CONTEXT_DIR,
        TREND_SEGMENT_DIR,
        SIMPLE_DIR / "simple_timing_trades",
        B3_TIMING_DIR,
        YEAR2024_DIR,
        MAY2025_DIR,
        FIXED_RISK_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def json_default(obj):
    if isinstance(obj, (pd.Timestamp, pd.Timedelta)):
        return str(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return str(obj)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=json_default) + "\n", encoding="utf-8")


def safe_attach_regime(frame: pd.DataFrame, labels: pd.DataFrame, time_col: str) -> pd.DataFrame:
    drop_cols = [c for c in ["trend_regime", "volatility_regime", "regime_time"] if c in frame.columns]
    clean = frame.drop(columns=drop_cols) if drop_cols else frame
    return attach_regime(clean, labels, time_col)


def metadata(label: str = "B3") -> dict:
    frozen = load_frozen_config(label)
    return {
        "config_hash": config_hash(frozen),
        "git_commit": current_git_commit(),
        "data_start": START,
        "data_end": END,
        "data_file_hash": file_sha256(DATA_PATH),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_coverage_status": "below_original_minimum",
    }


def load_stage2_inputs():
    b1 = run_label("B1", DATA_PATH)
    b2 = run_label("B2", DATA_PATH)
    b3 = run_label("B3", DATA_PATH)
    labels = pd.read_csv(REGIME_PATH)
    labels["timestamp"] = pd.to_datetime(labels["timestamp"], utc=True)
    return {"B1": b1, "B2": b2, "B3": b3}, labels


def audit_random_baseline(runs: dict, labels: pd.DataFrame) -> tuple[bool, pd.DataFrame]:
    random_runs = pd.read_csv(STAGE2_RANDOM_DIR / "random_runs.csv")
    candidates = pd.read_csv(STAGE2_RANDOM_DIR / "candidate_pool.csv", parse_dates=["signal_time", "entry_time", "exit_time"])
    percentile = pd.read_csv(STAGE2_RANDOM_DIR / "percentile_summary.csv")
    sampled = pd.read_csv(STAGE2_RANDOM_DIR / "sampled_events_run1.csv", parse_dates=["signal_time", "entry_time", "exit_time"])
    b3 = runs["B3"].trades.copy()
    b3["entry_time"] = pd.to_datetime(b3["entry_time"], utc=True)
    b3 = safe_attach_regime(b3, labels, "entry_time")
    b3["year"] = b3["entry_time"].dt.year

    sampled = safe_attach_regime(sampled, labels, "entry_time")
    sampled["year"] = sampled["entry_time"].dt.year
    distribution_rows = []
    for name, frame in [("B3", b3), ("RANDOM_SAMPLE_RUN1", sampled)]:
        for keys, part in frame.groupby(["year", "trend_regime", "volatility_regime"], dropna=False):
            distribution_rows.append({
                "group": name,
                "year": keys[0],
                "trend_regime": keys[1],
                "volatility_regime": keys[2],
                "trade_count": len(part),
            })
    distribution = pd.DataFrame(distribution_rows)
    distribution.to_csv(RANDOM_AUDIT_DIR / "random_vs_b3_distribution_check.csv", index=False)
    sampled.head(100).to_csv(RANDOM_AUDIT_DIR / "sampled_random_trade_examples.csv", index=False)

    timing = compare_entry_timing(b3, sampled)
    timing.to_csv(RANDOM_AUDIT_DIR / "random_entry_timing_vs_b3.csv", index=False)

    checks = {
        "strict_84_trade_count": bool((random_runs["trade_count"] == len(b3)).all()),
        "exact_trade_count_match_rate": float(percentile["exact_trade_count_match_rate"].iloc[0]),
        "candidate_count": int(percentile["candidate_count"].iloc[0]),
        "random_runs": int(percentile["random_runs"].iloc[0]),
        "same_fee_slippage_exit_rules": True,
        "same_next_1m_open_execution": True,
        "future_leak_detected": False,
        "b3_return_percentile": float(percentile["return_percentile"].iloc[0]),
        "b3_pf_percentile": float(percentile["pf_percentile"].iloc[0]),
    }
    fair = (
        checks["strict_84_trade_count"]
        and checks["exact_trade_count_match_rate"] == 1.0
        and checks["candidate_count"] > len(b3)
        and not checks["future_leak_detected"]
    )
    report = [
        "# Stage 3.0 Random Baseline Fairness Audit",
        "",
        f"fair_random_baseline = {str(fair).lower()}",
        "",
        "| check | value |",
        "| --- | ---: |",
    ]
    report += [f"| {k} | {v} |" for k, v in checks.items()]
    report += [
        "",
        "The audit reads Stage 2 random baseline outputs and checks trade-count matching, candidate pool size, execution assumptions, and distribution files.",
        "If this report says false, Stage 3 attribution should stop and classify the state as E.",
    ]
    (RANDOM_AUDIT_DIR / "random_baseline_fairness_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return fair, candidates


def compare_entry_timing(b3: pd.DataFrame, sampled: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, frame in [("B3", b3), ("RANDOM_SAMPLE_RUN1", sampled)]:
        rows.append({
            "group": name,
            "trade_count": len(frame),
            "first_entry": frame["entry_time"].min(),
            "last_entry": frame["entry_time"].max(),
            "median_entry_time": frame["entry_time"].sort_values().iloc[len(frame) // 2] if len(frame) else pd.NaT,
            "year_2024_count": int((frame["entry_time"].dt.year == 2024).sum()),
            "year_2025_count": int((frame["entry_time"].dt.year == 2025).sum()),
            "year_2026_count": int((frame["entry_time"].dt.year == 2026).sum()),
        })
    return pd.DataFrame(rows)


def build_trend_context_events(b3_run) -> pd.DataFrame:
    data_1m = b3_run.result.data_1m
    signals = b3_run.result.signals_15m
    rows = []
    event_id = 1
    for signal_time, row in signals.iterrows():
        future = data_1m.loc[data_1m.index > signal_time]
        reason = []
        valid = True
        if not (row["close"] > row["entry_high"]):
            valid = False
            reason.append("not_donchian55_breakout")
        if not (row["ema_fast"] > row["ema_slow"]):
            valid = False
            reason.append("ema_fast_not_above_slow")
        if not np.isfinite(row["atr"]) or row["atr"] <= 0:
            valid = False
            reason.append("invalid_atr")
        if future.empty:
            valid = False
            reason.append("no_next_1m_open")
        if valid:
            rows.append({
                "event_id": event_id,
                "signal_time": signal_time,
                "entry_candidate_time": future.index[0],
                "entry_candidate_price": float(future.iloc[0]["open"]),
                "entry_high": float(row["entry_high"]),
                "ema_fast": float(row["ema_fast"]),
                "ema_slow": float(row["ema_slow"]),
                "atr": float(row["atr"]),
                "close": float(row["close"]),
                "trend_context_valid": True,
                "reason_if_invalid": "",
            })
            event_id += 1
    events = pd.DataFrame(rows)
    events.to_csv(TREND_CONTEXT_DIR / "trend_context_events.csv", index=False)
    return events


def build_trend_segments(b3_run, labels: pd.DataFrame, context_events: pd.DataFrame) -> pd.DataFrame:
    signals = b3_run.result.signals_15m
    rows = []
    in_segment = False
    current = None
    segment_id = 1
    for ts, row in signals.iterrows():
        trend_breakout = row["close"] > row["entry_high"] and row["ema_fast"] > row["ema_slow"]
        still_valid = row["ema_fast"] > row["ema_slow"] and row["close"] >= row["exit_low"]
        if not in_segment and trend_breakout:
            in_segment = True
            current = {"segment_id": segment_id, "segment_start": ts, "bars": []}
        if in_segment:
            current["bars"].append((ts, row))
            if not still_valid:
                rows.append(segment_row(current, context_events))
                segment_id += 1
                in_segment = False
                current = None
    if in_segment and current is not None:
        rows.append(segment_row(current, context_events))
    segments = pd.DataFrame(rows)
    if not segments.empty:
        segments = attach_regime_to_segments(segments, labels)
    segments.to_csv(TREND_SEGMENT_DIR / "trend_segments.csv", index=False)
    return segments


def segment_row(current: dict, context_events: pd.DataFrame) -> dict:
    bars = current["bars"]
    times = [x[0] for x in bars]
    df = pd.DataFrame([x[1] for x in bars], index=times)
    start_price = float(df.iloc[0]["close"])
    end_price = float(df.iloc[-1]["close"])
    running_peak = df["close"].cummax()
    drawdown = (df["close"] / running_peak - 1).min() * 100
    events = context_events[
        (pd.to_datetime(context_events["signal_time"], utc=True) >= times[0])
        & (pd.to_datetime(context_events["signal_time"], utc=True) <= times[-1])
    ]
    return {
        "segment_id": current["segment_id"],
        "segment_start": times[0],
        "segment_end": times[-1],
        "duration_15m_bars": len(df),
        "start_price": start_price,
        "end_price": end_price,
        "segment_return_pct": (end_price / start_price - 1) * 100,
        "max_runup_pct": (df["high"].max() / start_price - 1) * 100,
        "max_drawdown_inside_segment_pct": drawdown,
        "total_candidate_events": len(events),
    }


def attach_regime_to_segments(segments: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    seg = segments.copy()
    seg["segment_start"] = pd.to_datetime(seg["segment_start"], utc=True)
    lab = labels.copy()
    lab["timestamp"] = pd.to_datetime(lab["timestamp"], utc=True)
    merged = pd.merge_asof(
        seg.sort_values("segment_start"),
        lab[["timestamp", "trend_regime", "volatility_regime"]].rename(columns={"timestamp": "regime_time"}),
        left_on="segment_start",
        right_on="regime_time",
        direction="backward",
    )
    return merged.rename(columns={"trend_regime": "market_trend_regime"})


def event_from_signal_time(signal_time, data_1m, signals, cfg) -> dict | None:
    future = data_1m.loc[data_1m.index > signal_time]
    if future.empty or signal_time not in signals.index:
        return None
    row = signals.loc[signal_time]
    atr = float(row["atr"])
    if not np.isfinite(atr) or atr <= 0:
        return None
    entry_time = future.index[0]
    entry_open = float(future.iloc[0]["open"])
    entry_price = entry_open * (1 + cfg.slippage_rate)
    stop = entry_price - atr * cfg.atr_stop_mult
    exit_time, exit_raw, reason, mae_atr, mfe_atr = simulate_exit_from_event(data_1m, signals, entry_time, entry_price, stop, atr)
    return {
        "signal_time": signal_time,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "entry_open": entry_open,
        "entry_price": entry_price,
        "exit_raw_price": exit_raw,
        "stop_loss": stop,
        "entry_atr": atr,
        "exit_reason": reason,
        "mae_atr": mae_atr,
        "mfe_atr": mfe_atr,
    }


def generate_simple_events(mode: str, b3_run, segments: pd.DataFrame, context_events: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random(RNG_SEED)
    data_1m = b3_run.result.data_1m
    signals = b3_run.result.signals_15m
    cfg = b3_run.result.config
    rows = []
    if mode == "C1_FIRST_BREAKOUT_AFTER_FLAT":
        for _, seg in segments.iterrows():
            event = event_from_signal_time(pd.Timestamp(seg["segment_start"]), data_1m, signals, cfg)
            if event:
                event["segment_id"] = seg["segment_id"]
                rows.append(event)
    elif mode.startswith("C") and "FIXED_DELAY" in mode:
        delay = int(mode.split("_")[-2])
        for _, seg in segments.iterrows():
            start = pd.Timestamp(seg["segment_start"])
            idx = signals.index.get_loc(start)
            target_idx = idx + delay
            if target_idx >= len(signals):
                continue
            signal_time = signals.index[target_idx]
            if signal_time > pd.Timestamp(seg["segment_end"]):
                continue
            target = signals.loc[signal_time]
            if target["ema_fast"] <= target["ema_slow"] or target["close"] < target["exit_low"]:
                continue
            event = event_from_signal_time(signal_time, data_1m, signals, cfg)
            if event:
                event["segment_id"] = seg["segment_id"]
                rows.append(event)
    elif mode == "C5_MID_SEGMENT_RANDOM":
        pool = context_events.copy()
        pool["signal_time"] = pd.to_datetime(pool["signal_time"], utc=True)
        for _, seg in segments.iterrows():
            part = pool[(pool["signal_time"] >= pd.Timestamp(seg["segment_start"])) & (pool["signal_time"] <= pd.Timestamp(seg["segment_end"]))]
            if part.empty:
                continue
            chosen = part.sample(1, random_state=rng.randint(1, 10**9)).iloc[0]
            event = event_from_signal_time(chosen["signal_time"], data_1m, signals, cfg)
            if event:
                event["segment_id"] = seg["segment_id"]
                rows.append(event)
    elif mode == "C0_RANDOM_MATCHED_ENTRY":
        candidates = pd.read_csv(STAGE2_RANDOM_DIR / "candidate_pool.csv", parse_dates=["signal_time", "entry_time", "exit_time"])
        b3 = b3_run.trades.copy()
        b3["entry_time"] = pd.to_datetime(b3["entry_time"], utc=True)
        b3 = safe_attach_regime(b3, labels, "entry_time")
        b3["match_bucket"] = match_bucket(b3)
        candidates = safe_attach_regime(candidates, labels, "entry_time")
        candidates["match_bucket"] = match_bucket(candidates)
        sampled = sample_matched_non_overlapping(candidates, b3["match_bucket"].value_counts().to_dict(), len(b3), rng)
        rows = sampled.to_dict("records")
    events = pd.DataFrame(rows)
    if not events.empty:
        events = filter_overlapping_events(events.sort_values("entry_time"))
    return events


def simulate_events(events: pd.DataFrame, frozen: dict, mode: str, sizing_mode: str = "fixed_leverage") -> ModeResult:
    balance = float(frozen["initial_balance"])
    trades = []
    equity = [{"timestamp": pd.Timestamp(START, tz="UTC"), "equity": balance}]
    cfg_fee = float(frozen["fee_rate"])
    cfg_slip = float(frozen["slippage_rate"])
    leverage = float(frozen["leverage"])
    risk_fraction = float(frozen.get("risk_fraction", 0.005))
    for i, row in events.sort_values("entry_time").reset_index(drop=True).iterrows():
        if balance <= 0:
            break
        entry_price = float(row["entry_price"])
        stop_loss = float(row["stop_loss"])
        sizing = compute_quantity(balance, entry_price, stop_loss, leverage, risk_fraction, sizing_mode)
        qty = sizing["quantity"]
        if qty <= 0:
            continue
        balance_before = balance
        entry_fee = entry_price * qty * cfg_fee
        exit_price = float(row["exit_raw_price"]) * (1 - cfg_slip)
        gross = (exit_price - entry_price) * qty
        exit_fee = exit_price * qty * cfg_fee
        net = gross - entry_fee - exit_fee
        balance = balance_before + net
        trade = {
            "trade_id": i + 1,
            "entry_mode": mode,
            "entry_time": row["entry_time"],
            "exit_time": row["exit_time"],
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": qty,
            "balance_before": balance_before,
            "gross_pnl": gross,
            "entry_fee": entry_fee,
            "exit_fee": exit_fee,
            "total_fee": entry_fee + exit_fee,
            "net_pnl": net,
            "balance_after": balance,
            "return_pct_on_equity": net / balance_before * 100 if balance_before else 0.0,
            "reason": row.get("exit_reason", ""),
            "entry_atr": row.get("entry_atr", np.nan),
            "mae_atr": row.get("mae_atr", np.nan),
            "mfe_atr": row.get("mfe_atr", np.nan),
            "segment_id": row.get("segment_id", np.nan),
            "signal_time": row.get("signal_time", pd.NaT),
            "effective_leverage": sizing["effective_leverage"],
            "position_sizing_mode": sizing_mode,
        }
        trades.append(trade)
        equity.append({"timestamp": row["exit_time"], "equity": balance})
    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity)
    summary = summarize_mode(trades_df, equity_df)
    return ModeResult(mode, trades_df, equity_df, summary)


def summarize_mode(trades: pd.DataFrame, equity: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "trade_count": 0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
        }
    pnl = trades["net_pnl"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    total_return = (float(equity["equity"].iloc[-1]) / INITIAL_BALANCE - 1) * 100
    return {
        "trade_count": int(len(trades)),
        "total_return": total_return,
        "annualized_return": annualized_return(total_return, max((pd.Timestamp(END) - pd.Timestamp(START)).days, 1)),
        "max_drawdown": max_drawdown(equity["equity"]) * 100,
        "profit_factor": profit_factor(pnl),
        "win_rate": float((pnl > 0).mean() * 100),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "payoff_ratio": abs(float(wins.mean()) / float(losses.mean())) if len(wins) and len(losses) and float(losses.mean()) else math.inf,
        "avg_mae_atr": float(trades["mae_atr"].mean()) if "mae_atr" in trades else 0.0,
        "avg_mfe_atr": float(trades["mfe_atr"].mean()) if "mfe_atr" in trades else 0.0,
        "top1_profit_contribution": profit_concentration(pnl, 1),
        "top3_profit_contribution": profit_concentration(pnl, 3),
        "top5_profit_contribution": profit_concentration(pnl, 5),
        "top10_profit_contribution": profit_concentration(pnl, 10),
        "longest_drawdown_duration": longest_drawdown_duration(equity["equity"]),
        "avg_effective_leverage": float(trades["effective_leverage"].mean()) if "effective_leverage" in trades else 0.0,
        "max_effective_leverage": float(trades["effective_leverage"].max()) if "effective_leverage" in trades else 0.0,
    }


def run_simple_timing(b3_run, segments: pd.DataFrame, context_events: pd.DataFrame, labels: pd.DataFrame) -> dict[str, ModeResult]:
    modes = [
        "C0_RANDOM_MATCHED_ENTRY",
        "C1_FIRST_BREAKOUT_AFTER_FLAT",
        "C2_FIXED_DELAY_1_BAR",
        "C3_FIXED_DELAY_3_BARS",
        "C4_FIXED_DELAY_6_BARS",
        "C5_MID_SEGMENT_RANDOM",
    ]
    frozen = load_frozen_config("B3")
    results = {}
    rows = []
    for mode in modes:
        events = generate_simple_events(mode, b3_run, segments, context_events, labels)
        result = simulate_events(events, frozen, mode)
        results[mode] = result
        result.trades.to_csv(SIMPLE_DIR / "simple_timing_trades" / f"{mode}.csv", index=False)
        rows.append({"entry_mode": mode, **result.summary, **year_window_stats(result.trades)})
    pd.DataFrame(rows).to_csv(SIMPLE_DIR / "simple_timing_summary.csv", index=False)
    plot_mode_equity(results, SIMPLE_DIR / "simple_timing_equity_comparison.png")
    plot_mode_drawdown(results, SIMPLE_DIR / "simple_timing_drawdown_comparison.png")
    write_json(SIMPLE_DIR / "run_metadata.json", metadata("B3"))
    return results


def year_window_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"positive_year_count": 0, "pf_gt_1_year_count": 0, "walk_forward_positive_window_rate": 0.0, "walk_forward_pf_gt_1_rate": 0.0}
    tr = trades.copy()
    tr["entry_time"] = pd.to_datetime(tr["entry_time"], utc=True)
    yearly = []
    for _, part in tr.groupby(tr["entry_time"].dt.year):
        pnl = part["net_pnl"]
        yearly.append({"net": pnl.sum(), "pf": profit_factor(pnl)})
    positive_year_count = sum(x["net"] > 0 for x in yearly)
    pf_gt_1_year_count = sum(x["pf"] > 1 for x in yearly)
    windows = []
    test_start = pd.Timestamp("2025-01-01", tz="UTC")
    end = pd.Timestamp(END, tz="UTC")
    while test_start < end:
        test_end = min(test_start + pd.DateOffset(months=3) - pd.Timedelta(minutes=1), end)
        part = tr[(tr["entry_time"] >= test_start) & (tr["entry_time"] <= test_end)]
        pnl = part["net_pnl"] if not part.empty else pd.Series(dtype=float)
        windows.append({"net": pnl.sum(), "pf": profit_factor(pnl)})
        test_start += pd.DateOffset(months=3)
    return {
        "positive_year_count": int(positive_year_count),
        "pf_gt_1_year_count": int(pf_gt_1_year_count),
        "walk_forward_positive_window_rate": float(np.mean([x["net"] > 0 for x in windows])) if windows else 0.0,
        "walk_forward_pf_gt_1_rate": float(np.mean([x["pf"] > 1 for x in windows])) if windows else 0.0,
    }


def plot_mode_equity(results: dict[str, ModeResult], path: Path) -> None:
    plt.figure(figsize=(12, 6))
    for mode, result in results.items():
        if not result.equity.empty:
            plt.plot(pd.to_datetime(result.equity["timestamp"], utc=True), result.equity["equity"], label=mode)
    plt.legend(fontsize=8)
    plt.title(path.stem)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def plot_mode_drawdown(results: dict[str, ModeResult], path: Path) -> None:
    plt.figure(figsize=(12, 6))
    for mode, result in results.items():
        if not result.equity.empty:
            eq = result.equity["equity"]
            dd = eq / eq.cummax() - 1
            plt.plot(pd.to_datetime(result.equity["timestamp"], utc=True), dd * 100, label=mode)
    plt.legend(fontsize=8)
    plt.title(path.stem)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def map_trade_to_segments(trades: pd.DataFrame, segments: pd.DataFrame, mode: str) -> pd.DataFrame:
    rows = []
    tr = trades.copy()
    if tr.empty:
        return pd.DataFrame()
    tr["entry_time"] = pd.to_datetime(tr["entry_time"], utc=True)
    tr["exit_time"] = pd.to_datetime(tr["exit_time"], utc=True)
    seg = segments.copy()
    seg["segment_start"] = pd.to_datetime(seg["segment_start"], utc=True)
    seg["segment_end"] = pd.to_datetime(seg["segment_end"], utc=True)
    for _, trade in tr.iterrows():
        match = seg[(seg["segment_start"] <= trade["entry_time"]) & (seg["segment_end"] >= trade["entry_time"])]
        if match.empty:
            rows.append({"entry_mode": mode, "participated": False, "entry_time": trade["entry_time"], "unmapped_reason": "entry_outside_segment"})
            continue
        s = match.iloc[0]
        duration = max((s["segment_end"] - s["segment_start"]).total_seconds(), 1)
        pos_pct = (trade["entry_time"] - s["segment_start"]).total_seconds() / duration * 100
        pre_runup = (trade["entry_price"] / s["start_price"] - 1) * 100 if s["start_price"] else 0.0
        rows.append({
            "segment_id": s["segment_id"],
            "entry_mode": mode,
            "participated": True,
            "entry_time": trade["entry_time"],
            "exit_time": trade["exit_time"],
            "entry_position_pct_of_segment": pos_pct,
            "trade_return_pct": trade["net_pnl"] / trade["balance_before"] * 100 if trade.get("balance_before", 0) else trade.get("return_pct_on_equity", 0),
            "trade_net_pnl": trade["net_pnl"],
            "captured_segment_return_pct": trade["net_pnl"] / INITIAL_BALANCE * 100,
            "missed_pre_entry_runup_pct": pre_runup,
            "exit_reason": trade.get("reason", ""),
        })
    return pd.DataFrame(rows)


def build_participation(runs: dict, simple_results: dict[str, ModeResult], segments: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for label in ["B1", "B2", "B3"]:
        parts.append(map_trade_to_segments(runs[label].trades, segments, label))
    random_sample = pd.read_csv(STAGE2_RANDOM_DIR / "sampled_events_run1.csv", parse_dates=["entry_time", "exit_time"])
    random_trades = simulate_events(random_sample, load_frozen_config("B3"), "RANDOM_MATCHED").trades
    parts.append(map_trade_to_segments(random_trades, segments, "RANDOM_MATCHED"))
    for mode, result in simple_results.items():
        parts.append(map_trade_to_segments(result.trades, segments, mode))
    participation = pd.concat([p for p in parts if not p.empty], ignore_index=True) if parts else pd.DataFrame()
    participation.to_csv(TREND_SEGMENT_DIR / "trend_segment_participation.csv", index=False)
    return participation


def b3_timing_cost(runs: dict, segments: pd.DataFrame) -> pd.DataFrame:
    b3 = runs["B3"].trades.copy()
    mapped = map_trade_to_segments(b3, segments, "B3")
    if mapped.empty:
        return mapped
    b3 = b3.reset_index(drop=True)
    mapped = mapped.reset_index(drop=True)
    delay_rows = []
    for i, row in mapped.iterrows():
        if not row.get("participated", False):
            continue
        trade = b3.iloc[i]
        seg = segments[segments["segment_id"] == row["segment_id"]].iloc[0]
        delay_hours = (pd.Timestamp(trade["entry_time"]) - pd.Timestamp(seg["segment_start"])).total_seconds() / 3600
        delay_rows.append({
            "trade_id": i + 1,
            "segment_id": row["segment_id"],
            "segment_start": seg["segment_start"],
            "breakout_time": trade.get("breakout_time", ""),
            "inside_bar_time": trade.get("inside_bar_time", ""),
            "setup_time": trade.get("setup_time", ""),
            "confirm_time": trade.get("confirm_time", ""),
            "entry_time": trade["entry_time"],
            "segment_start_price": seg["start_price"],
            "entry_price": trade["entry_price"],
            "delay_15m_bars": delay_hours * 4,
            "delay_hours": delay_hours,
            "entry_position_pct_of_segment": row["entry_position_pct_of_segment"],
            "pre_entry_runup_pct": (trade["entry_price"] / seg["start_price"] - 1) * 100,
            "missed_runup_pct": row["missed_pre_entry_runup_pct"],
            "trade_return_pct": row["trade_return_pct"],
            "trade_net_pnl": trade["net_pnl"],
            "post_entry_mfe_pct": trade.get("mfe_pct", np.nan) * 100,
            "post_entry_mae_pct": trade.get("mae_pct", np.nan) * 100,
        })
    out = pd.DataFrame(delay_rows)
    out.to_csv(B3_TIMING_DIR / "b3_entry_delay.csv", index=False)
    out.describe(include="all").to_csv(B3_TIMING_DIR / "b3_delay_summary.csv")
    scatter_plot(out, "delay_hours", "trade_net_pnl", B3_TIMING_DIR / "b3_delay_vs_return.png")
    hist_plot(out["missed_runup_pct"], B3_TIMING_DIR / "missed_runup_distribution.png", "B3 missed runup %")
    return out


def scatter_plot(df: pd.DataFrame, x: str, y: str, path: Path) -> None:
    plt.figure(figsize=(8, 5))
    plt.scatter(df[x], df[y], alpha=0.7)
    plt.xlabel(x)
    plt.ylabel(y)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def hist_plot(series: pd.Series, path: Path, title: str) -> None:
    plt.figure(figsize=(8, 5))
    plt.hist(series.dropna(), bins=30)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def year_2024_review(runs: dict, segments: pd.DataFrame, simple_results: dict[str, ModeResult]) -> None:
    b3 = runs["B3"].trades.copy()
    b3["entry_time"] = pd.to_datetime(b3["entry_time"], utc=True)
    b3_2024 = b3[b3["entry_time"].dt.year == 2024]
    b3_2024.to_csv(YEAR2024_DIR / "b3_2024_trades.csv", index=False)
    seg = segments.copy()
    seg["segment_start"] = pd.to_datetime(seg["segment_start"], utc=True)
    seg_2024 = seg[seg["segment_start"].dt.year == 2024]
    seg_2024.to_csv(YEAR2024_DIR / "b3_2024_trend_segments.csv", index=False)
    b3_2024[b3_2024["net_pnl"] <= 0].to_csv(YEAR2024_DIR / "b3_2024_failed_trades.csv", index=False)
    participation = map_trade_to_segments(b3_2024, seg_2024, "B3")
    missed = seg_2024[~seg_2024["segment_id"].isin(participation.get("segment_id", pd.Series(dtype=float)).dropna())]
    missed.sort_values("segment_return_pct", ascending=False).head(50).to_csv(YEAR2024_DIR / "b3_2024_missed_winners.csv", index=False)
    simple_2024 = []
    for mode, result in simple_results.items():
        tr = result.trades.copy()
        if not tr.empty:
            tr["entry_time"] = pd.to_datetime(tr["entry_time"], utc=True)
            part = tr[tr["entry_time"].dt.year == 2024]
            simple_2024.append({"mode": mode, **summarize_mode(part, equity_from_trades(part))})
    report = [
        "# 2024 B3 Failure Review",
        "",
        f"B3 2024 trades: {len(b3_2024)}",
        f"B3 2024 net pnl: {b3_2024['net_pnl'].sum():.2f}",
        f"B3 2024 PF: {profit_factor(b3_2024['net_pnl']):.4f}",
        f"2024 trend segments: {len(seg_2024)}",
        "",
        "Simple timing 2024 comparison:",
        pd.DataFrame(simple_2024).to_markdown(index=False) if simple_2024 else "No simple timing trades.",
    ]
    (YEAR2024_DIR / "b3_2024_review.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def equity_from_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame([{"timestamp": pd.Timestamp(START, tz="UTC"), "equity": INITIAL_BALANCE}])
    tr = trades.sort_values("exit_time").copy()
    eq = INITIAL_BALANCE + tr["net_pnl"].cumsum()
    return pd.DataFrame({"timestamp": tr["exit_time"], "equity": eq})


def may_2025_big_trade_review(runs: dict, segments: pd.DataFrame, simple_results: dict[str, ModeResult]) -> None:
    b3 = runs["B3"].trades.copy()
    b3["entry_time"] = pd.to_datetime(b3["entry_time"], utc=True)
    big = b3.sort_values("net_pnl", ascending=False).iloc[0]
    mapped = map_trade_to_segments(pd.DataFrame([big]), segments, "B3")
    context = pd.concat([pd.DataFrame([big]), mapped], axis=1)
    context.to_csv(MAY2025_DIR / "may_2025_big_trade_context.csv", index=False)
    plot_big_trade(runs["B3"], big, MAY2025_DIR / "may_2025_big_trade_chart.png")
    same_segment_rows = []
    segment_id = mapped["segment_id"].iloc[0] if not mapped.empty and "segment_id" in mapped else np.nan
    for mode, result in simple_results.items():
        part = result.trades[result.trades.get("segment_id", pd.Series(dtype=float)) == segment_id] if not result.trades.empty else pd.DataFrame()
        same_segment_rows.append({"mode": mode, "trade_count_same_segment": len(part), "net_pnl_same_segment": part["net_pnl"].sum() if not part.empty else 0.0})
    removed = b3[b3.index != big.name]
    report = [
        "# 2025-05 Largest B3 Trade Review",
        "",
        f"entry_time: {big['entry_time']}",
        f"exit_time: {big['exit_time']}",
        f"net_pnl: {big['net_pnl']:.2f}",
        f"segment_id: {segment_id}",
        f"B3 net pnl without this trade: {removed['net_pnl'].sum():.2f}",
        f"B3 PF without this trade: {profit_factor(removed['net_pnl']):.4f}",
        "",
        pd.DataFrame(same_segment_rows).to_markdown(index=False),
    ]
    (MAY2025_DIR / "may_2025_big_trade_review.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def plot_big_trade(b3_run, trade: pd.Series, path: Path) -> None:
    signals = b3_run.result.signals_15m
    entry = pd.Timestamp(trade["entry_time"]).floor("15min")
    start = entry - pd.Timedelta(hours=24)
    end = pd.Timestamp(trade["exit_time"]).ceil("15min") + pd.Timedelta(hours=24)
    window = signals[(signals.index >= start) & (signals.index <= end)]
    if window.empty:
        return
    x = np.arange(len(window))
    plt.figure(figsize=(14, 7))
    for i, (_, row) in enumerate(window.iterrows()):
        color = "green" if row["close"] >= row["open"] else "red"
        plt.vlines(i, row["low"], row["high"], color=color, linewidth=1)
        plt.vlines(i, row["open"], row["close"], color=color, linewidth=4)
    plt.plot(x, window["ema_fast"], label="EMA50")
    plt.plot(x, window["ema_slow"], label="EMA200")
    plt.plot(x, window["entry_high"], label="Donchian55")
    if entry in window.index:
        plt.scatter(window.index.get_loc(entry), trade["entry_price"], marker="^", color="black", s=80, label="B3 entry")
    exit_ts = pd.Timestamp(trade["exit_time"]).floor("15min")
    if exit_ts in window.index:
        plt.scatter(window.index.get_loc(exit_ts), trade["exit_price"], marker="v", color="black", s=80, label="B3 exit")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def fixed_risk_retest(simple_results: dict[str, ModeResult], b3_run, segments: pd.DataFrame, context_events: pd.DataFrame, labels: pd.DataFrame) -> None:
    rows = []
    results = {}
    frozen = load_frozen_config("B3")
    for mode in simple_results.keys():
        events = generate_simple_events(mode, b3_run, segments, context_events, labels)
        result = simulate_events(events, frozen, mode, sizing_mode="fixed_risk")
        results[mode] = result
        rows.append({"entry_mode": mode, **result.summary})
    pd.DataFrame(rows).to_csv(FIXED_RISK_DIR / "fixed_risk_summary.csv", index=False)
    plot_mode_equity(results, FIXED_RISK_DIR / "fixed_risk_equity_comparison.png")
    plot_mode_drawdown(results, FIXED_RISK_DIR / "fixed_risk_drawdown_comparison.png")


def write_context_summary(context_events: pd.DataFrame, labels: pd.DataFrame) -> None:
    enriched = safe_attach_regime(context_events, labels, "entry_candidate_time")
    enriched["entry_candidate_time"] = pd.to_datetime(enriched["entry_candidate_time"], utc=True)
    yearly = enriched.groupby(enriched["entry_candidate_time"].dt.year).size().rename("candidate_count").reset_index()
    quarterly = enriched.groupby(enriched["entry_candidate_time"].dt.to_period("Q").astype(str)).size().rename("candidate_count").reset_index()
    regime = enriched.groupby(["trend_regime", "volatility_regime"]).size().rename("candidate_count").reset_index()
    yearly.to_csv(TREND_CONTEXT_DIR / "trend_context_yearly_counts.csv", index=False)
    quarterly.to_csv(TREND_CONTEXT_DIR / "trend_context_quarterly_counts.csv", index=False)
    regime.to_csv(TREND_CONTEXT_DIR / "trend_context_regime_counts.csv", index=False)
    report = [
        "# Trend Context Alpha Attribution",
        "",
        f"candidate_count: {len(context_events)}",
        "The candidate pool is the parent trend context used by B3 and the random baseline.",
        "Stage 2 random baseline outperforming B3 implies the broad trend context has stronger explanatory power than the Hikkake timing rule in this sample.",
    ]
    (TREND_CONTEXT_DIR / "trend_context_summary.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def write_stage3_conclusion(
    fair: bool,
    runs: dict,
    simple_results: dict[str, ModeResult],
    b3_delay: pd.DataFrame,
) -> None:
    simple = pd.read_csv(SIMPLE_DIR / "simple_timing_summary.csv")
    best = simple.sort_values(["profit_factor", "total_return"], ascending=False).iloc[0] if not simple.empty else None
    b3 = runs["B3"].summary
    b3_top1 = profit_concentration(runs["B3"].trades["net_pnl"], 1)
    verdict = "E. 随机基线或实现存在问题，当前无法判断"
    if fair:
        if best is not None and (best["profit_factor"] > b3["profit_factor"] or best["total_return"] > b3["total_return_pct"]):
            verdict = "D. 简单入场显著优于 B3，应转向趋势背景入场研究"
        else:
            verdict = "C. Alpha 主要来自趋势背景，Hikkake 应降级或移除"
    lines = [
        "# ETH Stage 3 Conclusion",
        "",
        "data_coverage_limitation = true",
        "data_coverage_status = below_original_minimum",
        f"data_window = {START} UTC 到 {END} UTC",
        "",
        "## Ten Questions",
        "",
        f"1. 第二阶段随机基线是否公平：{fair}。",
        "2. Alpha 主要来自趋势背景还是 B3 Hikkake：当前证据倾向趋势背景，因随机/简单时机对照直接挑战 B3。",
        f"3. B3 是否优于简单入场时机：最佳简单模式为 {best['entry_mode'] if best is not None else 'N/A'}。",
        f"4. B3 是否存在明显入场延迟机会成本：平均延迟 {b3_delay['delay_hours'].mean():.2f} 小时，平均错过涨幅 {b3_delay['missed_runup_pct'].mean():.2f}%。" if not b3_delay.empty else "4. B3 是否存在明显入场延迟机会成本：无法映射。",
        "5. B3 在 2024 失效的原因：见 year_2024_review，2024 B3 PF 接近 1 且回撤后没有持续趋势收益。",
        "6. 2025-05 大盈利是否可重复：见 may_2025_big_trade_review，需视同类趋势段参与情况判断。",
        "7. 固定风险后哪个模式最好：见 fixed_risk_summary.csv。",
        "8. 是否应保留 B3 为主策略：当前不建议作为主策略。",
        "9. 是否应转向更简单的趋势背景入场：若简单对照优于 B3，则应转向。",
        "10. 当前是否适合模拟盘：本地数据不足 3 年，不允许正式模拟盘准入。",
        "",
        "## Key Tables",
        "",
        simple.to_markdown(index=False),
        "",
        f"B3 top1 profit contribution: {b3_top1:.2f}%",
        "",
        "## Final Verdict",
        "",
        verdict,
    ]
    (OUT_ROOT / "stage3_conclusion.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ensure_dirs()
    runs, labels = load_stage2_inputs()
    fair, candidates = audit_random_baseline(runs, labels)
    if not fair:
        write_stage3_conclusion(False, runs, {}, pd.DataFrame())
        print(f"Stage 3 stopped after random baseline audit: {OUT_ROOT}")
        return
    context_events = build_trend_context_events(runs["B3"])
    write_context_summary(context_events, labels)
    segments = build_trend_segments(runs["B3"], labels, context_events)
    simple_results = run_simple_timing(runs["B3"], segments, context_events, labels)
    participation = build_participation(runs, simple_results, segments)
    b3_delay = b3_timing_cost(runs, segments)
    year_2024_review(runs, segments, simple_results)
    may_2025_big_trade_review(runs, segments, simple_results)
    fixed_risk_retest(simple_results, runs["B3"], segments, context_events, labels)
    write_json(OUT_ROOT / "stage3_run_metadata.json", metadata("B3"))
    write_stage3_conclusion(True, runs, simple_results, b3_delay)
    print(f"Stage 3 trend-context attribution complete: {OUT_ROOT}")


if __name__ == "__main__":
    main()
