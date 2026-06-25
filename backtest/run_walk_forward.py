"""Development/validation split and shortened walk-forward."""

import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.eth_trend_engine import EthTrendEngine
from backtest.metrics import extended_summary
from strategy.eth_trend_signals import EntryMode, StrategyConfig

DATA_PATH = Path("/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv")
DEV_START = "2024-12-01 00:00:00"
DEV_END = "2025-08-31 23:59:59"
VAL_START = "2025-09-01 00:00:00"
VAL_END = "2025-12-12 20:00:00"
OUT = Path("backtest_results/stage1")

MODES = {
    "B0": EntryMode.NO_CANDLE,
    "B1": EntryMode.STRONG_BREAKOUT,
    "B2": EntryMode.PULLBACK_ENGULFING,
    "B3": EntryMode.BULLISH_HIKKAKE,
}


def run_window(label, mode, start, end, split_name):
    config = StrategyConfig(entry_mode=mode)
    engine = EthTrendEngine(config=config, data_path=DATA_PATH, start_date=start, end_date=end)
    engine.run(verbose=False)
    trades = pd.DataFrame(engine.trades)
    equity = pd.DataFrame(engine.equity_curve)
    summary = extended_summary(trades, 1000.0, equity, start, end)
    summary["label"] = label
    summary["split"] = split_name
    return summary


def walk_forward_windows():
    """Shortened walk-forward: 6-month train / 3-month test / 3-month step (non-standard)."""
    windows = []
    # Window 1: train Dec24-May25, test Jun25-Aug25
    windows.append(("WF1", "2024-12-01 00:00:00", "2025-05-31 23:59:59", "2025-06-01 00:00:00", "2025-08-31 23:59:59"))
    # Window 2: train Mar25-Aug25, test Sep25-Dec25
    windows.append(("WF2", "2025-03-01 00:00:00", "2025-08-31 23:59:59", "2025-09-01 00:00:00", VAL_END))
    return windows


def main():
    split_rows = []
    for label, mode in MODES.items():
        split_rows.append(run_window(label, mode, DEV_START, DEV_END, "development"))
        split_rows.append(run_window(label, mode, VAL_START, VAL_END, "validation"))

    split_df = pd.DataFrame(split_rows)
    split_df.to_csv(OUT / "dev_val_summary.csv", index=False)

    wf_detail = []
    for wf_id, train_start, train_end, test_start, test_end in walk_forward_windows():
        for label, mode in MODES.items():
            row = run_window(label, mode, test_start, test_end, f"walk_forward_test_{wf_id}")
            row["walk_forward_id"] = wf_id
            row["train_start"] = train_start
            row["train_end"] = train_end
            row["test_start"] = test_start
            row["test_end"] = test_end
            wf_detail.append(row)

    wf_df = pd.DataFrame(wf_detail)
    wf_df.to_csv(OUT / "walk_forward_windows.csv", index=False)

    wf_summary = wf_df.groupby("label").agg({
        "total_return_pct": "mean",
        "profit_factor": "mean",
        "max_drawdown_pct": "mean",
        "total_trades": "sum",
    }).reset_index()
    wf_summary.to_csv(OUT / "walk_forward_summary.csv", index=False)

    print(f"Saved dev/val and walk-forward results to {OUT}")


if __name__ == "__main__":
    main()
