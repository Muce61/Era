from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.dual_alpha_regime.config import RegimeResearchConfig
from research_core.dual_alpha_regime.regime_factor_registry import (
    assert_no_label_features,
    build_factor_registry,
    feature_columns,
)


def load_events(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    for col in ["bar_open_time", "available_time", "next_exec_time"]:
        if col in df:
            df[col] = pd.to_datetime(df[col], utc=True)
    return df


def _safe_corr(a: pd.Series, b: pd.Series) -> float:
    joined = pd.concat([a, b], axis=1).dropna()
    if len(joined) < 30:
        return np.nan
    return float(joined.iloc[:, 0].corr(joined.iloc[:, 1], method="spearman"))


def factor_stability(events: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    features = [c for c in feature_columns(registry) if c in events.columns]
    assert_no_label_features(features, registry)
    rows = []
    events = events.copy()
    events["month"] = events["bar_open_time"].dt.to_period("M").astype(str)
    events["quarter"] = events["bar_open_time"].dt.to_period("Q").astype(str)
    events["year"] = events["bar_open_time"].dt.year.astype(str)
    label_trend = events.get("label_fwd_ret_240m")
    label_reversion = -events.get("label_fwd_ret_120m") if "label_fwd_ret_120m" in events else None
    label_path = -events.get("label_fwd_mae_atr_120m") if "label_fwd_mae_atr_120m" in events else None
    for factor in features:
        s = events[factor]
        monthly = events.groupby("month")[factor].median()
        quarterly = events.groupby("quarter")[factor].median()
        yearly = events.groupby("year")[factor].median()
        by_symbol = events.groupby("symbol")[factor].median()
        rows.append(
            {
                "factor_name": factor,
                "count": int(s.notna().sum()),
                "missing_rate": float(s.isna().mean()),
                "mean": float(s.mean()) if s.notna().any() else np.nan,
                "median": float(s.median()) if s.notna().any() else np.nan,
                "std": float(s.std()) if s.notna().any() else np.nan,
                "p01": float(s.quantile(0.01)) if s.notna().any() else np.nan,
                "p99": float(s.quantile(0.99)) if s.notna().any() else np.nan,
                "monthly_median_std": float(monthly.std()) if len(monthly) else np.nan,
                "quarterly_median_std": float(quarterly.std()) if len(quarterly) else np.nan,
                "yearly_median_std": float(yearly.std()) if len(yearly) else np.nan,
                "symbol_median_std": float(by_symbol.std()) if len(by_symbol) else np.nan,
                "trend_continuation_spearman_240m": _safe_corr(s, label_trend) if label_trend is not None else np.nan,
                "mean_reversion_spearman_120m": _safe_corr(s, label_reversion) if label_reversion is not None else np.nan,
                "path_safety_spearman_120m": _safe_corr(s, label_path) if label_path is not None else np.nan,
            }
        )
    return pd.DataFrame(rows)


def factor_correlation(events: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    features = [c for c in feature_columns(registry) if c in events.columns]
    assert_no_label_features(features, registry)
    corr = events[features].corr(method="spearman", min_periods=100)
    corr.index.name = "factor_name"
    return corr.reset_index()


def role_classification(stability: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    base = registry[~registry["uses_future_data"]].copy()
    out = base.merge(stability, on="factor_name", how="left")
    out["data_quality_status"] = np.where(out["missing_rate"] <= 0.35, "usable", "high_missing")
    out["explanatory_status"] = "weak_or_untested"
    out.loc[out["trend_continuation_spearman_240m"].abs() >= 0.03, "explanatory_status"] = "trend_explanatory_candidate"
    out.loc[out["mean_reversion_spearman_120m"].abs() >= 0.03, "explanatory_status"] = "mean_reversion_explanatory_candidate"
    out.loc[out["path_safety_spearman_120m"].abs() >= 0.03, "explanatory_status"] = "path_safety_explanatory_candidate"
    out["research_decision"] = np.where(
        out["data_quality_status"].eq("usable"),
        "keep_for_fixed_prototypes",
        "report_but_do_not_use_until_data_issue_resolved",
    )
    return out[
        [
            "factor_name",
            "factor_family",
            "factor_role",
            "data_quality_status",
            "explanatory_status",
            "research_decision",
            "missing_rate",
            "trend_continuation_spearman_240m",
            "mean_reversion_spearman_120m",
            "path_safety_spearman_120m",
        ]
    ]


def write_report(stability: pd.DataFrame, roles: pd.DataFrame, output_path: Path) -> None:
    high_missing = roles[roles["data_quality_status"] != "usable"]
    lines = [
        "# Regime Factor Report",
        "",
        "This report is R2 factor research only. It does not select a trading strategy.",
        "",
        f"factor_count = {len(stability)}",
        f"high_missing_factor_count = {len(high_missing)}",
        "",
        "## Highest Missing Rates",
        "",
        stability.sort_values("missing_rate", ascending=False).head(20).to_markdown(index=False),
        "",
        "## Role Classification Preview",
        "",
        roles.head(40).to_markdown(index=False),
        "",
        "## R2 Gate",
        "",
        "Allowed to proceed to R3 if timing tests pass and core trend/range/volatility factors are available for ETH and BTC.",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_factor_research(output_dir: Path) -> None:
    events_path = output_dir / "market_regime_events.parquet"
    registry_path = output_dir / "regime_factor_registry.csv"
    registry = pd.read_csv(registry_path) if registry_path.exists() else build_factor_registry()
    events = load_events(events_path)
    stability = factor_stability(events, registry)
    corr = factor_correlation(events, registry)
    roles = role_classification(stability, registry)
    stability.to_csv(output_dir / "regime_factor_stability.csv", index=False)
    corr.to_csv(output_dir / "regime_factor_correlation.csv", index=False)
    roles.to_csv(output_dir / "regime_factor_role_classification.csv", index=False)
    write_report(stability, roles, output_dir / "regime_factor_report.md")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run R2 regime factor research.")
    parser.add_argument("--output-dir", default=str(RegimeResearchConfig().output_dir))
    args = parser.parse_args()
    run_factor_research(Path(args.output_dir))
    print(f"Wrote R2 factor research outputs to {args.output_dir}")


if __name__ == "__main__":
    main()

