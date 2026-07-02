from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.dual_alpha_regime.config import RegimeResearchConfig


def match_bucket(df: pd.DataFrame) -> pd.Series:
    t = pd.to_datetime(df["bar_open_time"], utc=True)
    month = t.dt.to_period("M").astype(str)
    hour = t.dt.hour.astype(str).str.zfill(2)
    vol = pd.cut(df["atr_percentile_200"], [-np.inf, 0.33, 0.66, np.inf], labels=["low_vol", "mid_vol", "high_vol"]).astype(str)
    liq = pd.cut(df["dollar_volume_percentile_200"], [-np.inf, 0.33, 0.66, np.inf], labels=["low_liq", "mid_liq", "high_liq"]).astype(str)
    return df["symbol"].astype(str) + "|" + month + "|" + hour + "|" + vol + "|" + liq


def sample_matched(target: pd.DataFrame, pool: pd.DataFrame, seed: int = 20260702) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    target = target.copy()
    pool = pool.copy()
    target["match_bucket"] = match_bucket(target)
    pool["match_bucket"] = match_bucket(pool)
    selected = []
    for bucket, n in target["match_bucket"].value_counts().items():
        candidates = pool[pool["match_bucket"] == bucket]
        if candidates.empty:
            continue
        take = min(n, len(candidates))
        selected.append(candidates.sample(take, replace=False, random_state=int(rng.integers(1, 1_000_000))))
    return pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()


def summarize(name: str, df: pd.DataFrame) -> dict:
    if df.empty:
        return {"baseline": name, "events": 0}
    return {
        "baseline": name,
        "events": len(df),
        "mean_fwd_ret_120m": float(df["label_fwd_ret_120m"].mean()),
        "median_fwd_ret_120m": float(df["label_fwd_ret_120m"].median()),
        "mean_mfe_atr_120m": float(df["label_fwd_mfe_atr_120m"].mean()),
        "mean_mae_atr_120m": float(df["label_fwd_mae_atr_120m"].mean()),
        "positive_symbol_count": int((df.groupby("symbol")["label_fwd_ret_120m"].mean() > 0).sum()),
        "positive_year_rate": float((df.groupby(pd.to_datetime(df["bar_open_time"], utc=True).dt.year)["label_fwd_ret_120m"].mean() > 0).mean()),
    }


def run_random_baseline(output_dir: Path) -> pd.DataFrame:
    mr_path = output_dir / "mean_reversion_events.parquet"
    classified_path = output_dir / "market_regime_events_classified.parquet"
    if not mr_path.exists() or not classified_path.exists():
        raise FileNotFoundError("R5 requires mean_reversion_events.parquet and market_regime_events_classified.parquet")
    mr = pd.read_parquet(mr_path)
    all_events = pd.read_parquet(classified_path)
    target = mr[mr["mr_prototype"] == "MR-P2"].copy()
    if target.empty:
        target = mr.copy()
    same_range_pool = all_events[(all_events["prototype"] == "Regime-3") & (all_events["regime"] == "RANGE")].copy()
    all_market_pool = all_events[all_events["prototype"] == "Regime-3"].copy()
    trend_deviation_pool = all_events[(all_events["prototype"] == "Regime-3") & (all_events["regime"] == "TREND")].copy()
    same_range = sample_matched(target, same_range_pool)
    all_market = sample_matched(target, all_market_pool)
    trend_same_deviation = sample_matched(target, trend_deviation_pool)
    rows = [
        summarize("mean_reversion_events", target),
        summarize("same_range_random", same_range),
        summarize("all_market_random", all_market),
        summarize("trend_state_counterfactual", trend_same_deviation),
    ]
    result = pd.DataFrame(rows)
    result.to_csv(output_dir / "mean_reversion_random_baseline.csv", index=False)
    wf = walk_forward_summary(target)
    wf.to_csv(output_dir / "mean_reversion_walk_forward.csv", index=False)
    failure = failure_analysis(target)
    failure.to_csv(output_dir / "mean_reversion_failure_analysis.csv", index=False)
    return result


def walk_forward_summary(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    df = events.copy()
    df["bar_open_time"] = pd.to_datetime(df["bar_open_time"], utc=True)
    rows = []
    start = df["bar_open_time"].min().normalize()
    end = df["bar_open_time"].max()
    test_start = start + pd.DateOffset(months=24)
    window_id = 1
    while test_start < end:
        test_end = min(test_start + pd.DateOffset(months=6) - pd.Timedelta(minutes=1), end)
        g = df[(df["bar_open_time"] >= test_start) & (df["bar_open_time"] <= test_end)]
        rows.append({"window_id": window_id, "test_start": test_start, "test_end": test_end, **summarize("mr_walk_forward", g)})
        window_id += 1
        test_start += pd.DateOffset(months=6)
    return pd.DataFrame(rows)


def failure_analysis(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    df = events.copy()
    df["bar_open_time"] = pd.to_datetime(df["bar_open_time"], utc=True)
    base = summarize("original", df)
    monthly = df.groupby(df["bar_open_time"].dt.to_period("M"))["label_fwd_ret_120m"].sum().sort_values(ascending=False)
    best_month = str(monthly.index[0]) if len(monthly) else ""
    remove_best_month = df[df["bar_open_time"].dt.to_period("M").astype(str) != best_month]
    remove_best_1pct = df.sort_values("label_fwd_ret_120m").iloc[: max(1, int(len(df) * 0.99))]
    return pd.DataFrame(
        [
            base,
            {"baseline": "remove_best_month", "removed_period": best_month, **summarize("remove_best_month", remove_best_month)},
            {"baseline": "remove_best_1pct_trades", **summarize("remove_best_1pct_trades", remove_best_1pct)},
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run R5 matched random baseline for MR events.")
    parser.add_argument("--output-dir", default=str(RegimeResearchConfig().output_dir))
    args = parser.parse_args()
    run_random_baseline(Path(args.output_dir))
    print(f"Wrote R5 random-baseline outputs to {args.output_dir}")


if __name__ == "__main__":
    main()

