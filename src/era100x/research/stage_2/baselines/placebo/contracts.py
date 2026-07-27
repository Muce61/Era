"""Frozen contracts for S2P14-T17 historical placebo evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.baselines.conditional.v14_contracts import (
    COMBINATION_ORDER,
    CONTROLS_PER_EPISODE,
    MatchLevel,
    OutcomeCell,
)
from era100x.research.stage_2.contracts.models import (
    Direction,
    Instrument,
    StrictEventModel,
)
from era100x.research.stage_2.paths.extraction.models import _canonical_json

SHA256_PATTERN = r"^[0-9a-f]{64}$"
GIT_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
TASK_ID = "S2P14-T17"
TASK_VERSION = "1.0"
PLAN_VERSION = "1.4"
PLACEBO_SEED = 20260716
PLACEBO_EVENT_NAMESPACE = "S2P14T17|PLACEBO_EVENT"
PLACEBO_CONTROL_NAMESPACE = "S2P14T17|PLACEBO_CONTROL"
RELAXATION_LEVELS: tuple[MatchLevel, ...] = ("L0", "L1", "L2", "L3", "L4")
RESEARCH_STATUS = "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING"
PROHIBITED_INTERPRETATIONS: tuple[str, ...] = (
    "PNL",
    "RETURN",
    "REAL_RETURN",
    "ROUND_SUCCESS",
    "CONFIDENCE_INTERVAL",
    "STAGE2_PRIMARY_PASS",
    "LIVE_EXECUTION",
)


def canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_json(payload: object) -> str:
    return _canonical_json(payload)


class PlaceboCandidate(StrictEventModel):
    control_candidate_id: str = Field(pattern=SHA256_PATTERN)
    control_anchor_id: str = Field(pattern=SHA256_PATTERN)
    instrument: Instrument
    candidate_timestamp_ns: int = Field(ge=0)
    direction: Direction = "LONG"
    setup_id: str = Field(min_length=1)
    context_model_id: str = Field(min_length=1)
    high_timeframe_trend_state: str = Field(min_length=1)
    pre_registered_period: Literal["P1", "P2", "P3"]
    evaluation_fold: Literal["F0", "F1", "F2", "F3"]
    parameter_set_id: str = Field(min_length=1)
    time_combination_id: Literal["T1", "T2", "T3", "T4"]
    label_contract_hash: str = Field(pattern=SHA256_PATTERN)
    volatility_quintile: int = Field(ge=1, le=5)
    activity_quintile: int = Field(ge=1, le=5)
    key_level_distance_quintile: int = Field(ge=1, le=5)
    utc_four_hour_bucket: int = Field(ge=0, le=5)
    utc_calendar_quarter: int = Field(ge=1, le=4)
    utc_calendar_year: int = Field(ge=2020, le=2026)
    binning_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    information_span_start_ns: int = Field(ge=0)
    information_span_end_ns: int = Field(gt=0)
    is_registered_same_family_event: bool = False

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.information_span_start_ns >= self.information_span_end_ns:
            raise ValueError("placebo candidate information span is empty")
        return self

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python")


class PlaceboEventReference(StrictEventModel):
    source_episode_id: str = Field(pattern=SHA256_PATTERN)
    source_h2_path_hash: str = Field(pattern=SHA256_PATTERN)
    instrument: Instrument
    anchor_ns: int = Field(ge=0)
    direction: Direction = "LONG"
    setup_id: str = Field(min_length=1)
    context_model_id: str = Field(min_length=1)
    high_timeframe_trend_state: str = Field(min_length=1)
    pre_registered_period: Literal["P1", "P2", "P3"]
    evaluation_fold: Literal["F0", "F1", "F2", "F3"]
    parameter_set_id: str = Field(min_length=1)
    time_combination_id: Literal["T1", "T2", "T3", "T4"]
    label_contract_hash: str = Field(pattern=SHA256_PATTERN)
    volatility_quintile: int = Field(ge=1, le=5)
    activity_quintile: int = Field(ge=1, le=5)
    key_level_distance_quintile: int = Field(ge=1, le=5)
    utc_four_hour_bucket: int = Field(ge=0, le=5)
    utc_calendar_quarter: int = Field(ge=1, le=4)
    utc_calendar_year: int = Field(ge=2020, le=2026)
    binning_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    information_span_start_ns: int = Field(ge=0)
    information_span_end_ns: int = Field(gt=0)
    original_control_candidate_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_original_controls(self) -> Self:
        if (
            len(self.original_control_candidate_ids) != CONTROLS_PER_EPISODE
            or len(set(self.original_control_candidate_ids)) != CONTROLS_PER_EPISODE
        ):
            raise ValueError("source matched event must bind five unique original controls")
        if self.information_span_start_ns >= self.information_span_end_ns:
            raise ValueError("source event information span is empty")
        return self


class BlindPlaceboSelection(StrictEventModel):
    schema_name: Literal["s2p14-t17-blind-placebo-selection"] = "s2p14-t17-blind-placebo-selection"
    source_episode_id: str = Field(pattern=SHA256_PATTERN)
    source_h2_path_hash: str = Field(pattern=SHA256_PATTERN)
    instrument: Instrument
    pre_registered_period: Literal["P1", "P2", "P3"]
    evaluation_fold: Literal["F0", "F1", "F2", "F3"]
    parameter_set_id: str = Field(min_length=1)
    time_combination_id: Literal["T1", "T2", "T3", "T4"]
    status: Literal[
        "MATCHED",
        "UNMATCHED_NO_PLACEBO_EVENT",
        "UNMATCHED_CONTROLS",
    ]
    placebo_event_candidate_id: str | None = None
    placebo_event_match_level: MatchLevel
    placebo_control_match_level: MatchLevel
    placebo_control_candidate_ids: tuple[str, ...]
    selection_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"selection_hash"}))

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.status == "MATCHED":
            if self.placebo_event_candidate_id is None:
                raise ValueError("matched placebo requires a fake event")
            if self.placebo_event_match_level == "L5" or self.placebo_control_match_level == "L5":
                raise ValueError("matched placebo cannot use L5")
            if (
                len(self.placebo_control_candidate_ids) != CONTROLS_PER_EPISODE
                or len(set(self.placebo_control_candidate_ids)) != CONTROLS_PER_EPISODE
            ):
                raise ValueError("matched placebo requires five unique controls")
        elif self.status == "UNMATCHED_NO_PLACEBO_EVENT":
            if (
                self.placebo_event_candidate_id is not None
                or self.placebo_event_match_level != "L5"
                or self.placebo_control_match_level != "L5"
                or self.placebo_control_candidate_ids
            ):
                raise ValueError("no-event unmatched selection must be empty L5")
        elif (
            self.placebo_event_candidate_id is None
            or self.placebo_event_match_level == "L5"
            or self.placebo_control_match_level != "L5"
            or self.placebo_control_candidate_ids
        ):
            raise ValueError("control-shortage selection must preserve the chosen fake event")
        if self.selection_hash != "0" * 64 and self.selection_hash != self.computed_hash():
            raise ValueError("blind placebo selection hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "selection_hash": "0" * 64})
        return provisional.model_copy(update={"selection_hash": provisional.computed_hash()})


class S2P14T17Authority(StrictEventModel):
    schema_name: Literal["s2p14-t17-authority"] = "s2p14-t17-authority"
    schema_version: Literal["1.0"] = "1.0"
    task_id: Literal["S2P14-T17"] = "S2P14-T17"
    task_version: Literal["1.0"] = "1.0"
    stage_plan_version: Literal["1.4"] = "1.4"
    code_commit: str = Field(pattern=GIT_COMMIT_PATTERN)
    policy_hash: str = Field(pattern=SHA256_PATTERN)
    approval_hash: str = Field(pattern=SHA256_PATTERN)
    preregistration_hash: str = Field(pattern=SHA256_PATTERN)
    source_t16_receipt_hash: str = Field(pattern=SHA256_PATTERN)
    source_t16_authority_hash: str = Field(pattern=SHA256_PATTERN)
    source_t16_binning_hash: str = Field(pattern=SHA256_PATTERN)
    source_t16_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    source_t16_catalog_hash: str = Field(pattern=SHA256_PATTERN)
    source_t16_snapshot_id: str = Field(pattern=SHA256_PATTERN)
    source_t16_verify_hash: str = Field(pattern=SHA256_PATTERN)
    source_counts_hash: str = Field(pattern=SHA256_PATTERN)
    placebo_seed: Literal[20260716] = 20260716
    exact_fields: tuple[str, ...]
    relaxation_order: tuple[Literal["L0", "L1", "L2", "L3", "L4"], ...]
    selection_must_be_outcome_blind: Literal[True] = True
    historical_evidence_only: Literal[True] = True
    stage3_locked: Literal[True] = True
    authority_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"authority_hash"}))

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if self.relaxation_order != RELAXATION_LEVELS:
            raise ValueError("placebo relaxation order drift")
        if self.authority_hash != "0" * 64 and self.authority_hash != self.computed_hash():
            raise ValueError("placebo authority hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "authority_hash": "0" * 64})
        return provisional.model_copy(update={"authority_hash": provisional.computed_hash()})


class PlaceboMatchMatrix(StrictEventModel):
    schema_name: Literal["s2p14-t17-placebo-match-matrix"] = "s2p14-t17-placebo-match-matrix"
    source_episode_id: str = Field(pattern=SHA256_PATTERN)
    source_real_matrix_hash: str = Field(pattern=SHA256_PATTERN)
    selection_hash: str = Field(pattern=SHA256_PATTERN)
    status: Literal[
        "MATCHED",
        "UNMATCHED_NO_PLACEBO_EVENT",
        "UNMATCHED_CONTROLS",
    ]
    placebo_event_candidate_id: str | None = None
    placebo_event_outcome_matrix_id: str | None = None
    placebo_event_outcomes: tuple[OutcomeCell, ...] = ()
    placebo_control_candidate_ids: tuple[str, ...] = ()
    placebo_control_outcome_matrix_ids: tuple[str, ...] = ()
    placebo_control_outcomes: tuple[tuple[OutcomeCell, ...], ...] = ()
    real_event_outcomes: tuple[OutcomeCell, ...]
    real_control_outcomes: tuple[tuple[OutcomeCell, ...], ...]
    historical_evidence_only: Literal[True] = True
    prohibited_interpretations: tuple[str, ...] = PROHIBITED_INTERPRETATIONS
    output_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"output_hash"}))

    @model_validator(mode="after")
    def validate_matrix(self) -> Self:
        def valid(cells: tuple[OutcomeCell, ...]) -> bool:
            return (
                len(cells) == len(COMBINATION_ORDER)
                and tuple(cell.combination_id for cell in cells) == COMBINATION_ORDER
            )

        if not valid(self.real_event_outcomes) or len(self.real_control_outcomes) != 5:
            raise ValueError("real T16 outcome binding is incomplete")
        if any(not valid(cells) for cells in self.real_control_outcomes):
            raise ValueError("real T16 control outcome order drift")
        if self.status == "MATCHED":
            if (
                self.placebo_event_candidate_id is None
                or self.placebo_event_outcome_matrix_id is None
                or not valid(self.placebo_event_outcomes)
                or len(self.placebo_control_candidate_ids) != 5
                or len(set(self.placebo_control_candidate_ids)) != 5
                or len(self.placebo_control_outcome_matrix_ids) != 5
                or len(self.placebo_control_outcomes) != 5
                or any(not valid(cells) for cells in self.placebo_control_outcomes)
            ):
                raise ValueError("matched placebo outcome matrix is incomplete")
        elif (
            self.placebo_event_outcomes
            or self.placebo_control_candidate_ids
            or self.placebo_control_outcome_matrix_ids
            or self.placebo_control_outcomes
        ):
            raise ValueError("unmatched placebo cannot attach placebo outcomes")
        if self.output_hash != "0" * 64 and self.output_hash != self.computed_hash():
            raise ValueError("placebo matrix hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "output_hash": "0" * 64})
        return provisional.model_copy(update={"output_hash": provisional.computed_hash()})


class PlaceboSummary(StrictEventModel):
    instrument: Instrument
    pre_registered_period: Literal["P1", "P2", "P3"]
    evaluation_fold: Literal["F0", "F1", "F2", "F3"]
    parameter_set_id: str
    time_combination_id: Literal["T1", "T2", "T3", "T4"]
    combination_id: str
    slot_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    unmatched_count: int = Field(ge=0)
    placebo_event_rate: str | None
    placebo_baseline_rate: str | None
    placebo_delta: str | None
    real_event_delta: str | None
    placebo_minus_real_delta: str | None
    research_status: Literal["DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING"] = (
        "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING"
    )

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        if self.matched_count + self.unmatched_count != self.slot_count:
            raise ValueError("placebo summary slot reconciliation failed")
        return self


def parse_outcome_cells(value: str) -> tuple[OutcomeCell, ...]:
    payload = json.loads(value)
    if not isinstance(payload, list):
        raise ValueError("outcome payload must be a list")
    cells = tuple(OutcomeCell.model_validate(item) for item in payload)
    if (
        len(cells) != len(COMBINATION_ORDER)
        or tuple(cell.combination_id for cell in cells) != COMBINATION_ORDER
    ):
        raise ValueError("outcome payload combination order drift")
    return cells
