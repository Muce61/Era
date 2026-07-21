"""Strict contracts for S2-T12 historical price-only path metrics."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.contracts.models import Instrument, StrictEventModel
from era100x.research.stage_2.paths.extraction.models import _canonical_json

SHA256_PATTERN = r"^[0-9a-f]{64}$"
ACTIVATION_SEMANTICS: Literal[
    "HISTORICAL_PRICE_ONLY_FAVORABLE_THRESHOLD_PROXY_NOT_LIVE_PROTECTION"
] = "HISTORICAL_PRICE_ONLY_FAVORABLE_THRESHOLD_PROXY_NOT_LIVE_PROTECTION"


class ActivationTiming(StrictEventModel):
    """First historical observation to reach a price-only favorable threshold."""

    threshold_bps: Decimal = Field(gt=0)
    activated: bool
    first_activation_ts_event_ns: int | None = Field(default=None, ge=0)
    time_to_activation_ns: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def activation_fields_are_consistent(self) -> Self:
        present = self.first_activation_ts_event_ns is not None
        if present != (self.time_to_activation_ns is not None):
            raise ValueError("activation timestamp and duration must be present together")
        if self.activated != present:
            raise ValueError("activated flag disagrees with activation timing")
        return self


class HistoricalPathMetrics(StrictEventModel):
    """Deterministic MFE/MAE/timing evidence for one Episode and evidence level."""

    schema_name: Literal["stage2-historical-path-metrics"] = "stage2-historical-path-metrics"
    schema_version: Literal["1.0"] = "1.0"
    task_id: Literal["S2-T12"] = "S2-T12"
    task_version: Literal["1.3"] = "1.3"
    instrument: Instrument
    market_episode_id: str = Field(pattern=SHA256_PATTERN)
    canonical_candidate_id: str = Field(pattern=SHA256_PATTERN)
    candidate_version_id: str = Field(pattern=SHA256_PATTERN)
    canonical_payload_hash: str = Field(pattern=SHA256_PATTERN)
    parameter_set_id: str = Field(min_length=1)
    evidence_level: Literal["H1", "H2"]
    reference_price_type: Literal["CONTRACT", "TRADE"]
    reference_price: Decimal = Field(gt=0)
    window_start_ns: int = Field(ge=0)
    window_end_ns: int = Field(gt=0)
    window_truncated: bool
    time_semantics: Literal["UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"] = (
        "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"
    )
    observation_count: int = Field(ge=0)
    metric_status: Literal["COMPUTED", "NO_OBSERVATIONS"]
    mfe_bps: Decimal | None = None
    mae_bps: Decimal | None = None
    mfe_first_ts_event_ns: int | None = Field(default=None, ge=0)
    mae_first_ts_event_ns: int | None = Field(default=None, ge=0)
    last_observation_ts_event_ns: int | None = Field(default=None, ge=0)
    time_since_mfe_ns: int | None = Field(default=None, ge=0)
    activation_semantics: Literal[
        "HISTORICAL_PRICE_ONLY_FAVORABLE_THRESHOLD_PROXY_NOT_LIVE_PROTECTION"
    ] = ACTIVATION_SEMANTICS
    activations: tuple[ActivationTiming, ...]
    source_quality_status: Literal["COMPLETE", "WITH_GAPS", "AMBIGUOUS", "WITH_GAPS_AND_AMBIGUITY"]
    source_gap_codes: tuple[str, ...]
    source_ambiguity_codes: tuple[str, ...]
    historical_evidence_only: Literal[True] = True
    prohibited_interpretations: tuple[
        Literal[
            "PNL",
            "RETURN",
            "REAL_RETURN",
            "LIVE_PROTECTION_ACTIVATION",
            "TARGET_FIRST",
            "STOP_FIRST",
            "ROUND_SUCCESS",
        ],
        ...,
    ]
    source_path_hash: str = Field(pattern=SHA256_PATTERN)
    output_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"output_hash"})
        return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        if self.window_end_ns <= self.window_start_ns:
            raise ValueError("path metric window must be non-empty")
        expected_price_type = "CONTRACT" if self.evidence_level == "H1" else "TRADE"
        if self.reference_price_type != expected_price_type:
            raise ValueError("evidence level and reference price type disagree")
        thresholds = tuple(item.threshold_bps for item in self.activations)
        if thresholds != tuple(sorted(set(thresholds))):
            raise ValueError("activation thresholds must be unique and ascending")
        if self.metric_status == "NO_OBSERVATIONS":
            metric_values = (
                self.mfe_bps,
                self.mae_bps,
                self.mfe_first_ts_event_ns,
                self.mae_first_ts_event_ns,
                self.last_observation_ts_event_ns,
                self.time_since_mfe_ns,
            )
            if self.observation_count != 0 or any(value is not None for value in metric_values):
                raise ValueError("NO_OBSERVATIONS cannot carry metric values")
            if any(item.activated for item in self.activations):
                raise ValueError("an empty path cannot activate")
        else:
            if self.observation_count == 0:
                raise ValueError("COMPUTED metrics require observations")
            required = (
                self.mfe_bps,
                self.mae_bps,
                self.mfe_first_ts_event_ns,
                self.mae_first_ts_event_ns,
                self.last_observation_ts_event_ns,
                self.time_since_mfe_ns,
            )
            if any(value is None for value in required):
                raise ValueError("COMPUTED metrics require all metric values")
            if self.mfe_bps is not None and self.mfe_bps < 0:
                raise ValueError("MFE must be non-negative")
            if self.mae_bps is not None and self.mae_bps > 0:
                raise ValueError("MAE must be non-positive")
            if (
                self.mfe_first_ts_event_ns is not None
                and self.last_observation_ts_event_ns is not None
                and self.mfe_first_ts_event_ns > self.last_observation_ts_event_ns
            ):
                raise ValueError("MFE timestamp cannot follow the last observation")
        if self.output_hash != "0" * 64 and self.output_hash != self.computed_hash():
            raise ValueError("path metrics output_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "output_hash": "0" * 64})
        return provisional.model_copy(update={"output_hash": provisional.computed_hash()})
