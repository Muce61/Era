"""Strict contracts for S2-T14 historical ambiguity evidence."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.contracts.models import Instrument, StrictEventModel
from era100x.research.stage_2.labels.first_passage.models import (
    FirstPassageLabel,
    LabelReason,
    ResolvedFirstPassageLabel,
)
from era100x.research.stage_2.paths.extraction.models import _canonical_json

SHA256_PATTERN = r"^[0-9a-f]{64}$"
EvidenceLevel = Literal["H1", "H2"]
TimingId = Literal["T1", "T2", "T3", "T4"]
AmbiguityProhibitedInterpretation = Literal[
    "PNL",
    "RETURN",
    "REAL_RETURN",
    "ROUND_SUCCESS",
    "LIVE_EXECUTION",
    "RAW_LABEL_RECLASSIFICATION",
    "AMBIGUITY_DELETION",
]

PROHIBITED_INTERPRETATIONS: tuple[AmbiguityProhibitedInterpretation, ...] = (
    "PNL",
    "RETURN",
    "REAL_RETURN",
    "ROUND_SUCCESS",
    "LIVE_EXECUTION",
    "RAW_LABEL_RECLASSIFICATION",
    "AMBIGUITY_DELETION",
)


class HistoricalAmbiguityBounds(StrictEventModel):
    """Bounds derived from one immutable S2-T13 first-passage classification."""

    schema_name: Literal["stage2-historical-ambiguity-bounds"] = (
        "stage2-historical-ambiguity-bounds"
    )
    schema_version: Literal["1.0"] = "1.0"
    task_id: Literal["S2-T14"] = "S2-T14"
    task_version: Literal["1.2"] = "1.2"
    instrument: Instrument
    market_episode_id: str = Field(pattern=SHA256_PATTERN)
    canonical_candidate_id: str = Field(pattern=SHA256_PATTERN)
    candidate_version_id: str = Field(pattern=SHA256_PATTERN)
    canonical_payload_hash: str = Field(pattern=SHA256_PATTERN)
    parameter_set_id: str = Field(min_length=1)
    evidence_level: EvidenceLevel
    target_bps: Decimal = Field(gt=0)
    stop_bps: Decimal = Field(gt=0)
    timing_id: TimingId
    raw_label: FirstPassageLabel
    raw_label_reason: LabelReason
    raw_ambiguous_preserved: bool
    primary_ambiguous_policy: Literal["FAILURE"] = "FAILURE"
    primary_target_first: Literal[0, 1]
    conditional_target_first: Literal[0, 1] | None
    theoretical_lower_target_first: Literal[0, 1]
    theoretical_upper_target_first: Literal[0, 1]
    pessimistic_path_label: ResolvedFirstPassageLabel | None = None
    optimistic_path_label: ResolvedFirstPassageLabel | None = None
    excluded_from_conditional: bool
    historical_evidence_only: Literal[True] = True
    prohibited_interpretations: tuple[AmbiguityProhibitedInterpretation, ...] = (
        PROHIBITED_INTERPRETATIONS
    )
    source_first_passage_hash: str = Field(pattern=SHA256_PATTERN)
    output_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"output_hash"})
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        determinate_reasons = {
            "TARGET_FIRST": "TARGET_OBSERVED_FIRST",
            "STOP_FIRST": "STOP_OBSERVED_FIRST",
            "EXPIRED": "HORIZON_EXPIRED_WITHOUT_TOUCH",
        }
        if (
            self.raw_label != "AMBIGUOUS"
            and self.raw_label_reason != determinate_reasons[self.raw_label]
        ):
            raise ValueError("raw determinate label and reason disagree")
        if self.raw_label == "AMBIGUOUS" and self.raw_label_reason in determinate_reasons.values():
            raise ValueError("raw AMBIGUOUS label cannot use a determinate reason")
        if self.raw_label == "AMBIGUOUS":
            if not self.raw_ambiguous_preserved:
                raise ValueError("AMBIGUOUS raw label must remain preserved")
            if (
                self.primary_target_first != 0
                or self.conditional_target_first is not None
                or self.theoretical_lower_target_first != 0
                or self.theoretical_upper_target_first != 1
                or not self.excluded_from_conditional
            ):
                raise ValueError("AMBIGUOUS bounds must be failure/excluded/theoretical-success")
            if self.raw_label_reason == "H1_SAME_EVENT_TARGET_AND_STOP":
                if (
                    self.evidence_level != "H1"
                    or self.pessimistic_path_label != "STOP_FIRST"
                    or self.optimistic_path_label != "TARGET_FIRST"
                ):
                    raise ValueError("H1 same-event ambiguity requires adverse/optimistic bounds")
            elif self.pessimistic_path_label is not None or self.optimistic_path_label is not None:
                raise ValueError("unresolved source ambiguity cannot invent path labels")
        else:
            expected = 1 if self.raw_label == "TARGET_FIRST" else 0
            if self.raw_ambiguous_preserved or self.excluded_from_conditional:
                raise ValueError("determinate labels cannot be marked ambiguous")
            if (
                self.primary_target_first != expected
                or self.conditional_target_first != expected
                or self.theoretical_lower_target_first != expected
                or self.theoretical_upper_target_first != expected
                or self.pessimistic_path_label != self.raw_label
                or self.optimistic_path_label != self.raw_label
            ):
                raise ValueError("determinate labels must collapse to one identical bound")
        if self.output_hash != "0" * 64 and self.output_hash != self.computed_hash():
            raise ValueError("ambiguity bounds output_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "output_hash": "0" * 64})
        return provisional.model_copy(update={"output_hash": provisional.computed_hash()})


class HistoricalAmbiguityDistribution(StrictEventModel):
    """Deterministic distribution for one BTC/ETH, H1/H2 and parameter slice."""

    schema_name: Literal["stage2-historical-ambiguity-distribution"] = (
        "stage2-historical-ambiguity-distribution"
    )
    schema_version: Literal["1.0"] = "1.0"
    task_id: Literal["S2-T14"] = "S2-T14"
    task_version: Literal["1.2"] = "1.2"
    instrument: Instrument
    evidence_level: EvidenceLevel
    parameter_set_id: str = Field(min_length=1)
    target_bps: Decimal = Field(gt=0)
    stop_bps: Decimal = Field(gt=0)
    timing_id: TimingId
    total_count: int = Field(gt=0)
    target_first_count: int = Field(ge=0)
    stop_first_count: int = Field(ge=0)
    expired_count: int = Field(ge=0)
    ambiguous_count: int = Field(ge=0)
    conditional_denominator: int = Field(ge=0)
    primary_target_first_rate: Decimal = Field(ge=0, le=1)
    conditional_target_first_rate: Decimal | None = Field(default=None, ge=0, le=1)
    theoretical_lower_target_first_rate: Decimal = Field(ge=0, le=1)
    theoretical_upper_target_first_rate: Decimal = Field(ge=0, le=1)
    source_bounds_hashes: tuple[str, ...]
    historical_evidence_only: Literal[True] = True
    prohibited_interpretations: tuple[AmbiguityProhibitedInterpretation, ...] = (
        PROHIBITED_INTERPRETATIONS
    )
    output_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"output_hash"})
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_distribution(self) -> Self:
        counts = (
            self.target_first_count,
            self.stop_first_count,
            self.expired_count,
            self.ambiguous_count,
        )
        if sum(counts) != self.total_count:
            raise ValueError("ambiguity distribution counts do not sum to total")
        if self.conditional_denominator != self.total_count - self.ambiguous_count:
            raise ValueError("conditional denominator must exclude AMBIGUOUS")
        total = Decimal(self.total_count)
        expected_primary = Decimal(self.target_first_count) / total
        expected_upper = Decimal(self.target_first_count + self.ambiguous_count) / total
        expected_conditional = (
            None
            if self.conditional_denominator == 0
            else Decimal(self.target_first_count) / Decimal(self.conditional_denominator)
        )
        if (
            self.primary_target_first_rate != expected_primary
            or self.theoretical_lower_target_first_rate != expected_primary
            or self.theoretical_upper_target_first_rate != expected_upper
            or self.conditional_target_first_rate != expected_conditional
        ):
            raise ValueError("ambiguity distribution rates disagree with raw counts")
        if self.source_bounds_hashes != tuple(sorted(set(self.source_bounds_hashes))):
            raise ValueError("source bounds hashes must be unique and stably sorted")
        if len(self.source_bounds_hashes) != self.total_count:
            raise ValueError("source bounds hash count must equal total")
        if self.output_hash != "0" * 64 and self.output_hash != self.computed_hash():
            raise ValueError("ambiguity distribution output_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "output_hash": "0" * 64})
        return provisional.model_copy(update={"output_hash": provisional.computed_hash()})
