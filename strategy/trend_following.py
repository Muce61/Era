from pathlib import Path

import pandas as pd


def load_ohlcv_1m(path, start_date, end_date):
    df = pd.read_csv(Path(path), parse_dates=["timestamp"])
    df = df.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df.columns = [c.lower() for c in df.columns]
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    start = pd.Timestamp(start_date, tz="UTC")
    end = pd.Timestamp(end_date, tz="UTC")
    return df.loc[start:end, required].copy()


def build_signal_frame(data_1m, config):
    df = data_1m.resample(config["signal_timeframe"]).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    df["ema50"] = df["close"].ewm(span=int(config["ema_fast"]), adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=int(config["ema_slow"]), adjust=False).mean()

    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(int(config["atr_period"])).mean()

    entry = int(config["donchian_entry"])
    exit_window = int(config["donchian_exit"])
    df["donchian_high_55"] = df["high"].shift(1).rolling(entry).max()
    df["donchian_low_55"] = df["low"].shift(1).rolling(entry).min()
    df["donchian_high_20"] = df["high"].shift(1).rolling(exit_window).max()
    df["donchian_low_20"] = df["low"].shift(1).rolling(exit_window).min()

    df["long_signal"] = (df["close"] > df["donchian_high_55"]) & (df["ema50"] > df["ema200"])
    df["short_signal"] = (df["close"] < df["donchian_low_55"]) & (df["ema50"] < df["ema200"])
    df["long_exit"] = df["close"] < df["donchian_low_20"]
    df["short_exit"] = df["close"] > df["donchian_high_20"]
    return df.dropna()
