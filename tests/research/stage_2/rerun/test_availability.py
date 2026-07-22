from __future__ import annotations

from datetime import date

from era100x.research.stage_2.rerun.availability import (
    BOUNDARY_WARMUP_END_NS,
    DATASET_START_NS,
    END_DATE_EXCLUSIVE,
    START_DATE,
    _classify_unavailable,
    _dates,
)


def test_whole_range_dates_are_contiguous_and_exclude_end() -> None:
    dates = _dates()
    assert dates[0] == START_DATE
    assert dates[-1] == date(2026, 7, 3)
    assert len(dates) == (END_DATE_EXCLUSIVE - START_DATE).days


def test_known_dataset_start_warmup_is_typed_not_silently_dropped() -> None:
    assert (
        _classify_unavailable(
            START_DATE,
            BOUNDARY_WARMUP_END_NS - 1,
            "PRICE_FEATURE_UNAVAILABLE",
        )
        == "BOUNDARY_WARMUP_UNAVAILABLE"
    )
    assert DATASET_START_NS < BOUNDARY_WARMUP_END_NS


def test_unknown_or_late_unavailability_blocks_instead_of_becoming_zero() -> None:
    assert (
        _classify_unavailable(
            START_DATE,
            BOUNDARY_WARMUP_END_NS,
            "PRICE_FEATURE_UNAVAILABLE",
        )
        == "UNCLASSIFIED_UNAVAILABLE"
    )
    assert (
        _classify_unavailable(
            date(2024, 1, 2),
            BOUNDARY_WARMUP_END_NS - 1,
            "ACTIVITY_FEATURE_UNAVAILABLE",
        )
        == "UNCLASSIFIED_UNAVAILABLE"
    )
