from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from research_core.dual_alpha_regime.config import RegimeResearchConfig
from research_core.dual_alpha_regime.market_regime_event_table import (
    add_forward_labels,
    build_completed_15m,
    build_market_regime_events,
    write_outputs,
)
from research_core.dual_alpha_regime.phase_gates import PhaseGateError
from research_core.dual_alpha_regime.regime_classifiers import add_scores, classify_regimes, fit_thresholds
from research_core.dual_alpha_regime.regime_factor_registry import assert_no_label_features, build_factor_registry
from research_core.dual_alpha_regime.regime_factor_research import run_factor_research
from research_core.dual_alpha_regime.mean_reversion_backtest import run_minimal_mean_reversion_backtest


def synthetic_1m(start="2024-01-01", periods=6000, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    drift = np.sin(np.arange(periods) / 200) * 0.0002
    returns = drift + rng.normal(0, 0.0008, periods)
    close = 100 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.maximum(close * 0.0005, np.abs(close - open_) * 0.5)
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = 1000 + rng.normal(0, 20, periods)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def write_symbol_csv(path: Path, df: pd.DataFrame) -> None:
    out = df.reset_index().rename(columns={"index": "timestamp"})
    out.to_csv(path, index=False)


def test_completed_15m_available_after_bar_end_and_execs_next_open():
    df = synthetic_1m(periods=45)
    bars = build_completed_15m(df, "ETHUSDT")
    first = bars.iloc[0]
    assert first["bar_open_time"] == pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    assert first["bar_close_time"] == pd.Timestamp("2024-01-01 00:14:00", tz="UTC")
    assert first["available_time"] == pd.Timestamp("2024-01-01 00:15:00", tz="UTC")
    assert first["next_exec_time"] == pd.Timestamp("2024-01-01 00:15:00", tz="UTC")
    assert len(bars) == 3


def test_forward_labels_are_future_only_and_registry_blocks_label_as_feature():
    df = synthetic_1m(periods=300)
    bars = build_completed_15m(df, "ETHUSDT")
    bars["atr_14"] = 1.0
    labelled = add_forward_labels(bars.head(3), df, [15])
    assert "label_fwd_ret_15m" in labelled.columns
    registry = build_factor_registry()
    with pytest.raises(ValueError):
        assert_no_label_features(["ema_gap_atr", "label_fwd_ret_15m"], registry)


def test_r1_to_r3_small_window_outputs(tmp_path):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "out"
    data_dir.mkdir()
    write_symbol_csv(data_dir / "ETHUSDT.csv", synthetic_1m(periods=7000, seed=1))
    write_symbol_csv(data_dir / "BTCUSDT.csv", synthetic_1m(periods=7000, seed=2))
    config = RegimeResearchConfig(data_dir=data_dir, output_dir=out_dir, symbols=["ETHUSDT", "BTCUSDT"])
    events, audit, missing = build_market_regime_events(config)
    write_outputs(events, audit, missing, config)
    run_factor_research(out_dir)
    classified = classify_regimes(out_dir, config)

    expected_complete_15m = 7000 // 15
    assert len(events) == expected_complete_15m * 2
    assert (out_dir / "market_regime_events.parquet").exists()
    assert (out_dir / "regime_factor_stability.csv").exists()
    assert (out_dir / "regime_transition_matrix.csv").exists()
    assert (out_dir / "regime_report.md").exists()
    assert set(classified["prototype"].unique()) == {"Regime-0", "Regime-1", "Regime-2", "Regime-3"}


def test_thresholds_fit_from_discovery_only():
    df = synthetic_1m(periods=7000)
    bars = build_completed_15m(df, "ETHUSDT")
    from research_core.dual_alpha_regime.market_regime_event_table import add_realtime_features

    events = add_realtime_features(bars)
    scored = add_scores(events)
    discovery_end = scored["bar_open_time"].iloc[len(scored) // 2]
    thresholds = fit_thresholds(scored, discovery_end)
    train = scored[scored["bar_open_time"] <= discovery_end]
    assert thresholds.trend_score_q60 == pytest.approx(float(train["trend_score"].quantile(0.60)), nan_ok=True)
    assert thresholds.range_score_q60 == pytest.approx(float(train["range_score"].quantile(0.60)), nan_ok=True)


def test_r6_backtest_gate_blocks_without_r4_r5_outputs(tmp_path):
    with pytest.raises(PhaseGateError):
        run_minimal_mean_reversion_backtest(tmp_path)
