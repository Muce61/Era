from __future__ import annotations

from decimal import Decimal

from era100x.research.stage_2.lifecycle import (
    CanonicalTradePoint,
    ContractPricePoint,
    CostScenario,
    FundingTrack,
    LifecycleTrack,
    SourceCoverage,
    evaluate_dual_track_lifecycle,
)
from era100x.research.stage_2.lifecycle.models import PRIMARY_LANDMARK_SECONDS
from era100x.research.stage_2.paths.extraction.models import PathGap

NS = 1_000_000_000
ENTRY_NS = 1_000 * NS
GAP_SECOND = ENTRY_NS + (PRIMARY_LANDMARK_SECONDS + 60) * NS
SCENARIO = CostScenario(
    scenario_id="PRIMARY_9BP_FEE_2BP_SLIPPAGE_250MS_100PCT",
    round_trip_fee_bps=Decimal("9"),
    total_slippage_bps=Decimal("2"),
    latency_ms=250,
    initial_fill_ratio=Decimal("1"),
)


def _contract(
    timestamp: int,
    *,
    high: str = "100.2",
    low: str = "99.9",
    close: str = "100.1",
) -> ContractPricePoint:
    return ContractPricePoint(
        event_ts_ns=timestamp,
        available_at_ns=timestamp + NS,
        close=Decimal(close),
        open=Decimal("100.1"),
        high=Decimal(high),
        low=Decimal(low),
        volume=Decimal("1"),
    )


def _gap() -> PathGap:
    return PathGap(
        evidence_level="H2",
        reason_code="H2_VENUE_TRADE_ID_GAP",
        preceding_ts_event_ns=GAP_SECOND,
        following_ts_event_ns=GAP_SECOND,
        missing_count=1,
        preceding_venue_trade_id=1,
        following_venue_trade_id=3,
    )


def _evaluate(*, high: str, low: str):
    landmark = ENTRY_NS + PRIMARY_LANDMARK_SECONDS * NS
    contract_prices = (
        _contract(landmark),
        _contract(GAP_SECOND, high=high, low=low),
    )
    return evaluate_dual_track_lifecycle(
        market_episode_id="e" * 64,
        instrument="BTCUSDT",
        entry_ts_ns=ENTRY_NS,
        entry_price=Decimal("100"),
        contract_prices=contract_prices,
        trades=(
            CanonicalTradePoint(GAP_SECOND, 1, "trade-1", Decimal("100.1")),
            CanonicalTradePoint(GAP_SECOND, 3, "trade-3", Decimal("101.5")),
        ),
        funding=(),
        source_gaps=(_gap(),),
        partition_hash_by_second={point.event_ts_ns: "b" * 64 for point in contract_prices},
        source_coverage=SourceCoverage.COMPLETE,
        scenario=SCENARIO,
        funding_track=FundingTrack.PRIMARY_HISTORICAL_ACTUAL,
        historical_funding_source_bound=True,
        stop_bps=Decimal("25"),
    )


def test_gap_before_decision_censors_pure_trade_but_ohlc_target_is_coarse() -> None:
    result = _evaluate(high="101.5", low="100")

    assert result.pure_trades_comparator.lifecycle_track is LifecycleTrack.PURE_TRADES_COMPARATOR
    assert result.pure_trades_comparator.continue_holding.censor_reason == "SOURCE_GAP_CENSORED"
    primary = result.contract_price_ohlc_primary
    assert primary.lifecycle_track is LifecycleTrack.CONTRACT_PRICE_OHLC_PRIMARY
    assert primary.continue_holding.exit_reason == "TICKET_DOUBLE_TARGET"
    assert primary.boundary_classification == "COARSE_TARGET_BOUNDARY_CROSSING"
    assert primary.intrasecond_order_known is False
    assert primary.synthetic_execution is False


def test_same_second_target_and_stop_remains_ambiguous() -> None:
    result = _evaluate(high="101.5", low="99")
    primary = result.contract_price_ohlc_primary
    assert primary.continue_holding.terminal_state == "AMBIGUOUS"
    assert primary.continue_holding.censor_reason == "INCONCLUSIVE_INTRASECOND_ORDER"
    assert primary.boundary_classification == "AMBIGUOUS"


def test_non_decisive_gap_does_not_create_a_trade_or_terminal() -> None:
    result = _evaluate(high="100.5", low="99.9")
    primary = result.contract_price_ohlc_primary
    assert primary.continue_holding.terminal_state == "RIGHT_CENSORED"
    assert primary.continue_holding.censor_reason == "MAX_HORIZON_CENSORED"
    assert primary.boundary_classification == "GAP_NON_DECISIVE"
    assert all(decision.observation is None for decision in result.gap_decisions)
