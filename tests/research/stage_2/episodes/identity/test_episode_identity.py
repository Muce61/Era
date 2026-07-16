from decimal import Decimal

import pytest

from era100x.research.stage_2.contracts.models import (
    CanonicalKeyLevel,
    HoldEvent,
    PriceTriggerFact,
    ReclaimEvent,
    SweepEpisode,
)
from era100x.research.stage_2.contracts.identity import (
    canonical_candidate_identity,
    canonical_identity_json,
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
    kwargs = dict(
        variant="V1_PRICE", event_parameter_set_id="G1-PRIMARY-V1", time_combination_id="T2"
    )
    first = build_market_episode(*chain(), None, **kwargs)
    changed = build_market_episode(*chain("9" * 64), None, **kwargs)
    eth = build_market_episode(*chain(instrument="ETHUSDT"), None, **kwargs)
    assert first.market_episode_id == changed.market_episode_id
    assert first.candidate_version_id != changed.candidate_version_id
    assert first.market_episode_id != eth.market_episode_id


def test_actual_ofat_parameter_and_timing_split_legacy_identity_conflict() -> None:
    primary = build_market_episode(
        *chain(),
        None,
        variant="V1_PRICE",
        event_parameter_set_id="G1-PRIMARY-V1",
        time_combination_id="T2",
    )
    timing = build_market_episode(
        *chain(),
        None,
        variant="V1_PRICE",
        event_parameter_set_id="G1-TIMING_T1-V1",
        time_combination_id="T1",
    )

    assert primary.market_episode_id == timing.market_episode_id
    assert primary.canonical_candidate_id != timing.canonical_candidate_id
    assert primary.candidate_version_id == primary.canonical_candidate_id
    assert timing.candidate_version_id == timing.canonical_candidate_id


def test_t1_through_t4_have_isolated_candidate_identities() -> None:
    identities = {
        build_market_episode(
            *chain(),
            None,
            variant="V1_PRICE",
            event_parameter_set_id=f"G1-TIMING_{timing}-V1",
            time_combination_id=timing,
        ).canonical_candidate_id
        for timing in ("T1", "T2", "T3", "T4")
    }
    assert len(identities) == 4


def test_candidate_dedup_and_consumption_are_separate_and_once_only() -> None:
    episode = build_market_episode(
        *chain(),
        None,
        variant="V1_PRICE",
        event_parameter_set_id="G1-PRIMARY-V1",
        time_combination_id="T2",
    )
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


def test_canonical_serialization_fixes_decimal_null_map_and_list_semantics() -> None:
    payload = {
        "decimal": Decimal("1.2300"),
        "negative_zero": Decimal("-0.00"),
        "null": None,
        "map": {"z": 1, "a": 2},
        "list": ["b", "a"],
    }
    assert canonical_identity_json(payload) == (
        '{"decimal":"1.23","list":["b","a"],"map":{"a":2,"z":1},"negative_zero":"0","null":null}'
    )
    with pytest.raises(TypeError, match="binary floats"):
        canonical_identity_json({"forbidden": 1.5})


def test_config_and_stage1_baseline_changes_invalidate_canonical_identity() -> None:
    base = {
        "variant": "V1_PRICE",
        "instrument": "BTCUSDT",
        "direction": "LONG",
        "key_level_id": "1" * 64,
        "sweep_id": "2" * 64,
        "reclaim_id": "3" * 64,
        "hold_id": "4" * 64,
        "price_trigger_id": "5" * 64,
        "time_combination_id": "T2",
        "event_parameter_set_id": "G1-PRIMARY-V1",
        "available_at_ts": 1,
        "stage1_data_run_id": "stage1-a",
        "stage1_instrument_logical_hash": "6" * 64,
        "config_hash": "7" * 64,
        "flow_feature_set_id": None,
    }
    identity = canonical_candidate_identity(base)
    assert identity != canonical_candidate_identity({**base, "config_hash": "8" * 64})
    assert identity != canonical_candidate_identity({**base, "stage1_data_run_id": "stage1-b"})
