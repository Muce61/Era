from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.dual_alpha_regime.config import RegimeResearchConfig
from research_core.dual_alpha_regime.regime_factor_registry import build_factor_registry, write_factor_registry


OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


def load_ohlcv_1m(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df.columns = [c.lower() for c in df.columns]
    missing = ["timestamp", *OHLCV_COLUMNS]
    missing = [c for c in missing if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing required columns: {missing}")
    df = df.dropna(subset=["timestamp"]).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    return df.set_index("timestamp")[OHLCV_COLUMNS].astype(float)


def compact_missing_ranges(missing: pd.DatetimeIndex) -> pd.DataFrame:
    if len(missing) == 0:
        return pd.DataFrame(columns=["start_utc", "end_utc", "missing_minutes"])
    s = pd.Series(missing)
    groups = (s.diff() != pd.Timedelta(minutes=1)).cumsum()
    return (
        s.groupby(groups)
        .agg(["first", "last", "count"])
        .rename(columns={"first": "start_utc", "last": "end_utc", "count": "missing_minutes"})
        .reset_index(drop=True)
    )


def audit_1m_data(symbol: str, df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    expected = pd.date_range(df.index.min(), df.index.max(), freq="1min", tz="UTC")
    missing = expected.difference(df.index)
    invalid = (
        (df["low"] > df["open"])
        | (df["low"] > df["close"])
        | (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df[OHLCV_COLUMNS] < 0).any(axis=1)
        | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    ret_abs = df["close"].pct_change().abs()
    outlier_threshold = (ret_abs.rolling(1440, min_periods=100).median() * 20).clip(lower=0.02).fillna(0.05)
    outliers = ret_abs > outlier_threshold
    bars_15m = df.resample("15min").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        minute_count=("close", "count"),
    )
    report = {
        "symbol": symbol,
        "start_utc": df.index.min(),
        "end_utc": df.index.max(),
        "rows": int(len(df)),
        "expected_minutes": int(len(expected)),
        "missing_minutes": int(len(missing)),
        "invalid_ohlc_rows": int(invalid.sum()),
        "outlier_rows": int(outliers.sum()),
        "complete_15m_bars": int((bars_15m["minute_count"] == 15).sum()),
        "incomplete_15m_bars": int((bars_15m["minute_count"] != 15).sum()),
    }
    ranges = compact_missing_ranges(missing)
    if not ranges.empty:
        ranges.insert(0, "symbol", symbol)
    return report, ranges


def build_completed_15m(df_1m: pd.DataFrame, symbol: str) -> pd.DataFrame:
    bars = df_1m.resample("15min", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        minute_count=("close", "count"),
    )
    bars = bars[bars["minute_count"] == 15].copy()
    bars.index.name = "bar_open_time"
    bars["symbol"] = symbol
    bars["bar_open_time"] = bars.index
    bars["bar_close_time"] = bars["bar_open_time"] + pd.Timedelta(minutes=14)
    bars["available_time"] = bars["bar_open_time"] + pd.Timedelta(minutes=15)
    next_pos = df_1m.index.searchsorted(bars["available_time"], side="left")
    next_exec = [df_1m.index[p] if p < len(df_1m.index) else pd.NaT for p in next_pos]
    bars["next_exec_time"] = pd.to_datetime(next_exec, utc=True)
    return bars.reset_index(drop=True)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def efficiency_ratio(close: pd.Series, window: int) -> pd.Series:
    change = (close - close.shift(window)).abs()
    path = close.diff().abs().rolling(window).sum()
    return change / path.replace(0, np.nan)


def rolling_autocorr(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).corr(series.shift(1))


def rolling_vwap(df: pd.DataFrame, window: int) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical * df["volume"]
    return pv.rolling(window).sum() / df["volume"].rolling(window).sum().replace(0, np.nan)


def add_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    atr = true_range(df).rolling(period).mean()
    plus_di = 100 * plus_dm.rolling(period).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(period).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean()


def add_realtime_features(bars: pd.DataFrame) -> pd.DataFrame:
    df = bars.copy()
    close = df["close"]
    ret = close.pct_change()
    tr = true_range(df)
    df["atr_14"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr_14"] / close
    df["atr_percentile_200"] = df["atr_pct"].rolling(200, min_periods=50).rank(pct=True)
    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()
    df["ema_gap_atr"] = (df["ema50"] - df["ema200"]) / df["atr_14"].replace(0, np.nan)
    df["ema200_slope_4h"] = (df["ema200"] - df["ema200"].shift(16)) / df["atr_14"].replace(0, np.nan)
    df["adx_14"] = add_adx(df, 14)
    df["efficiency_ratio_20"] = efficiency_ratio(close, 20)
    df["efficiency_ratio_40"] = efficiency_ratio(close, 40)

    high_20 = df["high"].shift(1).rolling(20).max()
    low_20 = df["low"].shift(1).rolling(20).min()
    high_55 = df["high"].shift(1).rolling(55).max()
    low_55 = df["low"].shift(1).rolling(55).min()
    high_96 = df["high"].shift(1).rolling(96).max()
    low_96 = df["low"].shift(1).rolling(96).min()
    df["donchian_high_20"] = high_20
    df["donchian_low_20"] = low_20
    df["donchian_high_55"] = high_55
    df["donchian_low_55"] = low_55
    width_55 = (high_55 - low_55).replace(0, np.nan)
    df["donchian_position_55"] = (close - low_55) / width_55
    df["range_width_atr_96"] = (high_96 - low_96) / df["atr_14"].replace(0, np.nan)

    breakout = close > high_55
    df["breakout_duration_55"] = breakout.groupby((~breakout).cumsum()).cumcount() + 1
    df.loc[~breakout, "breakout_duration_55"] = 0
    higher_high = df["high"] > df["high"].shift(20)
    higher_low = df["low"] > df["low"].shift(20)
    lower_high = df["high"] < df["high"].shift(20)
    lower_low = df["low"] < df["low"].shift(20)
    df["higher_high_lower_low_score"] = higher_high.astype(int) + higher_low.astype(int) - lower_high.astype(int) - lower_low.astype(int)
    df["return_autocorr_20"] = rolling_autocorr(ret, 20)
    df["trend_direction_consistency_20"] = np.sign(ret).rolling(20).mean().abs()

    df["mean_cross_count_ema20_96"] = ((close > df["ema20"]).astype(int).diff().abs()).rolling(96).sum()
    prev_close = close.shift(1)
    crosses_mid = ((prev_close <= df["ema20"].shift(1)) & (close > df["ema20"])) | ((prev_close >= df["ema20"].shift(1)) & (close < df["ema20"]))
    df["range_round_trip_count_96"] = crosses_mid.rolling(96).sum() / 2
    failed_up = (df["high"] > high_55) & (close <= high_55)
    failed_down = (df["low"] < low_55) & (close >= low_55)
    attempts = ((df["high"] > high_55) | (df["low"] < low_55)).rolling(96).sum()
    failures = (failed_up | failed_down).rolling(96).sum()
    df["breakout_failure_rate_96"] = failures / attempts.replace(0, np.nan)
    df["zscore_ema20"] = (close - df["ema20"]) / close.rolling(20).std().replace(0, np.nan)
    df["zscore_ema50"] = (close - df["ema50"]) / close.rolling(50).std().replace(0, np.nan)
    df["variance_ratio_20_80"] = ret.rolling(20).var() / ret.rolling(80).var().replace(0, np.nan)
    df["range_persistence_96"] = ((close <= high_96) & (close >= low_96)).rolling(96).mean()

    rv20 = ret.rolling(20).std() * np.sqrt(96)
    rv80 = ret.rolling(80).std() * np.sqrt(96)
    df["realized_volatility_20"] = rv20
    df["realized_volatility_80"] = rv80
    df["volatility_ratio_short_long"] = rv20 / rv80.replace(0, np.nan)
    rolling_std20 = close.rolling(20).std()
    df["bollinger_middle_20"] = close.rolling(20).mean()
    df["bollinger_upper_20"] = df["bollinger_middle_20"] + 2 * rolling_std20
    df["bollinger_lower_20"] = df["bollinger_middle_20"] - 2 * rolling_std20
    df["bollinger_bandwidth_20"] = (df["bollinger_upper_20"] - df["bollinger_lower_20"]) / df["bollinger_middle_20"].replace(0, np.nan)
    vol_ma = df["atr_pct"].rolling(200, min_periods=50).mean()
    compressed = df["atr_pct"] < vol_ma
    df["volatility_compression_duration"] = compressed.groupby((~compressed).cumsum()).cumcount() + 1
    df.loc[~compressed, "volatility_compression_duration"] = 0
    df["volatility_change_rate_20"] = df["atr_pct"] / df["atr_pct"].shift(20).replace(0, np.nan) - 1
    df["downside_volatility_80"] = ret.where(ret < 0, 0).rolling(80).std() * np.sqrt(96)
    df["jump_score_80"] = ret.abs() / ret.abs().rolling(80).median().replace(0, np.nan)

    df["vwap_96"] = rolling_vwap(df, 96)
    df["vwap_deviation_atr"] = (close - df["vwap_96"]) / df["atr_14"].replace(0, np.nan)
    df["rolling_median_50"] = close.rolling(50).median()
    df["donchian_midpoint_55"] = (high_55 + low_55) / 2
    df["range_position_96"] = (close - low_96) / (high_96 - low_96).replace(0, np.nan)
    df["lower_band_distance"] = (close - df["bollinger_lower_20"]) / df["atr_14"].replace(0, np.nan)
    df["short_return_oversold"] = ret.rolling(4).sum().rolling(200, min_periods=50).rank(pct=True)

    df["quote_volume_proxy"] = df["close"] * df["volume"]
    vol_mean = df["volume"].rolling(96).mean()
    vol_std = df["volume"].rolling(96).std()
    df["volume_zscore_96"] = (df["volume"] - vol_mean) / vol_std.replace(0, np.nan)
    df["dollar_volume_percentile_200"] = df["quote_volume_proxy"].rolling(200, min_periods=50).rank(pct=True)
    df["high_low_spread_pct"] = (df["high"] - df["low"]) / df["close"]
    df["missing_1m_count_in_15m"] = 15 - df["minute_count"]
    df["regime_feature_available"] = df[["atr_14", "ema200", "donchian_high_55", "efficiency_ratio_40"]].notna().all(axis=1)
    return df


def _forward_window_max(series: pd.Series, bars_forward: int) -> pd.Series:
    return series.shift(-1).rolling(bars_forward).max().shift(-(bars_forward - 1))


def _forward_window_min(series: pd.Series, bars_forward: int) -> pd.Series:
    return series.shift(-1).rolling(bars_forward).min().shift(-(bars_forward - 1))


def add_forward_labels(features: pd.DataFrame, data_1m: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    df = features.copy()
    if all(h % 15 == 0 for h in horizons):
        entry = df["open"].shift(-1)
        atr = df["atr_14"].replace(0, np.nan)
        for h in horizons:
            bars_forward = h // 15
            close_end = df["close"].shift(-bars_forward)
            future_high = _forward_window_max(df["high"], bars_forward)
            future_low = _forward_window_min(df["low"], bars_forward)
            df[f"label_fwd_ret_{h}m"] = close_end / entry - 1
            df[f"label_fwd_mfe_atr_{h}m"] = (future_high - entry) / atr
            df[f"label_fwd_mae_atr_{h}m"] = (entry - future_low) / atr
        return df

    idx = data_1m.index
    for h in horizons:
        fwd_ret = []
        fwd_mfe = []
        fwd_mae = []
        for _, row in df.iterrows():
            entry_time = row["next_exec_time"]
            if pd.isna(entry_time):
                fwd_ret.append(np.nan)
                fwd_mfe.append(np.nan)
                fwd_mae.append(np.nan)
                continue
            end_time = entry_time + pd.Timedelta(minutes=h)
            start_pos = idx.searchsorted(entry_time, side="left")
            end_pos = idx.searchsorted(end_time, side="right")
            path = data_1m.iloc[start_pos:end_pos]
            if path.empty:
                fwd_ret.append(np.nan)
                fwd_mfe.append(np.nan)
                fwd_mae.append(np.nan)
                continue
            entry = float(path.iloc[0]["open"])
            close_end = float(path.iloc[-1]["close"])
            atr = float(row["atr_14"]) if np.isfinite(row["atr_14"]) and row["atr_14"] > 0 else np.nan
            fwd_ret.append(close_end / entry - 1)
            fwd_mfe.append((path["high"].max() - entry) / atr if np.isfinite(atr) else np.nan)
            fwd_mae.append((entry - path["low"].min()) / atr if np.isfinite(atr) else np.nan)
        df[f"label_fwd_ret_{h}m"] = fwd_ret
        df[f"label_fwd_mfe_atr_{h}m"] = fwd_mfe
        df[f"label_fwd_mae_atr_{h}m"] = fwd_mae
    return df


def build_symbol_events(symbol: str, data_path: Path, horizons: list[int]) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    data_1m = load_ohlcv_1m(data_path)
    audit, missing_ranges = audit_1m_data(symbol, data_1m)
    bars = build_completed_15m(data_1m, symbol)
    features = add_realtime_features(bars)
    events = add_forward_labels(features, data_1m, horizons)
    return events, audit, missing_ranges


def build_market_regime_events(config: RegimeResearchConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    parts = []
    audits = []
    missing_ranges = []
    for symbol in config.symbols:
        path = config.data_dir / f"{symbol}.csv"
        if not path.exists():
            audits.append({"symbol": symbol, "missing_file": True, "path": str(path)})
            continue
        events, audit, ranges = build_symbol_events(symbol, path, config.horizons_minutes)
        parts.append(events)
        audits.append(audit)
        if not ranges.empty:
            missing_ranges.append(ranges)
    all_events = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    audit_df = pd.DataFrame(audits)
    missing_df = pd.concat(missing_ranges, ignore_index=True) if missing_ranges else pd.DataFrame()
    return all_events, audit_df, missing_df


def write_data_quality_report(audit: pd.DataFrame, missing_ranges: pd.DataFrame, output_path: Path) -> None:
    lines = [
        "# Regime Data Quality Report",
        "",
        "Generated from 1m OHLCV before market-regime feature research.",
        "",
        "## Symbol Summary",
        "",
        audit.to_markdown(index=False),
        "",
        "## Missing Ranges",
        "",
    ]
    if missing_ranges.empty:
        lines.append("No missing 1m ranges detected in audited symbols.")
    else:
        lines.append(missing_ranges.head(100).to_markdown(index=False))
        if len(missing_ranges) > 100:
            lines.append(f"\nOnly first 100 of {len(missing_ranges)} missing ranges shown.")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(events: pd.DataFrame, audit: pd.DataFrame, missing: pd.DataFrame, config: RegimeResearchConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    events.to_parquet(config.output_dir / "market_regime_events.parquet", index=False)
    audit.to_csv(config.output_dir / "regime_data_quality_summary.csv", index=False)
    missing.to_csv(config.output_dir / "regime_missing_ranges.csv", index=False)
    write_data_quality_report(audit, missing, config.output_dir / "regime_data_quality_report.md")
    registry = build_factor_registry()
    write_factor_registry(registry, config.output_dir / "regime_factor_dictionary.csv")
    write_factor_registry(registry, config.output_dir / "regime_factor_registry.csv")
    pd.DataFrame([asdict(config)]).to_csv(config.output_dir / "regime_run_config.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build R1 market-regime event table.")
    parser.add_argument("--data-dir", default=str(RegimeResearchConfig().data_dir))
    parser.add_argument("--output-dir", default=str(RegimeResearchConfig().output_dir))
    parser.add_argument("--symbols", nargs="*", default=RegimeResearchConfig().symbols)
    args = parser.parse_args()
    config = RegimeResearchConfig(data_dir=Path(args.data_dir), output_dir=Path(args.output_dir), symbols=args.symbols)
    events, audit, missing = build_market_regime_events(config)
    write_outputs(events, audit, missing, config)
    print(f"Wrote {len(events)} regime events to {config.output_dir}")


if __name__ == "__main__":
    main()
