import pandas as pd

from research_core.common import validate_run_log_row
from research_core.high_leverage_path_safety_analysis import (
    FORWARD_LABEL_PREFIXES,
    PATH_FACTOR_COLUMNS,
    build_failure_cases,
    compute_path_row,
    directional_edge,
    factor_safety_analysis,
    failure_review_markdown,
    first_touch,
)
from research_core.leverage_research_analysis import liquidation_price


def make_1m():
    idx = pd.date_range("2024-01-01 00:00:00+00:00", periods=4, freq="min")
    return pd.DataFrame({
        "open": [100, 100.5, 101, 101.5],
        "high": [101, 102, 103, 104],
        "low": [99.5, 100.2, 100.8, 101.1],
        "close": [100.5, 101, 101.5, 103],
        "volume": [1, 1, 1, 1],
    }, index=idx)


def base_row():
    return {
        "symbol": "ETHUSDT",
        "prototype": "P4_BREAKOUT_TOP20",
        "event_id": "e1",
        "entry_time": pd.Timestamp("2024-01-01 00:00:00+00:00"),
        "entry_price": 100.0,
        "atr": 2.0,
        "atr_pct": 0.02,
        "atr_pct_rank": 0.5,
        "breakout_score_quantile": 0.9,
        "momentum_score_quantile": 0.8,
    }


def test_safe_for_10x_label_calculation():
    row = compute_path_row(base_row(), make_1m(), 3)
    assert row["safe_for_10x"]
    assert not row["hit_liquidation_10x"]
    assert row["mae_pct"] > -0.05


def test_safe_for_20x_label_calculation():
    row = compute_path_row(base_row(), make_1m(), 3)
    assert row["safe_for_20x"]
    assert not row["hit_liquidation_20x"]
    assert row["mae_pct"] > -0.025


def test_ambiguous_touch_detected():
    idx = pd.date_range("2024-01-01 00:00:00+00:00", periods=1, freq="min")
    window = pd.DataFrame({"high": [101.5], "low": [98.5]}, index=idx)
    assert first_touch(window, 100.0, 2.0, 0.5) == "ambiguous"


def test_liquidation_model_reused():
    row = base_row()
    row["entry_price"] = 100.0
    data = make_1m()
    data.loc[data.index[0], "low"] = liquidation_price(100, 20)
    out = compute_path_row(row, data, 1)
    assert out["hit_liquidation_20x"]


def test_factor_list_excludes_forward_labels():
    assert not any(f.startswith(FORWARD_LABEL_PREFIXES) for f in PATH_FACTOR_COLUMNS)


def test_top20_bottom20_directional_edge():
    frame = pd.DataFrame({
        "factor": list(range(100)),
        "safe_for_20x": [False] * 50 + [True] * 50,
        "hit_liquidation_20x": [True] * 50 + [False] * 50,
        "symbol": ["ETHUSDT"] * 100,
    })
    edge = directional_edge(frame, "factor", "safe_for_20x")
    assert edge["top20_minus_bottom20"] > 0
    risk_edge = directional_edge(frame, "factor", "hit_liquidation_20x")
    assert risk_edge["top20_minus_bottom20"] > 0


def test_monthly_and_cross_symbol_summary():
    rows = []
    for symbol in ["ETHUSDT", "BTCUSDT"]:
        for month in ["2024-01", "2024-02"]:
            for i in range(40):
                rows.append({
                    "symbol": symbol,
                    "prototype": "P4_BREAKOUT_TOP20",
                    "event_id": f"{symbol}-{month}-{i}",
                    "entry_time": pd.Timestamp(f"{month}-01 00:00:00+00:00") + pd.Timedelta(minutes=i),
                    "forward_window": "1m",
                    "factor": i,
                    "safe_for_10x": i > 20,
                    "safe_for_20x": i > 20,
                    "fast_follow_through": i > 20,
                    "hit_liquidation_10x": i <= 20,
                    "hit_liquidation_20x": i <= 20,
                    "mae_pct": i / 1000,
                    "mfe_pct": i / 500,
                })
    labels = pd.DataFrame(rows)
    from research_core import high_leverage_path_safety_analysis as h

    original = h.PATH_FACTOR_COLUMNS
    h.PATH_FACTOR_COLUMNS = ["factor"]
    try:
        summary, _, symbol_summary, monthly = factor_safety_analysis(labels)
    finally:
        h.PATH_FACTOR_COLUMNS = original
    row = summary[(summary["factor"] == "factor") & (summary["label"] == "safe_for_20x")].iloc[0]
    assert row["monthly_positive_rate"] == 1.0
    assert row["cross_symbol_positive_count"] == 2
    assert not symbol_summary.empty
    assert not monthly.empty


def test_failure_review_empty_input():
    labels = pd.DataFrame(columns=["forward_window"])
    cases = build_failure_cases(labels)
    assert "failure_source" in cases.columns
    report = failure_review_markdown(cases)
    assert "No L1 liquidation" in report


def test_run_log_required_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-27T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "high_leverage_research",
    })
