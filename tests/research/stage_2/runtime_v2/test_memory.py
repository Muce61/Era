from __future__ import annotations

import time

import pytest

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


def test_memory_budget_rejects_phase_current_delta() -> None:
    current = iter((1_000_000_000, 1_600_000_001))
    budget = ProcessMemoryBudget(
        current_limit_bytes=3_000_000_000,
        delta_limit_bytes=500_000_000,
        current_reader=lambda: next(current),
        peak_reader=lambda: 2_500_000_001,
    )

    with pytest.raises(MemoryError, match="current RSS delta"):
        budget.check("fixture")


def test_continuous_phase_monitor_catches_transient_current_rss() -> None:
    current = [100]
    budget = ProcessMemoryBudget(
        current_limit_bytes=1_000,
        delta_limit_bytes=500,
        current_reader=lambda: current[0],
        peak_reader=lambda: 900,
    )

    with pytest.raises(MemoryError, match="current RSS delta"):
        with budget.monitor_phase("packing", interval_seconds=0.001):
            current[0] = 700
            time.sleep(0.02)
