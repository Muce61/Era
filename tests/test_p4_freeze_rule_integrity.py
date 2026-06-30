import pandas as pd

from research_core.event_table import add_base_indicators, strict_resample_15m
from research_core.p4_canonical_freeze.p4_freeze_rule_audit import candidate_registry, canonical_config


def test_donchian_uses_shift_one():
    idx = pd.date_range("2024-01-01", periods=60 * 15, freq="1min", tz="UTC")
    data = pd.DataFrame({
        "open": 100.0,
        "high": 100.0,
        "low": 90.0,
        "close": 95.0,
        "volume": 1.0,
    }, index=idx)
    bars = strict_resample_15m(data)
    bars.iloc[-1, bars.columns.get_loc("high")] = 999.0
    out = add_base_indicators(bars)
    assert out["donchian55_upper"].iloc[-1] < 999.0


def test_canonical_config_is_p4_fixed_1x_only():
    cfg = canonical_config("abc")
    assert cfg["prototype"] == "P4_BREAKOUT_TOP20"
    assert cfg["leverage_mode"] == "fixed_1x"
    assert cfg["donchian_entry_window"] == 55
    assert cfg["donchian_exit_window"] == 20
    assert cfg["data_layer"] == "expanded_discovery"
    assert cfg["oos_status"] == "not_oos"


def test_candidate_registry_has_only_authorized_final_candidates():
    reg = candidate_registry()
    final = reg[reg["candidate_role"] == "final_candidate"]
    assert set(final["candidate_id"]) == {"C1", "C2", "C3"}
    assert set(final["leverage_mode"]) == {"fixed_1x"}
    assert set(final["prototype"]) == {"P4_BREAKOUT_TOP20"}

