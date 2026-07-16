"""Strict immutable contracts for the Stage 2 Group 1 event chain."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Instrument = Literal["BTCUSDT", "ETHUSDT"]
Direction = Literal["LONG"]
Hash = str


class StrictEventModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Lineage(StrictEventModel):
    instrument: Instrument
    data_run_id: str = Field(min_length=1)
    dataset_logical_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    config_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    code_version: str = Field(min_length=7)
    parameter_set_id: str = Field(min_length=1)
    available_at_ts: int = Field(ge=0)


class RawKeyLevel(Lineage):
    raw_key_level_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    level_type: Literal["LOW"] = "LOW"
    source_type: Literal["rolling_low_1m", "rolling_low_5m", "range_low"]
    source_id: str
    source_timeframe: Literal["1m", "5m", "15m", "1H", "4H", "1D"]
    source_start_ts: int = Field(ge=0)
    source_end_ts: int = Field(ge=0)
    level_price: Decimal = Field(gt=0)
    priority: int = Field(gt=0)
    quality_status: Literal["ACCEPTED", "REJECTED"]
    rejection_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def causal_source(self) -> Self:
        if self.source_start_ts >= self.source_end_ts:
            raise ValueError("source window must be non-empty")
        if self.source_end_ts > self.available_at_ts:
            raise ValueError("key level cannot be available before its source closes")
        if self.quality_status == "REJECTED" and not self.rejection_reason:
            raise ValueError("rejected key level requires a reason")
        return self


class CanonicalKeyLevel(Lineage):
    key_level_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    level_type: Literal["LOW"] = "LOW"
    source_type: Literal["rolling_low_1m", "rolling_low_5m", "range_low"]
    source_id: str
    source_timeframe: Literal["1m", "5m", "15m", "1H", "4H", "1D"]
    source_start_ts: int = Field(ge=0)
    source_end_ts: int = Field(ge=0)
    level_price: Decimal = Field(gt=0)
    priority: int = Field(gt=0)
    normalization_group: str
    member_key_level_ids: tuple[str, ...]
    formed_at_ns: int = Field(ge=0)
    expires_at_ns: int = Field(gt=0)
    status: Literal["ACTIVE", "SUPERSEDED", "EXPIRED", "REJECTED"]
    reason_code: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def causal_and_traceable(self) -> Self:
        if self.source_start_ts >= self.source_end_ts:
            raise ValueError("source window must be non-empty")
        if self.source_end_ts > self.available_at_ts:
            raise ValueError("canonical level cannot predate its source close")
        if self.expires_at_ns <= self.available_at_ts:
            raise ValueError("canonical level expiry must follow availability")
        if not self.member_key_level_ids:
            raise ValueError("canonical level must preserve source members")
        return self


class SweepEpisode(Lineage):
    sweep_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_level_id: str
    direction: Direction = "LONG"
    sweep_start_ts: int = Field(ge=0)
    sweep_detection_ts: int = Field(ge=0)
    sweep_extreme_ts: int = Field(ge=0)
    sweep_extreme_price: Decimal = Field(gt=0)
    sweep_depth: Decimal = Field(ge=0)
    sweep_depth_unit: Literal["BPS"] = "BPS"
    pre_sweep_reference: Decimal = Field(gt=0)
    status: Literal["DETECTED", "INVALIDATED", "ENDED"]
    reason_code: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReclaimEvent(Lineage):
    reclaim_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    sweep_id: str
    reclaim_ts: int = Field(ge=0)
    reclaim_price: Decimal = Field(gt=0)
    status: Literal["RECLAIMED", "TIMED_OUT", "INVALIDATED"]
    reason_code: str


class HoldEvent(Lineage):
    hold_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    reclaim_id: str
    sweep_id: str
    hold_start_ts: int = Field(ge=0)
    hold_end_ts: int = Field(ge=0)
    hold_result: Literal["PASS", "FAIL", "INSUFFICIENT_WINDOW"]
    failure_reason: str | None


class PriceTriggerFact(Lineage):
    trigger_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    hold_id: str
    sweep_id: str
    trigger_version: str
    detection_ts: int = Field(ge=0)
    reference_price: Decimal = Field(gt=0)
    context_state: Literal["UP", "DOWN", "FLAT", "UNAVAILABLE"]
    status: Literal["PASS", "REJECTED", "UNAVAILABLE"]
    reason_code: str


class FlowFeatureSet(Lineage):
    flow_feature_set_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    flow_feature_version: str
    window_start_ts: int = Field(ge=0)
    window_end_ts: int = Field(ge=0)
    feature_values: dict[str, Decimal | int | str | bool | None]
    status: Literal["PASS", "REJECTED", "UNAVAILABLE"]
    unavailable_fields: tuple[str, ...]
    reason_code: str


class MarketEpisode(Lineage):
    market_episode_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_version_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    venue: Literal["BINANCE_USDM"]
    canonical_key_level_id: str
    sweep_id: str
    reclaim_id: str
    hold_id: str
    trigger_id: str
    flow_feature_set_id: str | None
    variant: Literal["V1_PRICE", "V1_FLOW"]
    sweep_start_ns: int = Field(ge=0)
    episode_status: Literal["CANDIDATE", "REJECTED", "INVALIDATED"]
    consumed: bool = False
    consumed_by_intent_id: None = None
    rearm_eligible_at_ns: int | None = None


class CandidateInclusionRecord(Lineage):
    inclusion_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_episode_id: str
    candidate_version_id: str
    included: bool
    reason_code: str
    deduplication_key: str
