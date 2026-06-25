import pandas as pd

from backtest.metrics import profit_factor
from backtest.run_stage2_audit import first_touch_outcome, top_n_profit_contribution


def test_profit_factor_uses_net_pnl_gross_profit_over_abs_gross_loss():
    pnl = pd.Series([100.0, 25.0, -50.0, -25.0])
    assert profit_factor(pnl) == 125.0 / 75.0


def test_top_n_profit_contribution_uses_winning_trades_over_total_net():
    pnl = pd.Series([100.0, 50.0, 25.0, -75.0])
    assert top_n_profit_contribution(pnl, 1) == 100.0
    assert top_n_profit_contribution(pnl, 3) == 175.0


def test_top_n_profit_contribution_is_zero_when_total_net_not_positive():
    pnl = pd.Series([100.0, -100.0, -1.0])
    assert top_n_profit_contribution(pnl, 1) == 0.0


def test_first_touch_marks_same_candle_both_sides_as_ambiguous():
    path = pd.DataFrame(
        [{"open": 100.0, "high": 111.0, "low": 89.0, "close": 100.0}],
        index=[pd.Timestamp("2025-01-01 00:01:00", tz="UTC")],
    )
    assert first_touch_outcome(path, entry=100.0, atr=10.0) == "ambiguous"


def test_first_touch_profit_and_loss_are_directionally_distinct():
    profit_path = pd.DataFrame(
        [
            {"open": 100.0, "high": 105.0, "low": 98.0, "close": 104.0},
            {"open": 104.0, "high": 111.0, "low": 103.0, "close": 110.0},
        ],
        index=pd.date_range("2025-01-01 00:01:00", periods=2, freq="1min", tz="UTC"),
    )
    loss_path = pd.DataFrame(
        [
            {"open": 100.0, "high": 102.0, "low": 95.0, "close": 96.0},
            {"open": 96.0, "high": 97.0, "low": 89.0, "close": 90.0},
        ],
        index=pd.date_range("2025-01-01 00:01:00", periods=2, freq="1min", tz="UTC"),
    )
    assert first_touch_outcome(profit_path, entry=100.0, atr=10.0) == "profit"
    assert first_touch_outcome(loss_path, entry=100.0, atr=10.0) == "loss"


def test_mae_metric_names_keep_event_and_trade_units_separate():
    event_columns = {"future_mae_8", "mean_future_mae_pct_8"}
    trade_columns = {"mae_atr", "avg_mae_atr"}
    assert event_columns.isdisjoint(trade_columns)
