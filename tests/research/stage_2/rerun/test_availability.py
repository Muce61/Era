from datetime import date
from datetime import timedelta

import pytest

from era100x.research.stage_2.rerun.availability import (
    BOUNDARY_WARMUP_END_NS,
    DATASET_START_NS,
    SOURCE_END_EXCLUSIVE,
    SOURCE_START_DATE,
    audit_dates,
    classify_unavailable,
)


def test_audit_dates_are_complete_and_end_exclusive() -> None:
    days = audit_dates(SOURCE_START_DATE, SOURCE_START_DATE.replace(day=8))
    assert len(days) == 7
    assert days[0] == date(2020, 1, 1)
    assert days[-1] == date(2020, 1, 7)


def test_audit_range_cannot_exceed_frozen_source() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        audit_dates(SOURCE_START_DATE, SOURCE_END_EXCLUSIVE + timedelta(days=1))


def test_missingness_categories_are_mutually_resolved() -> None:
    assert (
        classify_unavailable(
            owner_date=SOURCE_START_DATE,
            anchor_ns=BOUNDARY_WARMUP_END_NS - 1,
            raw_reason="PRICE_FEATURE_UNAVAILABLE",
        )
        == "BOUNDARY_WARMUP_UNAVAILABLE"
    )
    assert (
        classify_unavailable(
            owner_date=date(2024, 1, 1),
            anchor_ns=BOUNDARY_WARMUP_END_NS,
            raw_reason="DECLARED_SOURCE_GAP",
        )
        == "DECLARED_SOURCE_GAP"
    )
    assert (
        classify_unavailable(
            owner_date=date(2024, 1, 1),
            anchor_ns=BOUNDARY_WARMUP_END_NS,
            raw_reason="DUPLICATE_BAR_INVALID",
        )
        == "FEATURE_VALUE_INVALID"
    )
    assert (
        classify_unavailable(
            owner_date=date(2024, 1, 1),
            anchor_ns=BOUNDARY_WARMUP_END_NS,
            raw_reason="PRICE_FEATURE_UNAVAILABLE",
        )
        == "UNCLASSIFIED_UNAVAILABLE"
    )


def test_daily_offset_last_warmup_anchor_is_not_misclassified_unknown() -> None:
    last_unavailable_anchor = DATASET_START_NS + 3_609 * 1_000_000_000
    assert (
        classify_unavailable(
            owner_date=SOURCE_START_DATE,
            anchor_ns=last_unavailable_anchor,
            raw_reason="PRICE_FEATURE_UNAVAILABLE",
        )
        == "BOUNDARY_WARMUP_UNAVAILABLE"
    )
