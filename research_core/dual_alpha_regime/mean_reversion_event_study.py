from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.dual_alpha_regime.config import RegimeResearchConfig
from research_core.dual_alpha_regime.phase_gates import R4_GATE


DEVIATION_FACTORS = ["zscore_ema20", "zscore_ema50", "vwap_deviation_atr", "range_position_96", "lower_band_distance", "short_return_oversold"]
RANGE_QUALITY_FACTORS = ["efficiency_ratio_40", "return_autocorr_20", "range_width_atr_96", "mean_cross_count_ema20_96", "breakout_failure_rate_96", "range_persistence_96"]
PATH_SAFETY_FACTORS = ["atr_percentile_200", "downside_volatility_80", "jump_score_80", "high_low_spread_pct", "dollar_volume_percentile_200"]
BUCKETS = ["bottom20", "bottom40", "middle20", "top40", "top20"]


def load_range_events(output_dir: Path, prototype: str = "Regime-3") -> pd.DataFrame:
    R4_GATE.assert_open(output_dir)
    path = output_dir / "market_regime_events_classified.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing classified regime events: {path}")
    events = pd.read_parquet(path)
    events["bar_open_time"] = pd.to_datetime(events["bar_open_time"], utc=True)
    return events[(events["prototype"] == prototype) & (events["regime"] == "RANGE")].copy()


def add_mr_scores(events: pd.DataFrame, discovery_end: pd.Timestamp) -> pd.DataFrame:
    df = events.copy()
    lower_is_more_deviated = {
        "zscore_ema20": True,
        "zscore_ema50": True,
        "vwap_deviation_atr": True,
        "range_position_96": True,
        "lower_band_distance": True,
        "short_return_oversold": True,
    }
    for factor, lower in lower_is_more_deviated.items():
        if factor in df:
            pct = df.groupby("symbol")[factor].rank(pct=True)
            df[f"{factor}_deviation_score"] = 1 - pct if lower else pct
    deviation_cols = [f"{f}_deviation_score" for f in lower_is_more_deviated if f"{f}_deviation_score" in df]
    df["deviation_score"] = df[deviation_cols].mean(axis=1)

    quality_components = []
    if "efficiency_ratio_40" in df:
        quality_components.append(1 - df.groupby("symbol")["efficiency_ratio_40"].rank(pct=True))
    if "return_autocorr_20" in df:
        quality_components.append(df.groupby("symbol")["return_autocorr_20"].rank(pct=True).rsub(1))
    for factor in ["mean_cross_count_ema20_96", "breakout_failure_rate_96", "range_persistence_96"]:
        if factor in df:
            quality_components.append(df.groupby("symbol")[factor].rank(pct=True))
    df["range_quality_score"] = pd.concat(quality_components, axis=1).mean(axis=1) if quality_components else np.nan

    train = df[df["bar_open_time"] <= discovery_end]
    if train.empty:
        train = df
    dev_q80 = train["deviation_score"].quantile(0.80)
    quality_q60 = train["range_quality_score"].quantile(0.60)
    df["mr_prototype"] = "MR-P0"
    df.loc[df["deviation_score"] >= dev_q80, "mr_prototype"] = "MR-P1"
    df.loc[(df["deviation_score"] >= dev_q80) & (df["range_quality_score"] >= quality_q60), "mr_prototype"] = "MR-P2"
    df["deviation_threshold_train_q80"] = dev_q80
    df["range_quality_threshold_train_q60"] = quality_q60
    return df


def factor_bucket_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    label = "label_fwd_ret_120m"
    for factor in [*DEVIATION_FACTORS, *RANGE_QUALITY_FACTORS, *PATH_SAFETY_FACTORS]:
        if factor not in events:
            continue
        s = events[factor]
        cuts = {
            "bottom20": s <= s.quantile(0.20),
            "bottom40": s <= s.quantile(0.40),
            "middle20": (s > s.quantile(0.40)) & (s <= s.quantile(0.60)),
            "top40": s >= s.quantile(0.60),
            "top20": s >= s.quantile(0.80),
        }
        for bucket, mask in cuts.items():
            g = events[mask]
            if g.empty:
                continue
            rows.append(
                {
                    "factor_name": factor,
                    "bucket": bucket,
                    "events": len(g),
                    "mean_fwd_ret_120m": float(g[label].mean()) if label in g else np.nan,
                    "median_fwd_ret_120m": float(g[label].median()) if label in g else np.nan,
                    "mean_mfe_atr_120m": float(g["label_fwd_mfe_atr_120m"].mean()) if "label_fwd_mfe_atr_120m" in g else np.nan,
                    "mean_mae_atr_120m": float(g["label_fwd_mae_atr_120m"].mean()) if "label_fwd_mae_atr_120m" in g else np.nan,
                    "extreme_loss_rate_120m": float((g["label_fwd_mae_atr_120m"] > 3).mean()) if "label_fwd_mae_atr_120m" in g else np.nan,
                }
            )
    return pd.DataFrame(rows)


def prototype_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for proto in ["MR-P0", "MR-P1", "MR-P2"]:
        g = events if proto == "MR-P0" else events[events["mr_prototype"].isin([proto, "MR-P2"] if proto == "MR-P1" else [proto])]
        if g.empty:
            continue
        rows.append(
            {
                "mr_prototype": proto,
                "events": len(g),
                "symbols": ",".join(sorted(g["symbol"].unique())),
                "mean_fwd_ret_120m": float(g["label_fwd_ret_120m"].mean()),
                "median_fwd_ret_120m": float(g["label_fwd_ret_120m"].median()),
                "mean_mfe_atr_120m": float(g["label_fwd_mfe_atr_120m"].mean()),
                "mean_mae_atr_120m": float(g["label_fwd_mae_atr_120m"].mean()),
                "positive_year_rate": float((g.groupby(g["bar_open_time"].dt.year)["label_fwd_ret_120m"].mean() > 0).mean()),
                "eth_btc_supported": bool(set(["ETHUSDT", "BTCUSDT"]).issubset(set(g["symbol"].unique()))),
            }
        )
    return pd.DataFrame(rows)


def write_report(events: pd.DataFrame, group_summary: pd.DataFrame, proto_summary: pd.DataFrame, output_dir: Path) -> None:
    can_continue = False
    if not proto_summary.empty:
        mrp2 = proto_summary[proto_summary["mr_prototype"] == "MR-P2"]
        can_continue = bool(not mrp2.empty and mrp2["mean_fwd_ret_120m"].iloc[0] > 0 and mrp2["eth_btc_supported"].iloc[0])
    lines = [
        "# Mean Reversion Event Study Report",
        "",
        "R4 event study only. This is not an executable trading strategy.",
        "",
        f"range_event_count = {len(events)}",
        f"allow_r5_random_baseline = {str(can_continue).lower()}",
        "",
        "## Prototype Summary",
        "",
        proto_summary.to_markdown(index=False) if not proto_summary.empty else "No prototypes.",
        "",
        "## Factor Group Summary Preview",
        "",
        group_summary.head(50).to_markdown(index=False) if not group_summary.empty else "No factor groups.",
        "",
        "## Gate",
        "",
        "Proceed to R5 only if event advantage is stable enough to compare against matched random baselines. Do not proceed to R6 from this report alone.",
    ]
    output_dir.joinpath("mean_reversion_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_mean_reversion_event_study(output_dir: Path, config: RegimeResearchConfig | None = None) -> pd.DataFrame:
    config = config or RegimeResearchConfig(output_dir=output_dir)
    events = load_range_events(output_dir)
    events = add_mr_scores(events, config.discovery_end_ts)
    group_summary = factor_bucket_summary(events)
    proto_summary = prototype_summary(events)
    events.to_parquet(output_dir / "mean_reversion_events.parquet", index=False)
    proto_summary.to_csv(output_dir / "mean_reversion_factor_summary.csv", index=False)
    group_summary.to_csv(output_dir / "mean_reversion_group_summary.csv", index=False)
    write_report(events, group_summary, proto_summary, output_dir)
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Run R4 RANGE mean-reversion event study.")
    parser.add_argument("--output-dir", default=str(RegimeResearchConfig().output_dir))
    args = parser.parse_args()
    run_mean_reversion_event_study(Path(args.output_dir))
    print(f"Wrote R4 mean-reversion event outputs to {args.output_dir}")


if __name__ == "__main__":
    main()

