import pandas as pd

from research_core.event_table import first_touch_outcome, forward_labels


def test_first_touch_marks_same_bar_both_sides_ambiguous():
    window = pd.DataFrame(
        [{"open": 100, "high": 111, "low": 89, "close": 100}],
        index=[pd.Timestamp("2025-01-01 00:15", tz="UTC")],
    )
    assert first_touch_outcome(window, entry=100, atr=10) == "ambiguous"


def test_forward_labels_keep_ambiguous_separate():
    df = pd.DataFrame(
        [
            {"open": 100, "high": 100, "low": 100, "close": 100},
            {"open": 100, "high": 111, "low": 89, "close": 101},
        ],
        index=pd.date_range("2025-01-01", periods=2, freq="15min", tz="UTC"),
    )
    labels = forward_labels(df, df.index[0], entry_price=100, atr=10, horizons=[1])
    assert labels["ambiguous_touch_1"] is True
    assert labels["plus_1atr_first_1"] is False
    assert labels["minus_1atr_first_1"] is False

