import argparse
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_TRADES_DIR = Path("backtest_results/candlestick_mtf")
DEFAULT_OUTPUT = Path("backtest_results/candlestick_event_study/confirmation_random_baseline.csv")


def profit_factor(returns: pd.Series) -> float:
    wins = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()
    if losses == 0:
        return np.inf if wins > 0 else 0.0
    return abs(wins / losses)


def max_drawdown(returns: pd.Series) -> float:
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    return ((equity - peak) / peak).min()


def metrics(label: str, returns: pd.Series) -> dict:
    return {
        "sample": label,
        "trades": len(returns),
        "mean_return": returns.mean(),
        "median_return": returns.median(),
        "win_rate": (returns > 0).mean(),
        "pf": profit_factor(returns),
        "max_drawdown": max_drawdown(returns),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Random-sample B trades to test whether C improved per-trade quality.")
    parser.add_argument("--trades-dir", type=Path, default=DEFAULT_TRADES_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main():
    args = parse_args()
    b = pd.read_csv(args.trades_dir / "trades_group_B.csv")
    c = pd.read_csv(args.trades_dir / "trades_group_C.csv")
    b_returns = b["return_on_equity"]
    c_returns = c["return_on_equity"]
    sample_size = len(c_returns)

    rng = np.random.default_rng(args.seed)
    rows = [metrics("C_actual", c_returns)]
    sampled = []
    for i in range(args.iterations):
        idx = rng.choice(len(b_returns), size=sample_size, replace=False)
        sampled_returns = b_returns.iloc[idx].reset_index(drop=True)
        row = metrics(f"B_random_{i + 1}", sampled_returns)
        sampled.append(row)
        rows.append(row)

    sampled_df = pd.DataFrame(sampled)
    rows.append(
        {
            "sample": "B_random_mean",
            "trades": sample_size,
            "mean_return": sampled_df["mean_return"].mean(),
            "median_return": sampled_df["median_return"].mean(),
            "win_rate": sampled_df["win_rate"].mean(),
            "pf": sampled_df["pf"].replace([np.inf, -np.inf], np.nan).mean(),
            "max_drawdown": sampled_df["max_drawdown"].mean(),
        }
    )
    rows.append(
        {
            "sample": "C_percentile_vs_B_random",
            "trades": sample_size,
            "mean_return": (sampled_df["mean_return"] < c_returns.mean()).mean(),
            "median_return": (sampled_df["median_return"] < c_returns.median()).mean(),
            "win_rate": (sampled_df["win_rate"] < (c_returns > 0).mean()).mean(),
            "pf": (sampled_df["pf"] < profit_factor(c_returns)).mean(),
            "max_drawdown": (sampled_df["max_drawdown"] < max_drawdown(c_returns)).mean(),
        }
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(rows)
    out.to_csv(args.output, index=False)
    print(out.tail(3).to_string(index=False))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
