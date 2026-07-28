"""Typed source-provenance gate for the Plan v1.8 lifecycle successor."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from .models import canonical_hash


class InstrumentGapAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    instrument: Literal["BTCUSDT", "ETHUSDT"]
    trade_gap_count: int
    trade_gap_second_count: int
    contract_price_gap_seconds_covered: int
    contract_price_zero_volume_gap_seconds: int
    contract_price_duplicate_seconds: int
    contract_price_extreme_beyond_visible_trades_count: int


class LifecycleSourceAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_name: Literal["stage2-lifecycle-source-audit"]
    schema_version: Literal["1.0"]
    status: Literal["PASS", "BLOCKED_SOURCE_NOT_INDEPENDENT_OR_INFORMATIVE"]
    scope_start_date: str
    scope_end_date_exclusive: str
    contract_price_source_family: Literal["BINANCE_USDM_AGGTRADES_DERIVED_1S_OHLC"]
    canonical_trade_source_family: Literal["BINANCE_USDM_TRADES_ARCHIVES"]
    source_relationship: Literal["DISTINCT_BINANCE_ARCHIVE_FAMILIES"]
    information_status: Literal["SAME_SECOND_RANGE_BOUND_ADDITIONAL_ASSURANCE"]
    contract_price_root: str
    canonical_trade_root: str
    provenance_script_path: str
    provenance_script_sha256: str
    source_checkpoint_path: str
    source_checkpoint_sha256: str
    audits: tuple[InstrumentGapAudit, ...]
    forward_filled_seconds_forbidden: bool
    historical_execution_claim: bool
    audit_hash: str

    @model_validator(mode="after")
    def gate_and_hash_match(self) -> Self:
        if self.historical_execution_claim:
            raise ValueError("source audit cannot claim historical execution")
        if not self.forward_filled_seconds_forbidden:
            raise ValueError("zero-volume forward-filled seconds must remain forbidden")
        if {item.instrument for item in self.audits} != {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("source audit must keep BTC and ETH separate and complete")
        passed = all(
            item.trade_gap_second_count > 0
            and item.contract_price_gap_seconds_covered == item.trade_gap_second_count
            and item.contract_price_zero_volume_gap_seconds == 0
            and item.contract_price_duplicate_seconds == 0
            for item in self.audits
        )
        expected_status = (
            "PASS" if passed else "BLOCKED_SOURCE_NOT_INDEPENDENT_OR_INFORMATIVE"
        )
        if self.status != expected_status:
            raise ValueError("source audit status does not match its measured gates")
        payload = self.model_dump(mode="json", exclude={"audit_hash"})
        if self.audit_hash != canonical_hash(payload):
            raise ValueError("source audit hash mismatch")
        return self
