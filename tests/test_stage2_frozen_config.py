import copy

import pandas as pd
import pytest

from backtest.stage2_config import (
    assert_no_overrides,
    config_hash,
    load_frozen_config,
    strategy_config_from_frozen,
)
from strategy.eth_trend_signals import build_signal_frame, load_ohlcv_1m


def test_config_hash_is_stable_for_key_order():
    cfg = {"b": 2, "a": 1}
    assert config_hash(cfg) == config_hash({"a": 1, "b": 2})


def test_frozen_config_can_build_strategy_config():
    frozen = load_frozen_config("B3")
    config = strategy_config_from_frozen(frozen)
    assert config.entry_mode.value == "bullish_hikkake"
    assert config.ema_fast == frozen["ema_fast"]
    assert config.donchian_entry == 55


def test_illegal_parameter_override_is_blocked():
    frozen = load_frozen_config("B3")
    config = strategy_config_from_frozen(frozen)
    config.ema_fast = 49
    with pytest.raises(ValueError, match="differs from frozen config"):
        assert_no_overrides(frozen, config)


def test_same_frozen_config_produces_same_signals_on_sample():
    frozen = load_frozen_config("B1")
    data = load_ohlcv_1m(
        frozen["data_path"],
        "2025-01-01 00:00:00",
        "2025-02-01 00:00:00",
    )
    cfg1 = strategy_config_from_frozen(frozen)
    cfg2 = strategy_config_from_frozen(copy.deepcopy(frozen))

    signals1 = build_signal_frame(data, cfg1)
    signals2 = build_signal_frame(data, cfg2)

    pd.testing.assert_series_equal(signals1["long_signal"], signals2["long_signal"])
