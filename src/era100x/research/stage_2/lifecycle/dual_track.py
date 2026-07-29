"""Successor T11 dual-track lifecycle evaluation."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from decimal import Decimal

from era100x.research.stage_2.paths.extraction.models import PathGap

from .engine import evaluate_lifecycle_pair, funding_for_track
from .gap_recovery import (
    ContractPriceOhlcPoint,
    GapBoundaryDecision,
    classify_gap_bar,
    gap_second_bounds,
    with_cumulative_funding,
)
from .models import (
    BPS,
    TICKET_EQUITY,
    USABLE_MARGIN,
    BoundaryClassification,
    CostScenario,
    FundingTrack,
    LifecyclePairResult,
    LifecycleObservation,
    LifecycleTrack,
    PriceObservationSource,
    SourceCoverage,
)
from .producer import (
    CanonicalTradePoint,
    ContractPricePoint,
    FundingSettlement,
    assemble_lifecycle_observations,
)


@dataclass(frozen=True, slots=True)
class DualTrackLifecycleResult:
    pure_trades_comparator: LifecyclePairResult
    contract_price_ohlc_primary: LifecyclePairResult
    gap_decisions: tuple[GapBoundaryDecision, ...]


def _target_price(
    *,
    entry_price: Decimal,
    cumulative_funding: Decimal,
    scenario: CostScenario,
    funding_track: FundingTrack,
) -> Decimal:
    notional = USABLE_MARGIN * Decimal("100")
    cost = notional * scenario.total_cost_bps / BPS
    funding = funding_for_track(cumulative_funding, funding_track)
    return entry_price * (Decimal(1) + (TICKET_EQUITY + cost + funding) / notional)


def _funding_by_contract_second(
    observations: tuple[LifecycleObservation, ...],
) -> tuple[tuple[int, ...], tuple[Decimal, ...]]:
    rows = tuple(item for item in observations if item.price_source.value == "CONTRACT_PRICE_1S")
    return (
        tuple(item.ts_event_ns for item in rows),
        tuple(item.cumulative_funding for item in rows),
    )


def _funding_at(
    timestamp_ns: int, timestamps: tuple[int, ...], cumulative: tuple[Decimal, ...]
) -> Decimal:
    index = bisect_right(timestamps, timestamp_ns) - 1
    if index < 0:
        raise ValueError("gap boundary has no causal Contract Price funding valuation")
    return cumulative[index]


def _ohlc_points(
    contract_prices: tuple[ContractPricePoint, ...],
    *,
    partition_hash_by_second: dict[int, str],
) -> tuple[ContractPriceOhlcPoint, ...]:
    rows: list[ContractPriceOhlcPoint] = []
    for point in contract_prices:
        if point.open is None or point.high is None or point.low is None:
            raise ValueError("CONTRACT_PRICE_OHLC_NOT_BOUND")
        if point.volume is None:
            raise ValueError("CONTRACT_PRICE_VOLUME_NOT_BOUND")
        try:
            partition_hash = partition_hash_by_second[point.event_ts_ns]
        except KeyError as error:
            raise ValueError("CONTRACT_PRICE_PARTITION_HASH_UNBOUND") from error
        rows.append(
            ContractPriceOhlcPoint(
                event_ts_ns=point.event_ts_ns,
                available_at_ns=point.available_at_ns,
                open=point.open,
                high=point.high,
                low=point.low,
                close=point.close,
                volume=point.volume,
                partition_hash=partition_hash,
            )
        )
    return tuple(rows)


def _recover_gap_boundaries(
    *,
    gaps: tuple[PathGap, ...],
    bars: tuple[ContractPriceOhlcPoint, ...],
    entry_price: Decimal,
    scenario: CostScenario,
    funding_track: FundingTrack,
    stop_bps: Decimal,
    funding_timestamps: tuple[int, ...],
    cumulative_funding: tuple[Decimal, ...],
) -> tuple[GapBoundaryDecision, ...]:
    stop_price = entry_price * (Decimal(1) - stop_bps / BPS)
    decisions: list[GapBoundaryDecision] = []
    by_second = {bar.event_ts_ns: bar for bar in bars}
    for gap in sorted(
        gaps,
        key=lambda item: (
            item.preceding_ts_event_ns,
            item.following_ts_event_ns,
        ),
    ):
        first, last = gap_second_bounds(gap)
        second = first
        while second <= last:
            try:
                bar = by_second[second]
            except KeyError as error:
                raise ValueError("CONTRACT_PRICE_GAP_SECOND_UNAVAILABLE") from error
            funding = _funding_at(second, funding_timestamps, cumulative_funding)
            decision = classify_gap_bar(
                gap=gap,
                bar=bar,
                target_price=_target_price(
                    entry_price=entry_price,
                    cumulative_funding=funding,
                    scenario=scenario,
                    funding_track=funding_track,
                ),
                stop_price=stop_price,
            )
            decision = with_cumulative_funding(decision, funding)
            decisions.append(decision)
            if decision.boundary_classification is not BoundaryClassification.GAP_NON_DECISIVE:
                return tuple(decisions)
            second += 1_000_000_000
    return tuple(decisions)


def _seal_result_metadata(
    result: LifecyclePairResult,
    *,
    track: LifecycleTrack,
    decisions: tuple[GapBoundaryDecision, ...],
) -> LifecyclePairResult:
    decisive = next(
        (
            item
            for item in decisions
            if item.boundary_classification is not BoundaryClassification.GAP_NON_DECISIVE
        ),
        None,
    )
    representative = decisive or (decisions[-1] if decisions else None)
    value = replace(
        result,
        lifecycle_track=track,
        observation_source=(
            "CONTRACT_PRICE_1S_OHLC_BOUNDARY"
            if representative is not None
            else "CANONICAL_TRADES_AND_CONTRACT_PRICE_CLOSE"
        ),
        source_gap_id=representative.source_gap_id if representative is not None else None,
        contract_price_partition_hash=(
            representative.contract_price_partition_hash if representative is not None else None
        ),
        boundary_classification=(
            representative.boundary_classification
            if representative is not None
            else BoundaryClassification.NOT_APPLICABLE
        ),
        decision_available_at_ns=(
            decisive.decision_available_at_ns
            if decisive is not None
            else result.continue_holding.decision_ts_ns
        ),
        intrasecond_order_known=representative is None,
        synthetic_execution=False,
        output_hash="",
    )
    return replace(value, output_hash=value.computed_hash())


def _trade_observation_is_gap_affected(
    observation: LifecycleObservation, gaps: tuple[PathGap, ...]
) -> bool:
    if observation.price_source is not PriceObservationSource.CANONICAL_TRADE:
        return False
    timestamp = observation.ts_event_ns
    venue_trade_id = observation.venue_trade_id
    for gap in gaps:
        if gap.preceding_ts_event_ns < timestamp <= gap.following_ts_event_ns:
            return True
        if timestamp == gap.preceding_ts_event_ns == gap.following_ts_event_ns:
            if (
                gap.preceding_venue_trade_id is not None
                and gap.following_venue_trade_id is not None
                and gap.preceding_venue_trade_id < venue_trade_id <= gap.following_venue_trade_id
            ):
                return True
    return False


def evaluate_dual_track_lifecycle(
    *,
    market_episode_id: str,
    instrument: str,
    entry_ts_ns: int,
    entry_price: Decimal,
    contract_prices: tuple[ContractPricePoint, ...],
    trades: tuple[CanonicalTradePoint, ...],
    funding: tuple[FundingSettlement, ...],
    source_gaps: tuple[PathGap, ...],
    partition_hash_by_second: dict[int, str],
    source_coverage: SourceCoverage,
    scenario: CostScenario,
    funding_track: FundingTrack,
    historical_funding_source_bound: bool,
    stop_bps: Decimal,
) -> DualTrackLifecycleResult:
    """Evaluate immutable Trades and coarse OHLC recovery as separate tracks."""

    observations = assemble_lifecycle_observations(
        entry_price=entry_price,
        contract_prices=contract_prices,
        trades=trades,
        funding=funding,
    )
    first_gap_ns = (
        min(gap.preceding_ts_event_ns + 1 for gap in source_gaps) if source_gaps else None
    )
    reliable_observations = tuple(
        item for item in observations if not _trade_observation_is_gap_affected(item, source_gaps)
    )
    pure_coverage = SourceCoverage.DECLARED_GAP if source_gaps else source_coverage
    pure = evaluate_lifecycle_pair(
        market_episode_id=market_episode_id,
        instrument=instrument,
        entry_ts_ns=entry_ts_ns,
        entry_price=entry_price,
        observations=reliable_observations,
        source_coverage=pure_coverage,
        scenario=scenario,
        funding_track=funding_track,
        historical_funding_source_bound=historical_funding_source_bound,
        stop_bps=stop_bps,
        lifecycle_track=LifecycleTrack.PURE_TRADES_COMPARATOR,
        source_gap_start_ns=first_gap_ns,
    )
    if source_coverage is SourceCoverage.DATA_END:
        primary = evaluate_lifecycle_pair(
            market_episode_id=market_episode_id,
            instrument=instrument,
            entry_ts_ns=entry_ts_ns,
            entry_price=entry_price,
            observations=observations,
            source_coverage=source_coverage,
            scenario=scenario,
            funding_track=funding_track,
            historical_funding_source_bound=historical_funding_source_bound,
            stop_bps=stop_bps,
            lifecycle_track=LifecycleTrack.CONTRACT_PRICE_OHLC_PRIMARY,
        )
        return DualTrackLifecycleResult(pure, primary, ())
    bars = _ohlc_points(
        contract_prices,
        partition_hash_by_second=partition_hash_by_second,
    )
    funding_timestamps, cumulative = _funding_by_contract_second(observations)
    decisions = _recover_gap_boundaries(
        gaps=source_gaps,
        bars=bars,
        entry_price=entry_price,
        scenario=scenario,
        funding_track=funding_track,
        stop_bps=stop_bps,
        funding_timestamps=funding_timestamps,
        cumulative_funding=cumulative,
    )
    boundary_observations = tuple(
        decision.observation for decision in decisions if decision.observation is not None
    )
    primary_observations = tuple(
        sorted(
            (*reliable_observations, *boundary_observations),
            key=lambda item: item.stable_order_key,
        )
    )
    primary = evaluate_lifecycle_pair(
        market_episode_id=market_episode_id,
        instrument=instrument,
        entry_ts_ns=entry_ts_ns,
        entry_price=entry_price,
        observations=primary_observations,
        source_coverage=SourceCoverage.COMPLETE,
        scenario=scenario,
        funding_track=funding_track,
        historical_funding_source_bound=historical_funding_source_bound,
        stop_bps=stop_bps,
        lifecycle_track=LifecycleTrack.CONTRACT_PRICE_OHLC_PRIMARY,
    )
    return DualTrackLifecycleResult(
        pure_trades_comparator=_seal_result_metadata(
            pure,
            track=LifecycleTrack.PURE_TRADES_COMPARATOR,
            decisions=(),
        ),
        contract_price_ohlc_primary=_seal_result_metadata(
            primary,
            track=LifecycleTrack.CONTRACT_PRICE_OHLC_PRIMARY,
            decisions=decisions,
        ),
        gap_decisions=decisions,
    )
