import pandas as pd


def resolve_direction_conflicts(signals: pd.DataFrame) -> list[str]:
    held_until = {}
    accepted = []
    for _, row in signals.sort_values("time").iterrows():
        symbol = row["symbol"]
        if row["time"] < held_until.get(symbol, pd.Timestamp.min.tz_localize("UTC")):
            continue
        accepted.append(row["id"])
        held_until[symbol] = row["exit_time"]
    return accepted


def test_same_symbol_long_short_conflict_is_deterministic():
    signals = pd.DataFrame({
        "id": ["long1", "short1", "short2"],
        "symbol": ["ETHUSDT", "ETHUSDT", "ETHUSDT"],
        "side": ["long", "short", "short"],
        "time": pd.to_datetime(["2024-01-01 00:00", "2024-01-01 00:05", "2024-01-01 01:00"], utc=True),
        "exit_time": pd.to_datetime(["2024-01-01 00:30", "2024-01-01 00:40", "2024-01-01 02:00"], utc=True),
    })
    assert resolve_direction_conflicts(signals) == ["long1", "short2"]

