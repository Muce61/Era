"""Strict contracts for S2-T11 historical path extraction.

These contracts deliberately contain no MFE, MAE, first-passage, label, return,
or execution-quality field. Those concepts belong to later Stage 2 tasks.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.contracts.models import Instrument, StrictEventModel

SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _canonical_json(value: Any) -> str:
    def convert(item: Any) -> Any:
        if isinstance(item, Decimal):
            return format(item, "f")
        if isinstance(item, dict):
            return {str(key): convert(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [convert(val) for val in item]
        if isinstance(item, float):
            raise TypeError("binary floats are forbidden in path evidence")
        return item

    return json.dumps(convert(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class PathSource(StrictEventModel):
    instrument: Instrument
    evidence_level: Literal["H1", "H2"]
    reference_price_type: Literal["CONTRACT", "TRADE"]
    data_run_id: str = Field(min_length=1)
    dataset_logical_hash: str = Field(pattern=SHA256_PATTERN)
    source_manifest_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def evidence_matches_price_type(self) -> Self:
        expected = "CONTRACT" if self.evidence_level == "H1" else "TRADE"
        if self.reference_price_type != expected:
            raise ValueError("evidence level and reference price type disagree")
        return self


class H1PathPoint(StrictEventModel):
    instrument: Instrument
    ts_event_ns: int = Field(ge=0)
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    source_encoding: Literal["DECIMAL_TEXT", "SOURCE_FLOAT64"]
    source_row_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def valid_ohlc(self) -> Self:
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("H1 high is below another OHLC value")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("H1 low is above another OHLC value")
        return self


class H2PathPoint(StrictEventModel):
    instrument: Instrument
    ts_event_ns: int = Field(ge=0)
    venue_trade_id: int = Field(ge=0)
    canonical_trade_id: str = Field(pattern=SHA256_PATTERN)
    identity_status: Literal["UNIQUE_VENUE_ID", "CONFLICTING_VENUE_ID"]
    venue_trade_id_conflict_group: str | None = None
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    quote_quantity: Decimal = Field(ge=0)
    is_buyer_maker: bool
    aggressor_side: Literal["BUY", "SELL"] | None = None
    source_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def conflict_is_traceable(self) -> Self:
        expected = f"{self.instrument}:{self.venue_trade_id}"
        if self.identity_status == "CONFLICTING_VENUE_ID":
            if self.venue_trade_id_conflict_group != expected:
                raise ValueError("conflicting venue ID requires its deterministic conflict group")
        elif self.venue_trade_id_conflict_group is not None:
            raise ValueError("unique venue ID cannot carry a conflict group")
        return self


class PathGap(StrictEventModel):
    evidence_level: Literal["H1", "H2"]
    reason_code: Literal[
        "H1_MISSING_SECONDS",
        "H2_VENUE_TRADE_ID_GAP",
        "H2_VENUE_TRADE_ID_REVERSAL",
    ]
    preceding_ts_event_ns: int = Field(ge=0)
    following_ts_event_ns: int = Field(ge=0)
    missing_count: int = Field(gt=0)
    preceding_venue_trade_id: int | None = Field(default=None, ge=0)
    following_venue_trade_id: int | None = Field(default=None, ge=0)


class ExtractedHistoricalPath(StrictEventModel):
    schema_name: Literal["stage2-historical-path-extraction"] = "stage2-historical-path-extraction"
    schema_version: Literal["1.0"] = "1.0"
    instrument: Instrument
    market_episode_id: str = Field(pattern=SHA256_PATTERN)
    canonical_candidate_id: str = Field(pattern=SHA256_PATTERN)
    candidate_version_id: str = Field(pattern=SHA256_PATTERN)
    canonical_payload_hash: str = Field(pattern=SHA256_PATTERN)
    parameter_set_id: str = Field(min_length=1)
    episode_available_at_ns: int = Field(ge=0)
    window_start_ns: int = Field(ge=0)
    window_end_ns: int = Field(gt=0)
    time_semantics: Literal["UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"] = (
        "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"
    )
    h1_source: PathSource
    h2_source: PathSource
    h1_points: tuple[H1PathPoint, ...]
    h2_points: tuple[H2PathPoint, ...]
    gaps: tuple[PathGap, ...]
    ambiguity_codes: tuple[
        Literal[
            "H1_CONFLICTING_SAME_SECOND",
            "H2_CONFLICTING_VENUE_ID",
            "H2_EVENT_TIME_VENUE_REVERSAL",
        ],
        ...,
    ]
    h1_input_count: int = Field(ge=0)
    h2_input_count: int = Field(ge=0)
    h1_outside_window_count: int = Field(ge=0)
    h2_outside_window_count: int = Field(ge=0)
    h1_duplicate_count: int = Field(ge=0)
    h2_duplicate_count: int = Field(ge=0)
    quality_status: Literal["COMPLETE", "WITH_GAPS", "AMBIGUOUS", "WITH_GAPS_AND_AMBIGUITY"]
    prohibited_execution_fields: tuple[str, ...]
    output_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"output_hash"})
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        if self.window_end_ns <= self.window_start_ns:
            raise ValueError("path window must be non-empty")
        if self.window_start_ns < self.episode_available_at_ns:
            raise ValueError("path cannot begin before the episode is available")
        if self.h1_source.evidence_level != "H1" or self.h2_source.evidence_level != "H2":
            raise ValueError("H1/H2 sources are reversed")
        if (
            self.h1_source.instrument != self.instrument
            or self.h2_source.instrument != self.instrument
        ):
            raise ValueError("path source instrument does not match the MarketEpisode")
        if any(point.instrument != self.instrument for point in self.h1_points):
            raise ValueError("H1 path mixes instruments")
        if any(point.instrument != self.instrument for point in self.h2_points):
            raise ValueError("H2 path mixes instruments")
        h1_keys = tuple((point.ts_event_ns, point.source_row_hash) for point in self.h1_points)
        if h1_keys != tuple(sorted(h1_keys)):
            raise ValueError("H1 path is not stably ordered")
        h2_keys = tuple(
            (point.ts_event_ns, point.venue_trade_id, point.canonical_trade_id)
            for point in self.h2_points
        )
        if h2_keys != tuple(sorted(h2_keys)):
            raise ValueError("H2 path is not V2 stably ordered")
        if self.output_hash != "0" * 64 and self.output_hash != self.computed_hash():
            raise ValueError("path output_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "output_hash": "0" * 64})
        return provisional.model_copy(update={"output_hash": provisional.computed_hash()})
