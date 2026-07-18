from __future__ import annotations

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


def test_memory_budget_rejects_peak_delta_independently_of_current_rss() -> None:
    peak = iter((2_000_000_000, 2_500_000_001))
    budget = ProcessMemoryBudget(
        current_limit_bytes=3_000_000_000,
        delta_limit_bytes=500_000_000,
        current_reader=lambda: 2_100_000_000,
        peak_reader=lambda: next(peak),
    )

    with pytest.raises(MemoryError, match="peak RSS delta"):
        budget.check("fixture")
