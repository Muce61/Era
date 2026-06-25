"""Shared ETH trend-following backtest execution engine."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.metrics import max_drawdown, profit_factor, summarize_trades, extended_summary
from backtest.position_sizing import compute_quantity
from strategy.eth_trend_signals import (
    EntryMode,
    StrategyConfig,
    build_signal_frame,
    is_signal_bar_close,
    load_ohlcv_1m,
    signal_bar_timestamp,
)
from strategy.breakout_state import BreakoutStateMachine
from strategy.entry_handlers import EntryContext, evaluate_entry
from strategy.hikkake_tracker import HikkakeSetupTracker
from strategy.trend_segment_state import TrendSegmentTracker


@dataclass
class BacktestResult:
    trades: list[dict]
    equity_curve: list[dict]
    balance: float
    initial_balance: float
    data_1m: pd.DataFrame
    signals_15m: pd.DataFrame
    config: StrategyConfig
    symbol: str


class EthTrendEngine:
    """
    Signal layer: 15m Donchian breakout with configurable candlestick entry mode.
    Execution layer: 1m candles, next-bar open fills after 15m close confirmation.
    Direction: long only.
    """

    def __init__(
        self,
        config: StrategyConfig,
        data_path: Path | str,
        symbol: str = "ETHUSDT",
        start_date: str = "2024-12-01 00:00:00",
        end_date: str = "2025-12-12 20:00:00",
        initial_balance: float = 1000.0,
        partial_tp_pos_pct: float | None = None,
        partial_tp_fraction: float | None = None,
    ):
        self.config = config
        self.data_path = Path(data_path)
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.initial_balance = initial_balance
        self.partial_tp_pos_pct = partial_tp_pos_pct
        self.partial_tp_fraction = partial_tp_fraction

        self.balance = initial_balance
        self.position = None
        self.pending_action = None
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.data_1m: pd.DataFrame | None = None
        self.signals_15m: pd.DataFrame | None = None
        self.breakout_sm = BreakoutStateMachine()
        self.hikkake_tracker = HikkakeSetupTracker()
        self.trend_segment_tracker = TrendSegmentTracker()
        self._signal_bar_index: dict[pd.Timestamp, int] = {}

    def load_data(self) -> None:
        if not self.data_path.exists():
            raise FileNotFoundError(f"Data file not found: {self.data_path}")

        self.data_1m = load_ohlcv_1m(self.data_path, self.start_date, self.end_date)
        self.signals_15m = build_signal_frame(self.data_1m, self.config)
        self._signal_bar_index = {ts: i for i, ts in enumerate(self.signals_15m.index)}

    def run(self, verbose: bool = True) -> BacktestResult:
        self.load_data()
        warmup_start = self.signals_15m.index[0]
        data_1m = self.data_1m.loc[warmup_start:].copy()

        if verbose:
            self._print_header(data_1m)

        for current_time, candle in data_1m.iterrows():
            self._execute_pending_action(current_time, candle["open"])
            self._manage_position(current_time, candle)

            if is_signal_bar_close(current_time):
                signal_time = signal_bar_timestamp(current_time, self.config.signal_timeframe)
                if signal_time in self.signals_15m.index:
                    self._process_signal(signal_time)

            self._mark_equity(current_time, candle["close"])

        if self.position is not None:
            last_time = data_1m.index[-1]
            last_price = data_1m.iloc[-1]["close"]
            self._close_position(last_time, last_price, "End of Backtest")
            if self.equity_curve:
                self.equity_curve[-1]["equity"] = self.balance

        if verbose:
            self._report()

        return BacktestResult(
            trades=self.trades,
            equity_curve=self.equity_curve,
            balance=self.balance,
            initial_balance=self.initial_balance,
            data_1m=self.data_1m,
            signals_15m=self.signals_15m,
            config=self.config,
            symbol=self.symbol,
        )

    def _process_signal(self, signal_time: pd.Timestamp) -> None:
        row = self.signals_15m.loc[signal_time]
        has_position = self.position is not None
        self.breakout_sm.on_bar_close(signal_time, row, has_position=has_position)
        self.trend_segment_tracker.on_bar_close(signal_time, row, has_position=has_position)

        bar_idx = self._signal_bar_index.get(signal_time, -1)
        ctx = EntryContext(
            signal_time=signal_time,
            row=row,
            bar_idx=bar_idx,
            signals_15m=self.signals_15m,
            has_position=has_position,
            breakout_sm=self.breakout_sm,
            hikkake_tracker=self.hikkake_tracker,
            trend_segment_tracker=self.trend_segment_tracker,
        )
        entry_signal = evaluate_entry(self.config, ctx)

        if entry_signal is None:
            if has_position and row["long_exit"]:
                self.pending_action = {"action": "CLOSE", "reason": "Donchian Long Exit"}
            return

        if has_position:
            return

        self.pending_action = {
            "action": "OPEN",
            "side": "LONG",
            "atr": entry_signal.atr,
            "reason": entry_signal.reason,
            "metadata": entry_signal.metadata,
        }

    def _execute_pending_action(self, timestamp: pd.Timestamp, open_price: float) -> None:
        if self.pending_action is None:
            return

        action = self.pending_action
        self.pending_action = None

        if action["action"] == "CLOSE":
            self._close_position(timestamp, open_price, action["reason"])
        elif action["action"] == "OPEN":
            self._open_position(
                timestamp,
                open_price,
                action["side"],
                action["atr"],
                action["reason"],
                action.get("metadata", {}),
            )

    def _open_position(
        self,
        timestamp: pd.Timestamp,
        price: float,
        side: str,
        atr: float,
        reason: str,
        metadata: dict | None = None,
    ) -> None:
        cfg = self.config
        if self.balance <= 0 or not np.isfinite(atr) or atr <= 0:
            return

        balance_before = self.balance
        entry_price = price * (1 + cfg.slippage_rate)
        stop_loss = entry_price - (atr * cfg.atr_stop_mult)

        sizing = compute_quantity(
            balance_before,
            entry_price,
            stop_loss,
            cfg.leverage,
            cfg.risk_fraction,
            cfg.position_sizing_mode,
        )
        quantity = sizing["quantity"]
        if quantity <= 0:
            return

        entry_fee = entry_price * quantity * cfg.fee_rate

        self.balance -= entry_fee
        if self.balance <= 0:
            self.position = None
            return

        self.position = {
            "side": side,
            "entry_time": timestamp,
            "entry_price": entry_price,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "highest_price": entry_price,
            "lowest_price": entry_price,
            "entry_reason": reason,
            "balance_before": balance_before,
            "entry_fee": entry_fee,
            "entry_balance_after_fee": self.balance,
            "entry_atr": atr,
            "entry_metadata": metadata or {},
            "risk_fraction": sizing["risk_fraction"],
            "risk_amount": sizing["risk_amount"],
            "stop_distance": sizing["stop_distance"],
            "notional": sizing["notional"],
            "effective_leverage": sizing["effective_leverage"],
            "quantity_by_risk": sizing["quantity_by_risk"],
            "quantity_by_leverage": sizing["quantity_by_leverage"],
            "position_sizing_mode": sizing["position_sizing_mode"],
            "original_quantity": quantity,
            "partial_tp_done": False,
            "partial_closes": [],
        }

        if self.config.entry_mode == EntryMode.PULLBACK_ENGULFING:
            self.breakout_sm.mark_entered()
        elif self.config.entry_mode == EntryMode.BULLISH_HIKKAKE:
            self.breakout_sm.mark_entered()
            self.hikkake_tracker.mark_entered()

    def _manage_position(self, timestamp: pd.Timestamp, candle: pd.Series) -> None:
        if self.position is None:
            return

        pos = self.position
        if candle["open"] <= pos["stop_loss"]:
            self._close_position(timestamp, candle["open"], "Gap Stop Loss")
            return
        if candle["low"] <= pos["stop_loss"]:
            self._close_position(timestamp, pos["stop_loss"], "ATR Stop Loss")
            return
        pos["highest_price"] = max(pos["highest_price"], candle["high"])
        pos["lowest_price"] = min(pos["lowest_price"], candle["low"])
        self._maybe_partial_take_profit(timestamp, candle)

    def _partial_tp_target_price(self, pos: dict) -> float:
        """Price level where position return on entry equity reaches partial_tp_pos_pct."""
        entry_price = pos["entry_price"]
        balance_before = pos["balance_before"]
        notional = pos.get("notional", 0.0)
        if entry_price <= 0 or balance_before <= 0 or notional <= 0:
            return entry_price
        price_move = self.partial_tp_pos_pct / 100 * balance_before / notional
        return entry_price * (1 + price_move)

    def _maybe_partial_take_profit(self, timestamp: pd.Timestamp, candle: pd.Series) -> None:
        if self.position is None:
            return
        if self.partial_tp_pos_pct is None or self.partial_tp_fraction is None:
            return
        if self.partial_tp_fraction <= 0 or self.partial_tp_fraction >= 1:
            return

        pos = self.position
        if pos.get("partial_tp_done"):
            return

        target_price = self._partial_tp_target_price(pos)
        if candle["high"] < target_price:
            return

        original_qty = pos.get("original_quantity", pos["quantity"])
        qty_close = original_qty * self.partial_tp_fraction
        if qty_close <= 0 or pos["quantity"] <= qty_close:
            return

        reason = f"Partial TP ({self.partial_tp_pos_pct:.1f}% pos @ {self.partial_tp_fraction * 100:.0f}%)"
        self._partial_close(timestamp, target_price, qty_close, reason)
        pos["partial_tp_done"] = True

    def _partial_close(self, timestamp: pd.Timestamp, price: float, quantity: float, reason: str) -> None:
        if self.position is None or quantity <= 0:
            return

        pos = self.position
        cfg = self.config
        exit_price = price * (1 - cfg.slippage_rate)
        gross_pnl = (exit_price - pos["entry_price"]) * quantity
        exit_fee = exit_price * quantity * cfg.fee_rate
        net_pnl = gross_pnl - exit_fee
        self.balance += net_pnl
        pos["quantity"] -= quantity
        pos.setdefault("partial_closes", []).append({
            "time": timestamp,
            "quantity": quantity,
            "exit_price": exit_price,
            "gross_pnl": gross_pnl,
            "exit_fee": exit_fee,
            "net_pnl": net_pnl,
            "reason": reason,
        })

    def _close_position(self, timestamp: pd.Timestamp, price: float, reason: str) -> None:
        if self.position is None:
            return

        pos = self.position
        cfg = self.config
        balance_before = pos["balance_before"]
        entry_fee = pos["entry_fee"]
        exit_price = price * (1 - cfg.slippage_rate)
        remaining_qty = pos["quantity"]
        gross_pnl = (exit_price - pos["entry_price"]) * remaining_qty
        exit_fee = exit_price * remaining_qty * cfg.fee_rate
        partial_closes = pos.get("partial_closes", [])
        partial_gross = sum(p["gross_pnl"] for p in partial_closes)
        partial_exit_fee = sum(p["exit_fee"] for p in partial_closes)
        total_gross = gross_pnl + partial_gross
        total_fee = entry_fee + exit_fee + partial_exit_fee
        self.balance += gross_pnl - exit_fee
        balance_after = self.balance
        net_pnl = balance_after - balance_before

        entry_price = pos["entry_price"]
        entry_atr = pos.get("entry_atr", 0.0) or 0.0
        mfe_price = pos["highest_price"] - entry_price
        mae_price = pos["lowest_price"] - entry_price
        mfe_pct = mfe_price / entry_price if entry_price else 0.0
        mae_pct = mae_price / entry_price if entry_price else 0.0
        mfe_atr = mfe_price / entry_atr if entry_atr > 0 else 0.0
        mae_atr = mae_price / entry_atr if entry_atr > 0 else 0.0
        metadata = pos.get("entry_metadata", {}) or {}

        trade = {
            "symbol": self.symbol,
            "side": pos["side"],
            "entry_time": pos["entry_time"],
            "exit_time": timestamp,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": pos.get("original_quantity", remaining_qty),
            "balance_before": balance_before,
            "entry_fee": entry_fee,
            "entry_balance_after_fee": pos["entry_balance_after_fee"],
            "gross_pnl": total_gross,
            "exit_fee": exit_fee + partial_exit_fee,
            "total_fee": total_fee,
            "net_pnl": net_pnl,
            "balance_after": balance_after,
            "return_pct_on_equity": net_pnl / max(balance_before, 1e-12) * 100,
            "reason": reason,
            "partial_tp_count": len(partial_closes),
            "partial_tp_net_pnl": sum(p["net_pnl"] for p in partial_closes),
            "partial_tp_pos_pct": self.partial_tp_pos_pct,
            "partial_tp_fraction": self.partial_tp_fraction,
            "entry_reason": pos["entry_reason"],
            "duration": timestamp - pos["entry_time"],
            "entry_mode": self.config.entry_mode.value,
            "entry_atr": entry_atr,
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "mfe_atr": mfe_atr,
            "mae_atr": mae_atr,
            "risk_fraction": pos.get("risk_fraction", 0.0),
            "risk_amount": pos.get("risk_amount", 0.0),
            "stop_distance": pos.get("stop_distance", 0.0),
            "notional": pos.get("notional", 0.0),
            "effective_leverage": pos.get("effective_leverage", 0.0),
            "quantity_by_risk": pos.get("quantity_by_risk", 0.0),
            "quantity_by_leverage": pos.get("quantity_by_leverage", 0.0),
            "position_sizing_mode": pos.get("position_sizing_mode", self.config.position_sizing_mode),
        }
        for key, value in metadata.items():
            if key not in trade:
                trade[key] = value

        self.trades.append(trade)

        self.position = None

    def _mark_equity(self, timestamp: pd.Timestamp, price: float) -> None:
        unrealized = 0.0
        if self.position is not None:
            pos = self.position
            unrealized = (price - pos["entry_price"]) * pos["quantity"]

        self.equity_curve.append({
            "timestamp": timestamp,
            "equity": self.balance + unrealized,
        })

    def _print_header(self, data_1m: pd.DataFrame) -> None:
        cfg = self.config
        print("=" * 60)
        print("ETH Trend Following Engine")
        print("=" * 60)
        print(f"Symbol: {self.symbol}")
        print(f"Entry mode: {cfg.entry_mode.value}")
        print(f"Leverage: {cfg.leverage}x")
        print(f"Signal timeframe: {cfg.signal_timeframe}")
        print(f"Execution timeframe: 1m")
        print(f"Fees: {cfg.fee_rate * 100:.2f}% per side | Slippage: {cfg.slippage_rate * 100:.2f}% per side")
        print("=" * 60)
        print(f"Backtesting {self.symbol}: {data_1m.index[0]} -> {data_1m.index[-1]}")
        print(f"Signal candles: {len(self.signals_15m):,} | Execution candles: {len(data_1m):,}")

    def _report(self) -> None:
        trades_df = pd.DataFrame(self.trades)
        equity_df = pd.DataFrame(self.equity_curve)
        final_balance = self.balance
        total_return = (final_balance / self.initial_balance - 1) * 100

        print("\n" + "=" * 60)
        print("ETH TREND FOLLOWING RESULTS")
        print("=" * 60)
        print(f"Initial Balance: ${self.initial_balance:.2f}")
        print(f"Final Balance:   ${final_balance:.2f}")
        print(f"Total Return:    {total_return:.2f}%")
        print(f"Total Trades:    {len(trades_df)}")

        if not trades_df.empty:
            wins = trades_df[trades_df["net_pnl"] > 0]
            losses = trades_df[trades_df["net_pnl"] <= 0]
            pf = profit_factor(trades_df["net_pnl"])
            print(f"Win Rate:        {len(wins) / len(trades_df) * 100:.2f}%")
            print(f"Profit Factor:   {pf:.2f}")
            print(f"Avg Trade:       ${trades_df['net_pnl'].mean():.2f}")
            print(f"Best Trade:      ${trades_df['net_pnl'].max():.2f}")
            print(f"Worst Trade:     ${trades_df['net_pnl'].min():.2f}")
            print(f"Long Trades:     {(trades_df['side'] == 'LONG').sum()}")

        if not equity_df.empty:
            print(f"Max Drawdown:    {max_drawdown(equity_df['equity']) * 100:.2f}%")

    def summarize(self) -> dict:
        trades_df = pd.DataFrame(self.trades)
        equity_df = pd.DataFrame(self.equity_curve)
        summary = summarize_trades(trades_df, self.initial_balance, equity_df)
        summary["entry_mode"] = self.config.entry_mode.value
        if not trades_df.empty:
            summary["best_trade"] = float(trades_df["net_pnl"].max())
            summary["worst_trade"] = float(trades_df["net_pnl"].min())
            summary["long_trades"] = int((trades_df["side"] == "LONG").sum())
        return summary
