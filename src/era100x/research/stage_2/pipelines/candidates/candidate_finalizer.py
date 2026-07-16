"""Deterministic CR-2026-004 candidate ownership and deduplication finalization."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from era100x.research.stage_2.contracts.identity import canonical_identity_json, stable_id
from era100x.research.stage_2.contracts.models import MarketEpisode

SECOND_NS = 1_000_000_000


class CandidateIdentityConflict(ValueError):
    def __init__(self, conflicts: list[dict[str, Any]]) -> None:
        super().__init__(f"candidate identity conflict: {len(conflicts)} groups")
        self.conflicts = conflicts


@dataclass(frozen=True)
class FinalizedCandidates:
    market_episodes_by_date: dict[str, list[dict[str, Any]]]
    inclusion_by_date: dict[str, list[dict[str, Any]]]
    flow_windows_by_date: dict[str, list[dict[str, Any]]]
    audit_records: list[dict[str, Any]]
    summary: dict[str, Any]


def owner_partition(available_at_ts: int) -> str:
    if available_at_ts < 0:
        raise ValueError("available_at_ts must be non-negative")
    seconds = available_at_ts // SECOND_NS
    return datetime.fromtimestamp(seconds, tz=UTC).date().isoformat()


def partition_bounds(partition: str) -> tuple[int, int]:
    day = date.fromisoformat(partition)
    start = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * SECOND_NS
    return start, start + 86_400 * SECOND_NS


def audit_logical_hash(records: list[dict[str, Any]]) -> str:
    payload = canonical_identity_json(records)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def finalize_candidate_attempts(
    attempts: list[dict[str, Any]], *, include_flow_windows: bool = True
) -> FinalizedCandidates:
    ordered_attempts = sorted(attempts, key=_attempt_sort_key)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in ordered_attempts:
        _validate_attempt(attempt)
        groups[str(attempt["canonical_candidate_id"])].append(attempt)

    conflicts = []
    for canonical_id, items in sorted(groups.items()):
        payloads = sorted({str(item["canonical_payload_hash"]) for item in items})
        if len(payloads) > 1:
            conflicts.append(
                {
                    "canonical_candidate_id": canonical_id,
                    "payload_hashes": payloads,
                    "attempt_count": len(items),
                    "sources": [_source_fields(item) for item in items],
                }
            )
    if conflicts:
        raise CandidateIdentityConflict(conflicts)

    episodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    inclusions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    windows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    audit: list[dict[str, Any]] = []
    exact_duplicates = 0
    out_of_partition_context = 0
    for canonical_id, items in sorted(groups.items()):
        canonical = sorted(items, key=_attempt_sort_key)[0]
        owner = owner_partition(int(canonical["available_at_ts"]))
        episode = {field: canonical[field] for field in MarketEpisode.model_fields}
        MarketEpisode.model_validate(episode)
        episodes[owner].append(episode)
        inclusion = _inclusion_record(canonical, owner)
        inclusions[owner].append(inclusion)
        if include_flow_windows:
            windows[owner].append(_flow_window(canonical, owner))
        for index, item in enumerate(sorted(items, key=_attempt_sort_key)):
            source_owner = str(item["source_processing_partition"]) == owner
            if index == 0 and source_owner:
                audit.append(_audit_record(item, owner, True, "CANONICAL_INCLUDED", None))
            elif index == 0:
                out_of_partition_context += 1
                audit.append(
                    _audit_record(
                        item,
                        owner,
                        False,
                        "OUT_OF_PARTITION_CONTEXT",
                        canonical_id,
                    )
                )
                audit.append(
                    {
                        **_audit_record(item, owner, True, "CANONICAL_REHOMED_TO_OWNER", None),
                        "audit_record_type": "DERIVED_CANONICAL",
                    }
                )
            else:
                exact_duplicates += 1
                if not source_owner:
                    out_of_partition_context += 1
                audit.append(
                    _audit_record(
                        item,
                        owner,
                        False,
                        "EXACT_DUPLICATE_EXCLUDED",
                        canonical_id,
                    )
                )

    for collection in (episodes, inclusions, windows):
        for records in collection.values():
            records.sort(key=lambda row: str(row["canonical_candidate_id"]))
    audit.sort(
        key=lambda row: (
            str(row["canonical_candidate_id"]),
            0 if row["included"] else 1,
            str(row["source_processing_partition"]),
            int(row["source_row_ordinal"]),
            str(row["source_file_logical_path"]),
        )
    )
    summary = {
        "attempt_count": len(attempts),
        "canonical_count": len(groups),
        "exact_duplicate_excluded_count": exact_duplicates,
        "identity_conflict_count": 0,
        "out_of_partition_context_count": out_of_partition_context,
        "included_count": len(groups),
        "audit_logical_hash": audit_logical_hash(audit),
    }
    return FinalizedCandidates(dict(episodes), dict(inclusions), dict(windows), audit, summary)


def _validate_attempt(attempt: dict[str, Any]) -> None:
    required = {
        "canonical_candidate_id",
        "canonical_payload_hash",
        "source_processing_partition",
        "source_row_ordinal",
        "source_file_logical_path",
        "available_at_ts",
    }
    missing = required - attempt.keys()
    if missing:
        raise ValueError(f"candidate attempt missing fields: {sorted(missing)}")
    owner = owner_partition(int(attempt["available_at_ts"]))
    start, end = partition_bounds(owner)
    if not start <= int(attempt["available_at_ts"]) < end:
        raise ValueError("candidate owner partition boundary mismatch")


def _attempt_sort_key(attempt: dict[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(attempt["source_processing_partition"]),
        int(attempt["source_row_ordinal"]),
        str(attempt["source_file_logical_path"]),
        str(attempt["canonical_payload_hash"]),
    )


def _source_fields(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_processing_partition": attempt["source_processing_partition"],
        "source_row_ordinal": attempt["source_row_ordinal"],
        "source_file_logical_path": attempt["source_file_logical_path"],
    }


def _inclusion_record(attempt: dict[str, Any], owner: str) -> dict[str, Any]:
    canonical_id = str(attempt["canonical_candidate_id"])
    return {
        "instrument": attempt["instrument"],
        "data_run_id": attempt["data_run_id"],
        "dataset_logical_hash": attempt["dataset_logical_hash"],
        "config_hash": attempt["config_hash"],
        "code_version": attempt["code_version"],
        "parameter_set_id": attempt["parameter_set_id"],
        "available_at_ts": attempt["available_at_ts"],
        "inclusion_id": stable_id(
            "candidate-inclusion", "v2", canonical_id, attempt["canonical_payload_hash"]
        ),
        "market_episode_id": attempt["market_episode_id"],
        "canonical_candidate_id": canonical_id,
        "candidate_version_id": canonical_id,
        "canonical_payload_hash": attempt["canonical_payload_hash"],
        "variant_id": attempt["variant_id"],
        "time_combination_id": attempt["time_combination_id"],
        "research_role": attempt["research_role"],
        "primary_eligible": attempt["primary_eligible"],
        "included": True,
        "reason_code": "CANONICAL_INCLUDED",
        "deduplication_key": canonical_id,
        "ownership_status": "OWNED",
        "duplicate_of_candidate_id": None,
        "source_processing_partition": attempt["source_processing_partition"],
        "source_row_ordinal": attempt["source_row_ordinal"],
        "source_file_logical_path": attempt["source_file_logical_path"],
        "excluded_reason": None,
        "owner_partition": owner,
    }


def _flow_window(attempt: dict[str, Any], owner: str) -> dict[str, Any]:
    fields = (
        "instrument",
        "direction",
        "canonical_key_level_id",
        "sweep_id",
        "reclaim_id",
        "hold_id",
        "trigger_id",
        "time_combination_id",
        "parameter_set_id",
        "available_at_ts",
        "data_run_id",
        "dataset_logical_hash",
        "config_hash",
        "code_version",
        "venue",
        "sweep_start_ns",
        "market_episode_id",
        "canonical_candidate_id",
        "canonical_payload_hash",
        "variant_id",
        "research_role",
        "primary_eligible",
    )
    return {
        **{field: attempt[field] for field in fields},
        "candidate_version_id": attempt["canonical_candidate_id"],
        "trigger_available_at_ts": attempt["trigger_available_at_ts"],
        "window_start_ts": attempt["window_start_ts"],
        "window_end_ts": attempt["window_end_ts"],
        "event_parameter_set_id": attempt["parameter_set_id"],
        "owner_partition": owner,
    }


def _audit_record(
    attempt: dict[str, Any],
    owner: str,
    included: bool,
    reason: str,
    duplicate_of: str | None,
) -> dict[str, Any]:
    return {
        "audit_record_type": "SOURCE_ATTEMPT",
        "canonical_candidate_id": attempt["canonical_candidate_id"],
        "canonical_payload_hash": attempt["canonical_payload_hash"],
        "market_episode_id": attempt["market_episode_id"],
        "instrument": attempt["instrument"],
        "variant_id": attempt["variant_id"],
        "event_parameter_set_id": attempt["parameter_set_id"],
        "time_combination_id": attempt["time_combination_id"],
        "research_role": attempt["research_role"],
        "primary_eligible": attempt["primary_eligible"],
        "available_at_ts": attempt["available_at_ts"],
        "owner_partition": owner,
        "ownership_status": "OWNED"
        if str(attempt["source_processing_partition"]) == owner
        else "OUT_OF_PARTITION_CONTEXT",
        "included": included,
        "duplicate_of_candidate_id": duplicate_of,
        "source_processing_partition": attempt["source_processing_partition"],
        "source_row_ordinal": attempt["source_row_ordinal"],
        "source_file_logical_path": attempt["source_file_logical_path"],
        "excluded_reason": None if included else reason,
        "reason_code": reason,
    }
