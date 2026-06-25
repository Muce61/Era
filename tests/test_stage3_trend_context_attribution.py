import pandas as pd
import pytest

from backtest.run_stage3_trend_context_attribution import (
    attach_regime_to_segments,
    equity_from_trades,
    map_trade_to_segments,
    summarize_mode,
)


def test_map_trade_to_segments_computes_position_and_missed_runup():
    trades = pd.DataFrame([
        {
            "entry_time": pd.Timestamp("2025-01-01 01:00", tz="UTC"),
            "exit_time": pd.Timestamp("2025-01-01 02:00", tz="UTC"),
            "entry_price": 110.0,
            "net_pnl": 50.0,
            "balance_before": 1000.0,
            "reason": "Donchian Long Exit",
        }
    ])
    segments = pd.DataFrame([
        {
            "segment_id": 1,
            "segment_start": pd.Timestamp("2025-01-01 00:00", tz="UTC"),
            "segment_end": pd.Timestamp("2025-01-01 04:00", tz="UTC"),
            "start_price": 100.0,
        }
    ])

    mapped = map_trade_to_segments(trades, segments, "B3")

    assert bool(mapped.iloc[0]["participated"]) is True
    assert mapped.iloc[0]["entry_position_pct_of_segment"] == 25.0
    assert mapped.iloc[0]["missed_pre_entry_runup_pct"] == pytest.approx(10.0)


def test_map_trade_to_segments_marks_unmapped_trade():
    trades = pd.DataFrame([
        {
            "entry_time": pd.Timestamp("2025-01-02 01:00", tz="UTC"),
            "exit_time": pd.Timestamp("2025-01-02 02:00", tz="UTC"),
            "entry_price": 110.0,
            "net_pnl": -10.0,
            "balance_before": 1000.0,
        }
    ])
    segments = pd.DataFrame([
        {
            "segment_id": 1,
            "segment_start": pd.Timestamp("2025-01-01 00:00", tz="UTC"),
            "segment_end": pd.Timestamp("2025-01-01 04:00", tz="UTC"),
            "start_price": 100.0,
        }
    ])

    mapped = map_trade_to_segments(trades, segments, "B3")

    assert bool(mapped.iloc[0]["participated"]) is False
    assert mapped.iloc[0]["unmapped_reason"] == "entry_outside_segment"


def test_equity_from_trades_uses_cumulative_net_pnl():
    trades = pd.DataFrame([
        {"exit_time": pd.Timestamp("2025-01-01", tz="UTC"), "net_pnl": 100.0},
        {"exit_time": pd.Timestamp("2025-01-02", tz="UTC"), "net_pnl": -25.0},
    ])

    equity = equity_from_trades(trades)

    assert list(equity["equity"]) == [1100.0, 1075.0]


def test_summarize_mode_handles_empty_trades():
    summary = summarize_mode(pd.DataFrame(), pd.DataFrame([{"equity": 1000.0}]))
    assert summary["trade_count"] == 0
    assert summary["profit_factor"] == 0.0
