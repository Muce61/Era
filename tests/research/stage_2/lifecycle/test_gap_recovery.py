from __future__ import annotations

from decimal import Decimal

import pytest

from era100x.research.stage_2.lifecycle import (
    BoundaryClassification,
    ContractPriceOhlcPoint,
    classify_gap_bar,
    classify_gap_path,
)
from era100x.research.stage_2.paths.extraction.models import PathGap

NS = 1_000_000_000


def _gap(*, first: int = 10 * NS, last: int = 10 * NS) -> PathGap:
    return PathGap(
        evidence_level="H2",
        reason_code="H2_VENUE_TRADE_ID_GAP",
        preceding_ts_event_ns=first,
        following_ts_event_ns=last,
        missing_count=1,
        preceding_venue_trade_id=1,
        following_venue_trade_id=3,
    )


def _bar(
    second: int,
    *,
    high: str = "100.5",
    low: str = "99.5",
    close: str = "100",
) -> ContractPriceOhlcPoint:
    return ContractPriceOhlcPoint(
        event_ts_ns=second * NS,
        available_at_ns=(second + 1) * NS,
        open=Decimal("100"),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
        partition_hash="a" * 64,
    )


@pytest.mark.parametrize(
    ("high", "low", "expected"),
    [
        ("100.5", "99.5", BoundaryClassification.GAP_NON_DECISIVE),
        ("101.5", "99.5", BoundaryClassification.COARSE_TARGET_BOUNDARY_CROSSING),
        ("100.5", "98.5", BoundaryClassification.COARSE_STOP_BOUNDARY_CROSSING),
        ("101.5", "98.5", BoundaryClassification.AMBIGUOUS),
    ],
)
def test_same_second_gap_classification_is_coarse_and_never_synthetic(
    high: str, low: str, expected: BoundaryClassification
) -> None:
    decision = classify_gap_bar(
        gap=_gap(),
        bar=_bar(10, high=high, low=low),
        target_price=Decimal("101"),
        stop_price=Decimal("99"),
    )

    assert decision.boundary_classification is expected
    assert decision.decision_available_at_ns == 11 * NS
    assert decision.intrasecond_order_known is False
    assert decision.synthetic_execution is False
    if expected is BoundaryClassification.GAP_NON_DECISIVE:
        assert decision.observation is None
    else:
        assert decision.observation is not None
        assert decision.observation.synthetic_execution is False
        assert decision.observation.available_at_ns == 11 * NS


def test_multi_second_gap_requires_every_contract_price_second() -> None:
    gap = _gap(first=10 * NS, last=12 * NS)
    with pytest.raises(ValueError, match="CONTRACT_PRICE_GAP_SECOND_UNAVAILABLE"):
        classify_gap_path(
            gap=gap,
            bars=(_bar(10), _bar(12)),
            target_price=Decimal("101"),
            stop_price=Decimal("99"),
        )


def test_gap_path_stops_at_first_coarse_boundary() -> None:
    decisions = classify_gap_path(
        gap=_gap(first=10 * NS, last=12 * NS),
        bars=(_bar(10), _bar(11, high="101.5"), _bar(12, low="98.5")),
        target_price=Decimal("101"),
        stop_price=Decimal("99"),
    )
    assert [item.boundary_classification for item in decisions] == [
        BoundaryClassification.GAP_NON_DECISIVE,
        BoundaryClassification.COARSE_TARGET_BOUNDARY_CROSSING,
    ]


def test_zero_volume_forward_fill_cannot_recover_a_trade_gap() -> None:
    bar = ContractPriceOhlcPoint(
            event_ts_ns=10 * NS,
            available_at_ns=11 * NS,
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("0"),
            partition_hash="a" * 64,
        )
    with pytest.raises(
        ValueError, match="FORWARD_FILLED_CONTRACT_PRICE_CANNOT_RECOVER_TRADE_GAP"
    ):
        classify_gap_bar(
            gap=_gap(),
            bar=bar,
            target_price=Decimal("101"),
            stop_price=Decimal("99"),
        )
