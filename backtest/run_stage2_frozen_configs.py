"""Run Stage 2 frozen-config regression for B1/B2/B3."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.eth_trend_engine import EthTrendEngine
from backtest.metrics import extended_summary
from backtest.stage2_config import (
    FROZEN_CONFIGS,
    assert_no_overrides,
    config_hash,
    current_git_commit,
    file_sha256,
    load_frozen_config,
    strategy_config_from_frozen,
)


OUT_ROOT = Path("backtest_results/stage2/frozen_configs")
START = "2024-12-01 00:00:00"
END = "2025-12-12 20:00:00"


def run_frozen(label: str) -> dict:
    frozen = load_frozen_config(label)
    cfg_hash = config_hash(frozen)
    config = strategy_config_from_frozen(frozen)
    assert_no_overrides(frozen, config)

    data_path = Path(frozen["data_path"])
    engine = EthTrendEngine(
        config=config,
        data_path=data_path,
        symbol=frozen["symbol"],
        start_date=START,
        end_date=END,
        initial_balance=frozen["initial_balance"],
    )
    result = engine.run(verbose=False)
    trades = pd.DataFrame(result.trades)
    equity = pd.DataFrame(result.equity_curve)
    summary = extended_summary(trades, frozen["initial_balance"], equity, START, END)

    run_metadata = {
        "label": label,
        "entry_mode": frozen["entry_mode"],
        "config_path": str(FROZEN_CONFIGS[label]),
        "config_hash": cfg_hash,
        "git_commit": current_git_commit(),
        "data_start": str(result.data_1m.index[0]),
        "data_end": str(result.data_1m.index[-1]),
        "data_file_hash": file_sha256(data_path),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    out_dir = OUT_ROOT / label
    out_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out_dir / "trades.csv", index=False)
    equity.to_csv(out_dir / "equity.csv", index=False)
    with open(out_dir / "run_metadata.json", "w", encoding="utf-8") as f:
        json.dump(run_metadata, f, indent=2, default=str)
    with open(out_dir / "frozen_config_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(frozen, f, indent=2)
    with open(out_dir / "config.sha256", "w", encoding="utf-8") as f:
        f.write(cfg_hash + "\n")

    return {**run_metadata, **summary}


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = [run_frozen(label) for label in ["B1", "B2", "B3"]]
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_ROOT / "frozen_regression_summary.csv", index=False)
    print(summary[[
        "label",
        "entry_mode",
        "config_hash",
        "total_return_pct",
        "max_drawdown_pct",
        "profit_factor",
        "total_trades",
    ]].to_string(index=False))
    print(f"Frozen-config regression saved to {OUT_ROOT}")


if __name__ == "__main__":
    main()
