import numpy as np
import pandas as pd

from research_core.second_alpha_source_s29.exit_window_edge_attribution import (
    case_samples,
    decision_summary,
    edge_explainability_summary,
    period_failure_attribution,
    reversion_vs_continuation_diagnostics,
    side_failure_attribution,
    symbol_failure_attribution,
)


def _events(n=240):
    idx = pd.date_range("2020-01-01 00:15", periods=n, freq="15min", tz="UTC")
    symbols = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
    rows = []
    for i, ts in enumerate(idx):
        symbol = symbols[i % 4]
        ret = {
            "ETHUSDT": 0.0004,
            "BTCUSDT": -0.0005,
            "SOLUSDT": 0.0025,
            "BNBUSDT": 0.0012,
        }[symbol]
        if i % 23 == 0:
            ret = -0.012
        rows.append({
            "event_id": f"e{i}",
            "symbol": symbol,
            "side": "long" if i % 2 else "short",
            "signal_time": ts,
            "execution_time": ts,
            "month": ts.to_period("M").strftime("%Y-%m"),
            "quarter": ts.to_period("Q").strftime("%YQ%q"),
            "year": ts.year,
            "volatility_regime": "high_vol" if i % 11 == 0 else "mid_vol",
            "trend_strength_bucket": "1.0_1.5" if i % 7 == 0 else "0.5_1.0",
            "p4_state_bucket": "after_p4_exit_5_16_bars",
            "bars_since_p4_exit": 5 + (i % 12),
            "fwd_ret_16": ret,
            "fwd_mae_16": -0.004 - (0.01 if ret < -0.01 else 0),
            "fwd_mfe_16": 0.006 + max(ret, 0),
            "plus_1atr_first_16": ret > 0,
            "minus_1atr_first_16": ret < 0,
            "mean_reversion_bars": 3 if ret > 0 else np.nan,
            "subsequent_trend_breakout": bool(ret < -0.01),
            "data_layer": "expanded_discovery_long_history",
            "oos_status": "not_oos",
        })
    return pd.DataFrame(rows)


def _random_and_overlap():
    random = pd.DataFrame({
        "symbol": ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"],
        "percentile_vs_random_time": [0.9, 0.95, 0.99, 0.97],
    })
    overlap = pd.DataFrame({
        "symbol": ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"],
        "s28_positive_in_p4_negative_month_rate": [0.5, 0.55, 0.6, 0.6],
        "s28_positive_in_p4_weak_month_rate": [0.5, 0.55, 0.6, 0.6],
        "overlap_status": ["complementary"] * 4,
    })
    return random, overlap


def test_symbol_failure_reason_classification():
    events = _events(480)
    random, overlap = _random_and_overlap()
    out = symbol_failure_attribution(events, random, overlap)
    reasons = out.set_index("symbol")["failure_reason"].to_dict()
    assert reasons["BTCUSDT"] == "negative_mean"
    assert reasons["SOLUSDT"] in {"positive_and_stable", "mae_too_large", "positive_but_top_trade_dependent"}


def test_year_and_quarter_failure_reason_classification():
    events = _events()
    p4 = pd.DataFrame({
        "symbol": ["ETHUSDT"] * 12,
        "month": [f"2020-{m:02d}" for m in range(1, 13)],
        "p4_proxy_return": [0.01] * 12,
    })
    yearly = period_failure_attribution(events, p4, "year")
    quarterly = period_failure_attribution(events, p4, "quarter")
    assert "failure_reason" in yearly.columns
    assert "failure_reason" in quarterly.columns


def test_side_failure_attribution():
    out = side_failure_attribution(_events())
    assert {"symbol", "side", "failure_reason"}.issubset(out.columns)
    assert len(out) > 0


def test_continuation_breakout_diagnosis():
    events = _events()
    out = reversion_vs_continuation_diagnostics(events)
    assert "diagnosis" in out.columns
    assert set(out["diagnosis"]).issubset({"true_reversion_edge", "continuation_risk_dominates", "mixed_state", "insufficient_sample"})


def test_case_samples_include_failure_and_success_sets():
    failures, successes = case_samples(_events())
    assert not failures.empty
    assert not successes.empty
    assert set(failures["symbol"]).issubset({"BTCUSDT", "ETHUSDT"})
    assert set(successes["symbol"]).issubset({"SOLUSDT", "BNBUSDT"})


def test_explainability_summary_covers_key_questions():
    events = _events()
    random, overlap = _random_and_overlap()
    sym = symbol_failure_attribution(events, random, overlap)
    p4 = pd.DataFrame({"symbol": ["ETHUSDT"], "month": ["2020-01"], "p4_proxy_return": [0.01]})
    year = period_failure_attribution(events, p4, "year")
    rev = reversion_vs_continuation_diagnostics(events)
    out = edge_explainability_summary(sym, year, rev, overlap, "test_decision")
    joined = " ".join(out["question"].tolist())
    for phrase in ["BTC", "ETH", "SOL/BNB", "失败年份", "是否真回归", "是否与 P4 互补", "是否值得进入 S3"]:
        assert phrase in joined


def test_s29_no_strategy_backtest_non_oos_and_decision_rule():
    events = _events()
    random, overlap = _random_and_overlap()
    sym = symbol_failure_attribution(events, random, overlap)
    p4 = pd.DataFrame({"symbol": ["ETHUSDT"], "month": ["2020-01"], "p4_proxy_return": [0.01]})
    year = period_failure_attribution(events, p4, "year")
    rev = reversion_vs_continuation_diagnostics(events)
    input_val = pd.DataFrame({"input_validation_status": ["pass"]})
    out = decision_summary(input_val, sym, year, rev, overlap)
    assert out["strategy_backtest_generated"].iloc[0] == False  # noqa: E712
    assert out["oos_status"].iloc[0] == "not_oos"
    assert out["decision_letter"].iloc[0] in {"A", "B", "C", "D", "E"}
