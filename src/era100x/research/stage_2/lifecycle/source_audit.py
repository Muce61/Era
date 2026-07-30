"""Typed source-provenance gate reused by the Plan v1.10 lifecycle successor."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
from typing import Any, Literal, Self

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
    gap_second_check_status: Literal[
        "FULL_PERIOD_MEASURED",
        "DEFERRED_TO_T11_EPISODE_WINDOWS",
    ] = "FULL_PERIOD_MEASURED"
    stage1_gap_inventory_hash: str | None = None
    contract_price_partition_count: int | None = None


class LifecycleSourceAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_name: Literal["stage2-lifecycle-source-audit"]
    schema_version: Literal["1.0", "1.1", "1.2", "1.3"]
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
    canonical_trade_overlay_mode: Literal["EXACT_KEY_APPEND_ONLY_SUPPLEMENT_V1"] | None = None
    trade_supplement_acceptance_path: str | None = None
    trade_supplement_file_sha256: str | None = None
    trade_supplement_acceptance_hash: str | None = None
    trade_supplement_instrument: Literal["BTCUSDT", "ETHUSDT"] | None = None
    trade_supplement_date: str | None = None
    legacy_stage1_partition_modified: bool | None = None
    audits: tuple[InstrumentGapAudit, ...]
    forward_filled_seconds_forbidden: bool
    zero_trade_contract_price_proxy_allowed: bool | None = None
    historical_execution_claim: bool
    evidence_mode: Literal["SEALED_INCREMENTAL_V1"] | None = None
    full_trade_row_rescan: bool | None = None
    targeted_reverification: tuple[str, ...] = ()
    unverified_or_drifted_sources: tuple[str, ...] = ()
    audit_hash: str

    @model_validator(mode="after")
    def gate_and_hash_match(self) -> Self:
        if self.historical_execution_claim:
            raise ValueError("source audit cannot claim historical execution")
        if not self.forward_filled_seconds_forbidden:
            raise ValueError("forward-filled Contract Price cannot become a synthetic Trade")
        if {item.instrument for item in self.audits} != {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("source audit must keep BTC and ETH separate and complete")
        supplement_values = (
            self.canonical_trade_overlay_mode,
            self.trade_supplement_acceptance_path,
            self.trade_supplement_file_sha256,
            self.trade_supplement_acceptance_hash,
            self.trade_supplement_instrument,
            self.trade_supplement_date,
            self.legacy_stage1_partition_modified,
        )
        if self.schema_version in {"1.1", "1.2", "1.3"}:
            if (
                any(value is None for value in supplement_values)
                or self.canonical_trade_overlay_mode != "EXACT_KEY_APPEND_ONLY_SUPPLEMENT_V1"
                or self.trade_supplement_instrument != "BTCUSDT"
                or self.trade_supplement_date != "2022-03-01"
                or self.legacy_stage1_partition_modified is not False
            ):
                raise ValueError("source audit Trade supplement binding drift")
        elif any(value is not None for value in supplement_values):
            raise ValueError("legacy source audit cannot carry a Trade supplement")
        if self.schema_version in {"1.2", "1.3"}:
            if (
                self.evidence_mode != "SEALED_INCREMENTAL_V1"
                or self.full_trade_row_rescan is not False
                or self.unverified_or_drifted_sources
                or any(
                    item.trade_gap_count <= 0
                    or item.gap_second_check_status != "DEFERRED_TO_T11_EPISODE_WINDOWS"
                    or item.stage1_gap_inventory_hash is None
                    or item.contract_price_partition_count != 2376
                    for item in self.audits
                )
            ):
                raise ValueError("sealed incremental source audit gate failed")
            if (
                self.schema_version == "1.3"
                and self.zero_trade_contract_price_proxy_allowed is not True
            ):
                raise ValueError("zero-Trade Contract Price proxy contract is not approved")
            if (
                self.schema_version == "1.2"
                and self.zero_trade_contract_price_proxy_allowed is not None
            ):
                raise ValueError("legacy sealed audit cannot carry zero-Trade proxy approval")
            passed = True
        else:
            if (
                self.evidence_mode is not None
                or self.full_trade_row_rescan is not None
                or self.zero_trade_contract_price_proxy_allowed is not None
            ):
                raise ValueError("legacy source audit cannot claim sealed incremental evidence")
            passed = all(
                item.trade_gap_second_count > 0
                and item.contract_price_gap_seconds_covered == item.trade_gap_second_count
                and item.contract_price_zero_volume_gap_seconds == 0
                and item.contract_price_duplicate_seconds == 0
                for item in self.audits
            )
        expected_status = "PASS" if passed else "BLOCKED_SOURCE_NOT_INDEPENDENT_OR_INFORMATIVE"
        if self.status != expected_status:
            raise ValueError("source audit status does not match its measured gates")
        payload = self.model_dump(
            mode="json",
            exclude={"audit_hash"},
            exclude_none=True,
            exclude_unset=True,
        )
        if self.audit_hash != canonical_hash(payload):
            raise ValueError("source audit hash mismatch")
        return self


def validate_source_audit_payload(payload: Mapping[str, Any]) -> LifecycleSourceAudit:
    """Normalize JSON arrays for frozen tuple fields, then retain strict validation."""

    normalized = dict(payload)
    for field_name in (
        "audits",
        "targeted_reverification",
        "unverified_or_drifted_sources",
    ):
        value = normalized.get(field_name)
        if isinstance(value, list):
            normalized[field_name] = tuple(value)
    return LifecycleSourceAudit.model_validate(normalized)


def load_source_audit(path: Path, *, expected_hash: str) -> LifecycleSourceAudit:
    """Load one immutable passing audit without granting execution authority."""

    if path.is_symlink() or not path.is_file():
        raise ValueError("lifecycle source audit must be a regular non-symlink file")
    audit = LifecycleSourceAudit.model_validate_json(path.read_bytes(), strict=True)
    if audit.status != "PASS" or audit.audit_hash != expected_hash:
        raise ValueError("lifecycle source audit is not the expected PASS artifact")
    return audit
