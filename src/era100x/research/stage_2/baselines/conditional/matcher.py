"""Pure deterministic S2-T15 conditional-control matching."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from .models import (
    PERIODS,
    PROHIBITED_INTERPRETATIONS,
    ConditionalBaselineManifest,
    ConditionalBaselineMatch,
    ConditionalBaselineSummary,
    ControlCandidate,
    MatchLevel,
    PrimaryEpisode,
)


def _utc_parts(timestamp_ns: int) -> tuple[int, int, int]:
    instant = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=UTC)
    return instant.year, (instant.month - 1) // 3 + 1, instant.hour // 4


def _period_for(timestamp_ns: int) -> str | None:
    return next(
        (period_id for period_id, start_ns, end_ns in PERIODS if start_ns <= timestamp_ns < end_ns),
        None,
    )


def _overlaps(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start < right_end and right_start < left_end


def _structurally_eligible(episode: PrimaryEpisode, candidate: ControlCandidate) -> bool:
    if (
        candidate.instrument != episode.instrument
        or candidate.direction != episode.direction
        or candidate.setup_id != episode.setup_id
        or candidate.context_model_id != episode.context_model_id
        or candidate.high_timeframe_trend_state != episode.high_timeframe_trend_state
        or candidate.pre_registered_period != episode.pre_registered_period
        or candidate.research_split_or_fold != episode.research_split_or_fold
        or candidate.binning_snapshot_hash != episode.binning_snapshot_hash
        or candidate.is_registered_same_family_event
    ):
        return False
    if _overlaps(
        candidate.window_start_ns,
        candidate.window_end_ns,
        episode.event_window_start_ns,
        episode.event_window_end_ns,
    ):
        return False
    return not _overlaps(
        candidate.window_start_ns,
        candidate.window_end_ns,
        episode.purge_embargo_start_ns,
        episode.purge_embargo_end_ns,
    )


def _matches_level(episode: PrimaryEpisode, candidate: ControlCandidate, level: MatchLevel) -> bool:
    if level == "L5":
        return False
    activity_matches = abs(candidate.activity_quintile - episode.activity_quintile) <= (
        0 if level == "L0" else 1
    )
    volatility_matches = abs(candidate.volatility_quintile - episode.volatility_quintile) <= (
        0 if level in {"L0", "L1"} else 1
    )
    episode_bucket = int(episode.utc_four_hour_bucket[1])
    candidate_bucket = int(candidate.utc_four_hour_bucket[1])
    bucket_matches = candidate_bucket == episode_bucket
    if level in {"L3", "L4"}:
        bucket_matches = candidate_bucket in {
            (episode_bucket - 1) % 6,
            episode_bucket,
            (episode_bucket + 1) % 6,
        }
    episode_year, _, _ = _utc_parts(episode.available_at_ns)
    candidate_year, _, _ = _utc_parts(candidate.candidate_timestamp_ns)
    quarter_matches = candidate.utc_calendar_quarter == episode.utc_calendar_quarter
    if level == "L4":
        quarter_matches = candidate_year == episode_year
    return activity_matches and volatility_matches and bucket_matches and quarter_matches


def _validate_time_membership(record: PrimaryEpisode | ControlCandidate) -> None:
    timestamp_ns = (
        record.available_at_ns
        if isinstance(record, PrimaryEpisode)
        else record.candidate_timestamp_ns
    )
    year, quarter, bucket = _utc_parts(timestamp_ns)
    del year
    if _period_for(record.available_at_ns) != record.pre_registered_period:
        raise ValueError("record available_at_ns is outside its preregistered period")
    if _period_for(timestamp_ns) != record.pre_registered_period:
        raise ValueError("candidate timestamp crosses a preregistered period boundary")
    if record.utc_calendar_quarter != quarter:
        raise ValueError("UTC calendar quarter disagrees with event time")
    if record.utc_four_hour_bucket != f"B{bucket}":
        raise ValueError("UTC four-hour bucket disagrees with event time")


def match_conditional_controls(
    episode: PrimaryEpisode,
    candidates: tuple[ControlCandidate, ...],
    manifest: ConditionalBaselineManifest,
) -> ConditionalBaselineMatch:
    """Select five controls at the first successful preregistered relaxation level."""

    _validate_time_membership(episode)
    for candidate in candidates:
        _validate_time_membership(candidate)
    control_ids = [candidate.control_id for candidate in candidates]
    if len(control_ids) != len(set(control_ids)):
        raise ValueError("duplicate control_id is not allowed")
    eligible = tuple(
        candidate for candidate in candidates if _structurally_eligible(episode, candidate)
    )
    chosen_level: MatchLevel = "L5"
    selected: tuple[ControlCandidate, ...] = ()
    for level in manifest.relaxation_order[:-1]:
        matches = tuple(
            candidate for candidate in eligible if _matches_level(episode, candidate, level)
        )
        if len(matches) < manifest.controls_per_episode:
            continue
        chosen_level = level
        selected = tuple(
            sorted(
                matches,
                key=lambda candidate: (
                    hashlib.sha256(
                        (
                            f"{episode.market_episode_id}|{candidate.candidate_timestamp_ns}|"
                            f"{manifest.matching_seed}"
                        ).encode()
                    ).hexdigest(),
                    candidate.control_id,
                ),
            )[: manifest.controls_per_episode]
        )
        break
    values = tuple(candidate.target_first_strict for candidate in selected)
    matched = bool(selected)
    return ConditionalBaselineMatch.seal(
        {
            "instrument": episode.instrument,
            "setup_id": episode.setup_id,
            "context_model_id": episode.context_model_id,
            "pre_registered_period": episode.pre_registered_period,
            "research_split_or_fold": episode.research_split_or_fold,
            "market_episode_id": episode.market_episode_id,
            "raw_label": episode.raw_label,
            "primary_target_first": 1 if episode.raw_label == "TARGET_FIRST" else 0,
            "status": "MATCHED" if matched else "UNMATCHED",
            "event_match_level": chosen_level,
            "control_ids": tuple(candidate.control_id for candidate in selected),
            "control_target_first_values": values,
            "episode_control_mean": (
                Decimal(sum(values)) / Decimal(manifest.controls_per_episode) if matched else None
            ),
            "source_preregistration_manifest_hash": (manifest.source_preregistration_manifest_hash),
            "historical_evidence_only": True,
            "prohibited_interpretations": PROHIBITED_INTERPRETATIONS,
        }
    )


def summarize_conditional_matches(
    matches: tuple[ConditionalBaselineMatch, ...],
) -> ConditionalBaselineSummary:
    """Produce an episode-equal-weighted summary for one isolated research group."""

    if not matches:
        raise ValueError("at least one conditional match is required")
    for match in matches:
        if match.output_hash != match.computed_hash():
            raise ValueError("source conditional match hash is invalid")
    group_keys = {
        (
            match.instrument,
            match.setup_id,
            match.context_model_id,
            match.pre_registered_period,
            match.research_split_or_fold,
            match.source_preregistration_manifest_hash,
        )
        for match in matches
    }
    if len(group_keys) != 1:
        raise ValueError("instrument, setup, context, period and split must remain separate")
    episode_ids = [match.market_episode_id for match in matches]
    if len(episode_ids) != len(set(episode_ids)):
        raise ValueError("duplicate market_episode_id is not allowed")
    matched = tuple(match for match in matches if match.status == "MATCHED")
    assignments = tuple(control_id for match in matched for control_id in match.control_ids)
    eligible_count = len(matches)
    matched_count = len(matched)
    late_count = sum(match.event_match_level in {"L3", "L4"} for match in matched)
    event_rate: Decimal | None
    baseline_rate: Decimal | None
    late_share: Decimal | None
    reuse_rate: Decimal | None
    delta: Decimal | None
    if matched_count:
        event_rate = Decimal(sum(match.primary_target_first for match in matched)) / Decimal(
            matched_count
        )
        baseline_rate = sum(
            (
                match.episode_control_mean
                for match in matched
                if match.episode_control_mean is not None
            ),
            start=Decimal(0),
        ) / Decimal(matched_count)
        late_share = Decimal(late_count) / Decimal(matched_count)
        reuse_rate = Decimal(len(assignments) - len(set(assignments))) / Decimal(len(assignments))
        delta = event_rate - baseline_rate
    else:
        event_rate = baseline_rate = late_share = reuse_rate = delta = None
    instrument, setup_id, context_model_id, period, split, manifest_hash = next(iter(group_keys))
    return ConditionalBaselineSummary.seal(
        {
            "instrument": instrument,
            "setup_id": setup_id,
            "context_model_id": context_model_id,
            "pre_registered_period": period,
            "research_split_or_fold": split,
            "eligible_episode_count": eligible_count,
            "matched_episode_count": matched_count,
            "unmatched_episode_count": eligible_count - matched_count,
            "late_relaxation_count": late_count,
            "control_assignment_count": len(assignments),
            "unique_control_count": len(set(assignments)),
            "matching_coverage": Decimal(matched_count) / Decimal(eligible_count),
            "late_relaxation_share": late_share,
            "control_reuse_rate": reuse_rate,
            "event_target_first_rate": event_rate,
            "matched_baseline_target_first_rate": baseline_rate,
            "delta_target_first": delta,
            "source_match_hashes": tuple(sorted(match.output_hash for match in matches)),
            "source_preregistration_manifest_hash": manifest_hash,
            "historical_evidence_only": True,
            "prohibited_interpretations": PROHIBITED_INTERPRETATIONS,
        }
    )
