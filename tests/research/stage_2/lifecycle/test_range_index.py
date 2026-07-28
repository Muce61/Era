from __future__ import annotations

from decimal import Decimal

from era100x.research.stage_2.lifecycle.range_index import DecimalTimeRangeIndex


def _index() -> DecimalTimeRangeIndex:
    return DecimalTimeRangeIndex.build(
        timestamps_ns=(10, 20, 30, 40, 50),
        values=tuple(Decimal(value) for value in ("100", "102", "99", "103", "98")),
    )


def test_range_index_returns_first_crossing_and_extrema() -> None:
    index = _index()
    assert index.first_ge(10, 51, Decimal("102.5")) == (40, Decimal("103"), 3)
    assert index.first_le(10, 51, Decimal("99")) == (30, Decimal("99"), 2)
    assert index.range_max(20, 50) == (40, Decimal("103"))
    assert index.last_at_or_before(35) == (30, Decimal("99"))


def test_range_index_respects_half_open_window_and_no_match() -> None:
    index = _index()
    assert index.first_ge(10, 40, Decimal("103")) is None
    assert index.first_le(31, 50, Decimal("99")) is None
    assert index.range_max(51, 60) is None
