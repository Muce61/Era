"""Fixed risk vs fixed 2x comparison for selected signal."""

import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.eth_trend_engine import EthTrendEngine
from backtest.metrics import extended_summary
from strategy.eth_trend_signals import EntryMode, StrategyConfig

DATA_PATH = Path("/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv")
START = "2024-12-01 00:00:00"
END = "2025-12-12 20:00:00"
OUT = Path("backtest_results/stage1/risk_sizing_comparison.csv")

# B1 selected as most credible: positive PF, lower DD than B0, survives cost stress better than complex patterns
SELECTED_MODE = EntryMode.STRONG_BREAKOUT


def run(mode_config: StrategyConfig, label: str) -> dict:
    engine = EthTrendEngine(config=mode_config, data_path=DATA_PATH, start_date=START, end_date=END)
    engine.run(verbose=False)
    trades = pd.DataFrame(engine.trades)
    equity = pd.DataFrame(engine.equity_curve)
    summary = extended_summary(trades, 1000.0, equity, START, END)
    summary["sizing_label"] = label
    return summary


def main():
    fixed_2x = StrategyConfig(
        entry_mode=SELECTED_MODE,
        position_sizing_mode="fixed_leverage",
    )
    fixed_risk = StrategyConfig(
        entry_mode=SELECTED_MODE,
        position_sizing_mode="fixed_risk",
        risk_fraction=0.005,
    )
    rows = [
        run(fixed_2x, "B1_fixed_2x"),
        run(fixed_risk, "B1_fixed_risk_0.5pct_cap_2x"),
    ]
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(pd.DataFrame(rows)[["sizing_label", "total_return_pct", "max_drawdown_pct", "profit_factor", "calmar"]].to_string())
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
