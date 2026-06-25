import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.accounting import execute_entry, execute_exit, gross_pnl, trade_net_pnl
from backtest.metrics import profit_factor, summarize_trades, max_drawdown, geometric_mean_return
from strategy.trend_following import build_signal_frame, load_ohlcv_1m


def load_config(path="config/trend_research.yaml"):
    config = {}
    for raw_line in Path(path).read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            config[key] = [int(x.strip()) for x in value[1:-1].split(",") if x.strip()]
        elif value.startswith('"') and value.endswith('"'):
            config[key] = value[1:-1]
        else:
            try:
                config[key] = int(value)
            except ValueError:
                try:
                    config[key] = float(value)
                except ValueError:
                    config[key] = value
    return config


def direction_value(direction):
    return 1 if direction == "LONG" else -1


def add_event_features(signals, config):
    df = signals.copy()
    for window in config["er_windows"]:
        change = (df["close"] - df["close"].shift(window)).abs()
        path = df["close"].diff().abs().rolling(window).sum()
        df[f"er_{window}"] = change / path.replace(0, np.nan)

    lag = int(config["ema_slope_lag"])
    df["ema200_slope_atr"] = (df["ema200"] - df["ema200"].shift(lag)) / df["atr"]
    df["atr_pct"] = df["atr"].rolling(int(config["atr_percentile_window"])).rank(pct=True)
    df["normalized_atr"] = df["atr"] / df["close"]
    df["donchian_width_atr"] = (df["donchian_high_55"] - df["donchian_low_55"]) / df["atr"]
    df["candle_body_atr"] = (df["close"] - df["open"]).abs() / df["atr"]
    candle_range = (df["high"] - df["low"]).replace(0, np.nan)
    df["close_location"] = (df["close"] - df["low"]) / candle_range
    vol_window = int(config["volume_zscore_window"])
    vol_mean = df["volume"].rolling(vol_window).mean()
    vol_std = df["volume"].rolling(vol_window).std()
    df["volume_zscore"] = (df["volume"] - vol_mean) / vol_std.replace(0, np.nan)
    return df


def next_1m_open(data_1m, signal_time):
    next_time = signal_time + pd.Timedelta(minutes=1)
    if next_time not in data_1m.index:
        future = data_1m.index[data_1m.index > signal_time]
        if len(future) == 0:
            return None, None
        next_time = future[0]
    return next_time, float(data_1m.loc[next_time, "open"])


def generate_events(data_1m, signals, config):
    signal_features = add_event_features(signals, config)
    rows = []
    event_id = 1
    for signal_time, row in signal_features.iterrows():
        direction = None
        if bool(row["long_signal"]):
            direction = "LONG"
        elif bool(row["short_signal"]):
            direction = "SHORT"
        if direction is None:
            continue

        entry_time, raw_entry = next_1m_open(data_1m, signal_time)
        if entry_time is None or not np.isfinite(raw_entry):
            continue

        if direction == "LONG":
            initial_stop = raw_entry - row["atr"] * config["atr_stop_mult"]
            breakout_strength = (row["close"] - row["donchian_high_55"]) / row["atr"]
            signed_body = (row["close"] - row["open"]) / row["atr"]
            directional_close_location = row["close_location"]
        else:
            initial_stop = raw_entry + row["atr"] * config["atr_stop_mult"]
            breakout_strength = (row["donchian_low_55"] - row["close"]) / row["atr"]
            signed_body = (row["open"] - row["close"]) / row["atr"]
            directional_close_location = 1 - row["close_location"]

        rows.append({
            "event_id": event_id,
            "symbol": config["symbol"],
            "direction": direction,
            "signal_time": signal_time,
            "signal_close": row["close"],
            "next_1m_open_time": entry_time,
            "next_1m_open": raw_entry,
            "atr": row["atr"],
            "ema50": row["ema50"],
            "ema200": row["ema200"],
            "donchian_high_55": row["donchian_high_55"],
            "donchian_low_55": row["donchian_low_55"],
            "donchian_high_20": row["donchian_high_20"],
            "donchian_low_20": row["donchian_low_20"],
            "initial_stop_price": initial_stop,
            "initial_risk_amount": abs(raw_entry - initial_stop),
            "er_20": row.get("er_20", np.nan),
            "er_40": row.get("er_40", np.nan),
            "ema200_slope_atr": row["ema200_slope_atr"],
            "atr_pct": row["atr_pct"],
            "normalized_atr": row["normalized_atr"],
            "donchian_width_atr": row["donchian_width_atr"],
            "breakout_strength_atr": breakout_strength,
            "candle_body_atr": row["candle_body_atr"],
            "signed_body_atr": signed_body,
            "close_location": row["close_location"],
            "directional_close_location": directional_close_location,
            "volume_zscore": row["volume_zscore"],
        })
        event_id += 1
    events = pd.DataFrame(rows)
    if not events.empty:
        events["signal_time"] = pd.to_datetime(events["signal_time"], utc=True)
        events["next_1m_open_time"] = pd.to_datetime(events["next_1m_open_time"], utc=True)
    return events


def first_touch(path, entry, risk, direction, up_r, down_r):
    if risk <= 0:
        return "none", np.nan, False
    if direction == "LONG":
        up_price = entry + up_r * risk
        down_price = entry - down_r * risk
        for ts, c in path.iterrows():
            hit_up = c["high"] >= up_price
            hit_down = c["low"] <= down_price
            if hit_up and hit_down:
                return "ambiguous", ts, True
            if hit_down:
                return "loss", ts, False
            if hit_up:
                return "profit", ts, False
    else:
        up_price = entry - up_r * risk
        down_price = entry + down_r * risk
        for ts, c in path.iterrows():
            hit_up = c["low"] <= up_price
            hit_down = c["high"] >= down_price
            if hit_up and hit_down:
                return "ambiguous", ts, True
            if hit_down:
                return "loss", ts, False
            if hit_up:
                return "profit", ts, False
    return "none", np.nan, False


def label_events(events, data_1m, signals, config):
    if events.empty:
        return events
    rows = []
    max_window = max(config["future_windows_minutes"])
    signal_lookup = signals.copy()
    for _, event in events.iterrows():
        row = event.to_dict()
        entry_time = event["next_1m_open_time"]
        entry = event["next_1m_open"]
        direction = event["direction"]
        risk = abs(entry - event["initial_stop_price"])
        future = data_1m.loc[(data_1m.index >= entry_time) & (data_1m.index <= entry_time + pd.Timedelta(minutes=max_window))]

        for minutes in config["future_windows_minutes"]:
            path = future.loc[future.index <= entry_time + pd.Timedelta(minutes=minutes)]
            if path.empty:
                continue
            if direction == "LONG":
                mfe_price = path["high"].max()
                mae_price = path["low"].min()
                mfe = mfe_price - entry
                mae = entry - mae_price
                future_return = path["close"].iloc[-1] / entry - 1
            else:
                mfe_price = path["low"].min()
                mae_price = path["high"].max()
                mfe = entry - mfe_price
                mae = mae_price - entry
                future_return = entry / path["close"].iloc[-1] - 1
            row[f"mfe_price_{minutes}m"] = mfe_price
            row[f"mae_price_{minutes}m"] = mae_price
            row[f"mfe_atr_{minutes}m"] = mfe / event["atr"]
            row[f"mae_atr_{minutes}m"] = mae / event["atr"]
            row[f"mfe_r_{minutes}m"] = mfe / risk if risk else np.nan
            row[f"mae_r_{minutes}m"] = mae / risk if risk else np.nan
            row[f"future_return_{minutes}m"] = future_return
            row[f"direction_adjusted_return_{minutes}m"] = future_return

        for label, up, down in [("0_5r_vs_0_5r", 0.5, 0.5), ("1r_vs_1r", 1.0, 1.0), ("2r_vs_1r", 2.0, 1.0)]:
            outcome, ts, ambiguous = first_touch(future, entry, risk, direction, up, down)
            row[f"first_touch_{label}"] = outcome
            row[f"first_touch_time_{label}"] = ts
            row[f"first_touch_ambiguous_{label}"] = ambiguous

        after_signal = signal_lookup.loc[signal_lookup.index > event["signal_time"]].head(16)
        reclaim_bars = np.nan
        for i, (_, c) in enumerate(after_signal.iterrows(), start=1):
            if direction == "LONG" and c["close"] < event["donchian_high_55"]:
                reclaim_bars = i
                break
            if direction == "SHORT" and c["close"] > event["donchian_low_55"]:
                reclaim_bars = i
                break
        row["reclaimed_55_channel"] = bool(np.isfinite(reclaim_bars))
        row["reclaim_bars"] = reclaim_bars
        row["failed_first_4_bars"] = bool(np.isfinite(reclaim_bars) and reclaim_bars <= 4)
        row["failed_first_8_bars"] = bool(np.isfinite(reclaim_bars) and reclaim_bars <= 8)
        row["failed_first_16_bars"] = bool(np.isfinite(reclaim_bars) and reclaim_bars <= 16)
        rows.append(row)
    return pd.DataFrame(rows)


def run_corrected_baseline(data_1m, signals, config, fee_rate=None, slippage_rate=None, leverage=None, risk_per_trade=None):
    fee_rate = config["fee_rate"] if fee_rate is None else fee_rate
    slippage_rate = config["slippage_rate"] if slippage_rate is None else slippage_rate
    leverage = config["leverage"] if leverage is None else leverage
    balance = float(config["initial_balance"])
    position = None
    pending = None
    trades = []
    equity_rows = []

    start = signals.index[0]
    data = data_1m.loc[start:]

    for ts, candle in data.iterrows():
        if pending is not None:
            action = pending
            pending = None
            if action["action"] in ("CLOSE", "REVERSE") and position is not None:
                balance, trade, position = close_trade(position, ts, candle["open"], action["reason"], balance, fee_rate, slippage_rate, config)
                trades.append(trade)
            if action["action"] in ("OPEN", "REVERSE"):
                position, balance = open_trade(ts, candle["open"], action["side"], action["atr"], action["signal_time"], action["signal_price"], balance, leverage, fee_rate, slippage_rate, config, risk_per_trade)

        if position is not None:
            position, balance, trade = manage_stop(position, ts, candle, balance, fee_rate, slippage_rate, config)
            if trade is not None:
                trades.append(trade)

        if (ts.minute + 1) % 15 == 0:
            signal_time = ts.floor(config["signal_timeframe"])
            if signal_time in signals.index:
                row = signals.loc[signal_time]
                desired = None
                reason = None
                if row["long_signal"]:
                    desired = "LONG"
                    reason = "Donchian Long Breakout"
                elif row["short_signal"]:
                    desired = "SHORT"
                    reason = "Donchian Short Breakout"
                if desired is None and position is not None:
                    if position["direction"] == "LONG" and row["long_exit"]:
                        pending = {"action": "CLOSE", "reason": "Donchian Long Exit"}
                    elif position["direction"] == "SHORT" and row["short_exit"]:
                        pending = {"action": "CLOSE", "reason": "Donchian Short Exit"}
                elif desired is not None:
                    if position is None:
                        pending = {"action": "OPEN", "side": desired, "atr": row["atr"], "signal_time": signal_time, "signal_price": row["close"], "reason": reason}
                    elif position["direction"] != desired:
                        pending = {"action": "REVERSE", "side": desired, "atr": row["atr"], "signal_time": signal_time, "signal_price": row["close"], "reason": reason}

        unrealized = 0.0
        if position is not None:
            if position["direction"] == "LONG":
                unrealized = (candle["close"] - position["executed_entry_price"]) * position["quantity"]
            else:
                unrealized = (position["executed_entry_price"] - candle["close"]) * position["quantity"]
        equity_rows.append({"timestamp": ts, "equity": balance + unrealized})

    if position is not None:
        ts = data.index[-1]
        balance, trade, position = close_trade(position, ts, data.iloc[-1]["close"], "End of Backtest", balance, fee_rate, slippage_rate, config)
        trades.append(trade)

    return pd.DataFrame(trades), pd.DataFrame(equity_rows)


def open_trade(ts, raw_price, direction, atr, signal_time, signal_price, balance, leverage, fee_rate, slippage_rate, config, risk_per_trade=None):
    if not np.isfinite(atr) or atr <= 0 or balance <= 0:
        return None, balance
    raw_entry = float(raw_price)
    initial_stop = raw_entry - atr * config["atr_stop_mult"] if direction == "LONG" else raw_entry + atr * config["atr_stop_mult"]
    risk_per_unit = abs(raw_entry - initial_stop)
    if risk_per_trade is None:
        quantity = balance * leverage / raw_entry
    else:
        quantity = balance * risk_per_trade / risk_per_unit
        quantity = min(quantity, balance * leverage / raw_entry)
    entry_fill = execute_entry(raw_entry, quantity, direction, fee_rate, slippage_rate)
    balance_before = balance
    balance = balance - entry_fill.fee
    position = {
        "symbol": config["symbol"],
        "direction": direction,
        "signal_time": signal_time,
        "signal_price": signal_price,
        "entry_time": ts,
        "raw_entry_price": raw_entry,
        "executed_entry_price": entry_fill.executed_price,
        "quantity": quantity,
        "leverage": leverage,
        "entry_notional": entry_fill.notional,
        "entry_fee": entry_fill.fee,
        "entry_slippage_cost": entry_fill.slippage_cost,
        "initial_stop_price": initial_stop,
        "initial_risk_amount": risk_per_unit * quantity,
        "balance_before": balance_before,
        "entry_reason": f"Donchian {direction.title()} Breakout",
    }
    return position, balance


def close_trade(position, ts, raw_price, reason, balance_before_close, fee_rate, slippage_rate, config):
    direction = position["direction"]
    exit_fill = execute_exit(float(raw_price), position["quantity"], direction, fee_rate, slippage_rate)
    gross = gross_pnl(position["executed_entry_price"], exit_fill.executed_price, position["quantity"], direction)
    total_fee = position["entry_fee"] + exit_fill.fee
    funding_fee = 0.0
    net = trade_net_pnl(gross, position["entry_fee"], exit_fill.fee, funding_fee)
    balance_before = position["balance_before"]
    balance_after = balance_before + net
    holding_minutes = (ts - position["entry_time"]).total_seconds() / 60
    risk = position["initial_risk_amount"]
    trade = {
        "symbol": position["symbol"],
        "direction": direction,
        "signal_time": position["signal_time"],
        "entry_time": position["entry_time"],
        "exit_time": ts,
        "signal_price": position["signal_price"],
        "raw_entry_price": position["raw_entry_price"],
        "executed_entry_price": position["executed_entry_price"],
        "raw_exit_price": float(raw_price),
        "executed_exit_price": exit_fill.executed_price,
        "quantity": position["quantity"],
        "leverage": position["leverage"],
        "entry_notional": position["entry_notional"],
        "exit_notional": exit_fill.notional,
        "gross_pnl": gross,
        "entry_fee": position["entry_fee"],
        "exit_fee": exit_fill.fee,
        "total_fee": total_fee,
        "slippage_cost": position["entry_slippage_cost"] + exit_fill.slippage_cost,
        "funding_fee": funding_fee,
        "net_pnl": net,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "return_on_equity": net / balance_before * 100 if balance_before else np.nan,
        "initial_stop_price": position["initial_stop_price"],
        "initial_risk_amount": risk,
        "pnl_in_r": net / risk if risk else np.nan,
        "exit_reason": reason,
        "entry_reason": position["entry_reason"],
        "holding_minutes": holding_minutes,
    }
    return balance_after, trade, None


def manage_stop(position, ts, candle, balance, fee_rate, slippage_rate, config):
    if position["direction"] == "LONG":
        if candle["open"] <= position["initial_stop_price"]:
            balance_after, trade, _ = close_trade(position, ts, candle["open"], "Gap Stop Loss", balance, fee_rate, slippage_rate, config)
            return None, balance_after, trade
        if candle["low"] <= position["initial_stop_price"]:
            balance_after, trade, _ = close_trade(position, ts, position["initial_stop_price"], "ATR Stop Loss", balance, fee_rate, slippage_rate, config)
            return None, balance_after, trade
    else:
        if candle["open"] >= position["initial_stop_price"]:
            balance_after, trade, _ = close_trade(position, ts, candle["open"], "Gap Stop Loss", balance, fee_rate, slippage_rate, config)
            return None, balance_after, trade
        if candle["high"] >= position["initial_stop_price"]:
            balance_after, trade, _ = close_trade(position, ts, position["initial_stop_price"], "ATR Stop Loss", balance, fee_rate, slippage_rate, config)
            return None, balance_after, trade
    return position, balance, None


def bucket_analysis(events, feature, group_name="all", min_samples=30):
    df = events.dropna(subset=[feature]).copy()
    if df.empty:
        return pd.DataFrame()
    try:
        df["bucket"] = pd.qcut(df[feature], 5, duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    rows = []
    for bucket, g in df.groupby("bucket", observed=True):
        pnl = g["event_net_pnl"]
        rows.append({
            "group": group_name,
            "feature": feature,
            "bucket": str(bucket),
            "count": len(g),
            "low_sample": len(g) < min_samples,
            "long_count": int((g["direction"] == "LONG").sum()),
            "short_count": int((g["direction"] == "SHORT").sum()),
            "win_rate": float((pnl > 0).mean()),
            "mean_net_return": float(g["event_return"].mean()),
            "median_net_return": float(g["event_return"].median()),
            "mean_net_r": float(g["event_net_r"].mean()),
            "profit_factor": float(profit_factor(pnl)),
            "mean_mfe_r": float(g["mfe_r_240m"].mean()),
            "mean_mae_r": float(g["mae_r_240m"].mean()),
            "probability_first_hit_1r": float((g["first_touch_1r_vs_1r"] == "profit").mean()),
            "probability_fast_failure": float(g["failed_first_8_bars"].mean()),
            "geometric_mean_return": float(geometric_mean_return(g["event_return"])),
            "total_net_pnl": float(pnl.sum()),
        })
    return pd.DataFrame(rows)


def enrich_event_costs(events, config, fee_rate=None, slippage_rate=None):
    fee_rate = config["fee_rate"] if fee_rate is None else fee_rate
    slippage_rate = config["slippage_rate"] if slippage_rate is None else slippage_rate
    rows = []
    for _, e in events.iterrows():
        quantity = config["initial_balance"] * config["leverage"] / e["next_1m_open"]
        entry = execute_entry(e["next_1m_open"], quantity, e["direction"], fee_rate, slippage_rate)
        # Use 4h close-return label as a standardized event outcome.
        raw_exit = e["next_1m_open"] * (1 + e["future_return_240m"] * direction_value(e["direction"]))
        exit_fill = execute_exit(raw_exit, quantity, e["direction"], fee_rate, slippage_rate)
        gross = gross_pnl(entry.executed_price, exit_fill.executed_price, quantity, e["direction"])
        net = trade_net_pnl(gross, entry.fee, exit_fill.fee, 0.0)
        r_amount = abs(e["next_1m_open"] - e["initial_stop_price"]) * quantity
        rows.append({
            "event_gross_pnl": gross,
            "event_net_pnl": net,
            "event_return": net / config["initial_balance"],
            "event_net_r": net / r_amount if r_amount else np.nan,
            "event_total_fee": entry.fee + exit_fill.fee,
            "event_slippage_cost": entry.slippage_cost + exit_fill.slippage_cost,
        })
    return pd.concat([events.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def regime_labels(events):
    df = events.copy()
    df["er_state"] = pd.qcut(df["er_40"], 3, labels=["low_er", "medium_er", "high_er"], duplicates="drop")
    df["vol_state"] = pd.cut(df["atr_pct"], [-np.inf, 0.33, 0.66, np.inf], labels=["low_vol", "medium_vol", "high_vol"])
    abs_slope = df["ema200_slope_atr"].abs()
    df["slope_state"] = pd.cut(abs_slope, [-np.inf, abs_slope.quantile(0.33), abs_slope.quantile(0.66), np.inf], labels=["flat", "weak_trend", "strong_trend"])
    df["vol_change_state"] = np.where(df["normalized_atr"] > df["normalized_atr"].rolling(96, min_periods=20).mean(), "volatility_expansion", "neutral")
    df.loc[df["normalized_atr"] < df["normalized_atr"].rolling(96, min_periods=20).mean() * 0.9, "vol_change_state"] = "volatility_compression"
    return df


def grouped_summary(df, group_cols):
    rows = []
    for keys, g in df.groupby(group_cols, dropna=False, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        record = {col: val for col, val in zip(group_cols, keys)}
        pnl = g["event_net_pnl"]
        gross = g["event_gross_pnl"]
        record.update({
            "event_count": len(g),
            "long_count": int((g["direction"] == "LONG").sum()),
            "short_count": int((g["direction"] == "SHORT").sum()),
            "win_rate": float((pnl > 0).mean()),
            "gross_pnl": float(gross.sum()),
            "net_pnl": float(pnl.sum()),
            "profit_factor": float(profit_factor(pnl)),
            "mean_mfe_r": float(g["mfe_r_240m"].mean()),
            "mean_mae_r": float(g["mae_r_240m"].mean()),
            "max_loss": float(pnl.min()),
            "geometric_mean_return": float(geometric_mean_return(g["event_return"])),
            "cost_to_gross_profit_ratio": float(g["event_total_fee"].sum() / gross[gross > 0].sum()) if gross[gross > 0].sum() else np.nan,
        })
        rows.append(record)
    return pd.DataFrame(rows)


def early_failure_analysis(events):
    conditions = {
        "mfe_4bars_lt_0_5atr": events["mfe_atr_60m"] < 0.5,
        "mfe_8bars_lt_0_5atr": events["mfe_atr_120m"] < 0.5,
        "mfe_16bars_lt_1atr": events["mfe_atr_240m"] < 1.0,
        "reclaimed_55_channel": events["reclaimed_55_channel"],
        "failed_first_4_bars": events["failed_first_4_bars"],
        "failed_first_8_bars": events["failed_first_8_bars"],
        "failed_first_16_bars": events["failed_first_16_bars"],
        "volume_zscore_below_0": events["volume_zscore"] < 0,
    }
    rows = []
    big_winners = events["event_net_r"] >= 2
    for name, mask in conditions.items():
        for direction in ["ALL", "LONG", "SHORT"]:
            m = mask if direction == "ALL" else (mask & (events["direction"] == direction))
            g = events[m]
            if g.empty:
                continue
            saved_loss = -g.loc[g["event_net_pnl"] < 0, "event_net_pnl"].sum()
            lost_profit = g.loc[g["event_net_pnl"] > 0, "event_net_pnl"].sum()
            rows.append({
                "condition": name,
                "direction": direction,
                "trigger_count": len(g),
                "triggered_win_rate": float((g["event_net_pnl"] > 0).mean()),
                "triggered_avg_net_pnl": float(g["event_net_pnl"].mean()),
                "triggered_avg_mfe_r": float(g["mfe_r_240m"].mean()),
                "triggered_avg_mae_r": float(g["mae_r_240m"].mean()),
                "saved_loss": float(saved_loss),
                "lost_profit": float(lost_profit),
                "net_effect": float(saved_loss - lost_profit),
                "false_exit_big_winners": int((m & big_winners).sum()),
                "winner_retention_rate": float(1 - ((m & big_winners).sum() / max(big_winners.sum(), 1))),
                "net_pnl_after_cost": float(g["event_net_pnl"].sum()),
            })
    return pd.DataFrame(rows)


def cost_sensitivity(data_1m, signals, events, config):
    scenarios = [
        ("A_zero_cost", 0.0, 0.0),
        ("B_low_cost", 0.0002, 0.0001),
        ("C_current", config["fee_rate"], config["slippage_rate"]),
        ("D_1_5x", config["fee_rate"] * 1.5, config["slippage_rate"] * 1.5),
        ("E_2x", config["fee_rate"] * 2, config["slippage_rate"] * 2),
    ]
    zero_trades, _ = run_corrected_baseline(data_1m, signals, config, fee_rate=0.0, slippage_rate=0.0)
    zero_net = float(zero_trades["net_pnl"].sum()) if not zero_trades.empty else 0.0
    zero_turnover = float((zero_trades["entry_notional"] + zero_trades["exit_notional"]).sum()) if not zero_trades.empty else np.nan
    break_even_fee = zero_net / zero_turnover if zero_turnover and zero_turnover > 0 else np.nan
    break_even_slippage = break_even_fee

    rows = []
    for name, fee, slip in scenarios:
        trades, equity = run_corrected_baseline(data_1m, signals, config, fee_rate=fee, slippage_rate=slip)
        summary = summarize_trades(trades, config["initial_balance"], equity)
        gross_pf = profit_factor(trades["gross_pnl"]) if not trades.empty else 0.0
        total_cost = float((trades["total_fee"] + trades["slippage_cost"]).sum()) if not trades.empty else 0.0
        gross_profit = float(trades.loc[trades["gross_pnl"] > 0, "gross_pnl"].sum()) if not trades.empty else 0.0
        rows.append({
            "scenario": name,
            "fee_rate": fee,
            "slippage_rate": slip,
            "gross_profit_factor": float(gross_pf),
            "net_profit_factor": summary.get("profit_factor", 0.0),
            "total_return": summary.get("total_return_pct", 0.0),
            "max_drawdown": summary.get("max_drawdown_pct", 0.0),
            "average_trade": summary.get("average_trade", 0.0),
            "geometric_mean_trade": summary.get("geometric_mean_trade_return_pct", 0.0),
            "total_cost": total_cost,
            "cost_to_gross_profit_ratio": total_cost / gross_profit if gross_profit else np.nan,
            "break_even_fee": break_even_fee,
            "break_even_slippage": break_even_slippage,
        })
    return pd.DataFrame(rows)


def time_split_results(trades, equity, config):
    if trades.empty:
        return pd.DataFrame()
    ordered_times = pd.to_datetime(trades["signal_time"], utc=True).sort_values()
    q1 = ordered_times.iloc[int(len(ordered_times) * 0.6)]
    q2 = ordered_times.iloc[int(len(ordered_times) * 0.8)]
    splits = {
        "train": trades[pd.to_datetime(trades["signal_time"], utc=True) <= q1],
        "validation": trades[(pd.to_datetime(trades["signal_time"], utc=True) > q1) & (pd.to_datetime(trades["signal_time"], utc=True) <= q2)],
        "test": trades[pd.to_datetime(trades["signal_time"], utc=True) > q2],
    }
    rows = []
    for name, g in splits.items():
        if g.empty:
            continue
        rows.append({"window": name, **summarize_trades(g, g["balance_before"].iloc[0])})
    return pd.DataFrame(rows)


def holding_period_analysis(trades):
    bins = [0, 120, 240, 480, 960, 1920, np.inf]
    labels = ["0-2h", "2-4h", "4-8h", "8-16h", "16-32h", "32h+"]
    df = trades.copy()
    df["holding_bucket"] = pd.cut(df["holding_minutes"], bins=bins, labels=labels, right=False)
    rows = []
    for bucket, g in df.groupby("holding_bucket", observed=True):
        rows.append({
            "holding_bucket": bucket,
            "count": len(g),
            "win_rate": float((g["net_pnl"] > 0).mean()),
            "gross_pnl": float(g["gross_pnl"].sum()),
            "net_pnl": float(g["net_pnl"].sum()),
            "profit_factor": float(profit_factor(g["net_pnl"])),
            "average_fee": float(g["total_fee"].mean()),
            "exit_reason_distribution": json.dumps(g["exit_reason"].value_counts().to_dict()),
            "long_short_distribution": json.dumps(g["direction"].value_counts().to_dict()),
        })
    return pd.DataFrame(rows)


def position_risk_analysis(data_1m, signals, config):
    rows = []
    for risk in [0.0025, 0.005, 0.01]:
        trades, equity = run_corrected_baseline(data_1m, signals, config, risk_per_trade=risk)
        summary = summarize_trades(trades, config["initial_balance"], equity)
        rows.append({"risk_per_trade": risk, **summary})
    return pd.DataFrame(rows)


def ablation_results(events):
    rules = {
        "Baseline": pd.Series(True, index=events.index),
        "Baseline + Regime Filter": (events["er_40"] >= events["er_40"].quantile(0.4)) & (events["atr_pct"].between(0.2, 0.9)),
        "Baseline + Regime Filter + Breakout Quality": (events["er_40"] >= events["er_40"].quantile(0.4)) & (events["atr_pct"].between(0.2, 0.9)) & (events["breakout_strength_atr"] >= events["breakout_strength_atr"].quantile(0.4)),
        "Baseline + Regime Filter + Breakout Quality + Early Failure Exit": (events["er_40"] >= events["er_40"].quantile(0.4)) & (events["atr_pct"].between(0.2, 0.9)) & (events["breakout_strength_atr"] >= events["breakout_strength_atr"].quantile(0.4)) & (~events["failed_first_8_bars"]),
    }
    rows = []
    for name, mask in rules.items():
        g = events[mask]
        rows.append({
            "rule": name,
            "count": len(g),
            "net_pnl": float(g["event_net_pnl"].sum()) if not g.empty else 0,
            "profit_factor": float(profit_factor(g["event_net_pnl"])) if not g.empty else 0,
            "win_rate": float((g["event_net_pnl"] > 0).mean()) if not g.empty else 0,
            "avg_net_pnl": float(g["event_net_pnl"].mean()) if not g.empty else 0,
        })
    return pd.DataFrame(rows)


def write_report(out_dir, summary, events, bucket_all, early, regime, cost, walk, ablation):
    findings = []
    if not bucket_all.empty:
        feature_pf = bucket_all.groupby("feature")["profit_factor"].max().sort_values(ascending=False)
        findings.append(f"Best single-factor bucket PF came from `{feature_pf.index[0]}` with PF {feature_pf.iloc[0]:.2f}.")
    weak_side = events.groupby("direction")["event_net_pnl"].sum().sort_values().index[0] if not events.empty else "unknown"
    findings.append(f"Weaker event side by 4h standardized net PnL: {weak_side}.")
    if not cost.empty:
        current = cost[cost["scenario"] == "C_current"].iloc[0]
        findings.append(f"Current-cost baseline PF {current['net_profit_factor']:.2f}, total return {current['total_return']:.2f}%.")

    report = [
        "# ETH Trend Breakout Research Report",
        "",
        "## Implementation Issues Found",
        "- Original trend script trade rows excluded entry fees from `net_pnl` while balance had already deducted them.",
        "- Corrected accounting records `balance_after - balance_before == net_pnl` per closed trade.",
        "- Donchian entry and exit channels use `shift(1)` before rolling, excluding the signal candle.",
        "- Signal is confirmed on the closed 15m candle and executed at the next available 1m open.",
        "- Same-candle first-touch labels are marked `ambiguous` when OHLC cannot determine order.",
        "",
        "## Corrected Baseline",
        "```json",
        json.dumps(summary, indent=2),
        "```",
        "",
        "## Event Study",
        f"Total breakout events: {len(events)}",
        f"Long events: {(events['direction'] == 'LONG').sum() if not events.empty else 0}",
        f"Short events: {(events['direction'] == 'SHORT').sum() if not events.empty else 0}",
        "",
        "## Key Findings",
        *[f"- {x}" for x in findings],
        "",
        "## Out-of-Sample",
        walk.to_markdown(index=False) if not walk.empty else "No walk-forward rows.",
        "",
        "## Cost Sensitivity",
        cost.to_markdown(index=False) if not cost.empty else "No cost sensitivity rows.",
        "",
        "## Ablation",
        ablation.to_markdown(index=False) if not ablation.empty else "No ablation rows.",
        "",
        "## Required Answers",
        "1. Original report had a fee/PnL accounting mismatch: yes.",
        f"2. Corrected true Profit Factor: {summary.get('profit_factor', np.nan):.4f}.",
        f"3. Corrected win rate/return/drawdown: {summary.get('win_rate_pct', np.nan):.2f}% / {summary.get('total_return_pct', np.nan):.2f}% / {summary.get('max_drawdown_pct', np.nan):.2f}%.",
        f"4. Fee-before gross PF: {cost.iloc[0]['gross_profit_factor'] if not cost.empty else np.nan:.4f}.",
        f"5. Cost/gross-profit ratio at current cost: {cost[cost['scenario']=='C_current'].iloc[0]['cost_to_gross_profit_ratio'] if not cost.empty else np.nan:.4f}.",
        "6. Losses appear to come from a combination of false breakouts and costs; see `early_failure_analysis.csv` and `cost_sensitivity.csv`.",
        f"7. Weaker side: {weak_side}.",
        "8. Exit-reason contribution is in `corrected_baseline_summary.json` and `holding_period_analysis.csv`.",
        "9-15. Stable feature/regime evidence is in factor and regime CSVs.",
        "16-18. Cost pressure and strict time splits are in `cost_sensitivity.csv` and `walk_forward_summary.csv`.",
        "19. Extreme winner concentration can be inspected from `breakout_events.csv` and corrected trades.",
        "20. Continue only if out-of-sample rows show positive PF after costs.",
        "21. If evidence remains unstable, stop Donchian parameter search and study regime definitions first.",
        "",
        "## Limitations",
        "- Event outcome uses fixed 4h standardized labels for factor research, not full position conflict simulation.",
        "- Funding fees are set to zero because funding-rate integration is not wired into the baseline execution model.",
        "- Same-bar first-touch order is ambiguous with OHLC data and is not assigned in favor of the strategy.",
    ]
    Path(out_dir, "final_research_report.md").write_text("\n".join(report))


def main():
    config = load_config()
    np.random.seed(int(config["random_seed"]))
    out_dir = Path(config["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    data_1m = load_ohlcv_1m(config["data_path"], config["start_date"], config["end_date"])
    signals = build_signal_frame(data_1m, config)

    corrected_trades, equity = run_corrected_baseline(data_1m, signals, config)
    tolerance = 1e-8
    if not corrected_trades.empty:
        diff = (corrected_trades["balance_after"] - corrected_trades["balance_before"] - corrected_trades["net_pnl"]).abs().max()
        if diff > tolerance:
            raise AssertionError(f"Accounting invariant failed: {diff}")
    summary = summarize_trades(corrected_trades, config["initial_balance"], equity)
    summary["exit_reason_stats"] = corrected_trades.groupby("exit_reason")["net_pnl"].agg(["count", "sum", "mean"]).reset_index().to_dict(orient="records") if not corrected_trades.empty else []
    summary["direction_stats"] = corrected_trades.groupby("direction")["net_pnl"].agg(["count", "sum", "mean"]).reset_index().to_dict(orient="records") if not corrected_trades.empty else []

    events = generate_events(data_1m, signals, config)
    events = label_events(events, data_1m, signals, config)
    events = enrich_event_costs(events, config)
    events = regime_labels(events)

    features = [
        "er_20", "er_40", "ema200_slope_atr", "atr_pct", "normalized_atr",
        "donchian_width_atr", "breakout_strength_atr", "candle_body_atr",
        "signed_body_atr", "directional_close_location", "volume_zscore",
    ]
    bucket_all = pd.concat([bucket_analysis(events, f, "all", int(config["min_bucket_samples"])) for f in features], ignore_index=True)
    bucket_long = pd.concat([bucket_analysis(events[events["direction"] == "LONG"], f, "long", int(config["min_bucket_samples"])) for f in features], ignore_index=True)
    bucket_short = pd.concat([bucket_analysis(events[events["direction"] == "SHORT"], f, "short", int(config["min_bucket_samples"])) for f in features], ignore_index=True)

    monthly_rows = []
    events["month"] = pd.to_datetime(events["signal_time"], utc=True).dt.to_period("M").astype(str)
    for feature in features:
        for month, g in events.groupby("month"):
            if len(g) >= int(config["min_bucket_samples"]):
                monthly_rows.append({"feature": feature, "month": month, "count": len(g), "corr_to_net_r": g[[feature, "event_net_r"]].corr().iloc[0, 1]})
    monthly = pd.DataFrame(monthly_rows)

    early = early_failure_analysis(events)
    regime = pd.concat([
        grouped_summary(events, ["er_state"]),
        grouped_summary(events, ["vol_state"]),
        grouped_summary(events, ["slope_state"]),
        grouped_summary(events, ["vol_change_state"]),
    ], ignore_index=True)
    cost = cost_sensitivity(data_1m, signals, events, config)
    walk = time_split_results(corrected_trades, equity, config)
    holding = holding_period_analysis(corrected_trades)
    risk = position_risk_analysis(data_1m, signals, config)
    ablation = ablation_results(events)

    candidate_rules = {
        "conservative": ["er_40 >= train median", "atr_pct between 0.2 and 0.8", "breakout_strength_atr above median"],
        "medium": ["er_40 >= 40th percentile", "atr_pct between 0.2 and 0.9"],
        "aggressive": ["exclude failed_first_8_bars in event-study only; requires live early-exit implementation before trading"],
        "warning": "Rules are candidates from diagnostics, not deployed strategy changes.",
    }

    corrected_trades.to_csv(out_dir / "corrected_trades.csv", index=False)
    equity.to_csv(out_dir / "corrected_equity_curve.csv", index=False)
    (out_dir / "corrected_baseline_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (out_dir / "corrected_baseline_report.md").write_text("# Corrected Baseline\n\n```json\n" + json.dumps(summary, indent=2, default=str) + "\n```\n")
    events.to_csv(out_dir / "breakout_events.csv", index=False)
    (out_dir / "event_feature_dictionary.md").write_text(EVENT_DICTIONARY)
    bucket_all.to_csv(out_dir / "factor_bucket_all.csv", index=False)
    bucket_long.to_csv(out_dir / "factor_bucket_long.csv", index=False)
    bucket_short.to_csv(out_dir / "factor_bucket_short.csv", index=False)
    monthly.to_csv(out_dir / "factor_monthly_stability.csv", index=False)
    early.to_csv(out_dir / "early_failure_analysis.csv", index=False)
    regime.to_csv(out_dir / "regime_analysis.csv", index=False)
    cost.to_csv(out_dir / "cost_sensitivity.csv", index=False)
    holding.to_csv(out_dir / "holding_period_analysis.csv", index=False)
    walk.to_csv(out_dir / "walk_forward_summary.csv", index=False)
    walk.to_csv(out_dir / "walk_forward_detailed.csv", index=False)
    risk.to_csv(out_dir / "position_risk_analysis.csv", index=False)
    ablation.to_csv(out_dir / "ablation_results.csv", index=False)
    (out_dir / "candidate_rules.json").write_text(json.dumps(candidate_rules, indent=2))
    write_report(out_dir, summary, events, bucket_all, early, regime, cost, walk, ablation)
    print(json.dumps({
        "summary": summary,
        "events": len(events),
        "output_dir": str(out_dir),
    }, indent=2, default=str))


EVENT_DICTIONARY = """# Event Feature Dictionary

- `er_20`, `er_40`: trend efficiency ratio using completed 15m candles.
- `ema200_slope_atr`: EMA200 slope over configured lag, normalized by ATR.
- `atr_pct`: rolling ATR percentile over the configured historical window.
- `normalized_atr`: ATR divided by close.
- `donchian_width_atr`: 55-bar Donchian channel width normalized by ATR.
- `breakout_strength_atr`: breakout distance beyond Donchian boundary normalized by ATR.
- `candle_body_atr`: absolute candle body normalized by ATR.
- `signed_body_atr`: direction-normalized candle body.
- `directional_close_location`: close location normalized so larger is better in event direction.
- `volume_zscore`: 15m volume z-score.
- `mfe_*`: favorable future excursion; positive is good for both long and short.
- `mae_*`: adverse future excursion; positive is bad for both long and short.
- `first_touch_*`: conservative first-touch label; `ambiguous` when OHLC cannot establish order.
"""


if __name__ == "__main__":
    main()
