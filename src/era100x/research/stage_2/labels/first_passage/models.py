"""Strict contracts for S2-T13 historical first-passage evidence."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.contracts.models import Instrument, StrictEventModel
from era100x.research.stage_2.paths.extraction.models import _canonical_json

SHA256_PATTERN = r"^[0-9a-f]{64}$"
BPS = Decimal("10000")
REGISTERED_TARGET_BPS = tuple(map(Decimal, ("20", "30", "40", "50", "70", "100")))
REGISTERED_STOP_BPS = tuple(map(Decimal, ("15", "20", "25", "30", "35")))
REGISTERED_HORIZONS_SECONDS: dict[str, int] = {"T1": 60, "T2": 180, "T3": 300, "T4": 600}
FirstPassageLabel = Literal["TARGET_FIRST", "STOP_FIRST", "EXPIRED", "AMBIGUOUS"]
ResolvedFirstPassageLabel = Literal["TARGET_FIRST", "STOP_FIRST", "EXPIRED"]
LabelReason = Literal[
    "TARGET_OBSERVED_FIRST",
    "STOP_OBSERVED_FIRST",
    "HORIZON_EXPIRED_WITHOUT_TOUCH",
    "H1_SAME_EVENT_TARGET_AND_STOP",
    "NO_OBSERVATIONS",
    "SOURCE_GAP_BEFORE_DECISION",
    "WINDOW_TRUNCATED_BEFORE_DECISION",
]
ProhibitedInterpretation = Literal[
    "PNL",
    "RETURN",
    "REAL_RETURN",
    "ROUND_SUCCESS",
    "LIVE_EXECUTION",
    "AMBIGUOUS_BOUNDS",
]

PROHIBITED_INTERPRETATIONS: tuple[ProhibitedInterpretation, ...] = (
    "PNL",
    "RETURN",
    "REAL_RETURN",
    "ROUND_SUCCESS",
    "LIVE_EXECUTION",
    "AMBIGUOUS_BOUNDS",
)


class HistoricalFirstPassageLabel(StrictEventModel):
    """One deterministic H1/H2 historical first-passage classification."""

    schema_name: Literal["stage2-historical-first-passage"] = "stage2-historical-first-passage"
    schema_version: Literal["1.0"] = "1.0"
    task_id: Literal["S2-T13"] = "S2-T13"
    task_version: Literal["1.2"] = "1.2"
    instrument: Instrument
    market_episode_id: str = Field(pattern=SHA256_PATTERN)
    canonical_candidate_id: str = Field(pattern=SHA256_PATTERN)
    candidate_version_id: str = Field(pattern=SHA256_PATTERN)
    canonical_payload_hash: str = Field(pattern=SHA256_PATTERN)
    parameter_set_id: str = Field(min_length=1)
    evidence_level: Literal["H1", "H2"]
    reference_price_type: Literal["CONTRACT", "TRADE"]
    reference_price: Decimal = Field(gt=0)
    target_bps: Decimal = Field(gt=0)
    stop_bps: Decimal = Field(gt=0)
    target_price: Decimal = Field(gt=0)
    stop_price: Decimal = Field(gt=0)
    timing_id: Literal["T1", "T2", "T3", "T4"]
    horizon_seconds: int = Field(gt=0)
    window_start_ns: int = Field(ge=0)
    requested_window_end_ns: int = Field(gt=0)
    source_window_end_ns: int = Field(gt=0)
    window_complete: bool
    observation_count: int = Field(ge=0)
    label: FirstPassageLabel
    label_reason: LabelReason
    conservative_main_label: ResolvedFirstPassageLabel | None = None
    target_touch_ts_event_ns: int | None = Field(default=None, ge=0)
    stop_touch_ts_event_ns: int | None = Field(default=None, ge=0)
    decision_ts_event_ns: int | None = Field(default=None, ge=0)
    time_to_decision_ns: int | None = Field(default=None, ge=0)
    strict_target_first: bool
    time_semantics: Literal["UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"] = (
        "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"
    )
    stable_order: tuple[str, ...]
    source_quality_status: Literal["COMPLETE", "WITH_GAPS", "AMBIGUOUS", "WITH_GAPS_AND_AMBIGUITY"]
    source_gap_codes: tuple[str, ...]
    source_ambiguity_codes: tuple[str, ...]
    historical_evidence_only: Literal[True] = True
    prohibited_interpretations: tuple[ProhibitedInterpretation, ...] = PROHIBITED_INTERPRETATIONS
    source_path_hash: str = Field(pattern=SHA256_PATTERN)
    output_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"output_hash"})
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_label(self) -> Self:
        expected_type = "CONTRACT" if self.evidence_level == "H1" else "TRADE"
        if self.reference_price_type != expected_type:
            raise ValueError("evidence level and reference price type disagree")
        expected_order = (
            ("ts_event_ns", "source_row_hash")
            if self.evidence_level == "H1"
            else ("ts_event_ns", "venue_trade_id", "canonical_trade_id")
        )
        if self.stable_order != expected_order:
            raise ValueError("evidence level and stable order disagree")
        if self.target_bps not in REGISTERED_TARGET_BPS or self.stop_bps not in REGISTERED_STOP_BPS:
            raise ValueError("first-passage threshold is outside the frozen preregistration")
        if self.horizon_seconds != REGISTERED_HORIZONS_SECONDS[self.timing_id]:
            raise ValueError("timing horizon is outside the frozen preregistration")
        if self.requested_window_end_ns != (
            self.window_start_ns + self.horizon_seconds * 1_000_000_000
        ):
            raise ValueError("requested window does not match the registered horizon")
        if self.window_complete != (self.source_window_end_ns >= self.requested_window_end_ns):
            raise ValueError("window_complete disagrees with the source window")
        expected_target = self.reference_price * (Decimal(1) + self.target_bps / BPS)
        expected_stop = self.reference_price * (Decimal(1) - self.stop_bps / BPS)
        if self.target_price != expected_target or self.stop_price != expected_stop:
            raise ValueError("LONG target/stop prices do not match the registered basis points")
        expected_strict = self.label == "TARGET_FIRST"
        if self.strict_target_first != expected_strict:
            raise ValueError("strict TARGET_FIRST flag disagrees with label")
        decision_present = self.decision_ts_event_ns is not None
        if decision_present != (self.time_to_decision_ns is not None):
            raise ValueError("decision timestamp and duration must be present together")
        if self.decision_ts_event_ns is not None:
            if not self.window_start_ns <= self.decision_ts_event_ns < self.requested_window_end_ns:
                raise ValueError("decision must be inside the left-closed right-open window")
            if self.time_to_decision_ns != self.decision_ts_event_ns - self.window_start_ns:
                raise ValueError("decision duration disagrees with event time")
        if self.label == "TARGET_FIRST":
            if self.label_reason != "TARGET_OBSERVED_FIRST":
                raise ValueError("TARGET_FIRST reason is invalid")
            if self.target_touch_ts_event_ns != self.decision_ts_event_ns:
                raise ValueError("TARGET_FIRST requires target decision evidence")
            if (
                self.stop_touch_ts_event_ns is not None
                and self.target_touch_ts_event_ns is not None
                and self.stop_touch_ts_event_ns <= self.target_touch_ts_event_ns
            ):
                raise ValueError("TARGET_FIRST cannot follow an observed stop")
            if self.conservative_main_label != "TARGET_FIRST":
                raise ValueError("TARGET_FIRST must retain its primary label")
        elif self.label == "STOP_FIRST":
            if self.label_reason != "STOP_OBSERVED_FIRST":
                raise ValueError("STOP_FIRST reason is invalid")
            if self.stop_touch_ts_event_ns != self.decision_ts_event_ns:
                raise ValueError("STOP_FIRST requires stop decision evidence")
            if (
                self.target_touch_ts_event_ns is not None
                and self.stop_touch_ts_event_ns is not None
                and self.target_touch_ts_event_ns <= self.stop_touch_ts_event_ns
            ):
                raise ValueError("STOP_FIRST cannot follow an observed target")
            if self.conservative_main_label != "STOP_FIRST":
                raise ValueError("STOP_FIRST must retain its primary label")
        elif self.label == "EXPIRED":
            if self.label_reason != "HORIZON_EXPIRED_WITHOUT_TOUCH":
                raise ValueError("EXPIRED reason is invalid")
            if (
                decision_present
                or not self.window_complete
                or self.observation_count == 0
                or self.target_touch_ts_event_ns is not None
                or self.stop_touch_ts_event_ns is not None
            ):
                raise ValueError("EXPIRED requires a complete observed horizon without a decision")
            if self.conservative_main_label != "EXPIRED":
                raise ValueError("EXPIRED must retain its primary label")
        elif self.label_reason == "H1_SAME_EVENT_TARGET_AND_STOP":
            if (
                self.evidence_level != "H1"
                or self.target_touch_ts_event_ns != self.decision_ts_event_ns
                or self.stop_touch_ts_event_ns != self.decision_ts_event_ns
                or self.conservative_main_label != "STOP_FIRST"
            ):
                raise ValueError("same-event H1 ambiguity must use adverse-first primary handling")
        else:
            if self.label_reason == "NO_OBSERVATIONS" and self.observation_count != 0:
                raise ValueError("NO_OBSERVATIONS cannot contain observations")
            if self.label_reason == "SOURCE_GAP_BEFORE_DECISION" and not self.source_gap_codes:
                raise ValueError("source-gap ambiguity requires a propagated gap code")
            if self.label_reason == "WINDOW_TRUNCATED_BEFORE_DECISION" and self.window_complete:
                raise ValueError("truncation ambiguity requires an incomplete window")
            if self.conservative_main_label is not None:
                raise ValueError("unresolved input ambiguity cannot invent a primary path label")
        if self.output_hash != "0" * 64 and self.output_hash != self.computed_hash():
            raise ValueError("first-passage output_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "output_hash": "0" * 64})
        return provisional.model_copy(update={"output_hash": provisional.computed_hash()})
