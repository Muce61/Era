from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CandlestickConfig:
    risk_per_trade: float = 0.003
    max_leverage: float = 10.0
    fee_rate: float = 0.0005
    slippage_rate: float = 0.0005
    reward_r: float = 2.0
    max_hold_minutes: int = 60
    confirmation_minutes: int = 5
    atr_position_distance: float = 0.35


class MultiTimeframeCandlestickResearch:
    """
    Implements the research pipeline:
    market state -> multi-timeframe direction -> key location -> 5m candle event
    -> 1m confirmation -> risk sizing -> fixed 2R/1R/time exit.
    """

    def __init__(self, config: CandlestickConfig | None = None):
        self.config = config or CandlestickConfig()

    def run_symbol(self, symbol: str, df_1m: pd.DataFrame, start=None, end=None) -> dict[str, list[dict]]:
        df_1m = self._normalize_1m(df_1m)
        if len(df_1m) < 1500:
            return {"A": [], "B": [], "C": []}

        start_ts = pd.Timestamp(start) if start is not None else None
        end_ts = pd.Timestamp(end) if end is not None else None
        frames = self._build_timeframes(df_1m)
        events = self._build_events(symbol, df_1m, frames)
        if start_ts is not None:
            events = [event for event in events if event["event_time"] >= start_ts]
        if end_ts is not None:
            events = [event for event in events if event["event_time"] <= end_ts]

        trades = {"A": [], "B": [], "C": []}
        last_exit = {group: pd.Timestamp.min for group in trades}

        for event in events:
            for group in trades:
                if event["event_time"] <= last_exit[group]:
                    continue
                trade = self._trade_from_event(group, event, df_1m)
                if trade is None:
                    continue
                trades[group].append(trade)
                last_exit[group] = trade["exit_time"]

        return trades

    def summarize(self, trades: list[dict], initial_balance: float = 10000.0) -> dict:
        equity = initial_balance
        peak = initial_balance
        max_drawdown = 0.0
        wins = 0
        gross_win = 0.0
        gross_loss = 0.0

        for trade in sorted(trades, key=lambda x: x["exit_time"]):
            pnl = equity * trade["return_on_equity"]
            equity += pnl
            peak = max(peak, equity)
            max_drawdown = min(max_drawdown, (equity - peak) / peak if peak else 0.0)
            if pnl > 0:
                wins += 1
                gross_win += pnl
            else:
                gross_loss += pnl

        return {
            "trades": len(trades),
            "final_balance": equity,
            "return_pct": (equity / initial_balance - 1.0) * 100.0,
            "win_rate": wins / len(trades) * 100.0 if trades else 0.0,
            "profit_factor": abs(gross_win / gross_loss) if gross_loss < 0 else np.inf,
            "max_drawdown_pct": max_drawdown * 100.0,
        }

    def _normalize_1m(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
            df = df.set_index("timestamp")
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        required = ["open", "high", "low", "close", "volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing OHLCV columns: {missing}")
        return df[required].astype(float).dropna()

    def _build_timeframes(self, df_1m: pd.DataFrame) -> dict[str, pd.DataFrame]:
        return {
            "5m": self._resample(df_1m, "5min"),
            "15m": self._with_indicators(self._resample(df_1m, "15min")),
            "1h": self._with_indicators(self._resample(df_1m, "1h")),
            "1d": self._with_indicators(self._resample(df_1m, "1d")),
        }

    def _resample(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        out = df.resample(rule).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        out.index = out.index + pd.Timedelta(rule)
        return out

    def _with_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
        out["ema50"] = out["close"].ewm(span=50, adjust=False).mean()
        out["ema60"] = out["close"].ewm(span=60, adjust=False).mean()
        out["ema20_slope5"] = out["ema20"] - out["ema20"].shift(5)
        out["ema50_slope5"] = out["ema50"] - out["ema50"].shift(5)
        out["atr14"] = self._atr(out, 14)
        out["roll_low20"] = out["low"].rolling(20).min()
        out["roll_high20"] = out["high"].rolling(20).max()
        return out

    def _atr(self, df: pd.DataFrame, length: int) -> pd.Series:
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.rolling(length).mean()

    def _build_events(self, symbol: str, df_1m: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> list[dict]:
        df_5m = self._with_indicators(frames["5m"])
        events = []
        for i in range(80, len(df_5m)):
            event_time = df_5m.index[i]
            bar = df_5m.iloc[i]
            prev = df_5m.iloc[i - 1]
            atr5 = bar["atr14"]
            if not np.isfinite(atr5) or atr5 <= 0:
                continue

            daily = self._asof(frames["1d"], event_time)
            hourly = self._asof(frames["1h"], event_time)
            location = self._asof(frames["15m"], event_time)
            direction = self._direction(daily, hourly)
            if direction is None or location is None:
                continue

            in_location, location_reasons = self._key_location(direction, bar["close"], location)
            if not in_location:
                continue

            candle_name = self._candle_event(direction, bar, prev, atr5, df_5m.iloc[i - 6 : i])
            volume_ok = bar["volume"] > df_5m["volume"].iloc[i - 20 : i].median()
            if candle_name is None or not volume_ok:
                candle_name_for_b = None
            else:
                candle_name_for_b = candle_name

            stop = (
                bar["low"] - 0.15 * atr5
                if direction == "LONG"
                else bar["high"] + 0.15 * atr5
            )
            events.append(
                {
                    "symbol": symbol,
                    "event_time": event_time,
                    "side": direction,
                    "signal_high": bar["high"],
                    "signal_low": bar["low"],
                    "stop": stop,
                    "atr5": atr5,
                    "candle": candle_name_for_b,
                    "location": ",".join(location_reasons),
                    "daily_close": daily["close"],
                    "h1_close": hourly["close"],
                }
            )
        return events

    def _asof(self, df: pd.DataFrame, timestamp: pd.Timestamp):
        loc = df.index.searchsorted(timestamp, side="right") - 1
        if loc < 0:
            return None
        row = df.iloc[loc]
        return row if row.notna().all() else None

    def _direction(self, daily, hourly) -> str | None:
        if daily is None or hourly is None:
            return None

        daily_long = (
            daily["close"] > daily["ema20"]
            and daily["ema20"] > daily["ema60"]
            and daily["ema20_slope5"] > 0
        )
        daily_short = (
            daily["close"] < daily["ema20"]
            and daily["ema20"] < daily["ema60"]
            and daily["ema20_slope5"] < 0
        )
        h1_long = (
            hourly["ema20"] > hourly["ema50"]
            and hourly["close"] > hourly["ema50"]
            and hourly["ema50_slope5"] >= 0
        )
        h1_short = (
            hourly["ema20"] < hourly["ema50"]
            and hourly["close"] < hourly["ema50"]
            and hourly["ema50_slope5"] <= 0
        )

        if daily_long and h1_long:
            return "LONG"
        if daily_short and h1_short:
            return "SHORT"
        return None

    def _key_location(self, side: str, price: float, row) -> tuple[bool, list[str]]:
        atr = row["atr14"]
        if not np.isfinite(atr) or atr <= 0:
            return False, []

        checks = []
        if side == "LONG":
            levels = [("ema20_15m", row["ema20"]), ("ema50_15m", row["ema50"]), ("low20_15m", row["roll_low20"])]
        else:
            levels = [("ema20_15m", row["ema20"]), ("ema50_15m", row["ema50"]), ("high20_15m", row["roll_high20"])]

        for name, level in levels:
            if np.isfinite(level) and abs(price - level) / atr <= self.config.atr_position_distance:
                checks.append(name)
        return bool(checks), checks

    def _candle_event(self, side: str, bar, prev, atr: float, prior_6: pd.DataFrame) -> str | None:
        body = abs(bar["close"] - bar["open"])
        candle_range = bar["high"] - bar["low"]
        if candle_range <= 0:
            return None
        upper = bar["high"] - max(bar["open"], bar["close"])
        lower = min(bar["open"], bar["close"]) - bar["low"]
        body_ratio = body / candle_range
        upper_ratio = upper / candle_range
        lower_ratio = lower / candle_range
        min_tick = max(bar["close"] * 1e-8, 1e-12)

        if side == "LONG":
            had_pullback = len(prior_6) >= 3 and (
                (prior_6["close"].tail(6).iloc[-1] / prior_6["close"].tail(6).iloc[0] - 1) < 0
            )
            hammer = (
                candle_range >= 0.5 * atr
                and body_ratio <= 0.35
                and lower >= 2.0 * max(body, min_tick)
                and lower_ratio >= 0.55
                and upper_ratio <= 0.15
                and bar["close"] >= bar["low"] + 0.65 * candle_range
                and had_pullback
            )
            engulfing = (
                prev["close"] < prev["open"]
                and bar["close"] > bar["open"]
                and min(bar["open"], bar["close"]) <= min(prev["open"], prev["close"])
                and max(bar["open"], bar["close"]) >= max(prev["open"], prev["close"])
                and body >= 1.1 * abs(prev["close"] - prev["open"])
                and body >= 0.5 * atr
            )
            if hammer:
                return "bullish_hammer"
            if engulfing:
                return "bullish_engulfing"
            return None

        shooting_star = (
            candle_range >= 0.5 * atr
            and body_ratio <= 0.35
            and upper >= 2.0 * max(body, min_tick)
            and upper_ratio >= 0.55
            and lower_ratio <= 0.15
            and bar["close"] <= bar["low"] + 0.35 * candle_range
        )
        bearish_engulfing = (
            prev["close"] > prev["open"]
            and bar["close"] < bar["open"]
            and min(bar["open"], bar["close"]) <= min(prev["open"], prev["close"])
            and max(bar["open"], bar["close"]) >= max(prev["open"], prev["close"])
            and body >= 1.1 * abs(prev["close"] - prev["open"])
            and body >= 0.5 * atr
        )
        if shooting_star:
            return "shooting_star"
        if bearish_engulfing:
            return "bearish_engulfing"
        return None

    def _trade_from_event(self, group: str, event: dict, df_1m: pd.DataFrame) -> dict | None:
        if group in {"B", "C"} and event["candle"] is None:
            return None

        if group == "C":
            entry_time, entry_price = self._confirmed_entry(event, df_1m)
        else:
            entry_time = event["event_time"]
            entry_price = self._open_at(df_1m, entry_time)

        if entry_time is None or entry_price is None:
            return None

        side = event["side"]
        entry_price = entry_price * (1 + self.config.slippage_rate if side == "LONG" else 1 - self.config.slippage_rate)
        stop = event["stop"]
        risk_per_unit = abs(entry_price - stop)
        if risk_per_unit <= 0:
            return None
        target = entry_price + self.config.reward_r * risk_per_unit if side == "LONG" else entry_price - self.config.reward_r * risk_per_unit

        exit_time, exit_price, reason = self._exit_trade(df_1m, entry_time, side, stop, target)
        if exit_time is None:
            return None

        exit_price = exit_price * (1 - self.config.slippage_rate if side == "LONG" else 1 + self.config.slippage_rate)
        stop_pct = risk_per_unit / entry_price
        notional_to_equity = min(self.config.risk_per_trade / stop_pct, self.config.max_leverage)
        gross_return = (
            (exit_price - entry_price) / entry_price
            if side == "LONG"
            else (entry_price - exit_price) / entry_price
        )
        fee_drag = self.config.fee_rate * 2 * notional_to_equity
        roe = gross_return * notional_to_equity - fee_drag

        return {
            "group": group,
            "symbol": event["symbol"],
            "side": side,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "stop": stop,
            "target": target,
            "notional_to_equity": notional_to_equity,
            "return_on_equity": roe,
            "exit_reason": reason,
            "candle": event["candle"] or "none",
            "location": event["location"],
        }

    def _open_at(self, df: pd.DataFrame, timestamp: pd.Timestamp) -> float | None:
        if timestamp not in df.index:
            return None
        return float(df.loc[timestamp, "open"])

    def _confirmed_entry(self, event: dict, df: pd.DataFrame) -> tuple[pd.Timestamp | None, float | None]:
        side = event["side"]
        start = event["event_time"]
        window = df.loc[start : start + pd.Timedelta(minutes=self.config.confirmation_minutes - 1)]
        if window.empty:
            return None, None

        for ts, row in window.iterrows():
            hist = df.loc[:ts].tail(25)
            ema20 = hist["close"].ewm(span=20, adjust=False).mean().iloc[-1]
            body_ratio = abs(row["close"] - row["open"]) / max(row["high"] - row["low"], 1e-12)
            recent_3 = df.loc[:ts].tail(4).iloc[:-1]
            if len(recent_3) < 3:
                continue
            if side == "LONG":
                trigger = row["close"] > event["signal_high"] or row["close"] > recent_3["high"].max()
                valid = trigger and row["close"] > ema20 and body_ratio >= 0.5
            else:
                trigger = row["close"] < event["signal_low"] or row["close"] < recent_3["low"].min()
                valid = trigger and row["close"] < ema20 and body_ratio >= 0.5
            if not valid:
                continue
            entry_time = ts + pd.Timedelta(minutes=1)
            return entry_time, self._open_at(df, entry_time)
        return None, None

    def _exit_trade(self, df: pd.DataFrame, entry_time: pd.Timestamp, side: str, stop: float, target: float):
        end = entry_time + pd.Timedelta(minutes=self.config.max_hold_minutes)
        path = df.loc[entry_time:end]
        if path.empty:
            return None, None, None

        for ts, row in path.iterrows():
            if side == "LONG":
                if row["low"] <= stop:
                    return ts, stop, "stop_1r"
                if row["high"] >= target:
                    return ts, target, "target_2r"
            else:
                if row["high"] >= stop:
                    return ts, stop, "stop_1r"
                if row["low"] <= target:
                    return ts, target, "target_2r"
        last = path.iloc[-1]
        return path.index[-1], float(last["close"]), "time_exit"


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)
