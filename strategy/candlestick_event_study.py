from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from strategy.multitimeframe_candlestick import CandlestickConfig, MultiTimeframeCandlestickResearch


@dataclass(frozen=True)
class EventStudyConfig:
    fee_rate: float = 0.0005
    slippage_rate: float = 0.0005
    horizons_5m: tuple[int, ...] = (1, 3, 6, 12, 24)
    target_r_values: tuple[float, ...] = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
    confirmation_minutes: int = 5


class CandlestickEventStudy:
    def __init__(self, config: EventStudyConfig | None = None):
        self.config = config or EventStudyConfig()
        self.research = MultiTimeframeCandlestickResearch(
            CandlestickConfig(
                fee_rate=self.config.fee_rate,
                slippage_rate=self.config.slippage_rate,
                confirmation_minutes=self.config.confirmation_minutes,
            )
        )

    def build_dataset(self, symbol: str, df_1m: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
        df_1m = self.research._normalize_1m(df_1m)
        if len(df_1m) < 1500:
            return pd.DataFrame()

        start_ts = pd.Timestamp(start) if start is not None else None
        end_ts = pd.Timestamp(end) if end is not None else None
        frames = self.research._build_timeframes(df_1m)
        df_5m = self.research._with_indicators(frames["5m"])
        rows = []

        for i in range(80, len(df_5m)):
            event_time = df_5m.index[i]
            if start_ts is not None and event_time < start_ts:
                continue
            if end_ts is not None and event_time > end_ts:
                continue

            bar = df_5m.iloc[i]
            prev = df_5m.iloc[i - 1]
            atr5 = bar["atr14"]
            if not np.isfinite(atr5) or atr5 <= 0:
                continue

            patterns = self._detect_patterns(bar, prev, atr5, df_5m.iloc[i - 12 : i])
            if not patterns:
                continue

            daily = self.research._asof(frames["1d"], event_time)
            hourly = self.research._asof(frames["1h"], event_time)
            location = self.research._asof(frames["15m"], event_time)
            mtf_direction = self.research._direction(daily, hourly)

            candle_features = self._candle_features(bar, prev, atr5)
            trend_features = self._local_trend_features(df_5m, i, atr5)
            location_features = self._location_features(location, bar)
            volume_features = self._volume_features(df_5m, i, bar)

            for pattern_type, side in patterns:
                entry_time = event_time
                entry_price = self.research._open_at(df_1m, entry_time)
                if entry_price is None:
                    continue
                stop = bar["low"] - 0.15 * atr5 if side == "LONG" else bar["high"] + 0.15 * atr5
                risk = abs(entry_price - stop)
                if risk <= 0:
                    continue

                row = {
                    "symbol": symbol,
                    "event_time": event_time,
                    "pattern_type": pattern_type,
                    "side": side,
                    "mtf_direction": mtf_direction or "NONE",
                    "mtf_aligned": mtf_direction == side,
                    "entry_e0_time": entry_time,
                    "entry_e0_price": entry_price,
                    "stop_price": stop,
                    "risk_per_unit": risk,
                    "risk_pct": risk / entry_price,
                    **candle_features,
                    **trend_features,
                    **location_features,
                    **volume_features,
                }
                row.update(self._forward_labels(df_1m, row, bar))
                row.update(self._confirmation_labels(df_1m, row, bar))
                rows.append(row)

        return pd.DataFrame(rows)

    def write_outputs(self, events: pd.DataFrame, output_dir: Path) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs = {
            "events": output_dir / "events.csv",
            "pattern_summary": output_dir / "pattern_summary.csv",
            "target_hit_curve": output_dir / "target_hit_curve.csv",
            "horizon_returns": output_dir / "horizon_returns.csv",
            "mfe_mae_summary": output_dir / "mfe_mae_summary.csv",
            "confirmation_cost": output_dir / "confirmation_cost.csv",
            "location_type_summary": output_dir / "location_type_summary.csv",
            "local_trend_quantiles": output_dir / "local_trend_quantiles.csv",
            "volume_quantiles": output_dir / "volume_quantiles.csv",
        }
        events.to_csv(outputs["events"], index=False)
        self.pattern_summary(events).to_csv(outputs["pattern_summary"], index=False)
        self.target_hit_curve(events).to_csv(outputs["target_hit_curve"], index=False)
        self.horizon_returns(events).to_csv(outputs["horizon_returns"], index=False)
        self.mfe_mae_summary(events).to_csv(outputs["mfe_mae_summary"], index=False)
        self.confirmation_cost(events).to_csv(outputs["confirmation_cost"], index=False)
        self.location_type_summary(events).to_csv(outputs["location_type_summary"], index=False)
        self.local_trend_quantiles(events).to_csv(outputs["local_trend_quantiles"], index=False)
        self.volume_quantiles(events).to_csv(outputs["volume_quantiles"], index=False)
        return outputs

    def pattern_summary(self, events: pd.DataFrame) -> pd.DataFrame:
        if events.empty:
            return pd.DataFrame()
        return self._group_stats(events, ["pattern_type", "side"], "net_r_12bars")

    def target_hit_curve(self, events: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for target in self.config.target_r_values:
            col = self._target_col(target)
            r_col = self._target_net_r_col(target)
            hold_col = self._target_hold_col(target)
            for keys, group in events.groupby(["pattern_type", "side"], dropna=False):
                rows.append(
                    {
                        "pattern_type": keys[0],
                        "side": keys[1],
                        "target_r": target,
                        "events": len(group),
                        "target_first_rate": group[col].mean(),
                        "mean_net_r": group[r_col].mean(),
                        "median_net_r": group[r_col].median(),
                        "pf": self._profit_factor(group[r_col]),
                        "avg_hold_minutes": group[hold_col].mean(),
                    }
                )
        return pd.DataFrame(rows)

    def horizon_returns(self, events: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for horizon in self.config.horizons_5m:
            col = f"net_r_{horizon}bars"
            for keys, group in events.groupby(["pattern_type", "side"], dropna=False):
                rows.append(
                    {
                        "pattern_type": keys[0],
                        "side": keys[1],
                        "horizon_5m_bars": horizon,
                        "events": len(group),
                        "mean_net_r": group[col].mean(),
                        "median_net_r": group[col].median(),
                        "win_rate": (group[col] > 0).mean(),
                        "pf": self._profit_factor(group[col]),
                    }
                )
        return pd.DataFrame(rows)

    def mfe_mae_summary(self, events: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for horizon in self.config.horizons_5m:
            for keys, group in events.groupby(["pattern_type", "side"], dropna=False):
                rows.append(
                    {
                        "pattern_type": keys[0],
                        "side": keys[1],
                        "horizon_5m_bars": horizon,
                        "events": len(group),
                        "mean_mfe_r": group[f"mfe_r_{horizon}bars"].mean(),
                        "median_mfe_r": group[f"mfe_r_{horizon}bars"].median(),
                        "mean_mae_r": group[f"mae_r_{horizon}bars"].mean(),
                        "median_mae_r": group[f"mae_r_{horizon}bars"].median(),
                        "median_time_to_mfe_min": group[f"time_to_mfe_min_{horizon}bars"].median(),
                        "median_time_to_mae_min": group[f"time_to_mae_min_{horizon}bars"].median(),
                    }
                )
        return pd.DataFrame(rows)

    def confirmation_cost(self, events: pd.DataFrame) -> pd.DataFrame:
        cols = [
            "symbol",
            "event_time",
            "pattern_type",
            "side",
            "confirmation_triggered",
            "confirmation_wait_minutes",
            "entry_price_change_r",
            "e0_mfe_r_12bars",
            "e1_mfe_r_12bars",
            "confirmation_mfe_cost_r",
            "e0_net_r_12bars",
            "e1_net_r_12bars",
            "confirmation_net_r_delta",
        ]
        return events[[c for c in cols if c in events.columns]].copy()

    def location_type_summary(self, events: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for location in ["ema20_15m", "ema50_15m", "recent_swing", "sweep_reclaim"]:
            subset = events[events[location]]
            if subset.empty:
                continue
            stats = self._group_stats(subset, ["pattern_type", "side"], "net_r_12bars")
            stats.insert(0, "location_type", location)
            rows.append(stats)
        return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()

    def local_trend_quantiles(self, events: pd.DataFrame) -> pd.DataFrame:
        return self._quantile_summary(events, "move_6bars_atr", "local_trend_quantile")

    def volume_quantiles(self, events: pd.DataFrame) -> pd.DataFrame:
        return self._quantile_summary(events, "signal_volume_ratio", "volume_quantile")

    def _detect_patterns(self, bar, prev, atr: float, prior: pd.DataFrame) -> list[tuple[str, str]]:
        features = self._candle_features(bar, prev, atr)
        body = abs(bar["close"] - bar["open"])
        candle_range = bar["high"] - bar["low"]
        min_tick = max(bar["close"] * 1e-8, 1e-12)
        patterns = []

        had_pullback = len(prior) >= 6 and prior["close"].iloc[-1] < prior["close"].iloc[-6]
        hammer = (
            candle_range >= 0.5 * atr
            and features["body_ratio"] <= 0.35
            and features["lower_shadow_body_ratio"] >= 2.0
            and features["lower_shadow_ratio"] >= 0.55
            and features["upper_shadow_ratio"] <= 0.15
            and features["close_location_value"] >= 0.65
            and had_pullback
        )
        bullish_engulfing = (
            prev["close"] < prev["open"]
            and bar["close"] > bar["open"]
            and min(bar["open"], bar["close"]) <= min(prev["open"], prev["close"])
            and max(bar["open"], bar["close"]) >= max(prev["open"], prev["close"])
            and body >= 1.1 * max(abs(prev["close"] - prev["open"]), min_tick)
            and body >= 0.5 * atr
        )
        shooting_star = (
            candle_range >= 0.5 * atr
            and features["body_ratio"] <= 0.35
            and features["upper_shadow_body_ratio"] >= 2.0
            and features["upper_shadow_ratio"] >= 0.55
            and features["lower_shadow_ratio"] <= 0.15
            and features["close_location_value"] <= 0.35
        )
        bearish_engulfing = (
            prev["close"] > prev["open"]
            and bar["close"] < bar["open"]
            and min(bar["open"], bar["close"]) <= min(prev["open"], prev["close"])
            and max(bar["open"], bar["close"]) >= max(prev["open"], prev["close"])
            and body >= 1.1 * max(abs(prev["close"] - prev["open"]), min_tick)
            and body >= 0.5 * atr
        )

        if hammer:
            patterns.append(("bullish_hammer", "LONG"))
        if bullish_engulfing:
            patterns.append(("bullish_engulfing", "LONG"))
        if shooting_star:
            patterns.append(("shooting_star", "SHORT"))
        if bearish_engulfing:
            patterns.append(("bearish_engulfing", "SHORT"))
        return patterns

    def _candle_features(self, bar, prev, atr: float) -> dict:
        body = abs(bar["close"] - bar["open"])
        prev_body = abs(prev["close"] - prev["open"])
        candle_range = max(bar["high"] - bar["low"], 1e-12)
        upper = bar["high"] - max(bar["open"], bar["close"])
        lower = min(bar["open"], bar["close"]) - bar["low"]
        return {
            "body_atr": body / atr,
            "range_atr": candle_range / atr,
            "body_ratio": body / candle_range,
            "upper_shadow_ratio": upper / candle_range,
            "lower_shadow_ratio": lower / candle_range,
            "upper_shadow_body_ratio": upper / max(body, 1e-12),
            "lower_shadow_body_ratio": lower / max(body, 1e-12),
            "close_location_value": (bar["close"] - bar["low"]) / candle_range,
            "engulf_body_ratio": body / max(prev_body, 1e-12),
        }

    def _local_trend_features(self, df_5m: pd.DataFrame, i: int, atr: float) -> dict:
        row = {}
        close = df_5m["close"]
        for bars in (3, 6, 12):
            start_close = close.iloc[i - bars]
            ret = close.iloc[i - 1] / start_close - 1 if start_close else np.nan
            row[f"return_5m_{bars}bars"] = ret
            row[f"move_{bars}bars_atr"] = (close.iloc[i - 1] - start_close) / atr

        prior = df_5m.iloc[i - 20 : i]
        highs = prior["high"]
        lows = prior["low"]
        row["higher_high_count"] = int((highs.diff() > 0).sum())
        row["lower_low_count"] = int((lows.diff() < 0).sum())
        row["prior_swing_high"] = highs.max()
        row["prior_swing_low"] = lows.min()
        row["distance_from_recent_high_atr"] = (row["prior_swing_high"] - df_5m["close"].iloc[i]) / atr
        row["distance_from_recent_low_atr"] = (df_5m["close"].iloc[i] - row["prior_swing_low"]) / atr
        return row

    def _location_features(self, location, bar) -> dict:
        empty = {
            "ema20_15m": False,
            "ema50_15m": False,
            "recent_swing": False,
            "sweep_reclaim": False,
            "distance_ema20_atr": np.nan,
            "distance_ema50_atr": np.nan,
            "distance_swing_atr": np.nan,
        }
        if location is None or not np.isfinite(location["atr14"]) or location["atr14"] <= 0:
            return empty

        atr = location["atr14"]
        empty["distance_ema20_atr"] = abs(bar["close"] - location["ema20"]) / atr
        empty["distance_ema50_atr"] = abs(bar["close"] - location["ema50"]) / atr
        low_dist = abs(bar["close"] - location["roll_low20"]) / atr
        high_dist = abs(bar["close"] - location["roll_high20"]) / atr
        empty["distance_swing_atr"] = min(low_dist, high_dist)
        empty["ema20_15m"] = empty["distance_ema20_atr"] <= 0.35
        empty["ema50_15m"] = empty["distance_ema50_atr"] <= 0.35
        empty["recent_swing"] = empty["distance_swing_atr"] <= 0.35
        bullish_sweep = bar["low"] < location["roll_low20"] and bar["close"] > location["roll_low20"]
        bearish_sweep = bar["high"] > location["roll_high20"] and bar["close"] < location["roll_high20"]
        empty["sweep_reclaim"] = bool(bullish_sweep or bearish_sweep)
        return empty

    def _volume_features(self, df_5m: pd.DataFrame, i: int, bar) -> dict:
        window = df_5m["volume"].iloc[i - 20 : i]
        median = window.median()
        mean = window.mean()
        return {
            "signal_volume_ratio": bar["volume"] / median if median > 0 else np.nan,
            "signal_volume_mean_ratio": bar["volume"] / mean if mean > 0 else np.nan,
        }

    def _forward_labels(self, df_1m: pd.DataFrame, row: dict, bar) -> dict:
        out = {}
        side = row["side"]
        entry = row["entry_e0_price"]
        risk = row["risk_per_unit"]
        for horizon in self.config.horizons_5m:
            minutes = horizon * 5
            path = df_1m.loc[row["entry_e0_time"] : row["entry_e0_time"] + pd.Timedelta(minutes=minutes)]
            if path.empty:
                continue
            last_close = path["close"].iloc[-1]
            if side == "LONG":
                mfe = (path["high"].max() - entry) / risk
                mae = (entry - path["low"].min()) / risk
                gross_r = (last_close - entry) / risk
                time_to_mfe = (path["high"].idxmax() - row["entry_e0_time"]).total_seconds() / 60
                time_to_mae = (path["low"].idxmin() - row["entry_e0_time"]).total_seconds() / 60
            else:
                mfe = (entry - path["low"].min()) / risk
                mae = (path["high"].max() - entry) / risk
                gross_r = (entry - last_close) / risk
                time_to_mfe = (path["low"].idxmin() - row["entry_e0_time"]).total_seconds() / 60
                time_to_mae = (path["high"].idxmax() - row["entry_e0_time"]).total_seconds() / 60
            out[f"forward_return_{horizon}bars"] = (last_close / entry - 1) * (1 if side == "LONG" else -1)
            out[f"mfe_r_{horizon}bars"] = mfe
            out[f"mae_r_{horizon}bars"] = mae
            out[f"time_to_mfe_min_{horizon}bars"] = time_to_mfe
            out[f"time_to_mae_min_{horizon}bars"] = time_to_mae
            out[f"net_r_{horizon}bars"] = gross_r - self._round_trip_cost_r(entry, risk)

        for target in self.config.target_r_values:
            hit, net_r, hold = self._first_touch(df_1m, row, target, max_minutes=120)
            out[self._target_col(target)] = hit
            out[self._target_net_r_col(target)] = net_r
            out[self._target_hold_col(target)] = hold

        out["e0_mfe_r_12bars"] = out.get("mfe_r_12bars", np.nan)
        out["e0_net_r_12bars"] = out.get("net_r_12bars", np.nan)
        return out

    def _confirmation_labels(self, df_1m: pd.DataFrame, row: dict, bar) -> dict:
        event = {
            "side": row["side"],
            "event_time": row["event_time"],
            "signal_high": bar["high"],
            "signal_low": bar["low"],
        }
        entry_time, entry_price = self.research._confirmed_entry(event, df_1m)
        out = {
            "confirmation_triggered": entry_time is not None and entry_price is not None,
            "confirmation_wait_minutes": np.nan,
            "entry_e1_time": pd.NaT,
            "entry_e1_price": np.nan,
            "entry_price_change_r": np.nan,
            "e1_mfe_r_12bars": np.nan,
            "e1_net_r_12bars": np.nan,
            "confirmation_mfe_cost_r": np.nan,
            "confirmation_net_r_delta": np.nan,
        }
        if entry_time is None or entry_price is None:
            return out

        side = row["side"]
        risk = row["risk_per_unit"]
        path = df_1m.loc[entry_time : entry_time + pd.Timedelta(minutes=60)]
        if path.empty:
            return out
        if side == "LONG":
            mfe = (path["high"].max() - entry_price) / risk
            gross_r = (path["close"].iloc[-1] - entry_price) / risk
            price_change_r = (entry_price - row["entry_e0_price"]) / risk
        else:
            mfe = (entry_price - path["low"].min()) / risk
            gross_r = (entry_price - path["close"].iloc[-1]) / risk
            price_change_r = (row["entry_e0_price"] - entry_price) / risk

        net_r = gross_r - self._round_trip_cost_r(entry_price, risk)
        out.update(
            {
                "confirmation_wait_minutes": (entry_time - row["event_time"]).total_seconds() / 60,
                "entry_e1_time": entry_time,
                "entry_e1_price": entry_price,
                "entry_price_change_r": price_change_r,
                "e1_mfe_r_12bars": mfe,
                "e1_net_r_12bars": net_r,
                "confirmation_mfe_cost_r": row.get("e0_mfe_r_12bars", np.nan) - mfe,
                "confirmation_net_r_delta": net_r - row.get("e0_net_r_12bars", np.nan),
            }
        )
        return out

    def _first_touch(self, df_1m: pd.DataFrame, row: dict, target_r: float, max_minutes: int):
        side = row["side"]
        entry = row["entry_e0_price"]
        risk = row["risk_per_unit"]
        target = entry + target_r * risk if side == "LONG" else entry - target_r * risk
        stop = entry - risk if side == "LONG" else entry + risk
        path = df_1m.loc[row["entry_e0_time"] : row["entry_e0_time"] + pd.Timedelta(minutes=max_minutes)]
        if path.empty:
            return False, np.nan, np.nan
        for ts, candle in path.iterrows():
            if side == "LONG":
                if candle["low"] <= stop:
                    return False, -1.0 - self._round_trip_cost_r(entry, risk), (ts - row["entry_e0_time"]).total_seconds() / 60
                if candle["high"] >= target:
                    return True, target_r - self._round_trip_cost_r(entry, risk), (ts - row["entry_e0_time"]).total_seconds() / 60
            else:
                if candle["high"] >= stop:
                    return False, -1.0 - self._round_trip_cost_r(entry, risk), (ts - row["entry_e0_time"]).total_seconds() / 60
                if candle["low"] <= target:
                    return True, target_r - self._round_trip_cost_r(entry, risk), (ts - row["entry_e0_time"]).total_seconds() / 60
        last = path["close"].iloc[-1]
        gross_r = (last - entry) / risk if side == "LONG" else (entry - last) / risk
        return False, gross_r - self._round_trip_cost_r(entry, risk), max_minutes

    def _round_trip_cost_r(self, entry: float, risk: float) -> float:
        return (entry * (self.config.fee_rate * 2 + self.config.slippage_rate * 2)) / risk

    def _group_stats(self, df: pd.DataFrame, group_cols: list[str], value_col: str) -> pd.DataFrame:
        rows = []
        for keys, group in df.groupby(group_cols, dropna=False, observed=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            values = group[value_col]
            row = {col: key for col, key in zip(group_cols, keys)}
            row.update(
                {
                    "events": len(group),
                    "mean_net_r": values.mean(),
                    "median_net_r": values.median(),
                    "win_rate": (values > 0).mean(),
                    "pf": self._profit_factor(values),
                    "median_mfe_r_12bars": group["mfe_r_12bars"].median(),
                    "median_mae_r_12bars": group["mae_r_12bars"].median(),
                }
            )
            rows.append(row)
        return pd.DataFrame(rows)

    def _quantile_summary(self, events: pd.DataFrame, source_col: str, label: str) -> pd.DataFrame:
        df = events.dropna(subset=[source_col, "net_r_12bars"]).copy()
        if df.empty:
            return pd.DataFrame()
        try:
            df[label] = pd.qcut(df[source_col], q=5, duplicates="drop")
        except ValueError:
            return pd.DataFrame()
        return self._group_stats(df, [label, "pattern_type", "side"], "net_r_12bars")

    def _profit_factor(self, values: pd.Series) -> float:
        wins = values[values > 0].sum()
        losses = values[values < 0].sum()
        if losses == 0:
            return np.inf if wins > 0 else 0.0
        return abs(wins / losses)

    def _target_col(self, target: float) -> str:
        return f"target_{str(target).replace('.', '_')}r_first"

    def _target_net_r_col(self, target: float) -> str:
        return f"target_{str(target).replace('.', '_')}r_net_r"

    def _target_hold_col(self, target: float) -> str:
        return f"target_{str(target).replace('.', '_')}r_hold_min"


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)
