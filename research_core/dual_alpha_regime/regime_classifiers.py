from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.dual_alpha_regime.config import RegimeResearchConfig
from research_core.dual_alpha_regime.regime_factor_registry import assert_no_label_features


@dataclass(frozen=True)
class RegimeThresholds:
    atr_extreme_q90: float
    jump_extreme_q95: float
    trend_score_q60: float
    range_score_q60: float
    uncertain_band: float = 0.15


FEATURES_USED = [
    "ema_gap_atr",
    "ema200_slope_4h",
    "adx_14",
    "efficiency_ratio_40",
    "trend_direction_consistency_20",
    "return_autocorr_20",
    "mean_cross_count_ema20_96",
    "breakout_failure_rate_96",
    "range_persistence_96",
    "variance_ratio_20_80",
    "atr_percentile_200",
    "jump_score_80",
]


def _rank01(s: pd.Series) -> pd.Series:
    return s.rank(pct=True)


def add_scores(events: pd.DataFrame) -> pd.DataFrame:
    assert_no_label_features(FEATURES_USED)
    df = events.copy()
    parts = []
    for _, part in df.groupby("symbol", sort=False):
        p = part.copy()
        trend_score = (
            _rank01(p["ema_gap_atr"].clip(lower=0))
            + _rank01(p["ema200_slope_4h"].clip(lower=0))
            + _rank01(p["adx_14"])
            + _rank01(p["efficiency_ratio_40"])
            + _rank01(p["trend_direction_consistency_20"])
            + _rank01(p["return_autocorr_20"].clip(lower=0))
        ) / 6
        range_score = (
            _rank01(1 - p["efficiency_ratio_40"])
            + _rank01((-p["return_autocorr_20"]).clip(lower=0))
            + _rank01(p["mean_cross_count_ema20_96"])
            + _rank01(p["breakout_failure_rate_96"])
            + _rank01(p["range_persistence_96"])
            + _rank01(1 / p["variance_ratio_20_80"].replace(0, np.nan))
        ) / 6
        p["trend_score"] = trend_score
        p["range_score"] = range_score
        p["regime_confidence"] = (trend_score - range_score).abs()
        parts.append(p)
    return pd.concat(parts, ignore_index=True)


def fit_thresholds(scored: pd.DataFrame, discovery_end: pd.Timestamp) -> RegimeThresholds:
    train = scored[scored["bar_open_time"] <= discovery_end]
    if train.empty:
        train = scored
    return RegimeThresholds(
        atr_extreme_q90=float(train["atr_percentile_200"].quantile(0.90)),
        jump_extreme_q95=float(train["jump_score_80"].quantile(0.95)),
        trend_score_q60=float(train["trend_score"].quantile(0.60)),
        range_score_q60=float(train["range_score"].quantile(0.60)),
    )


def classify(scored: pd.DataFrame, thresholds: RegimeThresholds, prototype: str) -> pd.Series:
    df = scored
    extreme = (df["atr_percentile_200"] >= thresholds.atr_extreme_q90) | (df["jump_score_80"] >= thresholds.jump_extreme_q95)
    trend = (df["trend_score"] >= thresholds.trend_score_q60) & (df["trend_score"] > df["range_score"])
    range_ = (df["range_score"] >= thresholds.range_score_q60) & (df["range_score"] > df["trend_score"])
    close_call = (df["trend_score"] - df["range_score"]).abs() < thresholds.uncertain_band
    if prototype == "Regime-0":
        return pd.Series("ALL", index=df.index)
    if prototype == "Regime-1":
        return pd.Series(np.where(trend & ~extreme, "TREND", "NON_TREND"), index=df.index)
    if prototype == "Regime-2":
        return pd.Series(np.select([trend & ~extreme, range_ & ~extreme], ["TREND", "RANGE"], default="UNCERTAIN"), index=df.index)
    if prototype == "Regime-3":
        return pd.Series(
            np.select(
                [extreme, trend & ~close_call, range_ & ~close_call, close_call],
                ["EXTREME", "TREND", "RANGE", "TRANSITION"],
                default="TRANSITION",
            ),
            index=df.index,
        )
    raise ValueError(f"Unknown prototype: {prototype}")


def run_lengths(values: pd.Series) -> pd.Series:
    group = values.ne(values.shift()).cumsum()
    return values.groupby(group).transform("size")


def coverage_summary(classified: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for prototype, part in classified.groupby("prototype"):
        for keys, g in part.groupby(["symbol", "regime"], dropna=False):
            rows.append(
                {
                    "prototype": prototype,
                    "symbol": keys[0],
                    "regime": keys[1],
                    "bars": int(len(g)),
                    "coverage": float(len(g) / len(part[part["symbol"] == keys[0]])),
                    "avg_duration_bars": float(g["run_length"].mean()),
                    "avg_duration_minutes": float(g["run_length"].mean() * 15),
                    "mean_fwd_ret_240m": float(g["label_fwd_ret_240m"].mean()) if "label_fwd_ret_240m" in g else np.nan,
                    "mean_fwd_mae_atr_120m": float(g["label_fwd_mae_atr_120m"].mean()) if "label_fwd_mae_atr_120m" in g else np.nan,
                }
            )
    return pd.DataFrame(rows)


def transition_matrix(classified: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (prototype, symbol), part in classified.sort_values("bar_open_time").groupby(["prototype", "symbol"]):
        prev = part["regime"].shift()
        current = part["regime"]
        counts = pd.crosstab(prev, current, normalize="index")
        for from_state, row in counts.iterrows():
            for to_state, prob in row.items():
                rows.append({"prototype": prototype, "symbol": symbol, "from_regime": from_state, "to_regime": to_state, "probability": float(prob)})
    return pd.DataFrame(rows)


def period_summary(classified: pd.DataFrame, freq: str, name: str) -> pd.DataFrame:
    df = classified.copy()
    df["period"] = df["bar_open_time"].dt.to_period(freq).astype(str)
    counts = (
        df.groupby(["prototype", "symbol", "period", "regime"], observed=True)
        .size()
        .rename("bars")
        .reset_index()
    )
    totals = (
        df.groupby(["prototype", "symbol", "period"], observed=True)
        .size()
        .rename("total_bars")
        .reset_index()
    )
    out = counts.merge(totals, on=["prototype", "symbol", "period"], how="left")
    out["coverage"] = out["bars"] / out["total_bars"].replace(0, np.nan)
    return out.rename(columns={"period": name}).drop(columns=["total_bars"])


def classify_regimes(output_dir: Path, config: RegimeResearchConfig | None = None) -> pd.DataFrame:
    config = config or RegimeResearchConfig(output_dir=output_dir)
    events = pd.read_parquet(output_dir / "market_regime_events.parquet")
    events["bar_open_time"] = pd.to_datetime(events["bar_open_time"], utc=True)
    scored = add_scores(events)
    thresholds = fit_thresholds(scored, config.discovery_end_ts)
    classified_parts = []
    for prototype in ["Regime-0", "Regime-1", "Regime-2", "Regime-3"]:
        p = scored.copy()
        p["prototype"] = prototype
        p["regime"] = classify(p, thresholds, prototype)
        p["run_length"] = p.groupby(["prototype", "symbol"])["regime"].transform(run_lengths)
        classified_parts.append(p)
    classified = pd.concat(classified_parts, ignore_index=True)
    classified.to_parquet(output_dir / "market_regime_events_classified.parquet", index=False)
    coverage = coverage_summary(classified)
    transitions = transition_matrix(classified)
    monthly = period_summary(classified, "M", "month")
    yearly = period_summary(classified, "Y", "year")
    coverage.to_csv(output_dir / "regime_coverage_summary.csv", index=False)
    transitions.to_csv(output_dir / "regime_transition_matrix.csv", index=False)
    monthly.to_csv(output_dir / "regime_monthly_summary.csv", index=False)
    yearly.to_csv(output_dir / "regime_yearly_summary.csv", index=False)
    pd.DataFrame([thresholds.__dict__]).to_csv(output_dir / "regime_classifier_thresholds.csv", index=False)
    write_regime_report(output_dir, coverage, transitions, thresholds)
    return classified


def write_regime_report(output_dir: Path, coverage: pd.DataFrame, transitions: pd.DataFrame, thresholds: RegimeThresholds) -> None:
    r3 = coverage[coverage["prototype"] == "Regime-3"]
    avg_duration = r3.groupby("regime")["avg_duration_bars"].mean().sort_values() if not r3.empty else pd.Series(dtype=float)
    lines = [
        "# Regime Classification Report",
        "",
        "R3 compares fixed interpretable prototypes. Thresholds are fit on the discovery window only.",
        "",
        "## Frozen Thresholds",
        "",
        pd.DataFrame([thresholds.__dict__]).to_markdown(index=False),
        "",
        "## Regime-3 Coverage",
        "",
        r3.to_markdown(index=False) if not r3.empty else "No Regime-3 rows.",
        "",
        "## Shortest Average Durations",
        "",
        avg_duration.to_frame("avg_duration_bars").to_markdown() if not avg_duration.empty else "No duration data.",
        "",
        "## R3 Gate",
        "",
        "Proceed to R4 only if RANGE coverage is non-trivial, state switching is not excessive, and ETH/BTC both have usable state histories. This report does not by itself approve MR strategy construction.",
    ]
    output_dir.joinpath("regime_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run R3 fixed regime classifiers.")
    parser.add_argument("--output-dir", default=str(RegimeResearchConfig().output_dir))
    args = parser.parse_args()
    classify_regimes(Path(args.output_dir))
    print(f"Wrote R3 regime classifier outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
