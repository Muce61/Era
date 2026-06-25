import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from strategy.multitimeframe_candlestick import MultiTimeframeCandlestickResearch, load_csv


DEFAULT_DATA_DIR = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
DEFAULT_OUTPUT_DIR = Path("backtest_results/candlestick_mtf")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run A/B/C multi-timeframe candlestick research on 1m OHLCV CSV data."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--symbols", nargs="*", help="Optional symbol list, e.g. BTCUSDT ETHUSDT")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of CSV files for quick tests")
    parser.add_argument("--start", default=None, help="Inclusive UTC start, e.g. 2025-06-01")
    parser.add_argument("--end", default=None, help="Inclusive UTC end, e.g. 2025-07-01")
    parser.add_argument("--initial-balance", type=float, default=10000.0)
    return parser.parse_args()


def iter_files(data_dir: Path, symbols: list[str] | None, limit: int | None):
    if symbols:
        files = [data_dir / f"{symbol.upper()}.csv" for symbol in symbols]
    else:
        files = sorted(data_dir.glob("*.csv"))
    files = [path for path in files if path.exists()]
    return files[:limit] if limit else files


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    research = MultiTimeframeCandlestickResearch()
    all_trades = {"A": [], "B": [], "C": []}
    files = iter_files(args.data_dir, args.symbols, args.limit)

    print(f"Data dir: {args.data_dir}")
    print(f"Symbols/files: {len(files)}")
    print(f"Date range: {args.start or 'full'} -> {args.end or 'full'}")
    print("Groups:")
    print("  A = market direction + 15m key location")
    print("  B = A + 5m hammer/engulfing candle event + volume")
    print("  C = B + 1m breakout confirmation")

    for idx, path in enumerate(files, start=1):
        symbol = path.stem
        try:
            df = load_csv(path)
            trades_by_group = research.run_symbol(symbol, df, start=args.start, end=args.end)
        except Exception as exc:
            print(f"[{idx}/{len(files)}] {symbol}: skipped ({exc})")
            continue

        counts = {group: len(trades) for group, trades in trades_by_group.items()}
        print(f"[{idx}/{len(files)}] {symbol}: A={counts['A']} B={counts['B']} C={counts['C']}")
        for group, trades in trades_by_group.items():
            all_trades[group].extend(trades)

    summary_rows = []
    for group in ["A", "B", "C"]:
        trades = sorted(all_trades[group], key=lambda x: x["exit_time"])
        summary = research.summarize(trades, initial_balance=args.initial_balance)
        summary["group"] = group
        summary_rows.append(summary)

        trades_path = args.output_dir / f"trades_group_{group}.csv"
        pd.DataFrame(trades).to_csv(trades_path, index=False)

    summary_df = pd.DataFrame(summary_rows)[
        ["group", "trades", "final_balance", "return_pct", "win_rate", "profit_factor", "max_drawdown_pct"]
    ]
    summary_path = args.output_dir / "summary.csv"
    summary_df.to_csv(summary_path, index=False)

    print("\nSummary")
    print(summary_df.to_string(index=False))
    print(f"\nSaved summary: {summary_path}")
    print(f"Saved trades:  {args.output_dir}/trades_group_[A|B|C].csv")


if __name__ == "__main__":
    main()
