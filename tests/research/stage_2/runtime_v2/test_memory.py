from __future__ import annotations

import time

from era100x.research.stage_2.runtime_v2.memory import ProcessMemoryBudget


def test_memory_budget_records_baseline_current_peak_and_arrow_bytes() -> None:
    current = iter((1_700_000_000, 1_800_000_000))
    peak = iter((1_900_000_000, 2_100_000_000))
    budget = ProcessMemoryBudget(
        current_limit_bytes=3_000_000_000,
        delta_limit_bytes=500_000_000,
        current_reader=lambda: next(current),
        peak_reader=lambda: next(peak),
    )

    sample = budget.check("fixture", arrow_inflight_bytes=123_456)

    assert sample.baseline_current_rss_bytes == 1_700_000_000
    assert sample.baseline_peak_rss_bytes == 1_900_000_000
    assert sample.current_rss_bytes == 1_800_000_000
    assert sample.peak_rss_bytes == 2_100_000_000
    assert sample.current_rss_delta_bytes == 100_000_000
    assert sample.peak_rss_delta_bytes == 200_000_000
    assert sample.arrow_inflight_bytes == 123_456


def test_memory_budget_retains_lifetime_peak_as_audit_without_false_failure() -> None:
    peak = iter((2_000_000_000, 2_500_000_001))
    budget = ProcessMemoryBudget(
        current_limit_bytes=3_000_000_000,
        delta_limit_bytes=500_000_000,
        current_reader=lambda: 2_100_000_000,
        peak_reader=lambda: next(peak),
    )

    sample = budget.check("fixture")

    assert sample.peak_rss_delta_bytes == 500_000_001
    assert sample.current_rss_delta_bytes == 0


def test_memory_budget_records_phase_current_delta_as_anomaly() -> None:
    current = iter((1_000_000_000, 1_600_000_001))
    budget = ProcessMemoryBudget(
        current_limit_bytes=3_000_000_000,
        delta_limit_bytes=500_000_000,
        current_reader=lambda: next(current),
        peak_reader=lambda: 2_500_000_001,
    )

    sample = budget.check("fixture")

    assert sample.current_rss_delta_bytes == 600_000_001
    assert [item.metric_name for item in budget.anomalies] == ["CURRENT_RSS_DELTA_BYTES"]
    assert budget.anomalies[0].action == "CONTINUED"


def test_continuous_phase_monitor_records_transient_current_rss() -> None:
    current = [100]
    budget = ProcessMemoryBudget(
        current_limit_bytes=1_000,
        delta_limit_bytes=500,
        current_reader=lambda: current[0],
        peak_reader=lambda: 900,
    )

    with budget.monitor_phase("packing", interval_seconds=0.001):
        current[0] = 700
        time.sleep(0.02)

    assert any(item.metric_name == "CURRENT_RSS_DELTA_BYTES" for item in budget.anomalies)


def test_real_failure_observation_is_anomaly_not_terminal_failure() -> None:
    current = iter((245_186_560, 1_639_940_096))
    budget = ProcessMemoryBudget(
        current_limit_bytes=3_221_225_472,
        delta_limit_bytes=1_073_741_824,
        current_reader=lambda: next(current),
        peak_reader=lambda: 1_697_202_176,
    )

    sample = budget.check("Feature Foundation packing")

    assert sample.current_rss_delta_bytes == 1_394_753_536
    assert budget.anomalies[0].metric_name == "CURRENT_RSS_DELTA_BYTES"
    assert budget.anomalies[0].semantic_impact == "NONE"
