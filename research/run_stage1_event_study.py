"""Run stage-1 event study for all entry modes."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from research.event_study import run_event_study

DATA_PATH = "/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv"
START = "2024-12-01 00:00:00"
END = "2025-12-12 20:00:00"
OUT = Path("backtest_results/stage1")


def main():
    detail, summary = run_event_study(DATA_PATH, START, END)
    OUT.mkdir(parents=True, exist_ok=True)
    detail.to_csv(OUT / "event_study_detail.csv", index=False)
    summary.to_csv(OUT / "event_study_summary.csv", index=False)
    print(f"Event study: {len(detail)} signals")
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    main()
