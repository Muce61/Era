"""Run B0 (NO_CANDLE) vs B1 (STRONG_BREAKOUT) comparison for stage 3."""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.eth_trend_engine import EthTrendEngine
from backtest.run_stage1_experiments import run_experiment
from strategy.eth_trend_signals import EntryMode, StrategyConfig, load_ohlcv_1m

DEFAULT_DATA_PATH = Path("/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv")
DEFAULT_START = "2024-12-01 00:00:00"
DEFAULT_END = "2025-12-12 20:00:00"
RESULTS_ROOT = Path("backtest_results/stage3")

BASELINES = {
    "B0": (EntryMode.NO_CANDLE, RESULTS_ROOT / "baseline_B0"),
    "B1": (EntryMode.STRONG_BREAKOUT, RESULTS_ROOT / "baseline_B1"),
}


def extended_metrics(trades_df: pd.DataFrame, summary: dict) -> dict:
    pnl = trades_df["net_pnl"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else math.inf

    return {
        "total_return": round(summary["total_return_pct"], 2),
        "max_drawdown": round(summary.get("max_drawdown_pct", 0.0), 2),
        "profit_factor": round(summary["profit_factor"], 2),
        "win_rate": round(summary["win_rate_pct"], 2),
        "trade_count": int(summary["total_trades"]),
        "avg_trade": round(summary["average_trade"], 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "payoff_ratio": round(payoff_ratio, 2) if payoff_ratio != math.inf else math.inf,
        "final_balance": round(summary["final_balance"], 2),
    }


def buy_hold_return(data_path: Path, start_date: str, end_date: str) -> float:
    from strategy.eth_trend_signals import build_signal_frame

    data = load_ohlcv_1m(data_path, start_date, end_date)
    config = StrategyConfig(entry_mode=EntryMode.NO_CANDLE)
    signals = build_signal_frame(data, config)
    warmup_start = signals.index[0]
    window = data.loc[warmup_start:]
    start_price = float(window.iloc[0]["open"])
    end_price = float(window.iloc[-1]["close"])
    return (end_price / start_price - 1) * 100


def main():
    summaries = {}
    metrics_by_label = {}

    for label, (mode, out_dir) in BASELINES.items():
        print(f"\n>>> Running {label} ({mode.value})")
        summary = run_experiment(mode, out_dir, verbose=True)
        trades_df = pd.read_csv(out_dir / "trades.csv")
        extended = extended_metrics(trades_df, summary)
        metrics_by_label[label] = extended
        summaries[label] = summary

        with open(out_dir / "metrics.json", "w") as f:
            json.dump({**summary, **extended}, f, indent=2)

    comparison = pd.DataFrame(metrics_by_label).T
    comparison.index.name = "baseline"
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(RESULTS_ROOT / "b0_b1_comparison.csv")
    with open(RESULTS_ROOT / "b0_b1_comparison.json", "w") as f:
        json.dump(metrics_by_label, f, indent=2)

    bh_return = buy_hold_return(DEFAULT_DATA_PATH, DEFAULT_START, DEFAULT_END)

    print("\n" + "=" * 72)
    print("B0 vs B1 COMPARISON")
    print("=" * 72)
    print(comparison.to_string())
    print(f"\nBuy-and-hold ETH (same execution window): {bh_return:.2f}%")
    print(f"\nTrade count delta (B0 - B1): {metrics_by_label['B0']['trade_count'] - metrics_by_label['B1']['trade_count']}")
    print(f"Results saved to: {RESULTS_ROOT}")


if __name__ == "__main__":
    main()
