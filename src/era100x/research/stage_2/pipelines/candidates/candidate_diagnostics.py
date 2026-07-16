"""Read-only legacy candidate identity classification for CR-2026-004."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
import subprocess
from typing import Any

from era100x.research.stage_2.contracts.identity import (
    canonical_candidate_identity,
    canonical_candidate_payload_hash,
)
from era100x.research.stage_2.pipelines.candidates.candidate_finalizer import (
    audit_logical_hash,
    owner_partition,
)


@dataclass(frozen=True)
class LegacyDiagnosis:
    summary: dict[str, Any]
    classifications: list[dict[str, Any]]


def assert_code_commit_matches_head(code_commit: str) -> None:
    current_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if code_commit != current_commit:
        raise ValueError("diagnostic code commit does not match current HEAD")


def classify_legacy_price_records(
    records: list[dict[str, Any]], timing_by_parameter: Mapping[str, str]
) -> LegacyDiagnosis:
    classified = [_classify_row(row, timing_by_parameter) for row in records]
    classified.sort(key=_source_sort_key)
    by_legacy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_payload: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_new: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in classified:
        by_legacy[str(row["legacy_candidate_version_id"])].append(row)
        by_payload[str(row["diagnostic_payload_hash"])].append(row)
        by_new[str(row["canonical_candidate_id"])].append(row)

    case_a_groups = []
    case_c_groups = []
    legacy_excess: list[dict[str, Any]] = []
    for items in by_legacy.values():
        payloads = {str(item["diagnostic_payload_hash"]) for item in items}
        if len(payloads) == 1:
            case_a_groups.append(items)
            for index, item in enumerate(sorted(items, key=_source_sort_key)):
                item["classification"] = (
                    "CANONICAL_INCLUDED" if index == 0 else "EXACT_DUPLICATE_EXCLUDED"
                )
                if index:
                    item["duplicate_of_candidate_id"] = items[0]["canonical_candidate_id"]
                    legacy_excess.append(item)
        else:
            case_c_groups.append(items)
            for index, item in enumerate(sorted(items, key=_source_sort_key)):
                item["classification"] = "LEGACY_IDENTITY_CONFLICT_SPLIT_APPROVED"
                if index:
                    legacy_excess.append(item)

    case_b_groups = [
        items
        for items in by_payload.values()
        if len({str(item["legacy_candidate_version_id"]) for item in items}) > 1
    ]
    new_conflicts = [
        items
        for items in by_new.values()
        if len({str(item["diagnostic_payload_hash"]) for item in items}) > 1
    ]
    new_exact_excess = sum(
        len(items) - 1
        for items in by_new.values()
        if len({str(item["diagnostic_payload_hash"]) for item in items}) == 1
    )
    source_distribution = Counter(str(item["event_parameter_set_id"]) for item in legacy_excess)
    partition_distribution = Counter(
        str(item["source_processing_partition"]) for item in legacy_excess
    )
    ownership = Counter(str(item["ownership_status"]) for item in classified)
    summary = {
        "raw_record_count": len(classified),
        "legacy_identity_count": len(by_legacy),
        "legacy_excess_count": len(classified) - len(by_legacy),
        "case_a_group_count": len(case_a_groups),
        "case_a_row_count": sum(map(len, case_a_groups)),
        "case_a_exact_duplicate_excluded_count": sum(len(items) - 1 for items in case_a_groups),
        "case_b_group_count": len(case_b_groups),
        "case_b_row_count": sum(map(len, case_b_groups)),
        "case_c_group_count": len(case_c_groups),
        "case_c_row_count": sum(map(len, case_c_groups)),
        "canonical_candidate_count": len(by_new),
        "canonical_identity_conflict_count": len(new_conflicts),
        "canonical_exact_duplicate_excess_count": new_exact_excess,
        "ownership_distribution": dict(sorted(ownership.items())),
        "legacy_excess_by_parameter_set": dict(sorted(source_distribution.items())),
        "legacy_excess_by_source_partition": dict(sorted(partition_distribution.items())),
        "classification_logical_hash": audit_logical_hash(classified),
    }
    return LegacyDiagnosis(summary, classified)


def _classify_row(source: dict[str, Any], timing_by_parameter: Mapping[str, str]) -> dict[str, Any]:
    parameter = str(source["event_parameter_set_id"])
    timing = timing_by_parameter.get(parameter)
    if timing is None:
        raise ValueError(f"unknown event parameter set: {parameter}")
    identity_payload = {
        "variant": "V1_PRICE",
        "instrument": source["instrument"],
        "direction": source.get("direction", "LONG"),
        "key_level_id": source["canonical_key_level_id"],
        "sweep_id": source["sweep_id"],
        "reclaim_id": source["reclaim_id"],
        "hold_id": source["hold_id"],
        "price_trigger_id": source["trigger_id"],
        "time_combination_id": timing,
        "event_parameter_set_id": parameter,
        "available_at_ts": int(source["available_at_ts"]),
        "stage1_data_run_id": source["data_run_id"],
        "stage1_instrument_logical_hash": source["dataset_logical_hash"],
        "config_hash": source["config_hash"],
        "flow_feature_set_id": None,
    }
    canonical_id = canonical_candidate_identity(identity_payload)
    payload_hash = canonical_candidate_payload_hash(
        {
            "identity": identity_payload,
            "market_episode_id": source["market_episode_id"],
            "venue": source["venue"],
            "sweep_start_ns": int(source["sweep_start_ns"]),
            "episode_status": source["episode_status"],
        }
    )
    owner = owner_partition(int(source["available_at_ts"]))
    processing = str(source["source_processing_partition"])
    return {
        "legacy_candidate_version_id": source["candidate_version_id"],
        "canonical_candidate_id": canonical_id,
        "diagnostic_payload_hash": payload_hash,
        "market_episode_id": source["market_episode_id"],
        "instrument": source["instrument"],
        "event_parameter_set_id": parameter,
        "time_combination_id": timing,
        "available_at_ts": int(source["available_at_ts"]),
        "owner_partition": owner,
        "ownership_status": "OWNED" if processing == owner else "OUT_OF_PARTITION_CONTEXT",
        "source_processing_partition": processing,
        "source_row_ordinal": int(source["source_row_ordinal"]),
        "source_file_logical_path": source["source_file_logical_path"],
        "classification": "UNCLASSIFIED",
        "duplicate_of_candidate_id": None,
    }


def _source_sort_key(row: dict[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(row["source_processing_partition"]),
        int(row["source_row_ordinal"]),
        str(row["source_file_logical_path"]),
        str(row["diagnostic_payload_hash"]),
    )
