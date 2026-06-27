import numpy as np
import pandas as pd

from research_core.cross_asset_validation_analysis import (
    audit_symbol_data,
    cross_asset_decision,
    cross_asset_event_summary,
    make_cross_asset_frames,
    merge_symbol_1m,
)
from research_core.oos_validation_analysis import discovery_score_thresholds, transform_oos_scores


def test_merge_symbol_1m_deduplicates(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=3, freq="1min"),
        "open": [1, 2, 3],
        "high": [2, 3, 4],
        "low": [0.5, 1.5, 2.5],
        "close": [1, 2, 3],
        "volume": [1, 1, 1],
    }).to_csv(a, index=False)
    pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01 00:02", periods=2, freq="1min"),
        "open": [30, 40],
        "high": [31, 41],
        "low": [29, 39],
        "close": [30, 40],
        "volume": [1, 1],
    }).to_csv(b, index=False)
    out = merge_symbol_1m([a, b])
    assert len(out) == 4
    assert out.loc[pd.Timestamp("2024-01-01 00:02", tz="UTC"), "close"] == 30


def test_audit_symbol_data_reports_missing_minutes():
    idx = pd.to_datetime(["2024-01-01 00:00", "2024-01-01 00:02"], utc=True)
    data = pd.DataFrame({"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1}, index=idx)
    report = audit_symbol_data("BTCUSDT", data)
    assert report["missing_minute_count"] == 1
    assert report["invalid_ohlc_count"] == 0


def test_cross_asset_scores_use_discovery_metadata_and_thresholds():
    events = pd.DataFrame({
        "event_id": ["a", "b"],
        "signal_time": pd.date_range("2024-01-01", periods=2, freq="1h", tz="UTC"),
        "execution_time": pd.date_range("2024-01-01 00:01", periods=2, freq="1h", tz="UTC"),
        "ret_4h": [100, 200],
        "ret_12h": [100, 200],
        "ret_24h": [100, 200],
        "breakout_distance_atr": [100, 200],
        "range_atr": [100, 200],
        "body_ratio": [100, 200],
        "close_location": [100, 200],
        "first_breakout_after_flat": [False, True],
        "strong_breakout": [True, False],
    })
    metadata = pd.DataFrame({
        "family": ["momentum_continuation"] * 3 + ["breakout_conviction"] * 4,
        "factor": ["ret_4h", "ret_12h", "ret_24h", "breakout_distance_atr", "range_atr", "body_ratio", "close_location"],
        "direction": [1] * 7,
        "winsor_lower": [0] * 7,
        "winsor_upper": [10] * 7,
        "mean": [5] * 7,
        "std": [5] * 7,
        "missing_rate": [0] * 7,
    })
    scores = transform_oos_scores(events, metadata)
    thresholds = pd.DataFrame({
        "score": ["momentum", "momentum", "breakout", "breakout"],
        "quantile": [0.60, 0.80, 0.60, 0.80],
        "threshold": [2, 3, 2, 3],
    })
    frames = make_cross_asset_frames(events, scores, thresholds)
    assert len(frames["P3_MOMENTUM_TOP20"]) == 0
    assert len(frames["P2_STRONG_BREAKOUT"]) == 1


def test_cross_asset_event_summary_marks_sparse():
    events = pd.DataFrame({
        "first_breakout_after_flat": [True],
        "strong_breakout": [False],
    })
    masks = {p: pd.Series([True]) for p in [
        "P1_C1_FIRST_BREAKOUT",
        "P2_STRONG_BREAKOUT",
        "P3_MOMENTUM_TOP20",
        "P4_BREAKOUT_TOP20",
        "P5_MOMENTUM_AND_BREAKOUT_TOP40",
        "P6_MOMENTUM_OR_BREAKOUT_TOP20",
    ]}
    for h in [1, 4, 8, 16, 32]:
        events[f"fwd_ret_{h}"] = 0.01
        events[f"fwd_mfe_{h}"] = 0.02
        events[f"fwd_mae_{h}"] = -0.01
        events[f"plus_1atr_first_{h}"] = True
        events[f"minus_1atr_first_{h}"] = False
        events[f"ambiguous_touch_{h}"] = False
    out = cross_asset_event_summary("BTCUSDT", events, masks)
    assert (out["sample_status"] == "insufficient_sample").all()


def test_cross_asset_decision_supported_when_beats_p1():
    rows = []
    for symbol in ["BTCUSDT", "SOLUSDT", "BNBUSDT"]:
        rows.append({"symbol": symbol, "prototype": "P1_C1_FIRST_BREAKOUT", "sizing_mode": "fixed_2x", "trade_count": 100, "total_return": 0.1, "profit_factor": 1.1})
        rows.append({"symbol": symbol, "prototype": "P4_BREAKOUT_TOP20", "sizing_mode": "fixed_2x", "trade_count": 100, "total_return": 0.2, "profit_factor": 1.5})
    for prototype in ["P3_MOMENTUM_TOP20", "P5_MOMENTUM_AND_BREAKOUT_TOP40", "P6_MOMENTUM_OR_BREAKOUT_TOP20"]:
        for symbol in ["BTCUSDT", "SOLUSDT", "BNBUSDT"]:
            rows.append({"symbol": symbol, "prototype": prototype, "sizing_mode": "fixed_2x", "trade_count": 10, "total_return": -0.1, "profit_factor": 0.8})
    out = cross_asset_decision(pd.DataFrame(rows), pd.DataFrame())
    assert out[out["prototype"] == "P4_BREAKOUT_TOP20"]["decision_status"].iloc[0] == "cross_asset_supported"
