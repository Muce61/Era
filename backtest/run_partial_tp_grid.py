"""Grid search: partial take-profit on B3 (ETH + BTC), vs Donchian-only baseline."""

from __future__ import annotations

import itertools
from pathlib import Path

import pandas as pd

from backtest.eth_trend_engine import EthTrendEngine
from backtest.metrics import max_drawdown, profit_factor
from backtest.stage4_config import load_stage4_frozen_config, run_config_from_label

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "backtest_results" / "partial_tp_grid"

START = "2024-01-01 00:00:00"
END = "2026-06-24 12:05:00"
MODE = "B3"

ACTIVATE_POS_PCT = [2.0, 3.0, 5.0]
CLOSE_FRACTIONS = [0.2, 0.3, 0.5]

SYMBOLS = {
    "ETHUSDT": REPO_ROOT / "backtest_results" / "stage2" / "data_audit" / "merged_ethusdt_1m.csv",
    "BTCUSDT": REPO_ROOT / "backtest_results" / "stage2" / "data_audit" / "merged_btcusdt_1m.csv",
}


def run_engine(
    symbol: str,
    data_path: Path,
    partial_tp_pos_pct: float | None = None,
    partial_tp_fraction: float | None = None,
) -> dict:
    frozen = load_stage4_frozen_config(MODE)
    config = run_config_from_label(MODE)
    engine = EthTrendEngine(
        config=config,
        data_path=data_path,
        symbol=symbol,
        start_date=START,
        end_date=END,
        initial_balance=frozen["initial_balance"],
        partial_tp_pos_pct=partial_tp_pos_pct,
        partial_tp_fraction=partial_tp_fraction,
    )
    engine.run(verbose=False)
    trades_df = pd.DataFrame(engine.trades)
    equity_df = pd.DataFrame(engine.equity_curve)
    initial = engine.initial_balance
    final = engine.balance
    total_return = (final / initial - 1) * 100
    mdd = max_drawdown(equity_df["equity"]) * 100 if not equity_df.empty else 0.0
    pf = profit_factor(trades_df["net_pnl"]) if not trades_df.empty else 0.0
    win_rate = (
        float((trades_df["net_pnl"] > 0).mean() * 100) if not trades_df.empty else 0.0
    )
    partial_trades = int(trades_df.get("partial_tp_count", pd.Series(dtype=int)).fillna(0).gt(0).sum()) if not trades_df.empty else 0

    return {
        "symbol": symbol,
        "mode": MODE,
        "partial_tp_pos_pct": partial_tp_pos_pct,
        "partial_tp_fraction": partial_tp_fraction,
        "label": _grid_label(partial_tp_pos_pct, partial_tp_fraction),
        "trades": len(trades_df),
        "partial_tp_trades": partial_trades,
        "initial_balance": initial,
        "final_balance": final,
        "total_return_pct": total_return,
        "max_drawdown_pct": mdd,
        "profit_factor": pf,
        "win_rate_pct": win_rate,
        "avg_trade_net": float(trades_df["net_pnl"].mean()) if not trades_df.empty else 0.0,
    }


def _grid_label(pos_pct: float | None, frac: float | None) -> str:
    if pos_pct is None:
        return "baseline"
    return f"tp{pos_pct:g}pct_pos_close{int(frac * 100)}pct"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for symbol, data_path in SYMBOLS.items():
        if not data_path.exists():
            raise FileNotFoundError(f"Missing data for {symbol}: {data_path}")

        baseline = run_engine(symbol, data_path)
        rows.append(baseline)
        print(
            f"{symbol} baseline: return={baseline['total_return_pct']:.1f}% "
            f"PF={baseline['profit_factor']:.2f} trades={baseline['trades']}"
        )

        for pos_pct, frac in itertools.product(ACTIVATE_POS_PCT, CLOSE_FRACTIONS):
            result = run_engine(symbol, data_path, pos_pct, frac)
            result["delta_return_vs_baseline"] = result["total_return_pct"] - baseline["total_return_pct"]
            result["delta_pf_vs_baseline"] = result["profit_factor"] - baseline["profit_factor"]
            rows.append(result)
            print(
                f"  {result['label']}: return={result['total_return_pct']:.1f}% "
                f"(Δ{result['delta_return_vs_baseline']:+.1f}%) "
                f"PF={result['profit_factor']:.2f} partial_trades={result['partial_tp_trades']}"
            )

    summary = pd.DataFrame(rows)
    summary = summary.sort_values(["symbol", "total_return_pct"], ascending=[True, False])
    summary.to_csv(OUT_DIR / "partial_tp_grid_summary.csv", index=False)

    # Combined view: rank by symbol
    best = summary.groupby("symbol").head(3)
    best.to_csv(OUT_DIR / "partial_tp_grid_top3_per_symbol.csv", index=False)

    lines = [
        "# Partial TP Grid — B3 ETH + BTC",
        "",
        f"区间: {START} ~ {END}",
        "",
        "规则: 仓位浮盈达 X%（相对开仓前权益）时，平仓 Y% 数量；余仓仍用 Donchian + 3×ATR。",
        "每笔最多触发一次 partial TP。",
        "",
        "## Baseline",
        "",
    ]
    for symbol in SYMBOLS:
        b = summary[(summary["symbol"] == symbol) & (summary["label"] == "baseline")].iloc[0]
        lines.append(
            f"- {symbol}: return {b['total_return_pct']:.2f}%, PF {b['profit_factor']:.2f}, "
            f"MDD {b['max_drawdown_pct']:.2f}%, trades {int(b['trades'])}"
        )

    lines.extend(["", "## Top configs per symbol", ""])
    for symbol in SYMBOLS:
        sub = summary[summary["symbol"] == symbol].head(5)
        lines.append(f"### {symbol}")
        lines.append(sub[["label", "total_return_pct", "delta_return_vs_baseline", "profit_factor", "max_drawdown_pct", "partial_tp_trades"]].to_markdown(index=False))
        lines.append("")

    (OUT_DIR / "partial_tp_grid_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWritten to {OUT_DIR}")


if __name__ == "__main__":
    main()
