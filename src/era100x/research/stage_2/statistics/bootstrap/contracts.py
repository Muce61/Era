"""Frozen machine contracts for S2P15-T18."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.baselines.conditional.v14_contracts import COMBINATION_ORDER
from era100x.research.stage_2.contracts.models import Instrument, StrictEventModel

from .formatting import canonical_hash

SHA256_PATTERN = r"^[0-9a-f]{64}$"
GIT_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
TASK_ID = "S2P15-T18"
TASK_VERSION = "1.0"
PLAN_VERSION = "1.5"
BOOTSTRAP_ITERATIONS = 5000
BOOTSTRAP_SEED = 20260716
MetricFamily = Literal[
    "REAL_EVENT_DELTA",
    "PLACEBO_DELTA",
    "PAIRED_REAL_MINUS_PLACEBO",
]
AnalysisScope = Literal["FOLD", "PERIOD", "OVERALL"]
BootstrapStatus = Literal["PASS", "INSUFFICIENT_CLUSTERS"]
RESEARCH_STATUS = "STATISTICAL_EVIDENCE_ONLY_FINAL_GATE_PENDING"


class S2P15T18Authority(StrictEventModel):
    schema_name: Literal["s2p15-t18-authority"] = "s2p15-t18-authority"
    schema_version: Literal["1.0"] = "1.0"
    task_id: Literal["S2P15-T18"] = "S2P15-T18"
    task_version: Literal["1.0"] = "1.0"
    stage_plan_version: Literal["1.5"] = "1.5"
    code_commit: str = Field(pattern=GIT_COMMIT_PATTERN)
    policy_hash: str = Field(pattern=SHA256_PATTERN)
    approval_hash: str = Field(pattern=SHA256_PATTERN)
    preregistration_hash: str = Field(pattern=SHA256_PATTERN)
    format_smoke_hash: str = Field(pattern=SHA256_PATTERN)
    source_t16_verify_hash: str = Field(pattern=SHA256_PATTERN)
    source_t17_verify_hash: str = Field(pattern=SHA256_PATTERN)
    source_t16_snapshot_id: str = Field(pattern=SHA256_PATTERN)
    source_t17_snapshot_id: str = Field(pattern=SHA256_PATTERN)
    cluster_contract: Literal["INSTRUMENT_UTC_MONDAY_WEEK_V1"]
    bootstrap_iterations: Literal[5000] = 5000
    bootstrap_seed: Literal[20260716] = 20260716
    rng: Literal["NUMPY_PCG64_DERIVED_GROUP_SEED_V1"]
    metric_families: tuple[MetricFamily, ...]
    analysis_scopes: tuple[AnalysisScope, ...]
    historical_evidence_only: Literal[True] = True
    stage3_locked: Literal[True] = True
    authority_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"authority_hash"}))

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.authority_hash != "0" * 64 and self.authority_hash != self.computed_hash():
            raise ValueError("T18 Authority hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "authority_hash": "0" * 64})
        return provisional.model_copy(update={"authority_hash": provisional.computed_hash()})


class ClusterSufficientStatistic(StrictEventModel):
    schema_name: Literal["s2p15-t18-cluster-statistic"] = "s2p15-t18-cluster-statistic"
    instrument: Instrument
    pre_registered_period: Literal["P1", "P2", "P3"]
    evaluation_fold: Literal["F0", "F1", "F2", "F3"]
    parameter_set_id: str = Field(min_length=1)
    time_combination_id: Literal["T1", "T2", "T3", "T4"]
    week_start_ns: int = Field(ge=0)
    cluster_id: str = Field(min_length=1)
    real_count: int = Field(ge=0)
    placebo_count: int = Field(ge=0)
    paired_count: int = Field(ge=0)
    real_event_success: tuple[int, ...]
    real_control_success: tuple[int, ...]
    placebo_event_success: tuple[int, ...]
    placebo_control_success: tuple[int, ...]
    paired_real_event_success: tuple[int, ...]
    paired_real_control_success: tuple[int, ...]
    paired_placebo_event_success: tuple[int, ...]
    paired_placebo_control_success: tuple[int, ...]
    statistic_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"statistic_hash"}))

    @model_validator(mode="after")
    def validate_arrays(self) -> Self:
        arrays = (
            self.real_event_success,
            self.real_control_success,
            self.placebo_event_success,
            self.placebo_control_success,
            self.paired_real_event_success,
            self.paired_real_control_success,
            self.paired_placebo_event_success,
            self.paired_placebo_control_success,
        )
        if any(len(values) != len(COMBINATION_ORDER) for values in arrays):
            raise ValueError("T18 cluster statistic combination count drift")
        if self.placebo_count != self.paired_count:
            raise ValueError("placebo and paired complete-case counts disagree")
        if self.statistic_hash != "0" * 64 and self.statistic_hash != self.computed_hash():
            raise ValueError("T18 cluster statistic hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "statistic_hash": "0" * 64})
        return provisional.model_copy(update={"statistic_hash": provisional.computed_hash()})


class BootstrapSummary(StrictEventModel):
    schema_name: Literal["s2p15-t18-bootstrap-summary"] = "s2p15-t18-bootstrap-summary"
    instrument: Instrument
    analysis_scope: AnalysisScope
    pre_registered_period: str | None
    evaluation_fold: str | None
    parameter_set_id: str
    time_combination_id: Literal["T1", "T2", "T3", "T4"]
    combination_id: str
    metric_family: MetricFamily
    status: BootstrapStatus
    cluster_count: int = Field(ge=0)
    episode_count: int = Field(ge=0)
    meets_200_cluster_baseline: bool
    estimate: str | None
    ci_lower: str | None
    ci_upper: str | None
    bootstrap_median: str | None
    bootstrap_standard_error: str | None
    raw_p_value: str | None
    adjusted_q_value: str | None = None
    fdr_significant: bool | None = None
    fdr_role: Literal["PRIMARY_NOT_ADJUSTED", "EXPLORATORY_BH"]
    replicate_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    research_status: Literal["STATISTICAL_EVIDENCE_ONLY_FINAL_GATE_PENDING"] = (
        "STATISTICAL_EVIDENCE_ONLY_FINAL_GATE_PENDING"
    )
    summary_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"summary_hash"}))

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        statistic_values = (
            self.estimate,
            self.ci_lower,
            self.ci_upper,
            self.bootstrap_median,
            self.bootstrap_standard_error,
            self.raw_p_value,
            self.replicate_hash,
        )
        if self.status == "PASS" and any(value is None for value in statistic_values):
            raise ValueError("passing bootstrap summary is incomplete")
        if self.status == "INSUFFICIENT_CLUSTERS" and any(
            value is not None for value in statistic_values
        ):
            raise ValueError("insufficient-cluster summary cannot publish statistics")
        if self.summary_hash != "0" * 64 and self.summary_hash != self.computed_hash():
            raise ValueError("T18 bootstrap summary hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "summary_hash": "0" * 64})
        return provisional.model_copy(update={"summary_hash": provisional.computed_hash()})


class FdrFamilySummary(StrictEventModel):
    schema_name: Literal["s2p15-t18-fdr-family-summary"] = "s2p15-t18-fdr-family-summary"
    family_id: str = Field(min_length=1)
    instrument: Instrument
    metric_family: MetricFamily
    analysis_scope: AnalysisScope
    hypothesis_count: int = Field(ge=0)
    tested_hypothesis_count: int = Field(ge=0)
    significant_count: int = Field(ge=0)
    q_threshold: Literal["0.100000000000000000"] = "0.100000000000000000"
    family_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"family_hash"}))

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if (
            self.tested_hypothesis_count > self.hypothesis_count
            or self.significant_count > self.tested_hypothesis_count
        ):
            raise ValueError("FDR significant count exceeds hypotheses")
        if self.family_hash != "0" * 64 and self.family_hash != self.computed_hash():
            raise ValueError("T18 FDR family hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "family_hash": "0" * 64})
        return provisional.model_copy(update={"family_hash": provisional.computed_hash()})
