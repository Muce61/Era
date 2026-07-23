from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from era100x.research.stage_2.lifecycle import (
    CanonicalTradePoint,
    ContractPricePoint,
    FundingSettlement,
    PriceObservationSource,
    assemble_lifecycle_observations,
    replay_single_position_admission,
)
from era100x.research.stage_2.lifecycle.models import (
    CensorReason,
    FundingTrack,
    LifecyclePairResult,
    LifecyclePolicyResult,
    OptionalExitModelStatus,
    SourceCoverage,
)


def _policy(
    policy_id: str, *, decision_ns: int | None, censored: bool = False
) -> LifecyclePolicyResult:
    return LifecyclePolicyResult(
        policy_id=policy_id,
        terminal_state="RIGHT_CENSORED" if censored else "THEORETICAL_FULLY_FLAT",
        exit_reason=None,
        censor_reason=CensorReason.MAX_HORIZON_CENSORED if censored else None,
        decision_ts_ns=decision_ns,
        scenario_net_pnl=None,
        terminal_ticket_equity=None,
        ticket_doubled=None,
        reserve_breached=None,
        remaining_proxy_quantity=Decimal(1) if censored else Decimal(0),
    )


def _result(episode: str, immediate_ns: int, continue_ns: int | None) -> LifecyclePairResult:
    value = LifecyclePairResult(
        market_episode_id=episode,
        instrument="BTCUSDT",
        eligible_at_primary_landmark=True,
        activated_before_landmark=False,
        landmark_net_exitable_pnl=Decimal(0),
        immediate_exit=_policy("EXIT_AT_PRIMARY_LANDMARK", decision_ns=immediate_ns),
        continue_holding=_policy(
            "CONTINUE_TO_THEORETICAL_CLOSE",
            decision_ns=continue_ns,
            censored=continue_ns is None,
        ),
        source_coverage=SourceCoverage.COMPLETE,
        funding_track=FundingTrack.PRIMARY_HISTORICAL_ACTUAL,
        price_proxy_source="CONTRACT_PRICE_1S",
        protection_exit_model=OptionalExitModelStatus.NOT_MODELLED_STAGE2,
        structure_exit_model=OptionalExitModelStatus.NOT_MODELLED_STAGE2,
        historical_mark_price_claim=False,
        output_hash="",
    )
    return replace(value, output_hash=value.computed_hash())


def test_assembly_uses_contract_notional_for_actual_funding_and_frozen_order() -> None:
    observations = assemble_lifecycle_observations(
        entry_price=Decimal("100"),
        contract_prices=(
            ContractPricePoint(1_000_000_000, 1_000_000_000, Decimal("100")),
            ContractPricePoint(2_000_000_000, 2_000_000_000, Decimal("110")),
        ),
        trades=(CanonicalTradePoint(2_000_000_000, 7, "trade-7", Decimal("111")),),
        funding=(FundingSettlement(2_000_000_000, Decimal("0.001")),),
    )
    assert [item.price_source for item in observations] == [
        PriceObservationSource.CONTRACT_PRICE_1S,
        PriceObservationSource.CONTRACT_PRICE_1S,
        PriceObservationSource.CANONICAL_TRADE,
    ]
    # qty=800/100=8; funding cash cost=8*110*0.001=0.88.
    assert observations[1].cumulative_funding == Decimal("0.880")
    assert observations[2].cumulative_funding == Decimal("0.880")


def test_funding_without_prior_contract_price_fails_closed() -> None:
    with pytest.raises(ValueError, match="no causal Contract Price"):
        assemble_lifecycle_observations(
            entry_price=Decimal("100"),
            contract_prices=(ContractPricePoint(2_000_000_000, 2_000_000_000, Decimal("100")),),
            trades=(),
            funding=(FundingSettlement(1_000_000_000, Decimal("0.001")),),
        )


def test_single_position_timelines_are_independent_and_censor_blocks_later_entries() -> None:
    decisions = replay_single_position_admission(
        (
            _result("episode-a", immediate_ns=10, continue_ns=None),
            _result("episode-b", immediate_ns=20, continue_ns=30),
        ),
        entry_ts_ns_by_episode={"episode-a": 1, "episode-b": 15},
    )
    by_key = {(item.market_episode_id, item.policy_id): item for item in decisions}
    assert by_key[("episode-b", "EXIT_AT_PRIMARY_LANDMARK")].admitted is True
    assert by_key[("episode-b", "CONTINUE_TO_THEORETICAL_CLOSE")].admitted is False
    assert (
        by_key[("episode-b", "CONTINUE_TO_THEORETICAL_CLOSE")].reason
        == "SKIPPED_SINGLE_POSITION_OCCUPIED"
    )
