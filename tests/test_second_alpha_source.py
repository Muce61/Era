import numpy as np
import pandas as pd

from research_core.common import validate_run_log_row
from research_core.second_alpha_source.candidate_event_study import (
    EventConfig,
    add_second_alpha_indicators,
    first_touch_directional,
    subsequent_trend_breakout,
)
from research_core.second_alpha_source.candidate_minimal_backtest import minimal_backtest_blocked_reason
from research_core.second_alpha_source.matched_random_baseline import matched_random_summary


def _bars_15m(n=80):
    idx = pd.date_range("2024-01-01 00:15", periods=n, freq="15min", tz="UTC")
    base = np.linspace(100, 110, n)
    return pd.DataFrame({
        "open": base,
        "high": base + 1,
        "low": base - 1,
        "close": base + 0.2,
        "volume": np.ones(n),
    }, index=idx)


def test_range_uses_shifted_prior_bars_not_current_high():
    bars = _bars_15m(40)
    bars.iloc[-1, bars.columns.get_loc("high")] = 999.0
    out = add_second_alpha_indicators(bars, EventConfig(range_n=10))
    assert out["range_upper"].iloc[-1] < 999.0


def test_first_touch_marks_ambiguous_when_same_bar_hits_both_sides():
    window = pd.DataFrame({"high": [102.0], "low": [98.0]})
    assert first_touch_directional(window, entry=100.0, atr=1.0, direction=1) == "ambiguous"
    assert first_touch_directional(window, entry=100.0, atr=1.0, direction=-1) == "ambiguous"


def test_subsequent_trend_breakout_uses_future_window_only():
    bars = _bars_15m(70)
    out = add_second_alpha_indicators(bars)
    ts = out.index[60]
    out.loc[ts, "close"] = out.loc[ts, "donchian55_upper"] + 100
    assert not subsequent_trend_breakout(out, ts, direction=1, max_bars=2)
    future_ts = out.index[61]
    out.loc[future_ts, "close"] = out.loc[future_ts, "donchian55_upper"] + 100
    assert subsequent_trend_breakout(out, ts, direction=1, max_bars=2)


def test_matched_random_summary_percentile_formula_and_reproducible():
    rows = []
    for i in range(12):
        for candidate, ret in [
            ("FB1_FAILED_BREAKOUT_REVERSION", 0.01 + i * 0.0001),
            ("MR1_SHORT_TERM_DEVIATION_REVERSION", -0.01 + i * 0.0001),
        ]:
            rows.append({
                "candidate": candidate,
                "symbol": "ETHUSDT",
                "side": "long",
                "signal_time": pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=i),
                "trend_strength_atr": 1.0,
                "volatility_regime": "mid_vol",
                "fwd_ret_16": ret,
            })
    events = pd.DataFrame(rows)
    a = matched_random_summary(events, runs=20, seed=7)
    b = matched_random_summary(events, runs=20, seed=7)
    assert a["percentile_vs_random"].between(0, 1).all()
    pd.testing.assert_frame_equal(a, b)


def test_minimal_backtest_is_blocked_until_event_edge_passes():
    reason = minimal_backtest_blocked_reason()
    assert reason["status"] == "blocked_event_research_first"
    assert reason["oos_status"] == "not_oos"
    assert reason["deployable_strategy_generated"] is False


def test_second_alpha_run_log_required_fields_complete():
    row = {
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-28T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
    }
    assert validate_run_log_row(row)
