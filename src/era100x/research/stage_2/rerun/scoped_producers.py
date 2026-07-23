"""Explicit-input production cores shared by rehearsal and future formal runs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.labels.first_passage.full_run import (
    COMBINATION_ORDER,
    COMBINATIONS_PER_PATH,
    _build_instrument as build_first_passage,
)
from era100x.research.stage_2.metrics.path.full_run import (
    _build_instrument as build_path_metrics,
)
from era100x.research.stage_2.metrics.path.full_run import (
    _reference_prices as reference_prices,
)
from era100x.research.stage_2.paths.extraction.full_run import (
    EPISODE_SPEC_HASHES,
    FIXED_SNAPSHOT_ID,
    FIXED_SNAPSHOT_ROOT,
    STAGE1_CATALOG_ROOT,
    STAGE1_RUN_ID,
    _h1_partitions,
    _h2_row_groups,
    _stage1_quality,
    build_instrument_outputs,
)
from era100x.research.stage_2.runtime_v2.catalog import CatalogReaderV2

INSTRUMENTS = ("BTCUSDT", "ETHUSDT")
ACTIVATION_THRESHOLDS = (
    Decimal("5"),
    Decimal("10"),
    Decimal("15"),
    Decimal("20"),
    Decimal("30"),
    Decimal("40"),
    Decimal("50"),
    Decimal("70"),
    Decimal("100"),
)


def _ns(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp()) * 1_000_000_000


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_summary(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file()
        and not any(part.startswith("._") for part in item.relative_to(root).parts)
    ):
        files.append(
            {
                "relative_path": str(path.relative_to(root)),
                "byte_size": path.stat().st_size,
                "sha256": _hash_file(path),
                "row_count": (
                    pq.ParquetFile(path).metadata.num_rows if path.suffix == ".parquet" else None
                ),
            }
        )
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {
        "files": files,
        "file_count": len(files),
        "row_count": sum(int(item["row_count"] or 0) for item in files),
        "output_hash": hashlib.sha256(encoded).hexdigest(),
    }


def produce_scoped_paths(
    *,
    output_root: Path,
    start_date: date,
    end_date_exclusive: date,
) -> dict[str, Any]:
    """Run the real path extractor over scoped T10 episodes."""

    output_root.mkdir(parents=True, exist_ok=False)
    reader = CatalogReaderV2.open(
        FIXED_SNAPSHOT_ROOT,
        expected_snapshot_id=FIXED_SNAPSHOT_ID,
        deep_verify_objects=False,
    )
    h1 = _h1_partitions(reader)
    h2 = _h2_row_groups(reader)
    quality = _stage1_quality(STAGE1_CATALOG_ROOT)
    reports = []
    for instrument in INSTRUMENTS:
        reports.append(
            build_instrument_outputs(
                reader=reader,
                instrument=cast(Any, instrument),
                destination=output_root / instrument,
                h1=h1,
                h2=h2,
                quality=quality,
                scope_start_ns=_ns(start_date),
                scope_end_ns=_ns(end_date_exclusive),
                source_snapshot_id=FIXED_SNAPSHOT_ID,
                stage1_data_run_id=STAGE1_RUN_ID,
            )
        )
    tree = _tree_summary(output_root)
    return {
        "task_id": "S2P13-T12",
        "source_task": "S2-T10",
        "t11_pass_gate_bound": True,
        "t11_result_rows_consumed": False,
        "episode_spec_hashes": list(EPISODE_SPEC_HASHES),
        "reports": reports,
        **tree,
        "row_count": sum(int(item["episode_count"]) for item in reports),
    }


def _source_binding(
    *,
    snapshot_id: str,
    manifest_hash: str,
    catalog_hash: str,
) -> dict[str, str]:
    return {
        "source_s2t11_snapshot_id": snapshot_id,
        "source_s2t11_manifest_hash": manifest_hash,
        "source_s2t11_catalog_hash": catalog_hash,
    }


def produce_scoped_metrics(
    *,
    output_root: Path,
    source_paths_root: Path,
    source_snapshot_id: str,
    source_manifest_hash: str,
    source_catalog_hash: str,
) -> dict[str, Any]:
    """Run the real metric core against the current T12 handoff."""

    output_root.mkdir(parents=True, exist_ok=False)
    references = reference_prices(
        source_s2t10_snapshot_root=FIXED_SNAPSHOT_ROOT,
        source_s2t10_snapshot_id=FIXED_SNAPSHOT_ID,
    )
    source = _source_binding(
        snapshot_id=source_snapshot_id,
        manifest_hash=source_manifest_hash,
        catalog_hash=source_catalog_hash,
    )
    reports = [
        build_path_metrics(
            cast(Any, instrument),
            output_root / instrument / "path_metrics.parquet",
            thresholds=ACTIVATION_THRESHOLDS,
            source=source,
            references=references,
            source_s2t11_snapshot_root=source_paths_root,
            source_s2t10_snapshot_root=FIXED_SNAPSHOT_ROOT,
            source_s2t10_snapshot_id=FIXED_SNAPSHOT_ID,
        )
        for instrument in INSTRUMENTS
    ]
    return {"task_id": "S2P13-T13", "reports": reports, **_tree_summary(output_root)}


def produce_scoped_first_passage(
    *,
    output_root: Path,
    source_paths_root: Path,
    source_snapshot_id: str,
    source_manifest_hash: str,
    source_catalog_hash: str,
) -> dict[str, Any]:
    """Run the real First Passage core independently from T13 metrics."""

    output_root.mkdir(parents=True, exist_ok=False)
    references = reference_prices(
        source_s2t10_snapshot_root=FIXED_SNAPSHOT_ROOT,
        source_s2t10_snapshot_id=FIXED_SNAPSHOT_ID,
    )
    source = _source_binding(
        snapshot_id=source_snapshot_id,
        manifest_hash=source_manifest_hash,
        catalog_hash=source_catalog_hash,
    )
    reports = [
        build_first_passage(
            cast(Any, instrument),
            output_root / instrument / "first_passage.parquet",
            source=source,
            references=references,
            source_s2t11_snapshot_root=source_paths_root,
            source_s2t10_snapshot_root=FIXED_SNAPSHOT_ROOT,
        )
        for instrument in INSTRUMENTS
    ]
    return {"task_id": "S2P13-T14", "reports": reports, **_tree_summary(output_root)}


def produce_scoped_ambiguity(
    *,
    output_root: Path,
    source_first_passage_root: Path,
) -> dict[str, Any]:
    """Aggregate the current T14 matrices without joining any old T13 Run."""

    output_root.mkdir(parents=True, exist_ok=False)
    reports: list[dict[str, Any]] = []
    for instrument in INSTRUMENTS:
        path = source_first_passage_root / instrument / "first_passage.parquet"
        labels: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        groups: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
        row_count = 0
        classification_count = 0
        for batch in pq.ParquetFile(path).iter_batches(batch_size=2_000):
            for row in batch.to_pylist():
                if (
                    row["combination_order"] != list(COMBINATION_ORDER)
                    or int(row["classification_count"]) != COMBINATIONS_PER_PATH
                ):
                    raise ValueError("First Passage matrix contract drift")
                row_count += 1
                for label, reason in zip(row["labels"], row["label_reasons"], strict=True):
                    labels[str(label)] += 1
                    reasons[str(reason)] += 1
                    groups[
                        (
                            str(row["evidence_level"]),
                            str(row["parameter_set_id"]),
                            str(row["timing_id"]),
                        )
                    ][str(label)] += 1
                    classification_count += 1
        report = {
            "instrument": instrument,
            "path_rows": row_count,
            "classification_count": classification_count,
            "label_counts": dict(sorted(labels.items())),
            "label_reason_counts": dict(sorted(reasons.items())),
            "group_count": len(groups),
            "primary_ambiguous_policy": "FAILURE",
            "historical_evidence_only": True,
        }
        path_out = output_root / instrument / "ambiguity-summary.json"
        path_out.parent.mkdir(parents=True)
        path_out.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        reports.append(report)
    tree = _tree_summary(output_root)
    return {
        "task_id": "S2P13-T15",
        "reports": reports,
        **tree,
        "row_count": sum(int(item["path_rows"]) for item in reports),
    }
