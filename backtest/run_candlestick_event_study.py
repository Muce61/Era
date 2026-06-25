import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from strategy.candlestick_event_study import CandlestickEventStudy, load_csv


DEFAULT_DATA_DIR = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
DEFAULT_OUTPUT_DIR = Path("backtest_results/candlestick_event_study")


def parse_args():
    parser = argparse.ArgumentParser(description="Build candlestick event-study datasets from 1m OHLCV CSVs.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--symbols", nargs="*", help="Optional symbols, e.g. ETHUSDT BTCUSDT")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
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
    study = CandlestickEventStudy()
    frames = []
    files = iter_files(args.data_dir, args.symbols, args.limit)

    print(f"Data dir: {args.data_dir}")
    print(f"Files: {len(files)}")
    print(f"Date range: {args.start or 'full'} -> {args.end or 'full'}")

    for idx, path in enumerate(files, start=1):
        symbol = path.stem
        try:
            events = study.build_dataset(symbol, load_csv(path), start=args.start, end=args.end)
        except Exception as exc:
            print(f"[{idx}/{len(files)}] {symbol}: skipped ({exc})")
            continue
        frames.append(events)
        print(f"[{idx}/{len(files)}] {symbol}: events={len(events)}")

    all_events = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    outputs = study.write_outputs(all_events, args.output_dir)

    print("\nGenerated files:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")

    if not all_events.empty:
        print("\nPattern summary:")
        print(study.pattern_summary(all_events).to_string(index=False))


if __name__ == "__main__":
    main()
