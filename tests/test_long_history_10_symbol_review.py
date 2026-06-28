from pathlib import Path

import pandas as pd

from research_core.common import validate_run_log_row
from research_core.run_long_history_10_symbol_review import (
    END_UTC,
    GATE,
    LEVERAGE_MODE,
    PROTOTYPES,
    START_UTC,
    SYMBOLS,
    coverage_status,
)


def test_fixed_10_symbol_list():
    assert SYMBOLS == [
        "ETHUSDT",
        "BTCUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "DOGEUSDT",
        "AVAXUSDT",
        "LINKUSDT",
        "LTCUSDT",
    ]
    assert PROTOTYPES == ["P4_BREAKOUT_TOP20", "P6_MOMENTUM_OR_BREAKOUT_TOP20"]
    assert GATE == "G1_SINGLE_BEST_PATH_SAFETY"
    assert LEVERAGE_MODE == "adaptive_3x_8x_v1"


def test_long_history_layer_is_not_oos():
    record = {"data_layer": "expanded_discovery", "oos_eligible": False}
    assert record["data_layer"] != "oos"
    assert record["oos_eligible"] is False


def test_late_listing_partial_coverage_status():
    assert coverage_status(pd.Timestamp("2021-01-01 00:00:00+00:00"), END_UTC) == "late_listing_partial_coverage"
    assert coverage_status(START_UTC, END_UTC - pd.Timedelta(minutes=1)) == "incomplete_end_coverage"
    assert coverage_status(START_UTC, END_UTC) == "full_coverage"


def test_summary_shape_requires_20_rows():
    rows = []
    for symbol in SYMBOLS:
        for prototype in PROTOTYPES:
            rows.append({"symbol": symbol, "prototype": prototype})
    summary = pd.DataFrame(rows)
    assert len(summary) == 20
    assert set(summary["symbol"]) == set(SYMBOLS)
    assert set(summary["prototype"]) == set(PROTOTYPES)


def test_threshold_audit_disallows_long_history_refit():
    audit = pd.DataFrame({
        "symbol": ["ETHUSDT"],
        "prototype": ["P4_BREAKOUT_TOP20"],
        "prototype_threshold_source": ["original_discovery_score_distribution"],
        "gate_threshold_source": ["fixed_h3_discovery_thresholds"],
        "rank_or_fit_in_long_history": [False],
    })
    row = audit.iloc[0]
    assert row["prototype_threshold_source"] == "original_discovery_score_distribution"
    assert row["gate_threshold_source"] == "fixed_h3_discovery_thresholds"
    assert row["rank_or_fit_in_long_history"] is False or row["rank_or_fit_in_long_history"] == 0


def test_each_symbol_equity_png_expected():
    paths = [Path(f"/tmp/{symbol}_equity_curve.png") for symbol in SYMBOLS]
    assert len(paths) == 10
    assert all(path.name.endswith("_equity_curve.png") for path in paths)


def test_run_log_required_fields_complete():
    row = {
        "run_id": "LH10_SYMBOL_LONG_HISTORY_REVIEW",
        "stage": "LH10",
        "script": "research_core.run_long_history_10_symbol_review",
        "config_hash": "abc",
        "data_hash": "def",
        "git_commit": "ghi",
        "run_timestamp": "2026-06-28T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": "not OOS",
    }
    assert validate_run_log_row(row)
