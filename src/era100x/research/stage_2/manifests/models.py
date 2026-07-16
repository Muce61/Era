"""Frozen, deterministic Stage 2 Group 1 manifest contracts."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"


def canonical_json(value: Any) -> str:
    """Serialize with stable keys and Decimal text, without binary floats."""

    def convert(item: Any) -> Any:
        if isinstance(item, Decimal):
            return format(item, "f")
        if isinstance(item, dict):
            return {str(key): convert(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [convert(val) for val in item]
        if isinstance(item, float):
            raise TypeError("binary floats are forbidden in canonical manifests")
        return item

    return json.dumps(convert(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TimeConfiguration(FrozenModel):
    timing_id: Literal["T1", "T2", "T3", "T4"]
    role: Literal["PRIMARY", "EXPLORATORY_SENSITIVITY"]
    reclaim_timeout_seconds: int = Field(gt=0)
    hold_window_seconds: int = Field(gt=0)
    first_passage_horizon_seconds: int = Field(gt=0)


class ResearchPeriod(FrozenModel):
    period_id: Literal["P1", "P2", "P3"]
    start_ns: int = Field(ge=0)
    end_ns: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_ns <= self.start_ns:
            raise ValueError("period end must be after start")
        return self


class ParameterSet(FrozenModel):
    parameter_set_id: str = Field(min_length=1)
    parameter_set_version: str = "1.0"
    status: Literal["BASELINE", "RESEARCH"]
    changed_axis: str
    timing_id: Literal["T1", "T2", "T3", "T4"]
    merge_tolerance_bps: Decimal
    minimum_episode_gap_seconds: int
    rearm_above_level_seconds: int
    sweep_confirmation_bps: Decimal
    reclaim_buffer_bps: Decimal
    hold_failure_buffer_bps: Decimal
    max_sweep_depth_bps: Decimal = Decimal("25")
    max_episode_duration_seconds: int = 120


class Stage1Baseline(FrozenModel):
    baseline_version: str
    tag: str
    commit: str = Field(min_length=40, max_length=40)
    data_run_id: str
    canonical_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    physical_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    btc_catalog_sha256: str = Field(pattern=SHA256_PATTERN)
    eth_catalog_sha256: str = Field(pattern=SHA256_PATTERN)
    btc_trades_logical_hash: str = Field(pattern=SHA256_PATTERN)
    eth_trades_logical_hash: str = Field(pattern=SHA256_PATTERN)
    contract_price_inventory_hash: str = Field(pattern=SHA256_PATTERN)
    contract_price_file_count: int = Field(gt=0)


class OutputPolicy(FrozenModel):
    root: str
    layout: tuple[str, ...]
    append_only_directories: tuple[str, ...]
    required_free_space_multiplier: Decimal
    estimated_peak_bytes: int = Field(gt=0)
    required_free_bytes: int = Field(gt=0)
    available_free_bytes: int = Field(gt=0)
    fallback_root_allowed: Literal[False] = False
    failed_staging_auto_cleanup: Literal[False] = False


class Stage2PreregistrationManifest(FrozenModel):
    schema_name: Literal["stage2-group1-preregistration"]
    manifest_version: str
    research_run_family: str
    stage_plan_version: Literal["1.2"]
    task_version: Literal["1.3"]
    manual_version: Literal["V1.3.4"]
    governance_commit: str
    stage1: Stage1Baseline
    instruments: tuple[Literal["BTCUSDT", "ETHUSDT"], ...]
    primary_instrument: Literal["BTCUSDT"]
    secondary_instrument: Literal["ETHUSDT"]
    direction: Literal["LONG"]
    evidence_level: Literal["H2_HISTORICAL_CONDITIONAL_EVENT_EVIDENCE"]
    primary_hypothesis: str
    primary_label: Literal["TARGET_FIRST_STRICT"]
    ambiguous_primary_treatment: Literal["FAILURE"]
    time_semantics: Literal["UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"]
    timing_configurations: tuple[TimeConfiguration, ...]
    periods: tuple[ResearchPeriod, ...]
    parameter_sets: tuple[ParameterSet, ...]
    target_domain_bps: tuple[Decimal, ...]
    stop_domain_bps: tuple[Decimal, ...]
    matching_fields_never_relaxed: tuple[str, ...]
    matching_relaxation_order: tuple[Literal["L0", "L1", "L2", "L3", "L4", "L5"], ...]
    controls_per_episode: Literal[5]
    matching_seed: Literal[20260716]
    bootstrap_seed: Literal[20260716]
    cluster_definition: Literal["instrument_x_utc_calendar_week"]
    bootstrap_iterations: Literal[5000]
    ci_definition: Literal["two_sided_95_percentile_bootstrap"]
    primary_failure_lines: tuple[str, ...]
    eth_secondary_classes: tuple[str, ...]
    purge_embargo_rule: str
    small_sample_windows: tuple[str, ...]
    full_input_period: str
    allowed_outputs: tuple[str, ...]
    prohibited_metrics: tuple[str, ...]
    prohibited_capabilities: tuple[str, ...]
    full_run_cli: str
    output_policy: OutputPolicy
    invalidation_conditions: tuple[str, ...]
    config_hash: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        data = self.model_dump(mode="python", exclude={"manifest_hash"})
        return sha256_text(canonical_json(data))

    @model_validator(mode="after")
    def validate_frozen_family(self) -> Self:
        if self.manifest_hash != "0" * 64 and self.manifest_hash != self.computed_hash():
            raise ValueError("manifest_hash mismatch")
        if len(self.parameter_sets) != 20:
            raise ValueError("exactly 20 OFAT parameter sets are required")
        if sum(p.changed_axis == "PRIMARY" for p in self.parameter_sets) != 1:
            raise ValueError("exactly one Primary parameter set is required")
        if tuple(t.timing_id for t in self.timing_configurations) != ("T1", "T2", "T3", "T4"):
            raise ValueError("T1-T4 must be complete and ordered")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        unsealed = dict(payload)
        unsealed["manifest_hash"] = "0" * 64
        provisional = cls.model_validate(unsealed)
        return provisional.model_copy(update={"manifest_hash": provisional.computed_hash()})


class RecoveryMetadata(FrozenModel):
    recovery_of_run_id: str
    supersedes_failed_run_id: str
    failure_reason: str
    change_request: Literal["CR-2026-003"]
    fix_code_commit: str = Field(min_length=40, max_length=40)
    reused_price_staging: Literal[False] = False


class Stage2ExecutionManifest(FrozenModel):
    schema_name: Literal["stage2-group1-execution"]
    manifest_version: str
    preregistration_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit: str = Field(min_length=40, max_length=40)
    fixture_logical_hash: str = Field(pattern=SHA256_PATTERN)
    small_sample_validation_hash: str = Field(pattern=SHA256_PATTERN)
    config_hash: str = Field(pattern=SHA256_PATTERN)
    stage1_data_run_id: str
    stage1_logical_hashes: dict[Literal["BTCUSDT", "ETHUSDT"], str]
    full_run_cli: str
    invalidation_conditions: tuple[str, ...]
    recovery: RecoveryMetadata | None = None
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return sha256_text(
            canonical_json(
                self.model_dump(mode="python", exclude={"manifest_hash"}, exclude_none=True)
            )
        )

    @model_validator(mode="after")
    def hash_matches(self) -> Self:
        if self.manifest_hash != "0" * 64 and self.manifest_hash != self.computed_hash():
            raise ValueError("manifest_hash mismatch")
        if self.recovery is not None and self.recovery.fix_code_commit != self.code_commit:
            raise ValueError("recovery fix commit must equal execution code commit")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        unsealed = dict(payload)
        unsealed["manifest_hash"] = "0" * 64
        provisional = cls.model_validate(unsealed)
        return provisional.model_copy(update={"manifest_hash": provisional.computed_hash()})
