"""Strict Stage 1 data schemas."""

from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ContractPrice1s(StrictModel):
    instrument: Literal["BTCUSDT", "ETHUSDT"]
    ts_event_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source_encoding: Literal["DECIMAL_TEXT", "SOURCE_FLOAT64"]


class RawTrade(StrictModel):
    instrument: Literal["BTCUSDT", "ETHUSDT"]
    venue_trade_id: int
    price_text: str
    qty_text: str
    quote_qty_text: str
    ts_event_ms: int
    is_buyer_maker: bool
    source_sha256: str


class NormalizedTrade(StrictModel):
    instrument: Literal["BTCUSDT", "ETHUSDT"]
    venue_trade_id: int
    canonical_trade_id: str
    identity_status: Literal["UNIQUE_VENUE_ID", "CONFLICTING_VENUE_ID"]
    venue_trade_id_conflict_group: str | None = None
    price: Decimal
    quantity: Decimal
    quote_quantity: Decimal
    ts_event_ns: int
    is_buyer_maker: bool
    aggressor_side: Literal["BUY", "SELL"] | None = None
    source_sha256: str

    @field_validator("canonical_trade_id")
    @classmethod
    def canonical_id_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("canonical_trade_id must be a lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def conflict_group_matches_status(self) -> NormalizedTrade:
        expected = f"{self.instrument}:{self.venue_trade_id}"
        if self.identity_status == "CONFLICTING_VENUE_ID":
            if self.venue_trade_id_conflict_group != expected:
                raise ValueError("conflicting venue ID requires its deterministic conflict group")
        elif self.venue_trade_id_conflict_group is not None:
            raise ValueError("unique venue ID cannot carry a conflict group")
        return self


class HistoricalEvidenceRow(StrictModel):
    evidence_level: Literal["H1", "H2"]
    reference_price_type: Literal["CONTRACT", "TRADE"]
    reference_ask: None = None
    bid: None = None
    spread_bps: None = None
    ts_recv_ns: None = None
    receive_latency_ms: None = None
    queue_position: None = None
    partial_fill: None = None
    actual_slippage_bps: None = None


class ContractBar(StrictModel):
    instrument: Literal["BTCUSDT", "ETHUSDT"]
    source_type: Literal["CONTRACT", "TRADE"]
    interval_seconds: int
    bucket_start_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class DataQuality(StrictModel):
    instrument: Literal["BTCUSDT", "ETHUSDT"]
    issue_code: str
    severity: Literal["INFO", "WARN", "ERROR"]
    date: date
    count: int


class CatalogEntry(StrictModel):
    instrument: Literal["BTCUSDT", "ETHUSDT"]
    partition_date: date
    relative_path: str
    rows: int
    byte_sha256: str
    logical_sha256: str


class DataManifest(StrictModel):
    dataset_version: str
    run_id: str
    config_hash: str
    input_hash: str
    logical_data_hash: str
    entries: tuple[CatalogEntry, ...]

    @field_validator("dataset_version", "run_id", "config_hash", "input_hash", "logical_data_hash")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("manifest identifiers cannot be empty")
        return value
