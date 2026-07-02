from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class FactorSpec:
    factor_name: str
    factor_family: str
    factor_role: str
    formula: str
    lookback: str
    normalization: str
    expected_direction: str
    realtime_available: bool
    uses_future_data: bool
    leakage_risk: str
    used_by: str
    research_status: str
    oos_status: str
    version: str = "r1_v1"
    fit_scope: str = "rolling_history"
    transform_scope: str = "per_symbol_realtime"


def _spec(name, family, role, formula, lookback, norm, direction, used_by, risk="low"):
    return FactorSpec(
        factor_name=name,
        factor_family=family,
        factor_role=role,
        formula=formula,
        lookback=lookback,
        normalization=norm,
        expected_direction=direction,
        realtime_available=True,
        uses_future_data=False,
        leakage_risk=risk,
        used_by=used_by,
        research_status="candidate_frozen_before_r1",
        oos_status="not_tested",
    )


def build_factor_registry() -> pd.DataFrame:
    specs: list[FactorSpec] = [
        _spec("ema_gap_atr", "trend_structure", "trend_regime_factor", "(EMA50-EMA200)/ATR14", "200 bars", "ATR", "higher_trend", "R2,R3"),
        _spec("ema200_slope_4h", "trend_structure", "trend_regime_factor", "(EMA200-EMA200[-16])/ATR14", "216 bars", "ATR", "higher_trend", "R2,R3"),
        _spec("adx_14", "trend_structure", "trend_regime_factor", "ADX on completed 15m bars", "28 bars", "none", "higher_trend", "R2,R3"),
        _spec("efficiency_ratio_20", "trend_range_structure", "dual_use_candidate", "abs(close-close[-20])/sum(abs(diff(close)),20)", "20 bars", "ratio", "higher_trend_lower_range", "R2,R3,R4"),
        _spec("efficiency_ratio_40", "trend_range_structure", "dual_use_candidate", "abs(close-close[-40])/sum(abs(diff(close)),40)", "40 bars", "ratio", "higher_trend_lower_range", "R2,R3,R4"),
        _spec("higher_high_lower_low_score", "trend_structure", "trend_regime_factor", "HH+HL-LH-LL over 20 bars", "20 bars", "score", "higher_trend", "R2,R3"),
        _spec("donchian_position_55", "trend_structure", "trend_regime_factor", "(close-low55)/(high55-low55)", "55 bars", "range", "higher_uptrend", "R2,R3"),
        _spec("breakout_duration_55", "trend_structure", "trend_regime_factor", "consecutive completed bars closing above prior Donchian55 high", "55 bars", "bars", "higher_trend", "R2,R3"),
        _spec("return_autocorr_20", "trend_range_structure", "dual_use_candidate", "rolling corr(ret, ret[-1])", "20 bars", "correlation", "positive_trend_negative_range", "R2,R3,R4"),
        _spec("trend_direction_consistency_20", "trend_structure", "trend_regime_factor", "abs(mean(sign(ret),20))", "20 bars", "ratio", "higher_trend", "R2,R3"),
        _spec("mean_cross_count_ema20_96", "range_structure", "range_regime_factor", "cross count around EMA20 over 96 bars", "96 bars", "count", "higher_range", "R2,R3,R4"),
        _spec("range_width_atr_96", "range_structure", "range_regime_factor", "(rolling high96-low96)/ATR14", "96 bars", "ATR", "moderate_range", "R2,R3,R4"),
        _spec("range_round_trip_count_96", "range_structure", "range_regime_factor", "EMA20 cross count / 2 over 96 bars", "96 bars", "count", "higher_range", "R2,R3,R4"),
        _spec("breakout_failure_rate_96", "range_structure", "range_regime_factor", "failed Donchian55 attempts / attempts", "96 bars", "ratio", "higher_range", "R2,R3,R4"),
        _spec("zscore_ema20", "mean_deviation", "alpha_factor", "(close-EMA20)/rolling_std20", "20 bars", "zscore", "lower_long_reversion", "R4"),
        _spec("zscore_ema50", "mean_deviation", "alpha_factor", "(close-EMA50)/rolling_std50", "50 bars", "zscore", "lower_long_reversion", "R4"),
        _spec("vwap_deviation_atr", "mean_deviation", "alpha_factor", "(close-VWAP96)/ATR14", "96 bars", "ATR", "lower_long_reversion", "R4"),
        _spec("range_position_96", "mean_deviation", "alpha_factor", "(close-low96)/(high96-low96)", "96 bars", "range", "lower_long_reversion", "R4"),
        _spec("lower_band_distance", "mean_deviation", "alpha_factor", "(close-BollingerLower20)/ATR14", "20 bars", "ATR", "lower_oversold", "R4"),
        _spec("short_return_oversold", "mean_deviation", "alpha_factor", "rank(ret_4bar_sum, rolling 200)", "200 bars", "rolling_percentile", "lower_oversold", "R4"),
        _spec("variance_ratio_20_80", "range_structure", "range_regime_factor", "var(ret20)/var(ret80)", "80 bars", "ratio", "lower_range", "R2,R3"),
        _spec("range_persistence_96", "range_structure", "range_regime_factor", "share of closes inside prior 96 bar range", "96 bars", "ratio", "higher_range", "R2,R3,R4"),
        _spec("atr_pct", "volatility_structure", "volatility_regime_factor", "ATR14/close", "14 bars", "pct", "higher_volatility", "R2,R3,R5"),
        _spec("atr_percentile_200", "volatility_structure", "volatility_regime_factor", "rolling percentile of ATR pct", "200 bars", "rolling_percentile", "higher_extreme", "R2,R3,R5"),
        _spec("volatility_ratio_short_long", "volatility_structure", "volatility_regime_factor", "RV20/RV80", "80 bars", "ratio", "higher_expansion", "R2,R3"),
        _spec("realized_volatility_20", "volatility_structure", "volatility_regime_factor", "std(ret,20)*sqrt(96)", "20 bars", "annualized_intraday_proxy", "higher_volatility", "R2,R3"),
        _spec("realized_volatility_80", "volatility_structure", "volatility_regime_factor", "std(ret,80)*sqrt(96)", "80 bars", "annualized_intraday_proxy", "higher_volatility", "R2,R3"),
        _spec("bollinger_bandwidth_20", "volatility_structure", "volatility_regime_factor", "(upper-lower)/middle", "20 bars", "pct", "higher_volatility", "R2,R3"),
        _spec("volatility_compression_duration", "volatility_structure", "volatility_regime_factor", "consecutive bars ATR pct below rolling mean", "200 bars", "bars", "higher_compression", "R2,R3"),
        _spec("volatility_change_rate_20", "volatility_structure", "volatility_regime_factor", "atr_pct/atr_pct[-20]-1", "20 bars", "pct_change", "higher_expansion", "R2,R3"),
        _spec("downside_volatility_80", "volatility_structure", "path_safety_factor", "std(min(ret,0),80)*sqrt(96)", "80 bars", "volatility", "higher_risk", "R2,R4"),
        _spec("jump_score_80", "volatility_structure", "path_safety_factor", "abs(ret)/median(abs(ret),80)", "80 bars", "ratio", "higher_risk", "R2,R3,R4"),
        _spec("volume_zscore_96", "liquidity", "path_safety_factor", "(volume-mean96)/std96", "96 bars", "zscore", "higher_liquidity", "R2,R5"),
        _spec("dollar_volume_percentile_200", "liquidity", "path_safety_factor", "rolling percentile of close*volume", "200 bars", "rolling_percentile", "higher_liquidity", "R2,R5"),
        _spec("high_low_spread_pct", "liquidity", "path_safety_factor", "(high-low)/close", "current completed 15m", "pct", "higher_risk", "R2,R5"),
        _spec("missing_1m_count_in_15m", "liquidity", "path_safety_factor", "15-minute_count", "current completed 15m", "count", "higher_data_risk", "R1,R2"),
    ]
    labels = []
    for h in [15, 30, 60, 120, 240, 480]:
        for metric in ["fwd_ret", "fwd_mfe_atr", "fwd_mae_atr"]:
            labels.append(
                FactorSpec(
                    factor_name=f"label_{metric}_{h}m",
                    factor_family="forward_label",
                    factor_role="research_label",
                    formula=f"future {metric} over {h} minutes from next executable 1m open",
                    lookback=f"+{h} minutes",
                    normalization="label",
                    expected_direction="not_a_feature",
                    realtime_available=False,
                    uses_future_data=True,
                    leakage_risk="must_never_be_feature",
                    used_by="R2,R4,R5 labels only",
                    research_status="label_frozen_before_r1",
                    oos_status="not_applicable",
                    fit_scope="none",
                    transform_scope="future_path_label",
                )
            )
    return pd.DataFrame([asdict(x) for x in [*specs, *labels]])


def feature_columns(registry: pd.DataFrame | None = None) -> list[str]:
    registry = build_factor_registry() if registry is None else registry
    return registry.loc[(registry["realtime_available"]) & (~registry["uses_future_data"]), "factor_name"].tolist()


def label_columns(registry: pd.DataFrame | None = None) -> list[str]:
    registry = build_factor_registry() if registry is None else registry
    return registry.loc[registry["uses_future_data"], "factor_name"].tolist()


def assert_no_label_features(columns: list[str], registry: pd.DataFrame | None = None) -> None:
    forbidden = set(label_columns(registry))
    used = sorted(set(columns) & forbidden)
    if used:
        raise ValueError(f"Future label columns cannot be used as features: {used}")


def write_factor_registry(registry: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    registry.to_csv(path, index=False)


if __name__ == "__main__":
    write_factor_registry(build_factor_registry(), Path("regime_factor_registry.csv"))

