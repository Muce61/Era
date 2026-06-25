"""Event study for confirmed entry signals across entry modes."""

import numpy as np
import pandas as pd

from research.trend_research_pipeline import first_touch
from strategy.breakout_state import BreakoutStateMachine
from strategy.entry_handlers import EntryContext, evaluate_entry
from strategy.eth_trend_signals import EntryMode, StrategyConfig, build_signal_frame, load_ohlcv_1m
from strategy.hikkake_tracker import HikkakeSetupTracker
from strategy.trend_segment_state import TrendSegmentTracker

FORWARD_HORIZONS = [1, 4, 8, 16, 32]


def collect_entry_signals(data_1m: pd.DataFrame, config: StrategyConfig) -> list[dict]:
    signals_15m = build_signal_frame(data_1m, config)
    sm = BreakoutStateMachine()
    ht = HikkakeSetupTracker()
    ts_tracker = TrendSegmentTracker()
    bar_index = {ts: i for i, ts in enumerate(signals_15m.index)}
    events = []

    for signal_time, row in signals_15m.iterrows():
        bar_idx = bar_index[signal_time]
        sm.on_bar_close(signal_time, row, has_position=False)
        ts_tracker.on_bar_close(signal_time, row, has_position=False)
        ctx = EntryContext(
            signal_time=signal_time,
            row=row,
            bar_idx=bar_idx,
            signals_15m=signals_15m,
            has_position=False,
            breakout_sm=sm,
            hikkake_tracker=ht,
            trend_segment_tracker=ts_tracker,
        )
        entry = evaluate_entry(config, ctx)
        if entry is None:
            continue

        meta = entry.metadata
        vol_ma = signals_15m["volume"].shift(1).rolling(20).mean().iloc[bar_idx]
        vol_ratio = float(row["volume"]) / float(vol_ma) if vol_ma and vol_ma > 0 else 1.0
        events.append({
            "signal_time": signal_time,
            "entry_mode": config.entry_mode.value,
            "signal_close": float(row["close"]),
            "atr": float(row["atr"]),
            "entry_high": float(row["entry_high"]),
            "breakout_range_atr": (float(row["close"]) - float(row["entry_high"])) / float(row["atr"]),
            "volume_ratio": vol_ratio,
            "bars_after_breakout": meta.get("bars_after_breakout", 0),
            **{k: v for k, v in meta.items() if k != "entry_mode"},
        })
        if config.entry_mode in (EntryMode.PULLBACK_ENGULFING, EntryMode.BULLISH_HIKKAKE):
            sm.mark_entered()
            if config.entry_mode == EntryMode.BULLISH_HIKKAKE:
                ht.mark_entered()

    return events


def enrich_forward_metrics(event: dict, signals_15m: pd.DataFrame, data_1m: pd.DataFrame) -> dict:
    signal_time = event["signal_time"]
    idx = signals_15m.index.get_loc(signal_time)
    entry_price = float(data_1m.loc[data_1m.index > signal_time].iloc[0]["open"])
    atr = event["atr"]
    risk = atr

    row = dict(event)
    row["entry_price_1m_open"] = entry_price
    row["year_month"] = str(signal_time.to_period("M"))
    row["atr_percentile"] = float(signals_15m["atr"].rank(pct=True).iloc[idx])

    for h in FORWARD_HORIZONS:
        end_idx = min(idx + h, len(signals_15m) - 1)
        future = signals_15m.iloc[idx + 1: end_idx + 1]
        if future.empty:
            row[f"forward_return_{h}"] = np.nan
            row[f"future_mfe_{h}"] = np.nan
            row[f"future_mae_{h}"] = np.nan
            continue

        closes = future["close"]
        highs = future["high"]
        lows = future["low"]
        row[f"forward_return_{h}"] = float((closes.iloc[-1] - entry_price) / entry_price)
        row[f"future_mfe_{h}"] = float((highs.max() - entry_price) / entry_price)
        row[f"future_mae_{h}"] = float((lows.min() - entry_price) / entry_price)

        path_start = signal_time + pd.Timedelta(minutes=1)
        path_end = future.index[-1] + pd.Timedelta(minutes=15)
        path_1m = data_1m.loc[path_start:path_end]
        if not path_1m.empty and risk > 0:
            outcome, _, _ = first_touch(path_1m, entry_price, risk, "LONG", 1, 1)
            row[f"hit_plus_1atr_first_{h}"] = outcome == "profit"
            row[f"hit_minus_1atr_first_{h}"] = outcome == "loss"
        else:
            row[f"hit_plus_1atr_first_{h}"] = False
            row[f"hit_minus_1atr_first_{h}"] = False

    return row


def run_event_study(data_path, start_date, end_date) -> tuple[pd.DataFrame, pd.DataFrame]:
    data_1m = load_ohlcv_1m(data_path, start_date, end_date)
    detail_rows = []

    for mode in EntryMode:
        config = StrategyConfig(entry_mode=mode)
        signals_15m = build_signal_frame(data_1m, config)
        raw_events = collect_entry_signals(data_1m, config)
        for ev in raw_events:
            detail_rows.append(enrich_forward_metrics(ev, signals_15m, data_1m))

    detail = pd.DataFrame(detail_rows)
    if detail.empty:
        return detail, pd.DataFrame()

    group_cols = ["entry_mode", "year_month", "atr_percentile", "bars_after_breakout", "breakout_range_atr", "volume_ratio"]
    summary_rows = []
    for keys, grp in detail.groupby(["entry_mode"], dropna=False):
        row = {"entry_mode": keys[0], "signal_count": len(grp)}
        for h in FORWARD_HORIZONS:
            row[f"mean_forward_return_{h}"] = grp[f"forward_return_{h}"].mean()
            row[f"mean_future_mae_{h}"] = grp[f"future_mae_{h}"].mean()
            row[f"plus_1atr_rate_{h}"] = grp[f"hit_plus_1atr_first_{h}"].mean()
        summary_rows.append(row)

    summary = pd.DataFrame(summary_rows)
    return detail, summary
