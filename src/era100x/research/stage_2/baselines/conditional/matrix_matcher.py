"""Outcome-blind matching and later H2 matrix attachment for S2-T15 v1.4."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .v14_contracts import (
    COMBINATION_ORDER,
    CONTROLS_PER_EPISODE,
    MATCHING_SEED,
    ConditionalBaselineMatchMatrix,
    ControlOutcomeMatrix,
    MatchLevel,
    OutcomeCell,
    V14ControlCandidate,
    V14PrimaryEpisode,
)


def _overlaps(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start < right_end and right_start < left_end


def _exact_match(episode: V14PrimaryEpisode, candidate: V14ControlCandidate) -> bool:
    return (
        candidate.instrument == episode.instrument
        and candidate.direction == episode.direction
        and candidate.setup_id == episode.setup_id
        and candidate.context_model_id == episode.context_model_id
        and candidate.high_timeframe_trend_state == episode.high_timeframe_trend_state
        and candidate.pre_registered_period == episode.pre_registered_period
        and candidate.evaluation_fold == episode.evaluation_fold
        and candidate.parameter_set_id == episode.parameter_set_id
        and candidate.time_combination_id == episode.time_combination_id
        and candidate.label_contract_hash == episode.label_contract_hash
        and candidate.key_level_distance_quintile == episode.key_level_distance_quintile
        and candidate.binning_snapshot_hash == episode.binning_snapshot_hash
        and not candidate.is_registered_same_family_event
        and not _overlaps(
            candidate.information_span_start_ns,
            candidate.information_span_end_ns,
            episode.information_span_start_ns,
            episode.information_span_end_ns,
        )
    )


def _level_match(
    episode: V14PrimaryEpisode, candidate: V14ControlCandidate, level: MatchLevel
) -> bool:
    if level == "L5":
        return False
    activity_tolerance = 0 if level == "L0" else 1
    volatility_tolerance = 0 if level in {"L0", "L1"} else 1
    if abs(candidate.activity_quintile - episode.activity_quintile) > activity_tolerance:
        return False
    if abs(candidate.volatility_quintile - episode.volatility_quintile) > volatility_tolerance:
        return False
    bucket_delta = (candidate.utc_four_hour_bucket - episode.utc_four_hour_bucket) % 6
    if level in {"L0", "L1", "L2"}:
        if bucket_delta != 0:
            return False
    elif bucket_delta not in {0, 1, 5}:
        return False
    if level == "L4":
        return candidate.utc_calendar_year == episode.utc_calendar_year
    return candidate.utc_calendar_quarter == episode.utc_calendar_quarter


@dataclass(frozen=True, slots=True)
class OutcomeBlindSelection:
    """The only object allowed to authorize subsequent H2 outcome reads."""

    market_episode_id: str
    source_h2_path_hash: str
    parameter_set_id: str
    time_combination_id: str
    match_level: MatchLevel
    control_candidate_ids: tuple[str, ...]

    @property
    def status(self) -> str:
        return "MATCHED" if self.control_candidate_ids else "UNMATCHED"


def select_outcome_blind_controls(
    episode: V14PrimaryEpisode,
    candidates: tuple[V14ControlCandidate, ...],
) -> OutcomeBlindSelection:
    """Select five controls without accepting or reading any outcome fields."""

    candidate_ids = tuple(candidate.control_candidate_id for candidate in candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("duplicate control_candidate_id")
    structural = tuple(candidate for candidate in candidates if _exact_match(episode, candidate))
    chosen_level: MatchLevel = "L5"
    selected: tuple[V14ControlCandidate, ...] = ()
    for level in ("L0", "L1", "L2", "L3", "L4"):
        matches = tuple(
            candidate for candidate in structural if _level_match(episode, candidate, level)
        )
        if len(matches) < CONTROLS_PER_EPISODE:
            continue
        chosen_level = level
        selected = tuple(
            sorted(
                matches,
                key=lambda candidate: (
                    hashlib.sha256(
                        (
                            f"{episode.market_episode_id}|{candidate.candidate_timestamp_ns}|"
                            f"{MATCHING_SEED}"
                        ).encode()
                    ).hexdigest(),
                    candidate.control_candidate_id,
                ),
            )[:CONTROLS_PER_EPISODE]
        )
        break
    return OutcomeBlindSelection(
        market_episode_id=episode.market_episode_id,
        source_h2_path_hash=episode.source_h2_path_hash,
        parameter_set_id=episode.parameter_set_id,
        time_combination_id=episode.time_combination_id,
        match_level=chosen_level,
        control_candidate_ids=tuple(candidate.control_candidate_id for candidate in selected),
    )


def attach_outcome_matrices(
    selection: OutcomeBlindSelection,
    *,
    event_outcomes: tuple[OutcomeCell, ...],
    control_matrices: tuple[ControlOutcomeMatrix, ...],
) -> ConditionalBaselineMatchMatrix:
    """Attach exactly the outcomes authorized by a completed blind selection."""

    if (
        len(event_outcomes) != 30
        or tuple(cell.combination_id for cell in event_outcomes) != COMBINATION_ORDER
    ):
        raise ValueError("event outcome matrix must contain the frozen 30 cells")
    if selection.status == "UNMATCHED":
        if control_matrices:
            raise ValueError("UNMATCHED selection cannot read control outcomes")
    else:
        matrix_ids = tuple(matrix.control_candidate_id for matrix in control_matrices)
        if matrix_ids != selection.control_candidate_ids:
            raise ValueError("outcomes must match the five preselected controls in order")
        if any(
            matrix.time_combination_id != selection.time_combination_id
            for matrix in control_matrices
        ):
            raise ValueError("control outcome timing changed after matching")
    return ConditionalBaselineMatchMatrix.seal(
        {
            "market_episode_id": selection.market_episode_id,
            "source_h2_path_hash": selection.source_h2_path_hash,
            "parameter_set_id": selection.parameter_set_id,
            "time_combination_id": selection.time_combination_id,
            "status": selection.status,
            "match_level": selection.match_level,
            "control_candidate_ids": selection.control_candidate_ids,
            "event_outcomes": event_outcomes,
            "control_outcome_matrix_ids": tuple(
                matrix.control_outcome_matrix_id for matrix in control_matrices
            ),
            "historical_evidence_only": True,
        }
    )
