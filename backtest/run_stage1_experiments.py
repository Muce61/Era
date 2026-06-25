"""Unified stage-1 experiment runner for B0–B3."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.eth_trend_engine import EthTrendEngine
from backtest.metrics import extended_summary, max_drawdown
from strategy.eth_trend_signals import EntryMode, StrategyConfig

DEFAULT_DATA_PATH = Path("/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv")
DEFAULT_START = "2024-12-01 00:00:00"
DEFAULT_END = "2025-12-12 20:00:00"
RESULTS_ROOT = Path("backtest_results/stage1")

EXPERIMENTS = {
    "B0": EntryMode.NO_CANDLE,
    "B1": EntryMode.STRONG_BREAKOUT,
    "B2": EntryMode.PULLBACK_ENGULFING,
    "B3": EntryMode.BULLISH_HIKKAKE,
}


def run_single(label: str, mode: EntryMode, output_dir: Path) -> dict:
    config = StrategyConfig(entry_mode=mode)
    engine = EthTrendEngine(
        config=config,
        data_path=DEFAULT_DATA_PATH,
        start_date=DEFAULT_START,
        end_date=DEFAULT_END,
        initial_balance=1000.0,
    )
    engine.run(verbose=True)
    trades_df = pd.DataFrame(engine.trades)
    equity_df = pd.DataFrame(engine.equity_curve)
    summary = extended_summary(trades_df, 1000.0, equity_df, DEFAULT_START, DEFAULT_END)
    summary["entry_mode"] = mode.value
    summary["label"] = label

    output_dir.mkdir(parents=True, exist_ok=True)
    trades_df.to_csv(output_dir / "trades.csv", index=False)
    equity_df.to_csv(output_dir / "equity.csv", index=False)

    config_dict = {
        "label": label,
        "entry_mode": mode.value,
        "data_path": str(DEFAULT_DATA_PATH),
        "start_date": DEFAULT_START,
        "end_date": DEFAULT_END,
        "initial_balance": 1000.0,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "leverage": config.leverage,
        "ema_fast": config.ema_fast,
        "ema_slow": config.ema_slow,
        "donchian_entry": config.donchian_entry,
        "donchian_exit": config.donchian_exit,
        "atr_period": config.atr_period,
        "atr_stop_mult": config.atr_stop_mult,
        "fee_rate": config.fee_rate,
        "slippage_rate": config.slippage_rate,
        "signal_timeframe": config.signal_timeframe,
        "position_sizing_mode": config.position_sizing_mode,
        "risk_fraction": config.risk_fraction,
    }

    with open(output_dir / "metrics.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    with open(output_dir / "config.json", "w") as f:
        json.dump(config_dict, f, indent=2)

    return summary, trades_df, equity_df


def build_exit_reason_summary(all_trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for reason, grp in all_trades.groupby("reason"):
        pnl = grp["net_pnl"]
        rows.append({
            "reason": reason,
            "trade_count": len(grp),
            "win_rate": (pnl > 0).mean() * 100 if len(grp) else 0,
            "net_pnl": pnl.sum(),
            "avg_pnl": pnl.mean(),
            "avg_duration_minutes": grp["duration"].apply(lambda x: x.total_seconds() / 60).mean(),
        })
    return pd.DataFrame(rows)


def build_monthly_returns(equity_df: pd.DataFrame, label: str) -> pd.DataFrame:
    eq = equity_df.copy()
    eq["timestamp"] = pd.to_datetime(eq["timestamp"])
    eq = eq.set_index("timestamp")
    monthly = eq["equity"].resample("ME").last().pct_change()
    return pd.DataFrame({"label": label, "month": monthly.index.astype(str), "return_pct": monthly.values * 100})


def plot_equity_comparison(equities: dict[str, pd.DataFrame], out_path: Path):
    fig, ax = plt.subplots(figsize=(12, 6))
    ymin, ymax = None, None
    for label, eq in equities.items():
        eq = eq.copy()
        eq["timestamp"] = pd.to_datetime(eq["timestamp"])
        normalized = eq["equity"] / eq["equity"].iloc[0] * 1000
        ymin = min(ymin or normalized.min(), normalized.min())
        ymax = max(ymax or normalized.max(), normalized.max())
        ax.plot(eq["timestamp"], normalized, label=label)
    ax.set_ylim(ymin * 0.95, ymax * 1.05)
    ax.set_title("Equity Comparison B0–B3 (normalized to 1000)")
    ax.set_ylabel("Equity")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_drawdown_comparison(equities: dict[str, pd.DataFrame], out_path: Path):
    fig, ax = plt.subplots(figsize=(12, 6))
    ymin, ymax = 0, 0
    for label, eq in equities.items():
        eq = eq.copy()
        eq["timestamp"] = pd.to_datetime(eq["timestamp"])
        peak = eq["equity"].cummax()
        dd = eq["equity"] / peak - 1
        ymin = min(ymin, dd.min())
        ymax = max(ymax, dd.max())
        ax.plot(eq["timestamp"], dd * 100, label=label)
    ax.set_ylim(ymin * 100 * 1.05, ymax * 100 * 1.05 + 1)
    ax.set_title("Drawdown Comparison B0–B3")
    ax.set_ylabel("Drawdown %")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    summaries = []
    equities = {}
    all_trades = []
    monthly_parts = []

    for label, mode in EXPERIMENTS.items():
        print(f"\n>>> Running {label} ({mode.value})")
        out_dir = RESULTS_ROOT / label
        summary, trades_df, equity_df = run_single(label, mode, out_dir)
        summaries.append(summary)
        equities[label] = equity_df
        if not trades_df.empty:
            trades_df = trades_df.copy()
            trades_df["label"] = label
            all_trades.append(trades_df)
        monthly_parts.append(build_monthly_returns(equity_df, label))

    experiment_summary = pd.DataFrame(summaries)
    experiment_summary.to_csv(RESULTS_ROOT / "experiment_summary.csv", index=False)

    if all_trades:
        trades_all = pd.concat(all_trades, ignore_index=True)
        exit_summary = build_exit_reason_summary(trades_all)
        exit_summary.to_csv(RESULTS_ROOT / "exit_reason_summary.csv", index=False)

    monthly = pd.concat(monthly_parts, ignore_index=True)
    monthly.to_csv(RESULTS_ROOT / "monthly_returns.csv", index=False)

    plot_equity_comparison(equities, RESULTS_ROOT / "equity_comparison.png")
    plot_drawdown_comparison(equities, RESULTS_ROOT / "drawdown_comparison.png")

    print(f"\nAll results saved to {RESULTS_ROOT}")
    print(experiment_summary[["label", "total_return_pct", "max_drawdown_pct", "profit_factor", "total_trades"]].to_string())


if __name__ == "__main__":
    main()
