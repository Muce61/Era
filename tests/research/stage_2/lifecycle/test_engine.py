from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from era100x.research.stage_2.lifecycle import (
    CostScenario,
    FundingTrack,
    LifecycleObservation,
    PriceObservationSource,
    SourceCoverage,
    evaluate_lifecycle_pair,
)
from era100x.research.stage_2.lifecycle.models import (
    MAX_HORIZON_SECONDS,
    MONEY_QUANTUM,
    PRIMARY_LANDMARK_SECONDS,
)


ENTRY_NS = 1_000_000_000_000
ENTRY = Decimal("100")
SCENARIO = CostScenario(
    scenario_id="MAIN_9BP_2BP_250MS_FULL",
    round_trip_fee_bps=Decimal("9"),
    total_slippage_bps=Decimal("2"),
    latency_ms=250,
    initial_fill_ratio=Decimal("1"),
)


def _observation(
    seconds: int,
    price: str,
    *,
    trade_id: int = 1,
    source: PriceObservationSource = PriceObservationSource.CONTRACT_PRICE_1S,
) -> LifecycleObservation:
    return LifecycleObservation(
        ts_event_ns=ENTRY_NS + seconds * 1_000_000_000,
        price_source=source,
        venue_trade_id=trade_id,
        canonical_trade_id=f"{trade_id:064x}",
        price=Decimal(price),
    )


def _evaluate(observations: tuple[LifecycleObservation, ...], **kwargs: object):
    parameters: dict[str, object] = {
        "funding_track": FundingTrack.PRIMARY_HISTORICAL_ACTUAL,
        "historical_funding_source_bound": True,
        "stop_bps": Decimal("25"),
    }
    parameters.update(kwargs)
    return evaluate_lifecycle_pair(
        market_episode_id="e" * 64,
        instrument="BTCUSDT",
        entry_ts_ns=ENTRY_NS,
        entry_price=ENTRY,
        observations=observations,
        source_coverage=SourceCoverage.COMPLETE,
        scenario=SCENARIO,
        **parameters,
    )


def test_primary_near_zero_and_unactivated_pair_closes_target() -> None:
    result = _evaluate(
        (
            _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=1),
            _observation(
                PRIMARY_LANDMARK_SECONDS + 60,
                "101.36",
                trade_id=2,
                source=PriceObservationSource.CANONICAL_TRADE,
            ),
        )
    )
    assert result.eligible_at_primary_landmark is True
    assert result.activated_before_landmark is False
    assert result.immediate_exit.terminal_state == "THEORETICAL_FULLY_FLAT"
    assert result.continue_holding.exit_reason == "TICKET_DOUBLE_TARGET"
    assert result.continue_holding.remaining_proxy_quantity == 0
    assert result.price_proxy_source == "CONTRACT_PRICE_1S"
    assert result.protection_exit_model == "NOT_MODELLED_STAGE2"
    assert result.structure_exit_model == "NOT_MODELLED_STAGE2"
    assert result.historical_mark_price_claim is False
    assert result.output_hash == result.computed_hash()


def test_twenty_bp_auxiliary_crossing_does_not_close_the_lifecycle() -> None:
    result = _evaluate(
        (
            _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=1),
            _observation(
                PRIMARY_LANDMARK_SECONDS + 60,
                "100.20",
                trade_id=2,
                source=PriceObservationSource.CANONICAL_TRADE,
            ),
        ),
    )
    assert result.continue_holding.terminal_state == "RIGHT_CENSORED"
    assert result.continue_holding.exit_reason is None
    assert result.continue_holding.ticket_doubled is None


def test_activation_boundary_is_decimal_exact() -> None:
    activated = _evaluate(
        (
            _observation(300, "100.31", trade_id=1),
            _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=2),
        )
    )
    below = _evaluate(
        (
            _observation(300, str(Decimal("100.31") - MONEY_QUANTUM), trade_id=1),
            _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=2),
        )
    )
    assert activated.activated_before_landmark is True
    assert below.activated_before_landmark is False


@pytest.mark.parametrize("fill_ratio", ["1", "0.8", "0.5"])
def test_fill_scenarios_reconcile_remaining_quantity_to_zero(fill_ratio: str) -> None:
    scenario = replace(SCENARIO, initial_fill_ratio=Decimal(fill_ratio))
    result = evaluate_lifecycle_pair(
        market_episode_id="e" * 64,
        instrument="ETHUSDT",
        entry_ts_ns=ENTRY_NS,
        entry_price=ENTRY,
        observations=(
            _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=1),
            _observation(
                PRIMARY_LANDMARK_SECONDS + 1,
                "99.75",
                trade_id=2,
                source=PriceObservationSource.CANONICAL_TRADE,
            ),
        ),
        source_coverage=SourceCoverage.COMPLETE,
        scenario=scenario,
        funding_track=FundingTrack.PRIMARY_HISTORICAL_ACTUAL,
        historical_funding_source_bound=True,
        stop_bps=Decimal("25"),
    )
    assert result.continue_holding.remaining_proxy_quantity == 0
    assert result.continue_holding.terminal_state == "THEORETICAL_FULLY_FLAT"


def test_complete_zero_trade_path_is_right_censored_not_expired() -> None:
    result = _evaluate(())
    assert result.continue_holding.censor_reason == "MAX_HORIZON_CENSORED"
    assert result.continue_holding.ticket_doubled is None
    assert result.continue_holding.scenario_net_pnl is None


def test_missing_historical_funding_cannot_become_zero_or_stress() -> None:
    with pytest.raises(ValueError, match="historical funding source must be bound"):
        _evaluate((), historical_funding_source_bound=False)


@pytest.mark.parametrize(
    ("coverage", "reason"),
    [
        (SourceCoverage.DECLARED_GAP, "SOURCE_GAP_CENSORED"),
        (SourceCoverage.DATA_END, "DATA_END_CENSORED"),
    ],
)
def test_declared_incomplete_sources_have_distinct_censor_reasons(
    coverage: SourceCoverage, reason: str
) -> None:
    result = evaluate_lifecycle_pair(
        market_episode_id="e" * 64,
        instrument="BTCUSDT",
        entry_ts_ns=ENTRY_NS,
        entry_price=ENTRY,
        observations=(
            _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=1),
            _observation(PRIMARY_LANDMARK_SECONDS + 1, "99.00", trade_id=2),
        ),
        source_coverage=coverage,
        scenario=SCENARIO,
        funding_track=FundingTrack.PRIMARY_HISTORICAL_ACTUAL,
        historical_funding_source_bound=True,
        stop_bps=Decimal("25"),
    )
    assert result.continue_holding.censor_reason == reason
    assert result.continue_holding.exit_reason is None
    assert result.immediate_exit.censor_reason == reason
    assert result.eligible_at_primary_landmark is False
    assert result.landmark_net_exitable_pnl is None


@pytest.mark.parametrize("coverage", [SourceCoverage.UNBOUND, SourceCoverage.HASH_DRIFT])
def test_unbound_or_tampered_source_is_run_level_failure(coverage: SourceCoverage) -> None:
    with pytest.raises(ValueError, match="run-level source integrity"):
        evaluate_lifecycle_pair(
            market_episode_id="e" * 64,
            instrument="BTCUSDT",
            entry_ts_ns=ENTRY_NS,
            entry_price=ENTRY,
            observations=(),
            source_coverage=coverage,
            scenario=SCENARIO,
            funding_track=FundingTrack.PRIMARY_HISTORICAL_ACTUAL,
            historical_funding_source_bound=True,
            stop_bps=Decimal("25"),
        )


def test_liquidation_scenario_is_named_as_scenario_not_real_fact() -> None:
    result = _evaluate(
        (
            _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=1),
            _observation(PRIMARY_LANDMARK_SECONDS + 1, "99.00", trade_id=2),
        )
    )
    assert result.continue_holding.exit_reason == "SCENARIO_LIQUIDATION_BOUNDARY_CROSSED"
    assert result.continue_holding.terminal_ticket_equity == Decimal("1.120000000000000000")
    assert result.continue_holding.historical_execution_claim is False


def test_contract_risk_precedes_trade_target_in_the_same_second() -> None:
    second = PRIMARY_LANDMARK_SECONDS + 1
    result = _evaluate(
        (
            _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=1),
            _observation(second, "99.00", trade_id=2),
            _observation(
                second,
                "101.50",
                trade_id=3,
                source=PriceObservationSource.CANONICAL_TRADE,
            ),
        )
    )
    assert result.continue_holding.exit_reason == "SCENARIO_LIQUIDATION_BOUNDARY_CROSSED"


def test_funding_is_deducted_at_landmark() -> None:
    base = _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=1)
    funded = replace(base, cumulative_funding=Decimal("0.25"))
    without = _evaluate((base,))
    with_funding = _evaluate((funded,))
    assert with_funding.landmark_net_exitable_pnl == without.landmark_net_exitable_pnl - Decimal(
        "0.25"
    )


@pytest.mark.parametrize(
    ("track", "actual", "expected"),
    [
        (FundingTrack.PRIMARY_HISTORICAL_ACTUAL, "0.25", "0.25"),
        (FundingTrack.STRESS_ADVERSE_1_5X, "0.25", "0.375"),
        (FundingTrack.STRESS_ADVERSE_2X, "0.25", "0.50"),
        (FundingTrack.STRESS_ADVERSE_1_5X, "-0.25", "-0.25"),
        (FundingTrack.STRESS_ADVERSE_2X, "-0.25", "-0.25"),
        (FundingTrack.STRESS_NO_FUNDING_CREDIT, "-0.25", "0"),
    ],
)
def test_funding_tracks_are_separate_and_only_stress_adversely(
    track: FundingTrack, actual: str, expected: str
) -> None:
    observation = replace(
        _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=1),
        cumulative_funding=Decimal(actual),
    )
    baseline = _evaluate(
        (replace(observation, cumulative_funding=Decimal("0")),),
        funding_track=FundingTrack.PRIMARY_HISTORICAL_ACTUAL,
    )
    result = _evaluate((observation,), funding_track=track)
    assert result.landmark_net_exitable_pnl == (
        baseline.landmark_net_exitable_pnl - Decimal(expected)
    )
    assert result.funding_track is track


def test_ticket_doubling_target_moves_with_accumulated_funding() -> None:
    result = _evaluate(
        (
            _observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=1),
            replace(
                _observation(PRIMARY_LANDMARK_SECONDS + 60, "101.36", trade_id=2),
                cumulative_funding=Decimal("0.25"),
                price_source=PriceObservationSource.CANONICAL_TRADE,
            ),
            replace(
                _observation(PRIMARY_LANDMARK_SECONDS + 120, "101.40", trade_id=3),
                cumulative_funding=Decimal("0.25"),
                price_source=PriceObservationSource.CANONICAL_TRADE,
            ),
        )
    )
    assert result.continue_holding.exit_reason == "TICKET_DOUBLE_TARGET"
    assert result.continue_holding.decision_ts_ns == (
        ENTRY_NS + (PRIMARY_LANDMARK_SECONDS + 120) * 1_000_000_000
    )
    assert result.continue_holding.terminal_ticket_equity == Decimal("20.070000000000000000")


def test_stable_order_and_duplicate_identity_are_enforced() -> None:
    later = _observation(PRIMARY_LANDMARK_SECONDS + 1, "100.1", trade_id=2)
    earlier = _observation(PRIMARY_LANDMARK_SECONDS, "100.1", trade_id=1)
    with pytest.raises(ValueError, match="stable order"):
        _evaluate((later, earlier))
    with pytest.raises(ValueError, match="stable order"):
        _evaluate((earlier, earlier))


def test_seven_day_boundary_is_left_closed_right_open() -> None:
    at_end = _observation(MAX_HORIZON_SECONDS, "101.36", trade_id=2)
    result = _evaluate((_observation(PRIMARY_LANDMARK_SECONDS, "100.10", trade_id=1), at_end))
    assert result.continue_holding.censor_reason == "MAX_HORIZON_CENSORED"
