"""RB2 low-leverage ETH/BTC P4-only portfolio validation."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from research_core.common import RESEARCH_ROOT, append_run_log, current_git_commit, file_sha256, stable_hash
from research_core.high_leverage_gate_analysis import gate_mask_fixed, high_risk_mask_fixed
from research_core.leverage_research_analysis import INITIAL_BALANCE, profit_factor
from research_core.minimal_backtest_analysis import longest_drawdown_duration, max_drawdown, top_profit_contribution
from research_core.run_realistic_replay_10_symbol import (
    build_gate_events,
    build_symbol_events,
    data_quality_row,
)
from research_core.run_long_history_10_symbol_review import DATA_ROOT, END_UTC, START_UTC, annualized_return, coverage_status
from research_core.long_history_validation_analysis import build_lh1_scores
from research_core.strict_high_leverage_replay import strict_replay_events, strict_summary


RB2_SYMBOLS = ["ETHUSDT", "BTCUSDT"]
PROTOTYPE = "P4_BREAKOUT_TOP20"
GATES = ["P4_NO_GATE", "P4_G1_GATE"]
LEVERAGE_MODES = ["fixed_1x", "fixed_2x", "fixed_3x", "adaptive_1x_3x_v1", "adaptive_1x_5x_v1"]
OUT = RESEARCH_ROOT / "rb2_low_leverage_portfolio"


def select_gate_events(proto: pd.DataFrame, gate: str, gate_factors: pd.DataFrame, gate_thresholds: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if gate == "P4_NO_GATE":
        return proto.assign(gate_high_risk=False).copy(), "usable"
    high_risk = high_risk_mask_fixed(proto, gate_factors, gate_thresholds, PROTOTYPE) if not proto.empty else pd.Series(dtype=bool)
    proto = proto.assign(gate_high_risk=high_risk)
    mask, status = gate_mask_fixed(proto, gate_factors, gate_thresholds, PROTOTYPE, "G1_SINGLE_BEST_PATH_SAFETY")
    return proto.loc[mask].copy(), status


def rb2_summary_row(
    symbol: str,
    gate: str,
    leverage_mode: str,
    data_start: pd.Timestamp,
    data_end: pd.Timestamp,
    trades: pd.DataFrame,
    equity: pd.DataFrame,
) -> dict:
    summary = strict_summary(trades, equity)
    summary["annualized_return"] = annualized_return(summary["final_equity"], data_start, data_end)
    if not trades.empty:
        summary["longest_drawdown_duration"] = longest_drawdown_duration(equity)
    return {
        "symbol": symbol,
        "prototype": PROTOTYPE,
        "gate": gate,
        "leverage_mode": leverage_mode,
        "trade_count": summary["trade_count"],
        "total_return": summary["total_return"],
        "annualized_return": summary["annualized_return"],
        "max_drawdown": summary["max_drawdown"],
        "profit_factor": summary["profit_factor"],
        "win_rate": summary["win_rate"],
        "avg_win": summary["avg_win"],
        "avg_loss": summary["avg_loss"],
        "payoff_ratio": summary["payoff_ratio"],
        "final_equity": summary["final_equity"],
        "top1_profit_contribution": summary["top1_profit_contribution"],
        "top3_profit_contribution": summary["top3_profit_contribution"],
        "longest_drawdown_duration": summary["longest_drawdown_duration"],
        "liquidation_count": summary["liquidation_count"],
        "atr_stop_count": summary["atr_stop_count"],
        "donchian20_exit_count": summary["donchian20_exit_count"],
    }


def period_summary(trades_by_key: dict[tuple[str, str, str], pd.DataFrame], freq: str) -> pd.DataFrame:
    rows = []
    for (symbol, gate, leverage_mode), trades in trades_by_key.items():
        if trades.empty:
            continue
        work = trades.copy()
        work["exit_time"] = pd.to_datetime(work["exit_time"], utc=True)
        work["period"] = work["exit_time"].dt.to_period(freq)
        for period, part in work.groupby("period"):
            pnl = part["net_pnl"].astype(float)
            curve = pd.DataFrame({"equity": INITIAL_BALANCE + pnl.cumsum()})
            if freq == "Y":
                year = int(str(period))
                quarter = ""
                sample_status = "partial_year" if year == 2026 else ("insufficient_sample" if len(part) < 10 else "valid")
            else:
                year = int(str(period)[:4])
                quarter = str(period)
                sample_status = "partial_year" if str(period).startswith("2026") else ("insufficient_sample" if len(part) < 10 else "valid")
            rows.append({
                "symbol": symbol,
                "prototype": PROTOTYPE,
                "gate": gate,
                "leverage_mode": leverage_mode,
                "year": year,
                "quarter": quarter,
                "trade_count": int(len(part)),
                "return": float(pnl.sum() / INITIAL_BALANCE),
                "profit_factor": profit_factor(pnl),
                "max_drawdown": max_drawdown(curve),
                "win_rate": float((pnl > 0).mean()) if len(part) else np.nan,
                "sample_status": sample_status,
            })
    return pd.DataFrame(rows)


def combine_equal_weight(equities: list[pd.DataFrame]) -> pd.DataFrame:
    if len(equities) != 2:
        return pd.DataFrame()
    frames = []
    for i, eq in enumerate(equities):
        part = eq[["time", "equity"]].copy()
        part["time"] = pd.to_datetime(part["time"], utc=True)
        part = part.drop_duplicates("time").set_index("time").sort_index()
        part[f"component_{i}"] = part["equity"] / INITIAL_BALANCE
        frames.append(part[[f"component_{i}"]])
    union = frames[0].join(frames[1], how="outer").sort_index().ffill().fillna(1.0)
    out = pd.DataFrame({
        "time": union.index,
        "equity": union.mean(axis=1) * INITIAL_BALANCE,
    })
    return out.reset_index(drop=True)


def portfolio_summary(equity_map: dict[tuple[str, str, str], pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for gate in GATES:
        for leverage_mode in LEVERAGE_MODES:
            key_eth = ("ETHUSDT", gate, leverage_mode)
            key_btc = ("BTCUSDT", gate, leverage_mode)
            combined = combine_equal_weight([equity_map[key_eth], equity_map[key_btc]])
            if combined.empty:
                continue
            rows.append({
                "portfolio": "ETH_BTC_EQUAL_WEIGHT",
                "prototype": PROTOTYPE,
                "gate": gate,
                "leverage_mode": leverage_mode,
                "component_symbols": "ETHUSDT,BTCUSDT",
                "total_return": float(combined["equity"].iloc[-1] / INITIAL_BALANCE - 1),
                "max_drawdown": max_drawdown(combined["equity"]),
                "final_equity": float(combined["equity"].iloc[-1]),
                "longest_drawdown_duration": longest_drawdown_duration(combined),
            })
            combined.to_csv(OUT / "rb2_equity_curves" / f"PORTFOLIO_{gate}_{leverage_mode}_equity.csv", index=False)
    return pd.DataFrame(rows)


def plot_equity_curves(equity_map: dict[tuple[str, str, str], pd.DataFrame], path: Path) -> None:
    plt.figure(figsize=(13, 7))
    for (symbol, gate, mode), eq in equity_map.items():
        if mode not in {"fixed_2x", "adaptive_1x_3x_v1"}:
            continue
        plt.plot(pd.to_datetime(eq["time"], utc=True), eq["equity"], label=f"{symbol} {gate} {mode}", linewidth=0.9)
    plt.yscale("log")
    plt.legend(fontsize=7)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def build_windows(start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    windows = []
    train_start = start
    window_id = 1
    while True:
        train_end = train_start + pd.DateOffset(months=24)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=6)
        if test_start >= end:
            break
        windows.append({
            "window_id": window_id,
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": min(test_end, end),
        })
        train_start = train_start + pd.DateOffset(months=6)
        window_id += 1
    return windows


def run_walk_forward(prepared: dict, gate_factors: pd.DataFrame, gate_thresholds: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for symbol, payload in prepared.items():
        data_1m = payload["data_1m"]
        data_15m = payload["data_15m"]
        proto = payload["proto"]
        windows = build_windows(data_1m.index.min(), data_1m.index.max())
        for win in windows:
            for gate in GATES:
                accepted, gate_status = select_gate_events(proto, gate, gate_factors, gate_thresholds)
                accepted = accepted[
                    (pd.to_datetime(accepted["execution_time"], utc=True) >= win["test_start"])
                    & (pd.to_datetime(accepted["execution_time"], utc=True) < win["test_end"])
                ].copy()
                data_1m_win = data_1m[(data_1m.index >= win["test_start"]) & (data_1m.index <= win["test_end"])].copy()
                data_15m_win = data_15m[(data_15m.index >= win["test_start"]) & (data_15m.index <= win["test_end"])].copy()
                for leverage_mode in LEVERAGE_MODES:
                    trades, equity, _ = strict_replay_events(accepted, data_1m_win, data_15m_win, symbol, PROTOTYPE, gate, leverage_mode)
                    summary = strict_summary(trades, equity)
                    rows.append({
                        **win,
                        "symbol": symbol,
                        "prototype": PROTOTYPE,
                        "gate": gate,
                        "gate_status": gate_status,
                        "leverage_mode": leverage_mode,
                        "trade_count": summary["trade_count"],
                        "total_return": summary["total_return"],
                        "profit_factor": summary["profit_factor"],
                        "max_drawdown": summary["max_drawdown"],
                        "sample_status": "insufficient_sample" if summary["trade_count"] < 10 else "valid",
                    })
    windows_df = pd.DataFrame(rows)
    agg = []
    for keys, part in windows_df.groupby(["symbol", "prototype", "gate", "leverage_mode"]):
        valid = part[part["sample_status"] == "valid"]
        agg.append({
            "symbol": keys[0],
            "prototype": keys[1],
            "gate": keys[2],
            "leverage_mode": keys[3],
            "window_count": int(len(part)),
            "valid_window_count": int(len(valid)),
            "positive_window_rate": float((valid["total_return"] > 0).mean()) if len(valid) else np.nan,
            "pf_gt_1_window_rate": float((valid["profit_factor"] > 1).mean()) if len(valid) else np.nan,
            "median_return": float(valid["total_return"].median()) if len(valid) else np.nan,
            "worst_return": float(valid["total_return"].min()) if len(valid) else np.nan,
            "median_pf": float(valid["profit_factor"].median()) if len(valid) else np.nan,
            "walk_forward_status": "insufficient_sample" if len(valid) == 0 else ("wf_pass" if (valid["profit_factor"] > 1).mean() >= 0.6 else "wf_weak"),
        })
    return windows_df, pd.DataFrame(agg)


def decision(summary: pd.DataFrame, wf: pd.DataFrame) -> str:
    focus = summary[
        (summary["symbol"].isin(RB2_SYMBOLS))
        & (summary["gate"] == "P4_NO_GATE")
        & (summary["leverage_mode"].isin(["fixed_2x", "adaptive_1x_3x_v1"]))
    ]
    merged = focus.merge(
        wf[["symbol", "gate", "leverage_mode", "pf_gt_1_window_rate"]],
        on=["symbol", "gate", "leverage_mode"],
        how="left",
    )
    passing = merged[
        (merged["profit_factor"] > 1.15)
        & (merged["max_drawdown"] >= -0.25)
        & (merged["top1_profit_contribution"] <= 0.30)
        & (merged["pf_gt_1_window_rate"] >= 0.60)
    ]
    if len(passing) >= 2:
        return "A. ETH/BTC P4 low leverage passes internal validation; prepare RB3 OOS/shadow validation"
    if len(passing) == 1:
        return "B. Only one of ETH/BTC passes; narrow next research to the stronger single asset"
    if (focus["profit_factor"] <= 1.05).all():
        return "D. P4 low leverage has weak expectancy after realistic repair; downgrade route"
    return "C. P4 low leverage remains a research candidate but is not ready for OOS/shadow preparation"


def write_report(summary: pd.DataFrame, portfolio: pd.DataFrame, wf: pd.DataFrame) -> None:
    lines = [
        "# RB2 Low Leverage Portfolio Report",
        "",
        "data_layer: expanded_discovery",
        "oos_status: not_oos",
        "deployable_strategy_generated: false",
        "",
        "## Conclusion",
        "",
        decision(summary, wf),
        "",
        "## Backtest Summary",
        "",
        summary[[
            "symbol",
            "gate",
            "leverage_mode",
            "trade_count",
            "total_return",
            "max_drawdown",
            "profit_factor",
            "win_rate",
            "final_equity",
            "top1_profit_contribution",
        ]].to_markdown(index=False),
        "",
        "## Portfolio Summary",
        "",
        portfolio.to_markdown(index=False),
        "",
        "## Interpretation",
        "",
        "- RB2 uses only ETH/BTC P4 and realistic candle-close time alignment.",
        "- Results remain expanded_discovery, not OOS.",
        "- If low leverage still has deep drawdown or weak walk-forward, do not move to simulation.",
    ]
    (OUT / "rb2_low_leverage_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cache_dir = OUT / "_events_cache"
    trades_dir = OUT / "rb2_trades"
    equity_dir = OUT / "rb2_equity_curves"
    for directory in [cache_dir, trades_dir, equity_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    metadata = pd.read_csv(RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv")
    discovery_scores = pd.read_parquet(RESEARCH_ROOT / "family_validation" / "family_scores.parquet")
    gate_factors = pd.read_csv(RESEARCH_ROOT / "high_leverage_gate" / "h3_gate_factors.csv")
    gate_thresholds = pd.read_csv(RESEARCH_ROOT / "high_leverage_h4_validation" / "h4_gate_fixed_thresholds.csv")

    prepared = {}
    summary_rows = []
    quality_rows = []
    trades_by_key = {}
    equity_map = {}
    data_hashes = []

    for symbol in RB2_SYMBOLS:
        data_path = DATA_ROOT / f"{symbol}.csv"
        data_1m = pd.read_csv(data_path, parse_dates=["timestamp"])
        data_1m = data_1m.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
        if data_1m.index.tz is None:
            data_1m.index = data_1m.index.tz_localize("UTC")
        else:
            data_1m.index = data_1m.index.tz_convert("UTC")
        data_1m.columns = [c.lower() for c in data_1m.columns]
        data_1m = data_1m[["open", "high", "low", "close", "volume"]]
        data_1m = data_1m[(data_1m.index >= START_UTC) & (data_1m.index <= END_UTC)].copy()
        quality_rows.append(data_quality_row(symbol, data_1m, data_path))
        data_hashes.append(file_sha256(data_path))
        events, data_15m = build_symbol_events(symbol, data_1m, cache_dir / f"{symbol}_events.parquet")
        scores, _ = build_lh1_scores(events, metadata, discovery_scores)
        gate_events = build_gate_events(symbol, events, scores, discovery_scores)
        proto = gate_events[gate_events["prototype"] == PROTOTYPE].reset_index(drop=True)
        prepared[symbol] = {"data_1m": data_1m, "data_15m": data_15m, "proto": proto}
        for gate in GATES:
            accepted, gate_status = select_gate_events(proto, gate, gate_factors, gate_thresholds)
            for leverage_mode in LEVERAGE_MODES:
                trades, equity, audit = strict_replay_events(accepted, data_1m, data_15m, symbol, PROTOTYPE, gate, leverage_mode)
                trades_by_key[(symbol, gate, leverage_mode)] = trades
                equity_map[(symbol, gate, leverage_mode)] = equity
                trades.to_csv(trades_dir / f"{symbol}_{gate}_{leverage_mode}_trades.csv", index=False)
                audit.to_csv(trades_dir / f"{symbol}_{gate}_{leverage_mode}_adaptive_audit.csv", index=False)
                equity.to_csv(equity_dir / f"{symbol}_{gate}_{leverage_mode}_equity.csv", index=False)
                summary_rows.append(rb2_summary_row(
                    symbol,
                    gate,
                    leverage_mode,
                    data_1m.index.min(),
                    data_1m.index.max(),
                    trades,
                    equity,
                ) | {"gate_status": gate_status})

    summary = pd.DataFrame(summary_rows)
    yearly = period_summary(trades_by_key, "Y")
    quarterly = period_summary(trades_by_key, "Q")
    portfolio = portfolio_summary(equity_map)
    wf_windows, wf_summary = run_walk_forward(prepared, gate_factors, gate_thresholds)

    summary.to_csv(OUT / "rb2_backtest_summary.csv", index=False)
    pd.DataFrame(quality_rows).to_csv(OUT / "rb2_data_quality.csv", index=False)
    yearly.to_csv(OUT / "rb2_yearly_summary.csv", index=False)
    quarterly.to_csv(OUT / "rb2_quarterly_summary.csv", index=False)
    portfolio.to_csv(OUT / "rb2_portfolio_summary.csv", index=False)
    wf_windows.to_csv(OUT / "rb2_walk_forward_windows.csv", index=False)
    wf_summary.to_csv(OUT / "rb2_walk_forward_summary.csv", index=False)
    plot_equity_curves(equity_map, OUT / "rb2_equity_comparison.png")
    (OUT / "rb2_invalid_vs_rb1_context.md").write_text(
        "# RB2 Invalid vs RB1 Context\n\n"
        "Old long-history results are marked time_alignment_invalid. RB2 starts from RB1 realistic candle-close time alignment and only tests ETH/BTC P4 low leverage.\n",
        encoding="utf-8",
    )
    write_report(summary, portfolio, wf_summary)
    shutil.rmtree(cache_dir, ignore_errors=True)

    append_run_log({
        "run_id": "RB2_LOW_LEVERAGE_PORTFOLIO",
        "stage": "RB2",
        "script": "research_core.run_rb2_low_leverage_portfolio",
        "config_hash": stable_hash({
            "symbols": RB2_SYMBOLS,
            "prototype": PROTOTYPE,
            "gates": GATES,
            "leverage_modes": LEVERAGE_MODES,
            "time_alignment": "realistic_candle_close_time",
        }),
        "data_hash": stable_hash(data_hashes),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": "ETH/BTC P4-only low leverage validation; no alpha rule changed; not OOS; no deployable strategy rule generated",
    })


if __name__ == "__main__":
    run()
