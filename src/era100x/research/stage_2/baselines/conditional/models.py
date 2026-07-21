"""Strict historical-only contracts for S2-T15 conditional matching."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.contracts.models import Direction, Instrument, StrictEventModel
from era100x.research.stage_2.paths.extraction.models import _canonical_json

SHA256_PATTERN = r"^[0-9a-f]{64}$"
PeriodId = Literal["P1", "P2", "P3"]
MatchLevel = Literal["L0", "L1", "L2", "L3", "L4", "L5"]
FourHourBucket = Literal["B0", "B1", "B2", "B3", "B4", "B5"]
HistoricalLabel = Literal["TARGET_FIRST", "STOP_FIRST", "EXPIRED", "AMBIGUOUS"]
QuintileKind = Literal["VOLATILITY", "TRADES_ACTIVITY"]
ConditionalProhibitedInterpretation = Literal[
    "PNL",
    "RETURN",
    "REAL_RETURN",
    "ROUND_SUCCESS",
    "LIVE_EXECUTION",
    "CROSS_INSTRUMENT_MATCHING",
    "POST_RESULT_RELAXATION",
]

PROHIBITED_INTERPRETATIONS: tuple[ConditionalProhibitedInterpretation, ...] = (
    "PNL",
    "RETURN",
    "REAL_RETURN",
    "ROUND_SUCCESS",
    "LIVE_EXECUTION",
    "CROSS_INSTRUMENT_MATCHING",
    "POST_RESULT_RELAXATION",
)

EXACT_MATCH_FIELDS: tuple[str, ...] = (
    "instrument",
    "direction",
    "high_timeframe_trend_state",
    "pre_registered_period",
    "research_split_or_fold",
)
RELAXATION_ORDER: tuple[MatchLevel, ...] = ("L0", "L1", "L2", "L3", "L4", "L5")
PERIODS: tuple[tuple[PeriodId, int, int], ...] = (
    ("P1", 1_577_836_800_000_000_000, 1_640_995_200_000_000_000),
    ("P2", 1_640_995_200_000_000_000, 1_704_067_200_000_000_000),
    ("P3", 1_704_067_200_000_000_000, 1_783_123_200_000_000_000),
)


class ConditionalBaselineManifest(StrictEventModel):
    """Minimal immutable T19 snapshot required by the T15 fixture matcher."""

    schema_name: Literal["stage2-conditional-baseline-manifest-snapshot"] = (
        "stage2-conditional-baseline-manifest-snapshot"
    )
    task_id: Literal["S2-T15"] = "S2-T15"
    task_version: Literal["1.2"] = "1.2"
    source_preregistration_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    source_config_hash: str = Field(pattern=SHA256_PATTERN)
    time_semantics: Literal["UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"] = (
        "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"
    )
    exact_match_fields: tuple[str, ...] = EXACT_MATCH_FIELDS
    relaxation_order: tuple[MatchLevel, ...] = RELAXATION_ORDER
    periods: tuple[tuple[PeriodId, int, int], ...] = PERIODS
    controls_per_episode: Literal[5] = 5
    matching_seed: Literal[20260716] = 20260716
    ambiguous_primary_treatment: Literal["FAILURE"] = "FAILURE"
    primary_label: Literal["TARGET_FIRST_STRICT"] = "TARGET_FIRST_STRICT"
    historical_evidence_only: Literal[True] = True

    @model_validator(mode="after")
    def frozen_values_match_preregistration(self) -> Self:
        if self.exact_match_fields != EXACT_MATCH_FIELDS:
            raise ValueError("non-relaxable matching fields changed")
        if self.relaxation_order != RELAXATION_ORDER:
            raise ValueError("L0-L5 relaxation order changed")
        if self.periods != PERIODS:
            raise ValueError("preregistered period boundaries changed")
        return self


class FrozenQuintileBoundaries(StrictEventModel):
    """Training-only cut points frozen before validation or holdout matching."""

    boundary_kind: QuintileKind
    training_split_or_fold: str = Field(min_length=1)
    cut_points: tuple[Decimal, Decimal, Decimal, Decimal]
    training_sample_count: int = Field(ge=5)
    source_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    boundary_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"boundary_hash"})
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def assign(self, value: Decimal) -> int:
        """Apply the frozen left-closed quintile intervals deterministically."""

        return 1 + sum(value >= point for point in self.cut_points)

    @model_validator(mode="after")
    def validate_boundaries(self) -> Self:
        if any(
            right <= left for left, right in zip(self.cut_points, self.cut_points[1:], strict=False)
        ):
            raise ValueError("five valid bins require four strictly increasing cut points")
        if self.boundary_hash != "0" * 64 and self.boundary_hash != self.computed_hash():
            raise ValueError("quintile boundary hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "boundary_hash": "0" * 64})
        return provisional.model_copy(update={"boundary_hash": provisional.computed_hash()})


class MatchingRecord(StrictEventModel):
    instrument: Instrument
    direction: Direction = "LONG"
    setup_id: str = Field(min_length=1)
    context_model_id: str = Field(min_length=1)
    high_timeframe_trend_state: str = Field(min_length=1)
    pre_registered_period: PeriodId
    research_split_or_fold: str = Field(min_length=1)
    available_at_ns: int = Field(ge=0)
    utc_four_hour_bucket: FourHourBucket
    volatility_quintile: int = Field(ge=1, le=5)
    activity_quintile: int = Field(ge=1, le=5)
    utc_calendar_quarter: int = Field(ge=1, le=4)
    binning_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    historical_evidence_only: Literal[True] = True


class PrimaryEpisode(MatchingRecord):
    market_episode_id: str = Field(pattern=SHA256_PATTERN)
    event_window_start_ns: int = Field(ge=0)
    event_window_end_ns: int = Field(gt=0)
    purge_embargo_start_ns: int = Field(ge=0)
    purge_embargo_end_ns: int = Field(gt=0)
    raw_label: HistoricalLabel

    @model_validator(mode="after")
    def ordered_windows(self) -> Self:
        if self.event_window_end_ns <= self.event_window_start_ns:
            raise ValueError("event window must be non-empty")
        if self.purge_embargo_end_ns <= self.purge_embargo_start_ns:
            raise ValueError("purge/embargo window must be non-empty")
        if not (
            self.purge_embargo_start_ns <= self.event_window_start_ns
            and self.event_window_end_ns <= self.purge_embargo_end_ns
        ):
            raise ValueError("purge/embargo must contain the complete event window")
        return self


class ControlCandidate(MatchingRecord):
    control_id: str = Field(pattern=SHA256_PATTERN)
    candidate_timestamp_ns: int = Field(ge=0)
    window_start_ns: int = Field(ge=0)
    window_end_ns: int = Field(gt=0)
    is_registered_same_family_event: bool
    target_first_strict: Literal[0, 1]

    @model_validator(mode="after")
    def ordered_window(self) -> Self:
        if self.window_end_ns <= self.window_start_ns:
            raise ValueError("control window must be non-empty")
        if not self.window_start_ns <= self.candidate_timestamp_ns < self.window_end_ns:
            raise ValueError("candidate timestamp must lie inside its left-closed window")
        return self


class ConditionalBaselineMatch(StrictEventModel):
    schema_name: Literal["stage2-historical-conditional-baseline-match"] = (
        "stage2-historical-conditional-baseline-match"
    )
    task_id: Literal["S2-T15"] = "S2-T15"
    task_version: Literal["1.2"] = "1.2"
    instrument: Instrument
    setup_id: str
    context_model_id: str
    pre_registered_period: PeriodId
    research_split_or_fold: str
    market_episode_id: str = Field(pattern=SHA256_PATTERN)
    raw_label: HistoricalLabel
    primary_target_first: Literal[0, 1]
    status: Literal["MATCHED", "UNMATCHED"]
    event_match_level: MatchLevel
    control_ids: tuple[str, ...]
    control_target_first_values: tuple[Literal[0, 1], ...]
    episode_control_mean: Decimal | None = Field(default=None, ge=0, le=1)
    source_preregistration_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    historical_evidence_only: Literal[True] = True
    prohibited_interpretations: tuple[ConditionalProhibitedInterpretation, ...] = (
        PROHIBITED_INTERPRETATIONS
    )
    output_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"output_hash"})
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_match(self) -> Self:
        expected_primary = 1 if self.raw_label == "TARGET_FIRST" else 0
        if self.primary_target_first != expected_primary:
            raise ValueError("Primary must treat AMBIGUOUS and non-target labels as failure")
        if self.status == "MATCHED":
            if self.event_match_level == "L5":
                raise ValueError("MATCHED result cannot use L5")
            if len(self.control_ids) != 5 or len(set(self.control_ids)) != 5:
                raise ValueError("MATCHED result requires five unique controls")
            if len(self.control_target_first_values) != 5:
                raise ValueError("MATCHED result requires five control outcomes")
            expected_mean = Decimal(sum(self.control_target_first_values)) / Decimal(5)
            if self.episode_control_mean != expected_mean:
                raise ValueError("episode control mean must equally weight five controls")
        elif (
            self.event_match_level != "L5"
            or self.control_ids
            or self.control_target_first_values
            or self.episode_control_mean is not None
        ):
            raise ValueError("UNMATCHED result must be empty L5")
        if self.output_hash != "0" * 64 and self.output_hash != self.computed_hash():
            raise ValueError("conditional match output_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "output_hash": "0" * 64})
        return provisional.model_copy(update={"output_hash": provisional.computed_hash()})


class ConditionalBaselineSummary(StrictEventModel):
    schema_name: Literal["stage2-historical-conditional-baseline-summary"] = (
        "stage2-historical-conditional-baseline-summary"
    )
    task_id: Literal["S2-T15"] = "S2-T15"
    task_version: Literal["1.2"] = "1.2"
    instrument: Instrument
    setup_id: str
    context_model_id: str
    pre_registered_period: PeriodId
    research_split_or_fold: str
    eligible_episode_count: int = Field(gt=0)
    matched_episode_count: int = Field(ge=0)
    unmatched_episode_count: int = Field(ge=0)
    late_relaxation_count: int = Field(ge=0)
    control_assignment_count: int = Field(ge=0)
    unique_control_count: int = Field(ge=0)
    matching_coverage: Decimal = Field(ge=0, le=1)
    late_relaxation_share: Decimal | None = Field(default=None, ge=0, le=1)
    control_reuse_rate: Decimal | None = Field(default=None, ge=0, le=1)
    event_target_first_rate: Decimal | None = Field(default=None, ge=0, le=1)
    matched_baseline_target_first_rate: Decimal | None = Field(default=None, ge=0, le=1)
    delta_target_first: Decimal | None = Field(default=None, ge=-1, le=1)
    source_match_hashes: tuple[str, ...]
    source_preregistration_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    historical_evidence_only: Literal[True] = True
    prohibited_interpretations: tuple[ConditionalProhibitedInterpretation, ...] = (
        PROHIBITED_INTERPRETATIONS
    )
    output_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"output_hash"})
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.matched_episode_count + self.unmatched_episode_count != self.eligible_episode_count:
            raise ValueError("matched and unmatched counts must account for all episodes")
        if self.control_assignment_count != self.matched_episode_count * 5:
            raise ValueError("every matched episode must contribute exactly five controls")
        expected_coverage = Decimal(self.matched_episode_count) / Decimal(
            self.eligible_episode_count
        )
        if self.matching_coverage != expected_coverage:
            raise ValueError("matching coverage disagrees with counts")
        if self.source_match_hashes != tuple(sorted(set(self.source_match_hashes))):
            raise ValueError("source match hashes must be unique and sorted")
        if len(self.source_match_hashes) != self.eligible_episode_count:
            raise ValueError("one source match hash is required per eligible episode")
        if self.output_hash != "0" * 64 and self.output_hash != self.computed_hash():
            raise ValueError("conditional summary output_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "output_hash": "0" * 64})
        return provisional.model_copy(update={"output_hash": provisional.computed_hash()})
