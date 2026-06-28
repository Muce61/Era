import pandas as pd

from research_core.common import validate_run_log_row
from research_core.leverage_research_analysis import adaptive_leverage_by_mode, fixed_leverage_for_mode
from research_core.run_rb2_low_leverage_portfolio import (
    GATES,
    LEVERAGE_MODES,
    PROTOTYPE,
    RB2_SYMBOLS,
    combine_equal_weight,
    period_summary,
)


def test_rb2_scope_is_eth_btc_p4_only():
    assert RB2_SYMBOLS == ["ETHUSDT", "BTCUSDT"]
    assert PROTOTYPE == "P4_BREAKOUT_TOP20"
    assert GATES == ["P4_NO_GATE", "P4_G1_GATE"]


def test_rb2_fixed_low_leverage_values():
    assert fixed_leverage_for_mode("fixed_1x") == 1.0
    assert fixed_leverage_for_mode("fixed_2x") == 2.0
    assert fixed_leverage_for_mode("fixed_3x") == 3.0


def test_rb2_adaptive_modes_do_not_exceed_caps():
    lev, _, base = adaptive_leverage_by_mode("adaptive_1x_3x_v1", PROTOTYPE, 1.0, 0.1, 0.0, 0)
    assert base == 1.0
    assert lev == 3.0
    lev, _, base = adaptive_leverage_by_mode("adaptive_1x_5x_v1", PROTOTYPE, 1.0, 0.1, 0.0, 0)
    assert base == 1.0
    assert lev == 5.0


def test_rb2_adaptive_modes_downshift_to_one_on_risk():
    assert adaptive_leverage_by_mode("adaptive_1x_3x_v1", PROTOTYPE, 1.0, 0.9, 0.0, 0)[0] == 1.0
    assert adaptive_leverage_by_mode("adaptive_1x_5x_v1", PROTOTYPE, 1.0, 0.1, 0.21, 0)[0] == 1.0
    assert adaptive_leverage_by_mode("adaptive_1x_5x_v1", PROTOTYPE, 1.0, 0.1, 0.0, 3)[0] == 1.0


def test_rb2_leverage_mode_list_fixed():
    assert LEVERAGE_MODES == ["fixed_1x", "fixed_2x", "fixed_3x", "adaptive_1x_3x_v1", "adaptive_1x_5x_v1"]


def test_portfolio_equity_is_equal_weight_average():
    t = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC")
    eth = pd.DataFrame({"time": t, "equity": [1000.0, 2000.0]})
    btc = pd.DataFrame({"time": t, "equity": [1000.0, 500.0]})
    out = combine_equal_weight([eth, btc])
    assert out["equity"].tolist() == [1000.0, 1250.0]


def test_yearly_summary_marks_2026_partial_year():
    trades = pd.DataFrame({
        "exit_time": pd.to_datetime(["2026-01-01", "2026-02-01"], utc=True),
        "net_pnl": [10.0, -5.0],
    })
    out = period_summary({("ETHUSDT", "P4_NO_GATE", "fixed_1x"): trades}, "Y")
    assert out.iloc[0]["sample_status"] == "partial_year"


def test_run_log_required_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-28T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
    })
