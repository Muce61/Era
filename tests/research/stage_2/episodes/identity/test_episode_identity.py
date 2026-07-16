from decimal import Decimal

import pytest

from era100x.research.stage_2.contracts.models import (
    CanonicalKeyLevel,
    HoldEvent,
    PriceTriggerFact,
    ReclaimEvent,
    SweepEpisode,
)
from era100x.research.stage_2.episodes.identity import (
    CandidateInclusionLedger,
    EpisodeConsumptionLedger,
    build_market_episode,
    eligible_for_new_episode,
)
from era100x.research.stage_2.episodes.identity.episode import AboveLevelInterval


def chain(config_hash: str = "2" * 64, instrument: str = "BTCUSDT") -> tuple[object, ...]:
    common = dict(
        instrument=instrument,
        data_run_id="stage1",
        dataset_logical_hash="1" * 64,
        config_hash=config_hash,
        code_version="abcdef0",
        parameter_set_id="G1-PRIMARY-V1",
    )
    level = CanonicalKeyLevel(
        **common,
        available_at_ts=1,
        key_level_id="3" * 64,
        source_type="range_low",
        source_id="source",
        source_timeframe="1H",
        source_start_ts=0,
        source_end_ts=1,
        level_price=Decimal("100"),
        priority=3,
        normalization_group="group",
        member_key_level_ids=("4" * 64,),
        formed_at_ns=1,
        expires_at_ns=1000,
        status="ACTIVE",
        reason_code="TEST",
    )
    sweep = SweepEpisode(
        **common,
        available_at_ts=10,
        sweep_id="5" * 64,
        key_level_id=level.key_level_id,
        sweep_start_ts=8,
        sweep_detection_ts=10,
        sweep_extreme_ts=9,
        sweep_extreme_price=Decimal("99.98"),
        sweep_depth=Decimal("2"),
        pre_sweep_reference=Decimal("100"),
        status="DETECTED",
        reason_code="TEST",
    )
    reclaim = ReclaimEvent(
        **common,
        available_at_ts=11,
        reclaim_id="6" * 64,
        sweep_id=sweep.sweep_id,
        reclaim_ts=10,
        reclaim_price=Decimal("100.01"),
        status="RECLAIMED",
        reason_code="TEST",
    )
    hold = HoldEvent(
        **common,
        available_at_ts=20,
        hold_id="7" * 64,
        reclaim_id=reclaim.reclaim_id,
        sweep_id=sweep.sweep_id,
        hold_start_ts=11,
        hold_end_ts=20,
        hold_result="PASS",
        failure_reason=None,
    )
    trigger = PriceTriggerFact(
        **common,
        available_at_ts=21,
        trigger_id="8" * 64,
        hold_id=hold.hold_id,
        sweep_id=sweep.sweep_id,
        trigger_version="G1_G3_V1",
        detection_ts=21,
        reference_price=Decimal("101"),
        context_state="UP",
        status="PASS",
        reason_code="TEST",
    )
    return level, sweep, reclaim, hold, trigger


def test_frozen_market_identity_is_stable_while_candidate_version_changes() -> None:
    first = build_market_episode(*chain(), None, variant="V1_PRICE")
    changed = build_market_episode(*chain("9" * 64), None, variant="V1_PRICE")
    eth = build_market_episode(*chain(instrument="ETHUSDT"), None, variant="V1_PRICE")
    assert first.market_episode_id == changed.market_episode_id
    assert first.candidate_version_id != changed.candidate_version_id
    assert first.market_episode_id != eth.market_episode_id


def test_candidate_dedup_and_consumption_are_separate_and_once_only() -> None:
    episode = build_market_episode(*chain(), None, variant="V1_PRICE")
    ledger = CandidateInclusionLedger()
    assert ledger.include(episode).included is True
    assert ledger.include(episode).included is False
    assert episode.consumed is False
    consumption = EpisodeConsumptionLedger()
    consumption.consume(episode.market_episode_id, "intent-1")
    with pytest.raises(ValueError, match="already consumed"):
        consumption.consume(episode.market_episode_id, "intent-2")


def test_gap_and_rearm_boundaries_are_inclusive() -> None:
    assert eligible_for_new_episode(
        previous_episode_end_ns=0,
        new_crossing_ns=900_000_000_000,
        above_level_interval=AboveLevelInterval(0, 900_000_000_000),
        minimum_gap_seconds=300,
        rearm_seconds=900,
        level_active=True,
    )
    assert not eligible_for_new_episode(
        previous_episode_end_ns=0,
        new_crossing_ns=899_000_000_000,
        above_level_interval=AboveLevelInterval(0, 899_000_000_000),
        minimum_gap_seconds=300,
        rearm_seconds=900,
        level_active=True,
    )
