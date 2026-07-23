from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from era100x.research.stage_2.baselines.conditional.features import NS
from era100x.research.stage_2.baselines.conditional.outcome_blind_producer import (
    CandidateIndex,
    CandidateLite,
)
from era100x.research.stage_2.baselines.conditional.v14_contracts import V14PrimaryEpisode


def _ts(day: int) -> int:
    return int(datetime(2020, 6, day, 12, tzinfo=UTC).timestamp() * NS)


def _candidate(day: int, *, activity: int = 2) -> CandidateLite:
    return CandidateLite(
        anchor_ns=_ts(day),
        reference_price=Decimal(100),
        high_timeframe_trend_state="UP",
        volatility_quintile=2,
        activity_quintile=activity,
        distance_quintile=2,
        four_hour_bucket=3,
        quarter=2,
        year=2020,
    )


def _episode() -> V14PrimaryEpisode:
    anchor = _ts(1)
    return V14PrimaryEpisode(
        market_episode_id="1" * 64,
        source_h2_path_hash="2" * 64,
        instrument="BTCUSDT",
        anchor_ns=anchor,
        high_timeframe_trend_state="UP",
        pre_registered_period="P1",
        evaluation_fold="F0",
        parameter_set_id="G1-PRIMARY-V1",
        time_combination_id="T2",
        label_contract_hash="3" * 64,
        volatility_quintile=2,
        activity_quintile=2,
        key_level_distance_quintile=2,
        utc_four_hour_bucket=3,
        utc_calendar_quarter=2,
        utc_calendar_year=2020,
        binning_snapshot_hash="4" * 64,
        information_span_start_ns=anchor - 3600 * NS,
        information_span_end_ns=anchor + 600 * NS,
    )


def test_compact_candidate_index_preserves_l0_then_l1_relaxation() -> None:
    exact = tuple(_candidate(day) for day in range(2, 7))
    level, selected = CandidateIndex(exact).select(_episode())
    assert level == "L0"
    assert len(selected) == 5

    relaxed = tuple(_candidate(day, activity=3) for day in range(2, 7))
    level, selected = CandidateIndex(relaxed).select(_episode())
    assert level == "L1"
    assert len(selected) == 5


def test_compact_candidate_index_never_uses_overlapping_information_span() -> None:
    episode = _episode()
    overlapping = replace(_candidate(2), anchor_ns=episode.anchor_ns + 1)
    candidates = (overlapping, *tuple(_candidate(day) for day in range(3, 7)))
    level, selected = CandidateIndex(candidates).select(episode)
    assert level == "L5"
    assert selected == ()
