"""Backward-compatible runner for B1 STRONG_BREAKOUT strategy."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.eth_trend_engine import EthTrendEngine
from strategy.eth_trend_signals import EntryMode, StrategyConfig

DATA_PATH = Path("/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv")
OUTPUT_CSV = Path("backtest_results/csv/eth_long_candlestick_trend_2x_trades.csv")


def main():
    config = StrategyConfig(entry_mode=EntryMode.STRONG_BREAKOUT)
    engine = EthTrendEngine(
        config=config,
        data_path=DATA_PATH,
        start_date="2024-12-01 00:00:00",
        end_date="2025-12-12 20:00:00",
        initial_balance=1000.0,
    )
    engine.run()
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    pd.DataFrame(engine.trades).to_csv(OUTPUT_CSV, index=False)
    print(f"Trades saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
