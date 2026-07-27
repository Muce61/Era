"""Pure outcome-blind placebo matching."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from .contracts import (
    PLACEBO_CONTROL_NAMESPACE,
    PLACEBO_EVENT_NAMESPACE,
    PLACEBO_SEED,
    RELAXATION_LEVELS,
    BlindPlaceboSelection,
    PlaceboCandidate,
    PlaceboEventReference,
)


def overlaps(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start < right_end and right_start < left_end


def _exact(source: PlaceboEventReference | PlaceboCandidate, candidate: PlaceboCandidate) -> bool:
    return (
        candidate.instrument == source.instrument
        and candidate.direction == source.direction
        and candidate.setup_id == source.setup_id
        and candidate.context_model_id == source.context_model_id
        and candidate.high_timeframe_trend_state == source.high_timeframe_trend_state
        and candidate.pre_registered_period == source.pre_registered_period
        and candidate.evaluation_fold == source.evaluation_fold
        and candidate.parameter_set_id == source.parameter_set_id
        and candidate.time_combination_id == source.time_combination_id
        and candidate.label_contract_hash == source.label_contract_hash
        and candidate.key_level_distance_quintile == source.key_level_distance_quintile
        and candidate.binning_snapshot_hash == source.binning_snapshot_hash
        and not candidate.is_registered_same_family_event
    )


def _level(
    source: PlaceboEventReference | PlaceboCandidate,
    candidate: PlaceboCandidate,
    level: str,
) -> bool:
    activity_tolerance = 0 if level == "L0" else 1
    volatility_tolerance = 0 if level in {"L0", "L1"} else 1
    if abs(candidate.activity_quintile - source.activity_quintile) > activity_tolerance:
        return False
    if abs(candidate.volatility_quintile - source.volatility_quintile) > volatility_tolerance:
        return False
    bucket_delta = (candidate.utc_four_hour_bucket - source.utc_four_hour_bucket) % 6
    if level in {"L0", "L1", "L2"}:
        if bucket_delta != 0:
            return False
    elif bucket_delta not in {0, 1, 5}:
        return False
    if level == "L4":
        return candidate.utc_calendar_year == source.utc_calendar_year
    return candidate.utc_calendar_quarter == source.utc_calendar_quarter


def _ordered(
    namespace: str,
    source_id: str,
    candidates: Iterable[PlaceboCandidate],
) -> list[PlaceboCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            hashlib.sha256(
                (
                    f"{namespace}|{source_id}|{candidate.control_candidate_id}|{PLACEBO_SEED}"
                ).encode()
            ).hexdigest(),
            candidate.control_candidate_id,
        ),
    )


def _eligible_at_level(
    source: PlaceboEventReference | PlaceboCandidate,
    candidates: Iterable[PlaceboCandidate],
    *,
    level: str,
    excluded_ids: set[str],
    excluded_span: tuple[int, int],
) -> list[PlaceboCandidate]:
    return [
        candidate
        for candidate in candidates
        if candidate.control_candidate_id not in excluded_ids
        and _exact(source, candidate)
        and _level(source, candidate, level)
        and not overlaps(
            candidate.information_span_start_ns,
            candidate.information_span_end_ns,
            excluded_span[0],
            excluded_span[1],
        )
    ]


def select_placebo(
    source: PlaceboEventReference,
    candidates: tuple[PlaceboCandidate, ...],
    *,
    used_placebo_event_ids: set[str],
) -> BlindPlaceboSelection:
    """Select one fake event and then five controls without outcome access."""

    by_id: dict[str, PlaceboCandidate] = {}
    for candidate in candidates:
        existing = by_id.setdefault(candidate.control_candidate_id, candidate)
        if existing != candidate:
            raise ValueError("control_candidate_id maps to conflicting payloads")
    unique = tuple(by_id[key] for key in sorted(by_id))
    original = set(source.original_control_candidate_ids)
    fake_event: PlaceboCandidate | None = None
    fake_level = "L5"
    for level in RELAXATION_LEVELS:
        eligible = _eligible_at_level(
            source,
            unique,
            level=level,
            excluded_ids=original | used_placebo_event_ids,
            excluded_span=(source.information_span_start_ns, source.information_span_end_ns),
        )
        if eligible:
            fake_event = _ordered(
                PLACEBO_EVENT_NAMESPACE,
                source.source_episode_id,
                eligible,
            )[0]
            fake_level = level
            break
    if fake_event is None:
        return BlindPlaceboSelection.seal(
            {
                "source_episode_id": source.source_episode_id,
                "source_h2_path_hash": source.source_h2_path_hash,
                "instrument": source.instrument,
                "pre_registered_period": source.pre_registered_period,
                "evaluation_fold": source.evaluation_fold,
                "parameter_set_id": source.parameter_set_id,
                "time_combination_id": source.time_combination_id,
                "status": "UNMATCHED_NO_PLACEBO_EVENT",
                "placebo_event_candidate_id": None,
                "placebo_event_match_level": "L5",
                "placebo_control_match_level": "L5",
                "placebo_control_candidate_ids": (),
            }
        )
    used_placebo_event_ids.add(fake_event.control_candidate_id)
    control_level = "L5"
    selected_controls: tuple[PlaceboCandidate, ...] = ()
    control_excluded = original | {fake_event.control_candidate_id}
    for level in RELAXATION_LEVELS:
        eligible = _eligible_at_level(
            fake_event,
            unique,
            level=level,
            excluded_ids=control_excluded,
            excluded_span=(
                fake_event.information_span_start_ns,
                fake_event.information_span_end_ns,
            ),
        )
        ordered = _ordered(
            PLACEBO_CONTROL_NAMESPACE,
            fake_event.control_candidate_id,
            eligible,
        )
        if len(ordered) >= 5:
            selected_controls = tuple(ordered[:5])
            control_level = level
            break
    status = "MATCHED" if selected_controls else "UNMATCHED_CONTROLS"
    return BlindPlaceboSelection.seal(
        {
            "source_episode_id": source.source_episode_id,
            "source_h2_path_hash": source.source_h2_path_hash,
            "instrument": source.instrument,
            "pre_registered_period": source.pre_registered_period,
            "evaluation_fold": source.evaluation_fold,
            "parameter_set_id": source.parameter_set_id,
            "time_combination_id": source.time_combination_id,
            "status": status,
            "placebo_event_candidate_id": fake_event.control_candidate_id,
            "placebo_event_match_level": fake_level,
            "placebo_control_match_level": control_level,
            "placebo_control_candidate_ids": tuple(
                candidate.control_candidate_id for candidate in selected_controls
            ),
        }
    )
