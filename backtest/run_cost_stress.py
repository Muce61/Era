"""Cost stress test for B0–B3."""

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
OUT = Path("backtest_results/stage1/cost_stress_summary.csv")

SCENARIOS = {
    "C1": (0.0005, 0.0002),
    "C2": (0.00075, 0.0003),
    "C3": (0.001, 0.0004),
}

MODES = {
    "B0": EntryMode.NO_CANDLE,
    "B1": EntryMode.STRONG_BREAKOUT,
    "B2": EntryMode.PULLBACK_ENGULFING,
    "B3": EntryMode.BULLISH_HIKKAKE,
}


def main():
    rows = []
    for label, mode in MODES.items():
        for scenario, (fee, slip) in SCENARIOS.items():
            config = StrategyConfig(entry_mode=mode, fee_rate=fee, slippage_rate=slip)
            engine = EthTrendEngine(config=config, data_path=DATA_PATH, start_date=START, end_date=END)
            engine.run(verbose=False)
            trades = pd.DataFrame(engine.trades)
            equity = pd.DataFrame(engine.equity_curve)
            summary = extended_summary(trades, 1000.0, equity, START, END)
            rows.append({
                "entry_mode": label,
                "cost_scenario": scenario,
                "fee_rate": fee,
                "slippage_rate": slip,
                "total_return": summary.get("total_return_pct", 0),
                "profit_factor": summary.get("profit_factor", 0),
                "max_drawdown": summary.get("max_drawdown_pct", 0),
                "avg_trade": summary.get("average_trade", 0),
                "total_fee": summary.get("total_fee", 0),
                "trade_count": summary.get("total_trades", 0),
            })
            print(f"{label} {scenario}: return={summary.get('total_return_pct', 0):.2f}% PF={summary.get('profit_factor', 0):.2f}")

    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
