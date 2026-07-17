"""Read-only semantic release analysis for Stage 2 Group 1 candidate runs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from era100x.research.stage_2.manifests.configuration import research_classification
from era100x.research.stage_2.pipelines.candidates.candidate_finalizer import owner_partition
from era100x.research.stage_2.pipelines.candidates.io import catalog_tree

ID_FIELDS = {
    "raw_key_levels": "raw_key_level_id",
    "canonical_key_levels": "key_level_id",
    "arbitration": "key_level_id",
    "sweeps": "sweep_id",
    "reclaims": "reclaim_id",
    "holds": "hold_id",
    "price_triggers": "trigger_id",
    "flow_features": "flow_feature_set_id",
    "market_episodes": "canonical_candidate_id",
    "candidate_inclusion": "canonical_candidate_id",
    "flow_windows": "canonical_candidate_id",
}

PRICE_DATASETS = {
    "raw_key_levels",
    "canonical_key_levels",
    "arbitration",
    "sweeps",
    "reclaims",
    "holds",
    "price_triggers",
    "market_episodes",
    "candidate_inclusion",
    "flow_windows",
}
FLOW_DATASETS = {"flow_features", "market_episodes", "candidate_inclusion"}


def analyze_release(
    root: Path,
    *,
    expected_partition_count: int,
    checkpoint: dict[str, Any],
    manifest_hash: str,
    require_finalization_reports: bool = True,
) -> dict[str, Any]:
    """Recompute semantic counts and hard publication invariants from Parquet records."""

    catalog = catalog_tree(root)
    datasets: dict[str, dict[str, Any]] = {}
    distributions: dict[str, Counter[str]] = defaultdict(Counter)
    candidate_ids: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    unknown_count = 0
    role_errors: list[str] = []
    ownership_errors: list[str] = []

    entries_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in catalog["entries"]:
        instrument, variant, dataset, partition = _path_dimensions(entry["relative_path"])
        key = f"{instrument}/{variant}/{dataset}"
        entries_by_key[key].append({**entry, "partition": partition})

    for key, entries in sorted(entries_by_key.items()):
        instrument, variant, dataset = key.split("/", 2)
        partition_hashes: dict[str, str] = {}
        partition_id_hashes: dict[str, str] = {}
        row_count = 0
        id_count = 0
        unique_id_count = 0
        id_aggregate = hashlib.sha256()
        for entry in sorted(entries, key=lambda item: item["relative_path"]):
            path = root / entry["relative_path"]
            frame = pl.read_parquet(path)
            rows = [] if "empty_partition" in frame.columns else frame.to_dicts()
            row_count += len(rows)
            partition = str(entry["partition"])
            partition_hashes[partition] = str(entry["logical_sha256"])
            id_field = ID_FIELDS.get(dataset)
            if id_field and rows:
                ids = sorted(str(row[id_field]) for row in rows)
                unique_ids = sorted(set(ids))
                id_count += len(ids)
                unique_id_count += len(unique_ids)
                part_id_hash = hashlib.sha256("\n".join(unique_ids).encode()).hexdigest()
                partition_id_hashes[partition] = part_id_hash
                id_aggregate.update(f"{partition}:{part_id_hash}".encode())
            _inspect_rows(
                rows,
                instrument=instrument,
                variant=variant,
                dataset=dataset,
                partition=partition,
                distributions=distributions,
                candidate_ids=candidate_ids,
                role_errors=role_errors,
                ownership_errors=ownership_errors,
            )
            unknown_count += sum(
                1
                for row in rows
                for field, value in row.items()
                if (field == "status" or field.endswith("_status")) and value == "UNKNOWN"
            )
        datasets[key] = {
            "rows": row_count,
            "partition_count": len(entries),
            "partition_logical_hashes": partition_hashes,
            "id_count": id_count,
            "id_unique_count_within_partitions": unique_id_count,
            "id_duplicate_count_within_partitions": id_count - unique_id_count,
            "id_set_logical_hash": id_aggregate.hexdigest(),
            "partition_id_set_hashes": partition_id_hashes,
        }

    expected_keys = {
        f"{instrument}/{variant}/{dataset}"
        for instrument in ("BTCUSDT", "ETHUSDT")
        for variant, names in (("V1_PRICE", PRICE_DATASETS), ("V1_FLOW", FLOW_DATASETS))
        for dataset in names
    }
    missing_datasets = sorted(expected_keys - datasets.keys())
    bad_partition_counts = {
        key: stats["partition_count"]
        for key, stats in datasets.items()
        if key in expected_keys and stats["partition_count"] != expected_partition_count
    }
    candidate_duplicates = sum(
        message.startswith("duplicate canonical candidate:") for message in role_errors
    )
    inclusion_mismatches = _candidate_inclusion_mismatches(candidate_ids)
    finalization = _finalization_summary(root)
    expected_finalizers = {
        f"{instrument}/{variant}"
        for instrument in ("BTCUSDT", "ETHUSDT")
        for variant in ("V1_PRICE", "V1_FLOW")
    }
    missing_finalizers = (
        sorted(expected_finalizers - finalization["by_instrument_variant"])
        if require_finalization_reports
        else []
    )
    incomplete = sorted(set(checkpoint["planned"]) - set(checkpoint["completed"]))
    errors = list(checkpoint["failed"])
    quality_errors = {
        "missing_datasets": missing_datasets,
        "bad_partition_counts": bad_partition_counts,
        "role_errors": role_errors,
        "ownership_errors": ownership_errors,
        "candidate_inclusion_mismatches": inclusion_mismatches,
        "incomplete_tasks": incomplete,
        "execution_errors": errors,
        "unknown_count": unknown_count,
        "candidate_duplicate_count": candidate_duplicates,
        "identity_conflict_count": finalization["identity_conflict_count"],
        "missing_finalization_reports": missing_finalizers,
    }
    passed = not any(
        value if not isinstance(value, int) else value != 0 for value in quality_errors.values()
    )
    return {
        "schema_name": "stage2-group1-release-analysis-v1",
        "manifest_hash": manifest_hash,
        "catalog_logical_hash": catalog["logical_hash"],
        "catalog_physical_hash": catalog["physical_hash"],
        "datasets": datasets,
        "distributions": {
            name: dict(sorted(counter.items())) for name, counter in sorted(distributions.items())
        },
        "finalization": finalization,
        "quality": {"status": "PASS" if passed else "FAIL", **quality_errors},
    }


def semantic_comparison(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Compare run-independent semantic summaries and return a compact verdict."""

    fields = (
        "manifest_hash",
        "catalog_logical_hash",
        "datasets",
        "distributions",
        "finalization",
        "quality",
    )
    differences = [field for field in fields if left[field] != right[field]]
    return {
        "status": "PASS" if not differences else "FAIL",
        "different_fields": differences,
        "left_logical_hash": left["catalog_logical_hash"],
        "right_logical_hash": right["catalog_logical_hash"],
    }


def _inspect_rows(
    rows: list[dict[str, Any]],
    *,
    instrument: str,
    variant: str,
    dataset: str,
    partition: str,
    distributions: dict[str, Counter[str]],
    candidate_ids: dict[tuple[str, str, str], set[str]],
    role_errors: list[str],
    ownership_errors: list[str],
) -> None:
    for row in rows:
        for field in ("time_combination_id", "research_role", "reason_code", "ownership_status"):
            if field in row:
                distributions[field][str(row[field])] += 1
        parameter = row.get("parameter_set_id", row.get("event_parameter_set_id"))
        if parameter is not None:
            distributions["parameter_set_id"][str(parameter)] += 1
        if "primary_eligible" in row:
            distributions["primary_eligible"][str(bool(row["primary_eligible"])).lower()] += 1
        if dataset in {"market_episodes", "candidate_inclusion"}:
            candidate_id = str(row["canonical_candidate_id"])
            key = (instrument, variant, dataset)
            if candidate_id in candidate_ids[key]:
                role_errors.append(f"duplicate canonical candidate: {key}:{candidate_id}")
            candidate_ids[key].add(candidate_id)
            if row.get("variant_id") != variant or row.get("variant") not in (None, variant):
                role_errors.append(f"variant mismatch: {key}:{candidate_id}")
            timing = str(row["time_combination_id"])
            role, eligible = research_classification(str(parameter), timing)
            if row.get("research_role") != role or bool(row.get("primary_eligible")) != eligible:
                role_errors.append(f"research role mismatch: {key}:{candidate_id}")
            if owner_partition(int(row["available_at_ts"])) != partition:
                ownership_errors.append(f"owner mismatch: {key}:{candidate_id}:{partition}")
            if dataset == "candidate_inclusion" and (
                row.get("included") is not True or row.get("reason_code") != "CANONICAL_INCLUDED"
            ):
                role_errors.append(f"non-canonical formal inclusion: {key}:{candidate_id}")
            if dataset == "market_episodes":
                distributions["candidate_variant_id"][variant] += 1
                distributions["candidate_time_combination_id"][str(row["time_combination_id"])] += 1
                distributions["candidate_parameter_set_id"][str(parameter)] += 1
                distributions["candidate_research_role"][str(row["research_role"])] += 1


def _candidate_inclusion_mismatches(
    candidate_ids: dict[tuple[str, str, str], set[str]],
) -> list[str]:
    mismatches = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for variant in ("V1_PRICE", "V1_FLOW"):
            episodes = candidate_ids[(instrument, variant, "market_episodes")]
            inclusions = candidate_ids[(instrument, variant, "candidate_inclusion")]
            if episodes != inclusions:
                mismatches.append(f"{instrument}/{variant}")
    return mismatches


def _finalization_summary(root: Path) -> dict[str, Any]:
    run_root = root.parents[1]
    by_pair: dict[str, dict[str, Any]] = {}
    totals: Counter[str] = Counter()
    for path in sorted(
        path
        for path in (run_root / "reports").glob("*-V1_*-candidate-finalization.json")
        if not path.name.startswith("._")
    ):
        item = json.loads(path.read_text())
        key = f"{item['instrument']}/{item['variant']}"
        by_pair[key] = item
        for field in (
            "attempt_count",
            "canonical_count",
            "exact_duplicate_excluded_count",
            "identity_conflict_count",
            "out_of_partition_context_count",
            "out_of_period_count",
        ):
            totals[field] += int(item[field])
    fields = (
        "attempt_count",
        "canonical_count",
        "exact_duplicate_excluded_count",
        "identity_conflict_count",
        "out_of_partition_context_count",
        "out_of_period_count",
    )
    return {**{field: totals[field] for field in fields}, "by_instrument_variant": by_pair}


def _path_dimensions(relative: str) -> tuple[str, str, str, str]:
    parts = Path(relative).parts
    instrument = next(
        part.removeprefix("instrument=") for part in parts if part.startswith("instrument=")
    )
    variant = next(part.removeprefix("variant=") for part in parts if part.startswith("variant="))
    variant_index = parts.index(f"variant={variant}")
    dataset = parts[variant_index + 1]
    partition = next(part.removeprefix("date=") for part in parts if part.startswith("date="))
    datetime.fromisoformat(partition).replace(tzinfo=UTC)
    return instrument, variant, dataset, partition
