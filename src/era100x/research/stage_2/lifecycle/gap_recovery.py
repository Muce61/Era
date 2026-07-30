"""Fail-closed same-second OHLC boundary evidence for lifecycle Trade gaps."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from era100x.research.stage_2.baselines.conditional.v14_contracts import canonical_hash
from era100x.research.stage_2.paths.extraction.models import PathGap

from .models import (
    BoundaryClassification,
    LifecycleObservation,
    PriceObservationSource,
)

NS: Final[int] = 1_000_000_000


@dataclass(frozen=True, slots=True)
class ContractPriceOhlcPoint:
    event_ts_ns: int
    available_at_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    partition_hash: str

    def __post_init__(self) -> None:
        if self.event_ts_ns < 0 or self.available_at_ns < self.event_ts_ns:
            raise ValueError("invalid Contract Price OHLC availability")
        if self.available_at_ns > self.event_ts_ns + NS:
            raise ValueError("Contract Price OHLC is available after its one-second interval")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("Contract Price OHLC must be positive")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("Contract Price high violates OHLC bounds")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("Contract Price low violates OHLC bounds")
        if not self.partition_hash:
            raise ValueError("Contract Price OHLC partition hash is required")
        if self.volume < 0:
            raise ValueError("Contract Price volume cannot be negative")


@dataclass(frozen=True, slots=True)
class GapBoundaryDecision:
    source_gap_id: str
    boundary_classification: BoundaryClassification
    decision_available_at_ns: int | None
    contract_price_partition_hash: str | None
    boundary_price: Decimal | None
    observation: LifecycleObservation | None
    intrasecond_order_known: bool = False
    synthetic_execution: bool = False


def gap_identity(gap: PathGap) -> str:
    return canonical_hash(
        {
            "schema": "STAGE2_LIFECYCLE_SOURCE_GAP_V1",
            "evidence_level": gap.evidence_level,
            "reason_code": gap.reason_code,
            "preceding_ts_event_ns": gap.preceding_ts_event_ns,
            "following_ts_event_ns": gap.following_ts_event_ns,
            "missing_count": gap.missing_count,
            "preceding_venue_trade_id": gap.preceding_venue_trade_id,
            "following_venue_trade_id": gap.following_venue_trade_id,
        }
    )


def gap_second_bounds(gap: PathGap) -> tuple[int, int]:
    first = (gap.preceding_ts_event_ns // NS) * NS
    last = (gap.following_ts_event_ns // NS) * NS
    if last < first:
        raise ValueError("source gap timestamp order is invalid")
    return first, last


def classify_gap_bar(
    *,
    gap: PathGap,
    bar: ContractPriceOhlcPoint,
    target_price: Decimal,
    stop_price: Decimal,
) -> GapBoundaryDecision:
    """Classify one affected second without assigning intrasecond order."""

    if target_price <= stop_price or stop_price <= 0:
        raise ValueError("static lifecycle boundaries are invalid")
    if bar.volume == 0 and not bar.open == bar.high == bar.low == bar.close:
        raise ValueError("ZERO_TRADE_CONTRACT_PRICE_MUST_BE_FLAT")
    first, last = gap_second_bounds(gap)
    if not first <= bar.event_ts_ns <= last:
        raise ValueError("Contract Price bar is outside the source gap")
    source_gap_id = gap_identity(gap)
    target_crossed = bar.high >= target_price
    stop_crossed = bar.low <= stop_price
    if target_crossed and stop_crossed:
        classification = BoundaryClassification.AMBIGUOUS
        boundary_price = bar.close
    elif target_crossed:
        classification = BoundaryClassification.COARSE_TARGET_BOUNDARY_CROSSING
        boundary_price = target_price
    elif stop_crossed:
        classification = BoundaryClassification.COARSE_STOP_BOUNDARY_CROSSING
        boundary_price = stop_price
    else:
        return GapBoundaryDecision(
            source_gap_id=source_gap_id,
            boundary_classification=BoundaryClassification.GAP_NON_DECISIVE,
            decision_available_at_ns=bar.available_at_ns,
            contract_price_partition_hash=bar.partition_hash,
            boundary_price=None,
            observation=None,
        )
    observation = LifecycleObservation(
        ts_event_ns=bar.event_ts_ns,
        available_at_ns=bar.available_at_ns,
        price_source=PriceObservationSource.CONTRACT_PRICE_1S_OHLC_BOUNDARY,
        venue_trade_id=0,
        canonical_trade_id=f"ohlc-gap-{source_gap_id}-{bar.event_ts_ns}",
        price=boundary_price,
        source_gap_id=source_gap_id,
        contract_price_partition_hash=bar.partition_hash,
        boundary_classification=classification,
        intrasecond_order_known=False,
        synthetic_execution=False,
    )
    return GapBoundaryDecision(
        source_gap_id=source_gap_id,
        boundary_classification=classification,
        decision_available_at_ns=bar.available_at_ns,
        contract_price_partition_hash=bar.partition_hash,
        boundary_price=boundary_price,
        observation=observation,
    )


def classify_gap_path(
    *,
    gap: PathGap,
    bars: tuple[ContractPriceOhlcPoint, ...],
    target_price: Decimal,
    stop_price: Decimal,
) -> tuple[GapBoundaryDecision, ...]:
    """Classify every affected second in causal availability order."""

    first, last = gap_second_bounds(gap)
    selected = tuple(
        sorted(
            (bar for bar in bars if first <= bar.event_ts_ns <= last),
            key=lambda bar: (bar.available_at_ns, bar.event_ts_ns),
        )
    )
    expected_seconds = ((last - first) // NS) + 1
    if len(selected) != expected_seconds:
        raise ValueError("CONTRACT_PRICE_GAP_SECOND_UNAVAILABLE")
    if len({bar.event_ts_ns for bar in selected}) != len(selected):
        raise ValueError("duplicate Contract Price second in source gap")
    decisions: list[GapBoundaryDecision] = []
    for bar in selected:
        decision = classify_gap_bar(
            gap=gap,
            bar=bar,
            target_price=target_price,
            stop_price=stop_price,
        )
        decisions.append(decision)
        if decision.boundary_classification is not BoundaryClassification.GAP_NON_DECISIVE:
            break
    return tuple(decisions)


def with_cumulative_funding(
    decision: GapBoundaryDecision, cumulative_funding: Decimal
) -> GapBoundaryDecision:
    if decision.observation is None:
        return decision
    return replace(
        decision,
        observation=replace(
            decision.observation,
            cumulative_funding=cumulative_funding,
        ),
    )
