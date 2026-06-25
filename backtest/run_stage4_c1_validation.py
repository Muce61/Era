"""Run Stage 4 C1 engine validation with Stage 2-level checks."""

from __future__ import annotations

import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.eth_trend_engine import EthTrendEngine
from backtest.metrics import profit_concentration, profit_factor
from backtest.run_stage2_existing_data_pipeline import (
    BOOTSTRAP_RUNS,
    INITIAL_BALANCE,
    RNG_SEED,
    RANDOM_RUNS,
    START,
    END,
    Stage2Run,
    attach_regime,
    build_regime_labels,
    cost_adjusted_pf,
    full_summary,
    longest_loss_sequence,
    make_blocks,
    match_bucket,
    percentile_rank,
    period_summary,
    plot_drawdown_comparison,
    plot_equity_comparison,
    plot_distribution,
    sample_blocks,
    sample_matched_non_overlapping,
    sequence_metrics,
    simulate_exit_from_event,
    simulate_trade_sequence,
    write_json,
    yearly_summary,
)
from backtest.stage2_config import config_hash, current_git_commit, file_sha256
from backtest.stage4_config import (
    STAGE4_COMPARISON_LABELS,
    load_stage4_frozen_config,
    run_config_from_label,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "backtest_results" / "stage4"
DATA_PATH = REPO_ROOT / "backtest_results" / "stage2" / "data_audit" / "merged_ethusdt_1m.csv"
REGIME_LABELS = REPO_ROOT / "backtest_results" / "stage2" / "data_audit" / "regime_labels.csv"

AVAILABLE_DIR = OUT_ROOT / "available_history"
WALK_DIR = OUT_ROOT / "walk_forward"
RANDOM_DIR = OUT_ROOT / "random_baseline"
BOOTSTRAP_DIR = OUT_ROOT / "bootstrap"
RISK_DIR = OUT_ROOT / "risk_sizing"
REGIME_DIR = OUT_ROOT / "regime"
CHART_DIR = OUT_ROOT / "c1_audit_charts"
FROZEN_DIR = OUT_ROOT / "frozen_configs"


def ensure_dirs() -> None:
    for path in [
        OUT_ROOT,
        AVAILABLE_DIR,
        WALK_DIR,
        RANDOM_DIR,
        BOOTSTRAP_DIR,
        RISK_DIR,
        REGIME_DIR,
        CHART_DIR,
        FROZEN_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def run_label(label: str, position_sizing_mode: str | None = None) -> Stage2Run:
    frozen = load_stage4_frozen_config(label)
    config = run_config_from_label(label)
    if position_sizing_mode is not None:
        config.position_sizing_mode = position_sizing_mode
    engine = EthTrendEngine(
        config=config,
        data_path=DATA_PATH,
        symbol=frozen["symbol"],
        start_date=START,
        end_date=END,
        initial_balance=frozen["initial_balance"],
    )
    result = engine.run(verbose=False)
    trades = pd.DataFrame(result.trades)
    equity = pd.DataFrame(result.equity_curve)
    summary = full_summary(trades, equity, frozen["initial_balance"], START, END)
    return Stage2Run(label, frozen, trades, equity, summary, result)


def metadata_for_stage4_run(label: str, frozen: dict, result) -> dict:
    return {
        "label": label,
        "config_path": str(frozen.get("_config_path", "")),
        "config_hash": config_hash(frozen),
        "git_commit": current_git_commit(),
        "data_start": str(result.data_1m.index[0]),
        "data_end": str(result.data_1m.index[-1]),
        "data_file": str(DATA_PATH),
        "data_file_hash": file_sha256(DATA_PATH),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_coverage_status": "below_original_minimum",
    }


def segment_bar_times(signals: pd.DataFrame) -> list[pd.Timestamp]:
    times: list[pd.Timestamp] = []
    in_segment = False
    for ts, row in signals.iterrows():
        trend_breakout = row["close"] > row["entry_high"] and row["ema_fast"] > row["ema_slow"]
        still_valid = row["ema_fast"] > row["ema_slow"] and row["close"] >= row["exit_low"]
        if not in_segment and trend_breakout:
            in_segment = True
        if in_segment:
            times.append(ts)
            if not still_valid:
                in_segment = False
    return times


def precompute_c1_random_candidates(c1_run: Stage2Run) -> pd.DataFrame:
    data_1m = c1_run.result.data_1m
    signals = c1_run.result.signals_15m
    cfg = c1_run.result.config
    candidate_times = segment_bar_times(signals)
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


def run_random_baseline_c1(c1_run: Stage2Run, labels: pd.DataFrame) -> None:
    rng = random.Random(RNG_SEED)
    candidates = attach_regime(precompute_c1_random_candidates(c1_run), labels, "entry_time")
    candidates.to_csv(RANDOM_DIR / "candidate_pool.csv", index=False)
    c1 = c1_run.trades.copy()
    if c1.empty or candidates.empty:
        pd.DataFrame().to_csv(RANDOM_DIR / "random_runs.csv", index=False)
        return
    c1["entry_time"] = pd.to_datetime(c1["entry_time"], utc=True)
    c1 = attach_regime(c1, labels, "entry_time")
    c1["match_bucket"] = match_bucket(c1)
    candidates["match_bucket"] = match_bucket(candidates)
    bucket_counts = c1["match_bucket"].value_counts().to_dict()
    target_n = len(c1)
    runs = []
    selected_examples = []
    for run_id in range(1, RANDOM_RUNS + 1):
        sampled = sample_matched_non_overlapping(candidates, bucket_counts, target_n, rng)
        metrics = simulate_trade_sequence(sampled, c1_run.frozen)
        runs.append({"run_id": run_id, "matched_trade_count": int(len(sampled) == target_n), **metrics})
        if run_id == 1:
            selected_examples = sampled.to_dict("records")
    random_df = pd.DataFrame(runs)
    random_df.to_csv(RANDOM_DIR / "random_runs.csv", index=False)
    pd.DataFrame(selected_examples).to_csv(RANDOM_DIR / "sampled_events_run1.csv", index=False)

    c1_metrics = {
        "total_return": c1_run.summary.get("total_return_pct", 0.0),
        "profit_factor": c1_run.summary.get("profit_factor", 0.0),
        "max_drawdown": c1_run.summary.get("max_drawdown_pct", 0.0),
        "calmar": c1_run.summary.get("calmar", 0.0),
        "avg_mae_atr": float(c1["mae_atr"].mean()) if "mae_atr" in c1 else 0.0,
        "avg_mfe_atr": float(c1["mfe_atr"].mean()) if "mfe_atr" in c1 else 0.0,
        "top5_profit_contribution": profit_concentration(c1["net_pnl"], 5),
    }
    pct = {
        "return_percentile": percentile_rank(random_df["total_return"], c1_metrics["total_return"]),
        "pf_percentile": percentile_rank(random_df["profit_factor"], c1_metrics["profit_factor"]),
        "drawdown_percentile": percentile_rank(-random_df["max_drawdown"], -c1_metrics["max_drawdown"]),
        "calmar_percentile": percentile_rank(random_df["calmar"], c1_metrics["calmar"]),
        "mfe_mae_percentile": percentile_rank(
            random_df["avg_mfe_atr"] / random_df["avg_mae_atr"].abs().replace(0, np.nan),
            c1_metrics["avg_mfe_atr"] / abs(c1_metrics["avg_mae_atr"]) if c1_metrics["avg_mae_atr"] else np.nan,
        ),
        "c1_trade_count": int(len(c1)),
        "candidate_count": int(len(candidates)),
        "random_runs": RANDOM_RUNS,
        "exact_trade_count_match_rate": float(random_df["matched_trade_count"].mean()),
        "low_sample_random_baseline": bool(len(c1) < 100),
    }
    pd.DataFrame([{**c1_metrics, **pct}]).to_csv(RANDOM_DIR / "percentile_summary.csv", index=False)
    plot_distribution(
        random_df["total_return"], c1_metrics["total_return"],
        RANDOM_DIR / "return_distribution.png", "Random Total Return",
    )
    plot_distribution(
        random_df["profit_factor"].replace(np.inf, np.nan).dropna(), c1_metrics["profit_factor"],
        RANDOM_DIR / "pf_distribution.png", "Random Profit Factor",
    )
    plot_distribution(
        random_df["max_drawdown"], c1_metrics["max_drawdown"],
        RANDOM_DIR / "drawdown_distribution.png", "Random Max Drawdown",
    )


def run_bootstrap_c1(c1_run: Stage2Run) -> None:
    rng = np.random.default_rng(RNG_SEED)
    trades = c1_run.trades.copy()
    if trades.empty:
        return
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
    pnl = trades["net_pnl"].to_numpy(float)
    summary_rows = []
    removal_rows = []
    stress_rows = []
    label = "C1"
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
            "median_pf": float(sim_df["profit_factor"].replace(np.inf, -np.inf).median()),
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


def run_cost_stress(runs: dict[str, Stage2Run]) -> None:
    rows = []
    for label, run in runs.items():
        trades = run.trades
        if trades.empty:
            continue
        for mult, name in [(1.0, "C1"), (1.5, "C1_1p5x"), (2.0, "C2_2x")]:
            pf = cost_adjusted_pf(trades, mult)
            extra = trades["total_fee"] * (mult - 1)
            net_adj = trades["net_pnl"] - extra
            ret = float(net_adj.sum() / INITIAL_BALANCE * 100)
            rows.append({
                "label": label,
                "cost_scenario": name,
                "cost_multiplier": mult,
                "total_return_pct": ret,
                "profit_factor": pf,
                "trade_count": len(trades),
            })
    pd.DataFrame(rows).to_csv(OUT_ROOT / "cost_stress_summary.csv", index=False)


def run_risk_sizing() -> None:
    rows = []
    for label in ["C1", "B1", "B3"]:
        for mode_name, sizing_mode in [("fixed_2x", None), ("fixed_risk", "fixed_risk")]:
            run = run_label(label, position_sizing_mode=sizing_mode)
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
    pd.DataFrame(rows).to_csv(RISK_DIR / "fixed_risk_summary.csv", index=False)


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


def run_walk_forward_stage4() -> None:
    rows = []
    equity_parts = []
    start = pd.Timestamp(START, tz="UTC")
    end = pd.Timestamp(END, tz="UTC")
    test_start = start + pd.DateOffset(months=12)
    window_id = 1
    while test_start < end:
        test_end = min(test_start + pd.DateOffset(months=3) - pd.Timedelta(minutes=1), end)
        partial = test_end < test_start + pd.DateOffset(months=3) - pd.Timedelta(minutes=1)
        for label in STAGE4_COMPARISON_LABELS:
            frozen = load_stage4_frozen_config(label)
            config = run_config_from_label(label)
            engine = EthTrendEngine(
                config=config,
                data_path=DATA_PATH,
                symbol=frozen["symbol"],
                start_date=str(test_start),
                end_date=str(test_end),
                initial_balance=frozen["initial_balance"],
            )
            result = engine.run(verbose=False)
            trades = pd.DataFrame(result.trades)
            equity = pd.DataFrame(result.equity_curve)
            summary = full_summary(trades, equity, frozen["initial_balance"], str(test_start), str(test_end))
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
                "entry_mode": frozen["entry_mode"],
                "label": label,
                "trade_count": int(len(trades)),
                "total_return": summary.get("total_return_pct", 0.0),
                "profit_factor": summary.get("profit_factor", 0.0),
                "max_drawdown": summary.get("max_drawdown_pct", 0.0),
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
        plt.figure(figsize=(12, 6))
        for (label, window_id), part in eq_all.groupby(["label", "window_id"]):
            part = part.copy()
            part["timestamp"] = pd.to_datetime(part["timestamp"], utc=True)
            plt.plot(part["timestamp"], part["equity"], label=f"{label} w{window_id}", alpha=0.7)
        plt.title("Stage 4 Walk-forward Equity")
        plt.legend(fontsize=7)
        plt.tight_layout()
        plt.savefig(WALK_DIR / "walk_forward_equity.png", dpi=160)
        plt.close()


def _to_utc_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def plot_c1_audit_charts(c1_run: Stage2Run, max_charts: int = 20) -> None:
    trades = c1_run.trades.copy()
    if trades.empty:
        return
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], utc=True)
    trades = trades.sort_values("entry_time").reset_index(drop=True)
    audit_rows = []
    n = min(len(trades), max_charts)
    for trade_id in range(n):
        trade = trades.iloc[trade_id]
        signals = c1_run.result.signals_15m
        segment_start = trade.get("segment_start_time")
        if segment_start is not None and not (isinstance(segment_start, float) and np.isnan(segment_start)):
            seg_ts = _to_utc_timestamp(segment_start)
        else:
            seg_ts = trade["entry_time"].floor("15min")
        if seg_ts not in signals.index:
            continue
        idx = signals.index.get_loc(seg_ts)
        window = signals.iloc[max(0, idx - 10): min(len(signals), idx + 41)].copy()
        x = np.arange(len(window))
        plt.figure(figsize=(14, 7))
        for i, (_, row) in enumerate(window.iterrows()):
            color = "green" if row["close"] >= row["open"] else "red"
            plt.vlines(i, row["low"], row["high"], color=color, linewidth=1)
            plt.vlines(i, row["open"], row["close"], color=color, linewidth=5)
        plt.plot(x, window["ema_fast"], label="EMA50", color="blue", linewidth=1)
        plt.plot(x, window["ema_slow"], label="EMA200", color="purple", linewidth=1)
        plt.plot(x, window["entry_high"], label="Donchian55 upper", color="orange", linewidth=1)
        entry_15m = trade["entry_time"].floor("15min")
        signal_bar = seg_ts
        entry_matches = entry_15m == signal_bar or entry_15m == signal_bar + pd.Timedelta(minutes=15)
        if entry_15m in window.index:
            plt.scatter(window.index.get_loc(entry_15m), trade["entry_price"], marker="^", s=80, label="entry", color="black")
        if seg_ts in window.index:
            plt.axvline(window.index.get_loc(seg_ts), linestyle="--", linewidth=1, label="segment_start")
        plt.title(f"C1 Audit Trade {trade_id + 1}")
        plt.legend(fontsize=8)
        plt.tight_layout()
        plt.savefig(CHART_DIR / f"c1_trade_{trade_id + 1:04d}.png", dpi=150)
        plt.close()
        audit_rows.append({
            "trade_id": trade_id + 1,
            "entry_time": trade["entry_time"],
            "segment_start_time": seg_ts,
            "entry_matches_segment_start": entry_matches,
            "net_pnl": trade["net_pnl"],
        })
    pd.DataFrame(audit_rows).to_csv(CHART_DIR / "c1_manual_audit.csv", index=False)


def write_conclusion(runs: dict[str, Stage2Run]) -> None:
    available = pd.read_csv(AVAILABLE_DIR / "full_history_summary.csv")
    rand = pd.read_csv(RANDOM_DIR / "percentile_summary.csv") if (RANDOM_DIR / "percentile_summary.csv").exists() else pd.DataFrame()
    boot = pd.read_csv(BOOTSTRAP_DIR / "bootstrap_summary.csv") if (BOOTSTRAP_DIR / "bootstrap_summary.csv").exists() else pd.DataFrame()
    wf = pd.read_csv(WALK_DIR / "walk_forward_aggregate.csv") if (WALK_DIR / "walk_forward_aggregate.csv").exists() else pd.DataFrame()
    risk = pd.read_csv(RISK_DIR / "fixed_risk_summary.csv") if (RISK_DIR / "fixed_risk_summary.csv").exists() else pd.DataFrame()
    cost = pd.read_csv(OUT_ROOT / "cost_stress_summary.csv") if (OUT_ROOT / "cost_stress_summary.csv").exists() else pd.DataFrame()

    c1_row = available[available["label"] == "C1"].iloc[0] if (available["label"] == "C1").any() else None
    b0_row = available[available["label"] == "B0"].iloc[0] if (available["label"] == "B0").any() else None
    b3_row = available[available["label"] == "B3"].iloc[0] if (available["label"] == "B3").any() else None
    c1_rand = rand.iloc[0] if not rand.empty else None
    c1_boot = boot[(boot["label"] == "C1") & (boot["method"] == "trade")].iloc[0] if not boot.empty and ((boot["label"] == "C1") & (boot["method"] == "trade")).any() else None
    c1_wf = wf[wf["label"] == "C1"].iloc[0] if not wf.empty and (wf["label"] == "C1").any() else None
    c1_cost_2x = cost[(cost["label"] == "C1") & (cost["cost_scenario"] == "C2_2x")].iloc[0] if not cost.empty and ((cost["label"] == "C1") & (cost["cost_scenario"] == "C2_2x")).any() else None

    verdict = "B. C1 优于 B 系列但需继续验证"
    if c1_row is not None and b0_row is not None:
        trade_diff = abs(c1_row["total_trades"] - b0_row["total_trades"]) / max(b0_row["total_trades"], 1)
        pf_close = abs(c1_row["profit_factor"] - b0_row["profit_factor"]) < 0.05
        if trade_diff < 0.10 and pf_close:
            verdict = "C. C1 与 B0 接近，阶段3优势来自口径差异而非新 alpha"
    if c1_row is not None and float(c1_row["profit_factor"]) < 1.0:
        verdict = "D. C1 未通过阶段2级检验（全样本 PF<1，Bootstrap 多数 PF<1）"
    if c1_rand is not None and (c1_rand.get("return_percentile", 0) < 50 or c1_rand.get("pf_percentile", 0) < 50):
        verdict = "D. C1 未显著优于匹配随机基线"
    if (
        c1_row is not None and c1_rand is not None and c1_boot is not None and c1_cost_2x is not None
        and c1_rand.get("return_percentile", 0) >= 50
        and c1_rand.get("pf_percentile", 0) >= 50
        and c1_boot.get("pf_lt_1_probability", 1) < 0.10
        and c1_cost_2x.get("profit_factor", 0) > 1
        and b3_row is not None
        and c1_row["profit_factor"] > b3_row["profit_factor"]
    ):
        verdict = "A. C1 可作为候选主策略（仍待 3 年数据模拟盘）"

    lines = [
        "# ETH Stage 4 Conclusion",
        "",
        "data_coverage_limitation = true",
        "data_coverage_status = below_original_minimum",
        f"data_window = {START} UTC 到 {END} UTC",
        "",
        "## Comparison (engine, fixed 2x)",
        "",
        available[["label", "total_trades", "total_return_pct", "max_drawdown_pct", "profit_factor"]].to_markdown(index=False),
        "",
        "## Random Baseline (C0' matched to C1 trade count)",
        "",
    ]
    if not rand.empty:
        lines.append(rand.to_markdown(index=False))
    else:
        lines.append("No random baseline output.")
    lines.extend([
        "",
        "## Bootstrap C1 trade-level",
        "",
    ])
    if not boot.empty:
        lines.append(boot.to_markdown(index=False))
    lines.extend([
        "",
        f"## Final Verdict",
        "",
        verdict,
        "",
        "模拟盘：本地数据不足 3 年，不允许正式模拟盘准入。",
    ])
    (OUT_ROOT / "stage4_conclusion.md").write_text("\n".join(lines), encoding="utf-8")


def run_available_history() -> dict[str, Stage2Run]:
    runs: dict[str, Stage2Run] = {}
    rows = []
    data_hash = file_sha256(DATA_PATH)
    for label in STAGE4_COMPARISON_LABELS:
        run = run_label(label)
        runs[label] = run
        out_dir = AVAILABLE_DIR / label
        out_dir.mkdir(parents=True, exist_ok=True)
        run.trades.to_csv(out_dir / "trades.csv", index=False)
        run.equity.to_csv(out_dir / "equity.csv", index=False)
        frozen = dict(run.frozen)
        frozen["_config_path"] = str(FROZEN_DIR / label)
        meta = metadata_for_stage4_run(label, frozen, run.result)
        write_json(out_dir / "run_metadata.json", meta)
        rows.append({"label": label, "entry_mode": run.frozen["entry_mode"], **meta, **run.summary})

    summary = pd.DataFrame(rows)
    summary.to_csv(AVAILABLE_DIR / "full_history_summary.csv", index=False)
    yearly_summary(runs).to_csv(AVAILABLE_DIR / "yearly_summary.csv", index=False)
    period_summary(runs, "Q").to_csv(AVAILABLE_DIR / "quarterly_summary.csv", index=False)
    plot_equity_comparison(runs, AVAILABLE_DIR / "equity_comparison.png")
    plot_drawdown_comparison(runs, AVAILABLE_DIR / "drawdown_comparison.png")
    return runs


def main() -> None:
    ensure_dirs()
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Merged data not found: {DATA_PATH}. Run stage2 data audit first.")
    labels = pd.read_csv(REGIME_LABELS, parse_dates=["timestamp"]) if REGIME_LABELS.exists() else build_regime_labels(DATA_PATH)

    runs = run_available_history()
    run_walk_forward_stage4()
    c1_run = runs["C1"]
    run_random_baseline_c1(c1_run, labels)
    run_bootstrap_c1(c1_run)
    run_cost_stress(runs)
    run_risk_sizing()
    run_regime_analysis(runs, labels)
    plot_c1_audit_charts(c1_run)
    write_conclusion(runs)

    write_json(OUT_ROOT / "stage4_run_metadata.json", {
        "data_start": START,
        "data_end": END,
        "data_file": str(DATA_PATH),
        "data_file_hash": file_sha256(DATA_PATH),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_coverage_status": "below_original_minimum",
    })
    print(f"Stage 4 complete. Outputs: {OUT_ROOT}")


if __name__ == "__main__":
    main()
