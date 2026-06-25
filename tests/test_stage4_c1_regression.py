"""Stage 4 C1 regression: B0/B1 unchanged on short window; C1 engine smoke test."""

from pathlib import Path

import numpy as np
import pandas as pd

from backtest.eth_trend_engine import EthTrendEngine
from backtest.stage4_config import run_config_from_label
from strategy.eth_trend_signals import EntryMode, StrategyConfig

DATA_PATH = Path("/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv")
BASELINE_B0 = Path("backtest_results/stage3/baseline_B0/trades.csv")
BASELINE_B1 = Path("backtest_results/stage3/baseline_B1/trades.csv")
TOLERANCE = 1e-8

CORE_COLS = [
    "symbol", "side", "entry_price", "exit_price", "quantity",
    "balance_before", "entry_fee", "gross_pnl", "exit_fee", "total_fee",
    "net_pnl", "balance_after", "return_pct_on_equity", "reason", "entry_reason",
]


def _run_mode(mode: EntryMode) -> pd.DataFrame:
    engine = EthTrendEngine(
        config=StrategyConfig(entry_mode=mode),
        data_path=DATA_PATH,
    )
    engine.run(verbose=False)
    return pd.DataFrame(engine.trades)


def test_b0_matches_stage3_baseline():
    if not BASELINE_B0.exists():
        return
    baseline = pd.read_csv(BASELINE_B0)
    current = _run_mode(EntryMode.NO_CANDLE)
    cols = [c for c in CORE_COLS if c in baseline.columns and c in current.columns]
    for col in cols:
        if baseline[col].dtype in (float, np.float64):
            assert np.allclose(baseline[col], current[col], rtol=0, atol=TOLERANCE)
        else:
            assert baseline[col].equals(current[col])
    assert len(current) == len(baseline)


def test_b1_matches_stage3_baseline():
    if not BASELINE_B1.exists():
        return
    baseline = pd.read_csv(BASELINE_B1)
    current = _run_mode(EntryMode.STRONG_BREAKOUT)
    cols = [c for c in CORE_COLS if c in baseline.columns and c in current.columns]
    for col in cols:
        if baseline[col].dtype in (float, np.float64):
            assert np.allclose(baseline[col], current[col], rtol=0, atol=TOLERANCE)
        else:
            assert baseline[col].equals(current[col])
    assert len(current) == len(baseline)


def test_c1_enters_less_than_b0_on_same_window():
    if not DATA_PATH.exists():
        return
    b0 = _run_mode(EntryMode.NO_CANDLE)
    c1 = _run_mode(EntryMode.TREND_SEGMENT_ENTRY)
    assert len(c1) <= len(b0)
    assert len(c1) > 0
