"""
Export stage-1 baseline B1 artifacts without modifying trading logic.

Runs EthTrendFollowingBacktest as-is and writes:
  backtest_results/stage1/baseline_B1/
    trades.csv, equity.csv, metrics.json, run_config.json
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.eth_trend_engine import EthTrendEngine
from strategy.eth_trend_signals import EntryMode, StrategyConfig

BASELINE_DIR = Path("backtest_results/stage1/baseline_B1")


def _compute_metrics(engine: EthTrendEngine) -> dict:
    trades = pd.DataFrame(engine.trades)
    equity = pd.DataFrame(engine.equity_curve)
    final_balance = engine.balance
    total_return = (final_balance / engine.initial_balance - 1) * 100

    metrics = {
        "initial_balance": engine.initial_balance,
        "final_balance": round(final_balance, 2),
        "total_return_pct": round(total_return, 2),
        "total_trades": len(trades),
    }

    if not trades.empty:
        wins = trades[trades["net_pnl"] > 0]
        losses = trades[trades["net_pnl"] <= 0]
        profit_factor = (
            wins["net_pnl"].sum() / abs(losses["net_pnl"].sum())
            if not losses.empty
            else float("inf")
        )
        metrics.update({
            "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_trade": round(trades["net_pnl"].mean(), 2),
            "best_trade": round(trades["net_pnl"].max(), 2),
            "worst_trade": round(trades["net_pnl"].min(), 2),
            "long_trades": int((trades["side"] == "LONG").sum()),
        })

    if not equity.empty:
        peak = equity["equity"].cummax()
        drawdown = equity["equity"] / peak - 1
        metrics["max_drawdown_pct"] = round(drawdown.min() * 100, 2)

    return metrics


def _build_run_config(engine: EthTrendEngine) -> dict:
    cfg = engine.config
    data_1m = engine.data_1m
    signals = engine.signals_15m
    warmup_start = signals.index[0]
    backtest_1m = data_1m.loc[warmup_start:]
    return {
        "baseline_id": "B1",
        "strategy": "eth_trend_following_2x",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "symbol": engine.symbol,
        "data_path": str(engine.data_path),
        "data_start": str(data_1m.index[0]),
        "data_end": str(data_1m.index[-1]),
        "raw_execution_candle_count": len(data_1m),
        "backtest_execution_start": str(backtest_1m.index[0]),
        "backtest_execution_end": str(backtest_1m.index[-1]),
        "backtest_execution_candle_count": len(backtest_1m),
        "signal_candle_start": str(signals.index[0]),
        "signal_candle_end": str(signals.index[-1]),
        "signal_candle_count": len(signals),
        "requested_start_date": engine.start_date,
        "requested_end_date": engine.end_date,
        "signal_timeframe": cfg.signal_timeframe,
        "leverage": cfg.leverage,
        "initial_balance": engine.initial_balance,
        "fee_rate_per_side": cfg.fee_rate,
        "slippage_rate_per_side": cfg.slippage_rate,
        "ema_fast": cfg.ema_fast,
        "ema_slow": cfg.ema_slow,
        "donchian_entry": cfg.donchian_entry,
        "donchian_exit": cfg.donchian_exit,
        "atr_period": cfg.atr_period,
        "atr_stop_mult": cfg.atr_stop_mult,
        "entry_mode": cfg.entry_mode.value,
        "direction": "LONG_ONLY",
        "entry_rules": {
            "donchian_breakout_bars": cfg.donchian_entry,
            "ema_fast_above_slow": True,
            "bullish_candle": True,
            "body_ratio_min": 0.35,
            "close_location_min": 0.70,
            "upper_shadow_ratio_max": 0.30,
            "volume_vs_ma20": True,
        },
        "exit_rules": {
            "donchian_exit_bars": cfg.donchian_exit,
            "atr_stop_mult": cfg.atr_stop_mult,
        },
        "runner_script": "backtest/run_eth_trend_following_2x.py",
        "export_script": "backtest/export_baseline_B1.py",
    }


def main():
    config = StrategyConfig(entry_mode=EntryMode.STRONG_BREAKOUT)
    engine = EthTrendEngine(
        config=config,
        data_path="/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv",
        start_date="2024-12-01 00:00:00",
        end_date="2025-12-12 20:00:00",
        initial_balance=1000.0,
    )
    engine.run(verbose=False)

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    trades = pd.DataFrame(engine.trades)
    equity = pd.DataFrame(engine.equity_curve)
    metrics = _compute_metrics(engine)
    run_config = _build_run_config(engine)

    trades.to_csv(BASELINE_DIR / "trades.csv", index=False)
    equity.to_csv(BASELINE_DIR / "equity.csv", index=False)

    with open(BASELINE_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    with open(BASELINE_DIR / "run_config.json", "w") as f:
        json.dump(run_config, f, indent=2)

    print(f"Baseline B1 exported to: {BASELINE_DIR}")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
