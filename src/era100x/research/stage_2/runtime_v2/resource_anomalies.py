"""Append-only execution anomalies that never alter research semantics."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from era100x.research.stage_2.manifests.models import canonical_json

from .models import SHA256_PATTERN, ZERO_SHA256

ResourceCategory = Literal[
    "MEMORY_RSS",
    "ARROW_INFLIGHT",
    "SHARD_SIZE",
    "OBJECT_COUNT",
    "DISK_CAPACITY",
    "STORAGE_AVAILABILITY",
    "PERFORMANCE",
    "MONITOR_STALL",
]
ResourceAction = Literal["CONTINUED", "THROTTLED", "SPLIT", "PAUSED", "RECOVERED"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


@dataclass(frozen=True, slots=True)
class ResourceThresholdObservation:
    category: ResourceCategory
    phase: str
    metric_name: str
    unit: str
    threshold: int
    observed: int
    action: ResourceAction = "CONTINUED"
    observed_at_ns: int = 0
    semantic_impact: Literal["NONE"] = "NONE"
    integrity_impact: Literal["NONE"] = "NONE"

    def with_clock(self) -> ResourceThresholdObservation:
        if self.observed_at_ns:
            return self
        return type(self)(
            category=self.category,
            phase=self.phase,
            metric_name=self.metric_name,
            unit=self.unit,
            threshold=self.threshold,
            observed=self.observed,
            action=self.action,
            observed_at_ns=time.time_ns(),
        )


class ResourceAnomalyV1(_FrozenModel):
    anomaly_id: str = Field(pattern=SHA256_PATTERN)
    category: ResourceCategory
    phase: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    threshold: int = Field(ge=0)
    first_observed: int = Field(ge=0)
    latest_observed: int = Field(ge=0)
    peak_observed: int = Field(ge=0)
    first_seen_ns: int = Field(ge=0)
    last_seen_ns: int = Field(ge=0)
    sample_count: int = Field(gt=0)
    duration_ns: int = Field(ge=0)
    action: ResourceAction
    semantic_impact: Literal["NONE"] = "NONE"
    integrity_impact: Literal["NONE"] = "NONE"


class ResourceAnomalyReportV1(_FrozenModel):
    schema_name: Literal["stage2-v2-resource-anomaly-report"] = "stage2-v2-resource-anomaly-report"
    report_version: Literal["1.0"] = "1.0"
    run_id: str
    task_id: str
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    code_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_impact: Literal["NONE"] = "NONE"
    integrity_impact: Literal["NONE"] = "NONE"
    anomalies: tuple[ResourceAnomalyV1, ...]
    report_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return hashlib.sha256(
            canonical_json(self.model_dump(mode="json", exclude={"report_hash"})).encode("utf-8")
        ).hexdigest()

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        keys = tuple((item.category, item.phase, item.metric_name) for item in self.anomalies)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("resource anomalies must be unique and deterministically sorted")
        if self.report_hash != ZERO_SHA256 and self.report_hash != self.computed_hash():
            raise ValueError("resource anomaly report hash mismatch")
        return self

    @classmethod
    def seal(
        cls,
        *,
        run_id: str,
        task_id: str,
        snapshot_id: str,
        manifest_hash: str,
        config_sha256: str,
        code_tree_sha256: str,
        observations: tuple[ResourceThresholdObservation, ...],
    ) -> Self:
        grouped: dict[tuple[ResourceCategory, str, str], list[ResourceThresholdObservation]] = {}
        for raw in observations:
            item = raw.with_clock()
            grouped.setdefault((item.category, item.phase, item.metric_name), []).append(item)
        anomalies: list[ResourceAnomalyV1] = []
        for key, values in sorted(grouped.items()):
            category, phase, metric = key
            first = min(values, key=lambda item: item.observed_at_ns)
            last = max(values, key=lambda item: item.observed_at_ns)
            anomaly_id = hashlib.sha256(
                canonical_json(
                    {
                        "schema": "stage2-v2-resource-anomaly-id-v1",
                        "run_id": run_id,
                        "task_id": task_id,
                        "category": category,
                        "phase": phase,
                        "metric_name": metric,
                        "threshold": first.threshold,
                    }
                ).encode("utf-8")
            ).hexdigest()
            anomalies.append(
                ResourceAnomalyV1(
                    anomaly_id=anomaly_id,
                    category=category,
                    phase=phase,
                    metric_name=metric,
                    unit=first.unit,
                    threshold=first.threshold,
                    first_observed=first.observed,
                    latest_observed=last.observed,
                    peak_observed=max(item.observed for item in values),
                    first_seen_ns=first.observed_at_ns,
                    last_seen_ns=last.observed_at_ns,
                    sample_count=len(values),
                    duration_ns=max(0, last.observed_at_ns - first.observed_at_ns),
                    action=last.action,
                )
            )
        provisional = cls(
            run_id=run_id,
            task_id=task_id,
            snapshot_id=snapshot_id,
            manifest_hash=manifest_hash,
            config_sha256=config_sha256,
            code_tree_sha256=code_tree_sha256,
            anomalies=tuple(anomalies),
            report_hash=ZERO_SHA256,
        )
        return provisional.model_copy(update={"report_hash": provisional.computed_hash()})


class ResourcePause(RuntimeError):
    """A resource condition that requires checkpointed, authority-bound resume."""

    def __init__(self, reason: str, *, storage: bool = False) -> None:
        super().__init__(reason)
        self.storage = storage
