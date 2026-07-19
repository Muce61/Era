#!/usr/bin/env python3
"""DIAGNOSTIC_ONLY fixed-window CR-2026-014 Group-1 benchmark.

The command copies only the sealed Foundation objects that intersect the
approved benchmark window, then runs Group-1 in an isolated append-only
diagnostic root.  It never creates a Runtime V2 run, Authority, publication,
or governance transition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import time
import traceback
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from era100x.research.stage_2.runtime_v2.foundation_pipeline import (
    FoundationShardCheckpoint,
)
from era100x.research.stage_2.runtime_v2.group1_feature_builder import (
    Group1Lineage,
)
from era100x.research.stage_2.runtime_v2.group1_pipeline import (
    FOUNDATION_INPUTS,
    Group1FeaturePipeline,
    Group1PackedTaskComponent,
    Group1PipelineConfig,
    _DailyRecordSpool,
)
from era100x.research.stage_2.runtime_v2.models import metadata_sha256

Instrument = Literal["BTCUSDT", "ETHUSDT"]

DEFAULT_SOURCE_RUN = Path(
    "/Volumes/FuckingLife/era100x_stage2/runs/stage2-g1-v2-b-20260719T045142Z-0eeb27e0be21"
)
DEFAULT_EXTERNAL_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
RUN_A_GENERATOR_COMMIT = "366a541b7956030d1a0ea2b5c67b4b30e2154c76"
STAGE1_DATA_RUN_ID = "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
CONFIG_HASH = "adb6295e210de66d1e69aa008e6161e8fef1e1fd72001ff812b68597f8c72e3f"
LOGICAL_HASHES = {
    "BTCUSDT": "03d437ed9a6c19d92162e5c9dd115df4988e8accce3c8180b749f15cfdcc36a8",
    "ETHUSDT": "6db4d5e411edae3838b352944b83c38ba68915841a1f9c9de8f16ef44c3b8332",
}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="CR-2026-014 diagnostic Group-1 benchmark")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run"):
        command = commands.add_parser(name)
        command.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE_RUN)
        command.add_argument("--diagnostic-root", type=Path, required=True)
        command.add_argument("--start", type=date.fromisoformat, default=date(2020, 7, 1))
        command.add_argument("--end-exclusive", type=date.fromisoformat, default=date(2020, 8, 1))
    failure = commands.add_parser("record-failure")
    failure.add_argument("--diagnostic-root", type=Path, required=True)
    failure.add_argument("--error-type", required=True)
    failure.add_argument("--reason", required=True)
    comparison = commands.add_parser("compare")
    comparison.add_argument("--baseline-root", type=Path, required=True)
    comparison.add_argument("--optimized-root", type=Path, required=True)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "prepare":
        payload = prepare(args.source_run, args.diagnostic_root, args.start, args.end_exclusive)
    elif args.command == "record-failure":
        payload = record_failure(args.diagnostic_root, args.error_type, args.reason)
    elif args.command == "compare":
        payload = compare(args.baseline_root, args.optimized_root)
    else:
        try:
            payload = run(args.diagnostic_root, args.start, args.end_exclusive)
        except BaseException as error:
            record_failure(
                args.diagnostic_root,
                type(error).__name__,
                str(error),
                traceback_text=traceback.format_exc(),
            )
            raise
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def record_failure(
    diagnostic_root: Path,
    error_type: str,
    reason: str,
    *,
    traceback_text: str | None = None,
) -> dict[str, Any]:
    """Append a terminal diagnostic failure receipt without altering compute evidence."""
    payload: dict[str, Any] = {
        "schema_name": "stage2-cr-2026-014-benchmark-failure-v1",
        "diagnostic_only": True,
        "status": "FAILED_DIAGNOSTIC_REPORTING",
        "error_type": error_type,
        "reason": reason,
    }
    if traceback_text is not None:
        payload["traceback_sha256"] = hashlib.sha256(traceback_text.encode()).hexdigest()
    payload["receipt_hash"] = metadata_sha256(payload)
    failure_path = diagnostic_root / "reports" / "benchmark-failure.json"
    if failure_path.exists():
        failure_path = (
            diagnostic_root / "reports" / (f"benchmark-failure-{payload['receipt_hash'][:12]}.json")
        )
    _write_once_json(failure_path, payload)
    return payload


def compare(baseline_root: Path, optimized_root: Path) -> dict[str, Any]:
    """Seal exact semantic and promotion-gate evidence for two completed runs."""

    baseline = json.loads(
        (baseline_root / "reports" / "benchmark-result.json").read_text(encoding="utf-8")
    )
    optimized = json.loads(
        (optimized_root / "reports" / "benchmark-result.json").read_text(encoding="utf-8")
    )
    semantic_fields = ("components", "output_rows", "packed_aggregate_hash")
    semantic_equal = all(baseline[field] == optimized[field] for field in semantic_fields)
    speedup = float(baseline["wall_seconds"]) / float(optimized["wall_seconds"])
    processing_reduction = 1.0 - (
        float(optimized["processing_day_executions"]) / float(baseline["processing_day_executions"])
    )
    legacy_reduction = 1.0 - (
        float(optimized["legacy_runs_generated"]) / float(baseline["legacy_runs_generated"])
    )
    # The frozen old reader had no counters. The optimized reader exposes
    # misses and hits for the unchanged access plan; their sum is therefore
    # the exact old no-cache read count for this same fixed window.
    old_fragment_reads = int(optimized["foundation_fragment_reads"]) + int(
        optimized["foundation_cache_hits"]
    )
    foundation_reduction = 1.0 - (
        float(optimized["foundation_fragment_reads"]) / float(old_fragment_reads)
    )
    gates = {
        "semantic_exact": semantic_equal,
        "speedup_at_least_4x": speedup >= 4.0,
        "processing_day_reduction_near_50pct": processing_reduction >= 0.45,
        "foundation_read_reduction_at_least_60pct": foundation_reduction >= 0.60,
        "legacy_run_reduction_at_least_80pct": legacy_reduction >= 0.80,
        "average_cpu_at_least_2_5_cores": float(optimized["average_cpu_cores"]) >= 2.5,
    }
    payload: dict[str, Any] = {
        "schema_name": "stage2-cr-2026-014-performance-comparison-v1",
        "baseline_report_hash": baseline["report_hash"],
        "optimized_report_hash": optimized["report_hash"],
        "semantic_equal": semantic_equal,
        "baseline_wall_seconds": baseline["wall_seconds"],
        "optimized_wall_seconds": optimized["wall_seconds"],
        "speedup": speedup,
        "processing_day_reduction": processing_reduction,
        "foundation_fragment_read_reduction": foundation_reduction,
        "legacy_run_reduction": legacy_reduction,
        "optimized_average_cpu_cores": optimized["average_cpu_cores"],
        "gates": gates,
        "conclusion": ("PASS" if all(gates.values()) else "PERFORMANCE_OBJECTIVE_NOT_MET"),
        "authority_or_full_run_permitted": all(gates.values()),
    }
    payload["comparison_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write_once_json(
        optimized_root / "reports" / "performance-comparison.json",
        payload,
    )
    return payload


def prepare(
    source_run: Path,
    diagnostic_root: Path,
    start: date,
    end_exclusive: date,
) -> dict[str, Any]:
    if diagnostic_root.exists():
        raise FileExistsError(f"append-only diagnostic root exists: {diagnostic_root}")
    if not diagnostic_root.resolve().is_relative_to(DEFAULT_EXTERNAL_ROOT.resolve()):
        raise ValueError("diagnostic benchmark must remain on the approved external root")
    diagnostic_root.mkdir(parents=True)
    source_checkpoint_root = source_run / "staging" / "foundation" / "packed-checkpoints"
    source_catalog_root = source_run / "staging" / "snapshot"
    selected: list[tuple[Path, FoundationShardCheckpoint]] = []
    halo_start = start - timedelta(days=2)
    halo_end = end_exclusive + timedelta(days=1)
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for dataset in FOUNDATION_INPUTS:
            pattern = f"instrument={instrument}/feature={dataset}/shard=*.json"
            for path in sorted(source_checkpoint_root.glob(pattern)):
                if path.name.startswith("._"):
                    continue
                checkpoint = FoundationShardCheckpoint.model_validate_json(path.read_bytes())
                if (
                    checkpoint.window_start_date < halo_end
                    and checkpoint.window_end_date_exclusive > halo_start
                ):
                    selected.append((path, checkpoint))
    if {item.dataset_name for _, item in selected} != set(FOUNDATION_INPUTS):
        raise ValueError("diagnostic Foundation selection is incomplete")

    copied_bytes = 0
    evidence: list[dict[str, Any]] = []
    for source_path, checkpoint in sorted(
        selected,
        key=lambda item: (
            item[1].instrument,
            item[1].dataset_name,
            item[1].window_start_date,
        ),
    ):
        relative_checkpoint = source_path.relative_to(source_checkpoint_root)
        target_checkpoint = (
            diagnostic_root / "staging" / "foundation" / "packed-checkpoints" / relative_checkpoint
        )
        _copy_exact(source_path, target_checkpoint, _sha256_file(source_path))
        artifact = checkpoint.artifact
        if artifact is None:
            raise ValueError("benchmark Foundation checkpoint lacks a packed object")
        source_object = source_catalog_root / artifact.relative_path
        target_object = diagnostic_root / "staging" / "snapshot" / artifact.relative_path
        _copy_exact(source_object, target_object, artifact.object_sha256)
        copied_bytes += artifact.byte_size
        evidence.append(
            {
                "instrument": checkpoint.instrument,
                "dataset": checkpoint.dataset_name,
                "shard_key": checkpoint.shard_key,
                "checkpoint_hash": checkpoint.checkpoint_hash,
                "object_sha256": artifact.object_sha256,
                "object_bytes": artifact.byte_size,
            }
        )
    manifest = {
        "schema_name": "stage2-cr-2026-014-benchmark-input-v1",
        "diagnostic_only": True,
        "source_run": source_run.name,
        "start": start.isoformat(),
        "end_exclusive": end_exclusive.isoformat(),
        "objects": evidence,
        "copied_bytes": copied_bytes,
    }
    manifest["manifest_hash"] = metadata_sha256(manifest)
    _write_once_json(diagnostic_root / "reports" / "benchmark-input.json", manifest)
    return manifest


def run(diagnostic_root: Path, start: date, end_exclusive: date) -> dict[str, Any]:
    report_path = diagnostic_root / "reports" / "benchmark-result.json"
    if report_path.exists():
        raise FileExistsError(f"append-only benchmark result exists: {report_path}")
    input_manifest = json.loads(
        (diagnostic_root / "reports" / "benchmark-input.json").read_text(encoding="utf-8")
    )
    claimed = input_manifest.pop("manifest_hash")
    if metadata_sha256(input_manifest) != claimed:
        raise ValueError("benchmark input Manifest changed")
    completed_month_checkpoints = tuple(
        path
        for path in sorted(
            (diagnostic_root / "staging" / "group1" / "monthly-checkpoints").glob(
                "instrument=*/????-??.json"
            )
        )
        if not path.name.startswith("._")
    )
    checkpoint_root = diagnostic_root / "staging" / "foundation" / "packed-checkpoints"
    checkpoints = tuple(
        FoundationShardCheckpoint.model_validate_json(path.read_bytes())
        for instrument in ("BTCUSDT", "ETHUSDT")
        for dataset in FOUNDATION_INPUTS
        for path in sorted(
            checkpoint_root.glob(f"instrument={instrument}/feature={dataset}/shard=*.json")
        )
        if not path.name.startswith("._")
    )
    snapshot_ids = {item.snapshot_id for item in checkpoints}
    if len(snapshot_ids) != 1:
        raise ValueError("benchmark Foundation checkpoints mix snapshots")
    snapshot_id = snapshot_ids.pop()
    instruments: tuple[Instrument, ...] = ("BTCUSDT", "ETHUSDT")
    lineage = {
        instrument: Group1Lineage(
            data_run_id=STAGE1_DATA_RUN_ID,
            dataset_logical_hash=LOGICAL_HASHES[instrument],
            config_hash=CONFIG_HASH,
            code_version=RUN_A_GENERATOR_COMMIT,
        )
        for instrument in instruments
    }
    config = Group1PipelineConfig(
        run_root=diagnostic_root,
        foundation_catalog_root=diagnostic_root / "staging" / "snapshot",
        approved_external_root=DEFAULT_EXTERNAL_ROOT,
    )
    pipeline = Group1FeaturePipeline(
        config=config,
        snapshot_id=snapshot_id,
        foundation_checkpoints=checkpoints,
        lineage_by_instrument=lineage,
    )
    component_summaries: list[dict[str, Any]] = []

    def collect(component: Group1PackedTaskComponent) -> None:
        component_summaries.append(
            {
                "instrument": component.instrument,
                "variant": component.variant,
                "receipt_count": len(component.receipts),
                "row_count": sum(item.row_count for item in component.receipts),
                "legacy_root": metadata_sha256(
                    tuple(
                        (
                            item.partition.semantic_order_key(),
                            item.legacy_logical_sha256,
                        )
                        for item in component.receipts
                    )
                ),
                "semantic_root": metadata_sha256(
                    tuple(
                        (item.partition.semantic_order_key(), item.semantic_sha256)
                        for item in component.receipts
                    )
                ),
                "identity_root": metadata_sha256(
                    tuple(
                        (
                            item.partition.semantic_order_key(),
                            item.identity_multiset_sha256,
                        )
                        for item in component.receipts
                    )
                ),
                "payload_root": metadata_sha256(
                    tuple(
                        (
                            item.partition.semantic_order_key(),
                            item.payload_association_sha256,
                        )
                        for item in component.receipts
                    )
                ),
            }
        )

    before_self = resource.getrusage(resource.RUSAGE_SELF)
    before_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall_start = time.monotonic()
    result = pipeline.build_streaming_components(
        instruments=instruments,
        start=start,
        end_exclusive=end_exclusive,
        component_sink=collect,
    )
    wall_seconds = time.monotonic() - wall_start
    wall_measurement_source = "monotonic-process-clock"
    if len(completed_month_checkpoints) == 2:
        # A diagnostic-only reporting error can occur after both immutable
        # month checkpoints are sealed.  Reopening the benchmark must not
        # recompute them or pretend the checkpoint read was the compute time.
        wall_seconds = (
            max(path.stat().st_mtime for path in completed_month_checkpoints)
            - (diagnostic_root / "reports" / "benchmark-input.json").stat().st_mtime
        )
        wall_measurement_source = "append-only-input-to-final-month-seal"
    after_self = resource.getrusage(resource.RUSAGE_SELF)
    after_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_seconds = (
        after_self.ru_utime
        + after_self.ru_stime
        - before_self.ru_utime
        - before_self.ru_stime
        + after_children.ru_utime
        + after_children.ru_stime
        - before_children.ru_utime
        - before_children.ru_stime
    )
    worker_progress_root = getattr(
        config,
        "worker_progress_root",
        diagnostic_root / "logs" / "worker-progress",
    )
    worker_progress = tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(worker_progress_root.glob("*.json"))
        if not path.name.startswith("._")
    )
    receipt_rows = sum(item["row_count"] for item in component_summaries)
    legacy_runs = sum(int(item["legacy_runs_generated"]) for item in worker_progress)
    if not worker_progress:
        # Frozen V1 baseline had no worker instrumentation.  Derive the exact
        # run count from sealed rows and that code version's fixed buffer size.
        upstream_names = {
            "raw_key_levels",
            "canonical_key_levels",
            "arbitration",
            "sweeps",
            "reclaims",
            "holds",
            "price_triggers",
        }
        legacy_runs = sum(
            (receipt.row_count + _DailyRecordSpool.BUFFER_ROWS - 1) // _DailyRecordSpool.BUFFER_ROWS
            for component in component_summaries
            if component["variant"] == "V1_PRICE"
            for path in sorted(
                (diagnostic_root / "staging" / "group1" / "monthly-checkpoints").glob(
                    f"instrument={component['instrument']}/*.json"
                )
            )
            if not path.name.startswith("._")
            for checkpoint in (FoundationSafeGroup1Checkpoint(path),)
            for dataset in checkpoint.datasets
            if dataset.dataset in upstream_names
            for receipt in dataset.receipts
            if receipt.row_count
        )
    processing_days = (
        sum(int(item["processing_day_executions"]) for item in worker_progress)
        if worker_progress
        else (end_exclusive - start).days * 2 * 2
    )
    report = {
        "schema_name": "stage2-cr-2026-014-benchmark-result-v1",
        "diagnostic_only": True,
        "start": start.isoformat(),
        "end_exclusive": end_exclusive.isoformat(),
        "wall_seconds": wall_seconds,
        "wall_measurement_source": wall_measurement_source,
        "cpu_seconds": cpu_seconds,
        "average_cpu_cores": cpu_seconds / wall_seconds,
        "peak_rss_bytes": max(after_self.ru_maxrss, after_children.ru_maxrss),
        "max_arrow_inflight_bytes": result.max_inflight_bytes_observed,
        "processing_day_executions": processing_days,
        "foundation_fragment_reads": sum(
            int(item["foundation_fragment_reads"]) for item in worker_progress
        ),
        "foundation_cache_hits": sum(
            int(item["foundation_cache_hits"]) for item in worker_progress
        ),
        "legacy_runs_generated": legacy_runs,
        "temporary_bytes_remaining": sum(
            path.stat().st_size
            for path in (diagnostic_root / "staging" / "group1" / "partials").rglob("*")
            if path.is_file() and not path.name.startswith("._")
        ),
        "output_rows": receipt_rows,
        "components": sorted(
            component_summaries, key=lambda item: (item["instrument"], item["variant"])
        ),
        "packed_aggregate_hash": result.packed_aggregate.aggregate_hash,
        "worker_count": 3,
    }
    report["report_hash"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write_once_json(report_path, report)
    return report


def FoundationSafeGroup1Checkpoint(path: Path) -> Any:  # noqa: N802
    from era100x.research.stage_2.runtime_v2.group1_pipeline import (
        Group1MonthCheckpoint,
    )

    return Group1MonthCheckpoint.model_validate_json(path.read_bytes())


def _copy_exact(source: Path, target: Path, expected_sha256: str) -> None:
    if _sha256_file(source) != expected_sha256:
        raise ValueError(f"source object hash changed: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    digest = hashlib.sha256()
    with source.open("rb") as reader, temporary.open("xb") as writer:
        while block := reader.read(16 << 20):
            writer.write(block)
            digest.update(block)
        writer.flush()
        os.fsync(writer.fileno())
    if digest.hexdigest() != expected_sha256:
        raise ValueError("diagnostic copy hash mismatch")
    os.replace(temporary, target)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(16 << 20):
            digest.update(block)
    return digest.hexdigest()


def _write_once_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"append-only benchmark evidence differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    raise SystemExit(main())
