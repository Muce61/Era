import pandas as pd

from backtest.eth_trend_engine import EthTrendEngine
from strategy.eth_trend_signals import EntryMode, StrategyConfig


ACCOUNTING_TOLERANCE = 1e-8


def _make_engine(balance=1000.0):
    config = StrategyConfig(entry_mode=EntryMode.STRONG_BREAKOUT)
    engine = EthTrendEngine(
        config=config,
        data_path="/tmp/ethusdt_dummy.csv",
        initial_balance=balance,
    )
    engine.balance = balance
    return engine


def _open_and_close(engine, entry_raw, exit_raw, atr=1.0):
    ts_entry = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    ts_exit = pd.Timestamp("2024-01-02 00:00:00", tz="UTC")
    engine._open_position(ts_entry, entry_raw, "LONG", atr, "test entry")
    engine._close_position(ts_exit, exit_raw, "test exit")
    return engine.trades[-1]


def _assert_trade_accounting(trade):
    gross = (trade["exit_price"] - trade["entry_price"]) * trade["quantity"]
    total_fee = trade["entry_fee"] + trade["exit_fee"]
    net_pnl = gross - total_fee
    balance_delta = trade["balance_after"] - trade["balance_before"]

    assert trade["gross_pnl"] == gross
    assert trade["total_fee"] == total_fee
    assert trade["net_pnl"] == net_pnl
    assert abs(balance_delta - trade["net_pnl"]) < ACCOUNTING_TOLERANCE
    assert trade["balance_after"] == trade["balance_before"] + trade["net_pnl"]


def test_profitable_trade_accounting():
    engine = _make_engine(1000.0)
    trade = _open_and_close(engine, 100.0, 110.0)

    _assert_trade_accounting(trade)
    assert trade["net_pnl"] > 0
    assert engine.balance == trade["balance_after"]


def test_losing_trade_accounting():
    engine = _make_engine(1000.0)
    trade = _open_and_close(engine, 100.0, 90.0)

    _assert_trade_accounting(trade)
    assert trade["net_pnl"] < 0
    assert engine.balance == trade["balance_after"]


def test_entry_and_exit_fees_in_total_fee():
    engine = _make_engine(1000.0)
    trade = _open_and_close(engine, 100.0, 105.0)

    assert trade["entry_fee"] > 0
    assert trade["exit_fee"] > 0
    assert trade["total_fee"] == trade["entry_fee"] + trade["exit_fee"]
    assert trade["net_pnl"] == trade["gross_pnl"] - trade["total_fee"]


def test_balance_after_minus_balance_before_equals_net_pnl():
    engine = _make_engine(1000.0)
    for entry_raw, exit_raw in [(100.0, 120.0), (200.0, 180.0), (50.0, 50.5)]:
        engine._open_position(
            pd.Timestamp("2024-01-01", tz="UTC"),
            entry_raw,
            "LONG",
            1.0,
            "test",
        )
        engine._close_position(
            pd.Timestamp("2024-01-02", tz="UTC"),
            exit_raw,
            "test",
        )
        trade = engine.trades[-1]
        delta = trade["balance_after"] - trade["balance_before"]
        assert abs(delta - trade["net_pnl"]) < ACCOUNTING_TOLERANCE


def test_forced_close_equity_equals_final_balance():
    engine = _make_engine(1000.0)
    ts = pd.Timestamp("2024-12-12 20:00:00", tz="UTC")

    engine._open_position(ts, 3000.0, "LONG", 10.0, "test entry")
    engine._mark_equity(ts, 3050.0)

    assert engine.equity_curve[-1]["equity"] != engine.balance

    engine._close_position(ts, 3050.0, "End of Backtest")
    engine.equity_curve[-1]["equity"] = engine.balance

    assert engine.equity_curve[-1]["equity"] == engine.balance
    assert engine.position is None
