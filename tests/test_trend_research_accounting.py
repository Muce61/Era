import pandas as pd

from backtest.accounting import execute_entry, execute_exit, gross_pnl, trade_net_pnl
from backtest.metrics import profit_factor
from research.trend_research_pipeline import close_trade, open_trade


CONFIG = {
    "symbol": "ETHUSDT",
    "atr_stop_mult": 3.0,
}


def test_single_long_pnl_accounting():
    entry = execute_entry(100.0, 10, "LONG", 0.001, 0.01)
    exit_fill = execute_exit(110.0, 10, "LONG", 0.001, 0.01)
    gross = gross_pnl(entry.executed_price, exit_fill.executed_price, 10, "LONG")
    net = trade_net_pnl(gross, entry.fee, exit_fill.fee, 0)
    assert gross == (108.9 - 101.0) * 10
    assert net == gross - entry.fee - exit_fill.fee


def test_single_short_pnl_accounting():
    entry = execute_entry(100.0, 10, "SHORT", 0.001, 0.01)
    exit_fill = execute_exit(90.0, 10, "SHORT", 0.001, 0.01)
    gross = gross_pnl(entry.executed_price, exit_fill.executed_price, 10, "SHORT")
    net = trade_net_pnl(gross, entry.fee, exit_fill.fee, 0)
    assert gross == (99.0 - 90.9) * 10
    assert net == gross - entry.fee - exit_fill.fee


def test_entry_and_exit_fees_are_in_trade_net_pnl():
    position, _ = open_trade(
        pd.Timestamp("2025-01-01", tz="UTC"),
        100.0,
        "LONG",
        2.0,
        pd.Timestamp("2025-01-01", tz="UTC"),
        100.0,
        1000.0,
        2.0,
        0.001,
        0.0,
        CONFIG,
    )
    balance_after, trade, _ = close_trade(position, pd.Timestamp("2025-01-02", tz="UTC"), 110.0, "test", 998.0, 0.001, 0.0, CONFIG)
    assert trade["total_fee"] == trade["entry_fee"] + trade["exit_fee"]
    assert abs((trade["balance_after"] - trade["balance_before"]) - trade["net_pnl"]) < 1e-9
    assert balance_after == trade["balance_after"]


def test_slippage_is_not_double_deducted():
    entry = execute_entry(100.0, 1, "LONG", 0.0, 0.01)
    exit_fill = execute_exit(110.0, 1, "LONG", 0.0, 0.01)
    gross = gross_pnl(entry.executed_price, exit_fill.executed_price, 1, "LONG")
    net = trade_net_pnl(gross, 0.0, 0.0, 0.0)
    assert net == gross
    assert net == 108.9 - 101.0


def test_profit_factor_uses_net_pnl():
    assert profit_factor(pd.Series([10.0, -5.0, -5.0])) == 1.0
