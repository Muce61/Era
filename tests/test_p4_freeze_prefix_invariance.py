import pandas as pd

from research_core.p4_canonical_freeze.p4_freeze_stability import prefix_invariance_status


def test_prefix_invariance_passes_identical_completed_trades():
    trades = pd.DataFrame({
        "signal_time": ["2024-01-01 00:15:00+00:00"],
        "entry_time": ["2024-01-01 00:15:00+00:00"],
        "exit_time": ["2024-01-01 01:00:00+00:00"],
        "entry_price": [100.0],
        "exit_price": [110.0],
        "quantity": [10.0],
        "net_pnl": [99.0],
        "exit_reason": ["donchian20_exit"],
    })
    cutoff = pd.Timestamp("2024-01-02", tz="UTC")
    assert prefix_invariance_status(trades, trades.copy(), cutoff) == "pass"

