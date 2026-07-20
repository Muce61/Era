from __future__ import annotations

from era100x.research.stage_2.runtime_v2.resource_anomalies import (
    ResourceCategory,
    ResourceAnomalyReportV1,
    ResourceThresholdObservation,
)
from era100x.research.stage_2.runtime_v2.memory import ProcessMemoryBudget
from era100x.research.stage_2.runtime_v2.production_backend import (
    EvidenceFileBinding,
    PublicationQualityReport,
    TaskAggregateEvidence,
)

H = "a" * 64


def _report(observations: tuple[ResourceThresholdObservation, ...]) -> ResourceAnomalyReportV1:
    return ResourceAnomalyReportV1.seal(
        run_id="stage2-g1-v2-b-fixture",
        task_id="FOUNDATION:BTCUSDT",
        snapshot_id=H,
        manifest_hash=H,
        config_sha256=H,
        code_tree_sha256=H,
        observations=observations,
    )


def test_anomaly_id_is_stable_across_sample_order_and_observed_value() -> None:
    first = ResourceThresholdObservation(
        category="MEMORY_RSS",
        phase="packing",
        metric_name="CURRENT_RSS_DELTA_BYTES",
        unit="bytes",
        threshold=100,
        observed=120,
        observed_at_ns=10,
    )
    second = ResourceThresholdObservation(
        category="MEMORY_RSS",
        phase="packing",
        metric_name="CURRENT_RSS_DELTA_BYTES",
        unit="bytes",
        threshold=100,
        observed=150,
        observed_at_ns=20,
    )

    forward = _report((first, second)).anomalies[0]
    reverse = _report((second, first)).anomalies[0]

    assert forward.anomaly_id == reverse.anomaly_id
    assert forward.peak_observed == reverse.peak_observed == 150
    assert forward.sample_count == 2
    assert forward.semantic_impact == "NONE"


def test_resource_report_hash_is_audit_only_and_reproducible() -> None:
    observation = ResourceThresholdObservation(
        category="SHARD_SIZE",
        phase="release",
        metric_name="PACKED_OBJECT_BYTES",
        unit="bytes",
        threshold=512,
        observed=513,
        observed_at_ns=10,
    )

    first = _report((observation,))
    second = _report((observation,))

    assert first == second
    assert first.report_hash == first.computed_hash()
    assert first.integrity_impact == "NONE"


def test_resource_audit_metadata_does_not_change_task_semantic_hash() -> None:
    common = {
        "task_id": "FOUNDATION:BTCUSDT",
        "snapshot_id": H,
        "manifest_hash": H,
        "artifacts": (),
        "receipts": (),
        "fragments": (),
        "seals": (),
        "global_distributions": (),
        "quality_status": "PASS",
    }
    normal = TaskAggregateEvidence.seal(
        {
            **common,
            "max_inflight_bytes_observed": 1,
            "peak_process_rss_bytes": 1,
            "resource_anomaly_count": 0,
        }
    )
    anomalous = TaskAggregateEvidence.seal(
        {
            **common,
            "supporting_evidence": (
                EvidenceFileBinding(
                    relative_path="staging/evidence/resource-anomalies/foundation.json",
                    physical_sha256=H,
                ),
            ),
            "max_inflight_bytes_observed": 2_000_000_000,
            "peak_process_rss_bytes": 4_000_000_000,
            "resource_anomaly_count": 3,
        }
    )

    assert anomalous.semantic_sha256 == normal.semantic_sha256
    assert anomalous.evidence_hash != normal.evidence_hash


def test_quality_report_accepts_resource_anomalies_and_more_than_200_objects() -> None:
    report = PublicationQualityReport.seal(
        {
            "run_id": "stage2-g1-v2-b-fixture",
            "snapshot_id": H,
            "manifest_hash": H,
            "catalog_hash": H,
            "partition_count": 80_784,
            "object_count": 316,
            "fragment_count": 80_784,
            "seal_count": 316,
            "resource_anomaly_count": 7,
            "task_evidence_hashes": tuple(H for _ in range(6)),
        }
    )

    assert report.quality_status == "PASS"
    assert report.object_count == 316
    assert report.resource_anomaly_count == 7


def test_every_resource_threshold_category_is_audit_only() -> None:
    budget = ProcessMemoryBudget(current_reader=lambda: 0, peak_reader=lambda: 0)
    categories: tuple[ResourceCategory, ...] = (
        "MEMORY_RSS",
        "ARROW_INFLIGHT",
        "SHARD_SIZE",
        "OBJECT_COUNT",
        "DISK_CAPACITY",
        "STORAGE_AVAILABILITY",
        "PERFORMANCE",
        "MONITOR_STALL",
    )

    for category in categories:
        budget.observe_threshold(
            category=category,
            phase="repository audit",
            metric_name=f"{category}_TEST",
            threshold=1,
            observed=2,
        )

    assert {item.category for item in budget.drain_anomalies()} == set(categories)
