"""Exact V1 Run-A to V2 owner-day semantic compatibility.

The cross-implementation proof deliberately excludes snapshot identifiers,
physical paths, Parquet hashes, compression facts, and fragment layout.  Run A
and V2 instead bind the same complete canonical-row hash for every logical UTC
owner day.  Equality of that hash proves the identity-to-payload association and
all row-level ownership/role/timing/parameter/reason facts without rereading the
formal Run-A Parquet publication.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Literal, cast

from era100x.research.stage_2.manifests.models import canonical_json

from .errors import ContractViolation
from .models import Receipt

LEGACY_HASH_ALGORITHM: Literal["era-canonical-json-row-v1"] = "era-canonical-json-row-v1"
V2_RECEIPT_LEGACY_HASH_ALGORITHM = "ERA_CANONICAL_JSON_ROW_V1"
PAYLOAD_AND_DISTRIBUTION_PROOF: Literal["CANONICAL_ROW_HASH_EQUALITY"] = (
    "CANONICAL_ROW_HASH_EQUALITY"
)
FORMAL_RUN_A_CATALOG_ENTRY_COUNT = 61_776
FORMAL_PERIOD_START = date(2020, 1, 1)
FORMAL_PERIOD_END_EXCLUSIVE = date(2026, 7, 4)
LEGACY_ID_SET_QUALITY_FACT = "legacy_id_set_sha256"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_REQUIRED_GLOBAL_DISTRIBUTIONS = frozenset(
    {
        "ownership_status",
        "research_role",
        "time_combination_id",
        "parameter_set_id",
        "reason_code",
    }
)
_PRICE_DATASETS = frozenset(
    {
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
)
_FLOW_DATASETS = frozenset(
    {
        "flow_features",
        "market_episodes",
        "candidate_inclusion",
    }
)
_FORMAL_GROUPS = frozenset(
    (instrument, variant, dataset)
    for instrument in ("BTCUSDT", "ETHUSDT")
    for variant, datasets in (("V1_PRICE", _PRICE_DATASETS), ("V1_FLOW", _FLOW_DATASETS))
    for dataset in datasets
)


class CompatibilityMismatch(ContractViolation):
    """The two complete logical projections are not exactly equivalent."""

    def __init__(self, report: CompatibilityReport) -> None:
        self.report = report
        super().__init__(
            "Run A/V2 compatibility failed: "
            f"missing={len(report.missing_in_v2)}, extra={len(report.extra_in_v2)}, "
            f"differences={len(report.differences)}"
        )


@dataclass(frozen=True, slots=True, order=True)
class DailySemanticKey:
    instrument: str
    variant: str
    dataset: str
    owner_date: date

    @property
    def label(self) -> str:
        return f"{self.instrument}/{self.variant}/{self.dataset}/{self.owner_date.isoformat()}"


@dataclass(frozen=True, slots=True)
class DailySemanticRecord:
    key: DailySemanticKey
    row_count: int
    empty: bool
    legacy_logical_sha256: str
    legacy_id_set_sha256: str | None
    payload_and_distribution_proof: Literal["CANONICAL_ROW_HASH_EQUALITY"] = (
        "CANONICAL_ROW_HASH_EQUALITY"
    )

    def __post_init__(self) -> None:
        if isinstance(self.row_count, bool) or self.row_count < 0:
            raise ContractViolation("daily row_count must be a non-negative integer")
        if self.empty != (self.row_count == 0):
            raise ContractViolation("daily empty flag must equal row_count == 0")
        _require_sha256(self.legacy_logical_sha256, "legacy_logical_sha256")
        if self.legacy_id_set_sha256 is not None:
            _require_sha256(self.legacy_id_set_sha256, "legacy_id_set_sha256")


@dataclass(frozen=True, slots=True, order=True)
class GlobalDistribution:
    name: str
    counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class RunACompatibilityAuthority:
    """Locked authority supplied by the Run-A protection/migration manifests."""

    source_run_id: str
    catalog_logical_hash: str
    legacy_hash_algorithm: Literal["era-canonical-json-row-v1"]
    catalog_entry_count: Literal[61776] = 61_776

    def __post_init__(self) -> None:
        if not self.source_run_id:
            raise ContractViolation("Run A source_run_id is required")
        _require_sha256(self.catalog_logical_hash, "Run A catalog_logical_hash")
        if self.legacy_hash_algorithm != LEGACY_HASH_ALGORITHM:
            raise ContractViolation("Run A legacy hash algorithm is not approved")
        if self.catalog_entry_count != FORMAL_RUN_A_CATALOG_ENTRY_COUNT:
            raise ContractViolation("formal Run A must bind exactly 61,776 Catalog entries")


@dataclass(frozen=True, slots=True)
class RunAProjection:
    source_run_id: str
    legacy_hash_algorithm: Literal["era-canonical-json-row-v1"]
    records: tuple[DailySemanticRecord, ...]
    global_distributions: tuple[GlobalDistribution, ...]
    payload_and_distribution_proof: Literal["CANONICAL_ROW_HASH_EQUALITY"] = (
        "CANONICAL_ROW_HASH_EQUALITY"
    )

    def __post_init__(self) -> None:
        keys = tuple(record.key for record in self.records)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ContractViolation("Run A daily semantic records must be unique and sorted")
        names = tuple(item.name for item in self.global_distributions)
        if names != tuple(sorted(names)) or len(set(names)) != len(names):
            raise ContractViolation("Run A global distributions must be unique and sorted")


CompatibilityValue = str | int | bool | None


@dataclass(frozen=True, slots=True)
class CompatibilityDifference:
    key: DailySemanticKey | None
    field: str
    run_a_value: CompatibilityValue
    v2_value: CompatibilityValue


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    status: Literal["PASS", "FAIL"]
    payload_and_distribution_proof: Literal["CANONICAL_ROW_HASH_EQUALITY"]
    run_a_partition_count: int
    v2_partition_count: int
    matched_partition_count: int
    daily_row_hash_match_count: int
    daily_id_set_checked_count: int
    global_distributions_equal: bool
    missing_in_v2: tuple[DailySemanticKey, ...]
    extra_in_v2: tuple[DailySemanticKey, ...]
    differences: tuple[CompatibilityDifference, ...]

    def require_pass(self) -> None:
        if self.status != "PASS":
            raise CompatibilityMismatch(self)


@dataclass(frozen=True, slots=True)
class _CatalogDay:
    key: DailySemanticKey
    relative_path: str
    row_count: int
    legacy_logical_sha256: str


def project_formal_run_a(
    catalog: Mapping[str, object],
    release_analysis: Mapping[str, object],
    *,
    authority: RunACompatibilityAuthority,
) -> RunAProjection:
    """Validate and project the complete formal V1 Run A without reading Parquet.

    Physical fields are used only to authenticate the immutable V1 Catalog.  They
    are discarded before the returned logical projection is constructed.
    """

    entries = _sequence(catalog.get("entries"), "Run A Catalog entries")
    if len(entries) != authority.catalog_entry_count:
        raise ContractViolation("Run A Catalog does not contain all 61,776 daily entries")
    catalog_logical_hash = _require_sha256(
        catalog.get("logical_hash"), "Run A Catalog logical_hash"
    )
    if catalog_logical_hash != authority.catalog_logical_hash:
        raise ContractViolation("Run A Catalog logical hash does not match locked authority")

    days_by_group: dict[tuple[str, str, str], dict[date, _CatalogDay]] = {}
    catalog_paths: list[str] = []
    logical_digest = hashlib.sha256()
    for raw_entry in entries:
        entry = _mapping(raw_entry, "Run A Catalog entry")
        relative_path = _string(entry.get("relative_path"), "Catalog relative_path")
        row_count = _non_negative_int(entry.get("rows"), "Catalog rows")
        logical_hash = _require_sha256(entry.get("logical_sha256"), "Catalog logical_sha256")
        key = _path_key(relative_path)
        group = (key.instrument, key.variant, key.dataset)
        group_days = days_by_group.setdefault(group, {})
        if key.owner_date in group_days:
            raise ContractViolation(f"duplicate Run A owner-day key: {key.label}")
        group_days[key.owner_date] = _CatalogDay(
            key=key,
            relative_path=relative_path,
            row_count=row_count,
            legacy_logical_sha256=logical_hash,
        )
        catalog_paths.append(relative_path)
        logical_digest.update(
            canonical_json(
                {
                    "relative_path": relative_path,
                    "rows": row_count,
                    "logical_sha256": logical_hash,
                }
            ).encode("utf-8")
        )
    if catalog_paths != sorted(catalog_paths) or len(set(catalog_paths)) != len(catalog_paths):
        raise ContractViolation("Run A Catalog paths must be unique and deterministically sorted")
    if logical_digest.hexdigest() != catalog_logical_hash:
        raise ContractViolation("Run A Catalog logical aggregate cannot be reproduced")
    _require_complete_group_coverage(days_by_group)

    if release_analysis.get("schema_name") != "stage2-group1-release-analysis-v1":
        raise ContractViolation("Run A release-analysis schema is not approved")
    if release_analysis.get("catalog_logical_hash") != catalog_logical_hash:
        raise ContractViolation("Run A Catalog/release-analysis logical hash mismatch")
    _require_clean_quality(release_analysis.get("quality"))
    analysis_datasets = _mapping(release_analysis.get("datasets"), "release-analysis datasets")
    expected_dataset_names = {
        _group_label(instrument, variant, dataset)
        for instrument, variant, dataset in _FORMAL_GROUPS
    }
    if set(analysis_datasets) != expected_dataset_names:
        missing = sorted(expected_dataset_names - set(analysis_datasets))
        extra = sorted(set(analysis_datasets) - expected_dataset_names)
        raise ContractViolation(f"release-analysis dataset coverage mismatch: {missing=}, {extra=}")

    records: list[DailySemanticRecord] = []
    for group in sorted(_FORMAL_GROUPS):
        instrument, variant, dataset = group
        group_days = days_by_group[group]
        stats = _mapping(
            analysis_datasets[_group_label(instrument, variant, dataset)],
            "release-analysis dataset statistics",
        )
        if _non_negative_int(stats.get("partition_count"), "partition_count") != len(group_days):
            raise ContractViolation("release-analysis partition_count mismatch")
        expected_rows = sum(item.row_count for item in group_days.values())
        if _non_negative_int(stats.get("rows"), "dataset rows") != expected_rows:
            raise ContractViolation("release-analysis dataset row count mismatch")
        partition_hashes = _date_hash_mapping(
            stats.get("partition_logical_hashes"),
            label="partition_logical_hashes",
            allowed_dates=frozenset(group_days),
            require_complete=True,
        )
        id_hashes = _date_hash_mapping(
            stats.get("partition_id_set_hashes", {}),
            label="partition_id_set_hashes",
            allowed_dates=frozenset(group_days),
            require_complete=False,
        )
        for owner_date, item in sorted(group_days.items()):
            if partition_hashes[owner_date] != item.legacy_logical_sha256:
                raise ContractViolation(
                    f"Catalog/release-analysis day hash mismatch: {item.key.label}"
                )
            records.append(
                DailySemanticRecord(
                    key=item.key,
                    row_count=item.row_count,
                    empty=item.row_count == 0,
                    legacy_logical_sha256=item.legacy_logical_sha256,
                    legacy_id_set_sha256=id_hashes.get(owner_date),
                )
            )

    return RunAProjection(
        source_run_id=authority.source_run_id,
        legacy_hash_algorithm=authority.legacy_hash_algorithm,
        records=tuple(sorted(records, key=lambda item: item.key)),
        global_distributions=_normalize_global_distributions(
            release_analysis.get("distributions"), label="Run A global distributions"
        ),
    )


def project_v2_receipts(
    receipts: Iterable[Receipt],
    *,
    legacy_hash_algorithm: str,
) -> tuple[DailySemanticRecord, ...]:
    """Project V2 receipts onto the snapshot- and layout-independent daily key."""

    if legacy_hash_algorithm != LEGACY_HASH_ALGORITHM:
        raise ContractViolation("V2 receipts are not bound to the approved legacy hash algorithm")
    by_key: dict[DailySemanticKey, DailySemanticRecord] = {}
    for receipt in receipts:
        if receipt.legacy_hash_algorithm != V2_RECEIPT_LEGACY_HASH_ALGORITHM:
            raise ContractViolation("V2 receipt does not bind the approved legacy hash algorithm")
        legacy_logical_sha256 = receipt.legacy_logical_sha256
        if legacy_logical_sha256 is None:
            raise ContractViolation("V2 compatibility receipt is missing its legacy logical hash")
        key = DailySemanticKey(
            instrument=receipt.partition.instrument,
            variant=receipt.partition.variant,
            dataset=receipt.partition.dataset_name,
            owner_date=receipt.partition.owner_date,
        )
        if key in by_key:
            raise ContractViolation(f"conflicting V2 receipts for owner-day key: {key.label}")
        legacy_id_set = _legacy_id_set_from_receipt(receipt)
        by_key[key] = DailySemanticRecord(
            key=key,
            row_count=receipt.row_count,
            empty=receipt.terminal_state == "EMPTY",
            legacy_logical_sha256=legacy_logical_sha256,
            legacy_id_set_sha256=legacy_id_set,
        )
    return tuple(by_key[key] for key in sorted(by_key))


def compare_run_a_to_v2(
    run_a: RunAProjection,
    receipts: Iterable[Receipt],
    *,
    v2_legacy_hash_algorithm: str,
    v2_global_distributions: Mapping[str, object],
) -> CompatibilityReport:
    """Return a zero-tolerance semantic comparison report."""

    if run_a.legacy_hash_algorithm != LEGACY_HASH_ALGORITHM:
        raise ContractViolation("Run A projection uses an unapproved legacy hash algorithm")
    v2_records = project_v2_receipts(receipts, legacy_hash_algorithm=v2_legacy_hash_algorithm)
    left = {record.key: record for record in run_a.records}
    right = {record.key: record for record in v2_records}
    missing = tuple(sorted(set(left) - set(right)))
    extra = tuple(sorted(set(right) - set(left)))
    differences: list[CompatibilityDifference] = []
    row_hash_matches = 0
    id_checks = 0
    for key in sorted(set(left).intersection(right)):
        run_a_record = left[key]
        v2_record = right[key]
        for field in ("row_count", "empty", "legacy_logical_sha256", "legacy_id_set_sha256"):
            run_a_value = cast(CompatibilityValue, getattr(run_a_record, field))
            v2_value = cast(CompatibilityValue, getattr(v2_record, field))
            if run_a_value != v2_value:
                differences.append(
                    CompatibilityDifference(
                        key=key,
                        field=field,
                        run_a_value=run_a_value,
                        v2_value=v2_value,
                    )
                )
        if run_a_record.legacy_logical_sha256 == v2_record.legacy_logical_sha256:
            row_hash_matches += 1
        if run_a_record.legacy_id_set_sha256 is not None:
            id_checks += 1

    normalized_v2_distributions = _normalize_global_distributions(
        v2_global_distributions, label="V2 global distributions"
    )
    distributions_equal = run_a.global_distributions == normalized_v2_distributions
    if not distributions_equal:
        differences.append(
            CompatibilityDifference(
                key=None,
                field="global_distributions",
                run_a_value=_global_distribution_hash(run_a.global_distributions),
                v2_value=_global_distribution_hash(normalized_v2_distributions),
            )
        )

    status: Literal["PASS", "FAIL"] = (
        "PASS" if not missing and not extra and not differences else "FAIL"
    )
    return CompatibilityReport(
        status=status,
        payload_and_distribution_proof=PAYLOAD_AND_DISTRIBUTION_PROOF,
        run_a_partition_count=len(run_a.records),
        v2_partition_count=len(v2_records),
        matched_partition_count=len(set(left).intersection(right)),
        daily_row_hash_match_count=row_hash_matches,
        daily_id_set_checked_count=id_checks,
        global_distributions_equal=distributions_equal,
        missing_in_v2=missing,
        extra_in_v2=extra,
        differences=tuple(differences),
    )


def compare_run_a_to_v2_sorted_stream(
    run_a: RunAProjection,
    receipts: Iterable[Receipt],
    *,
    v2_legacy_hash_algorithm: str,
    v2_global_distributions: Mapping[str, object],
) -> CompatibilityReport:
    """Compare a strictly DailySemanticKey-sorted V2 stream in bounded memory."""

    if run_a.legacy_hash_algorithm != LEGACY_HASH_ALGORITHM:
        raise ContractViolation("Run A projection uses an unapproved legacy hash algorithm")
    if v2_legacy_hash_algorithm != LEGACY_HASH_ALGORITHM:
        raise ContractViolation("V2 receipts are not bound to the approved legacy hash algorithm")

    left_index = 0
    left_records = run_a.records
    previous_right: DailySemanticKey | None = None
    missing: list[DailySemanticKey] = []
    extra: list[DailySemanticKey] = []
    differences: list[CompatibilityDifference] = []
    row_hash_matches = 0
    id_checks = 0
    right_count = 0
    matched = 0

    for receipt in receipts:
        right = _daily_record_from_v2_receipt(
            receipt, legacy_hash_algorithm=v2_legacy_hash_algorithm
        )
        if previous_right is not None and right.key <= previous_right:
            raise ContractViolation("streamed V2 receipts must be unique and strictly sorted")
        previous_right = right.key
        right_count += 1
        while left_index < len(left_records) and left_records[left_index].key < right.key:
            missing.append(left_records[left_index].key)
            left_index += 1
        if left_index >= len(left_records) or right.key < left_records[left_index].key:
            extra.append(right.key)
            continue
        left = left_records[left_index]
        left_index += 1
        matched += 1
        for field in ("row_count", "empty", "legacy_logical_sha256", "legacy_id_set_sha256"):
            left_value = cast(CompatibilityValue, getattr(left, field))
            right_value = cast(CompatibilityValue, getattr(right, field))
            if left_value != right_value:
                differences.append(
                    CompatibilityDifference(
                        key=right.key,
                        field=field,
                        run_a_value=left_value,
                        v2_value=right_value,
                    )
                )
        if left.legacy_logical_sha256 == right.legacy_logical_sha256:
            row_hash_matches += 1
        if left.legacy_id_set_sha256 is not None:
            id_checks += 1
    missing.extend(item.key for item in left_records[left_index:])

    normalized_v2_distributions = _normalize_global_distributions(
        v2_global_distributions, label="V2 global distributions"
    )
    distributions_equal = run_a.global_distributions == normalized_v2_distributions
    if not distributions_equal:
        differences.append(
            CompatibilityDifference(
                key=None,
                field="global_distributions",
                run_a_value=_global_distribution_hash(run_a.global_distributions),
                v2_value=_global_distribution_hash(normalized_v2_distributions),
            )
        )
    status: Literal["PASS", "FAIL"] = (
        "PASS" if not missing and not extra and not differences else "FAIL"
    )
    return CompatibilityReport(
        status=status,
        payload_and_distribution_proof=PAYLOAD_AND_DISTRIBUTION_PROOF,
        run_a_partition_count=len(left_records),
        v2_partition_count=right_count,
        matched_partition_count=matched,
        daily_row_hash_match_count=row_hash_matches,
        daily_id_set_checked_count=id_checks,
        global_distributions_equal=distributions_equal,
        missing_in_v2=tuple(missing),
        extra_in_v2=tuple(extra),
        differences=tuple(differences),
    )


def _daily_record_from_v2_receipt(
    receipt: Receipt, *, legacy_hash_algorithm: str
) -> DailySemanticRecord:
    if receipt.legacy_hash_algorithm != V2_RECEIPT_LEGACY_HASH_ALGORITHM:
        raise ContractViolation("V2 receipt does not bind the approved legacy hash algorithm")
    if legacy_hash_algorithm != LEGACY_HASH_ALGORITHM:
        raise ContractViolation("V2 receipts are not bound to the approved legacy hash algorithm")
    if receipt.legacy_logical_sha256 is None:
        raise ContractViolation("V2 compatibility receipt is missing its legacy logical hash")
    return DailySemanticRecord(
        key=DailySemanticKey(
            instrument=receipt.partition.instrument,
            variant=receipt.partition.variant,
            dataset=receipt.partition.dataset_name,
            owner_date=receipt.partition.owner_date,
        ),
        row_count=receipt.row_count,
        empty=receipt.terminal_state == "EMPTY",
        legacy_logical_sha256=receipt.legacy_logical_sha256,
        legacy_id_set_sha256=_legacy_id_set_from_receipt(receipt),
    )


def assert_run_a_v2_compatible(
    run_a: RunAProjection,
    receipts: Iterable[Receipt],
    *,
    v2_legacy_hash_algorithm: str,
    v2_global_distributions: Mapping[str, object],
) -> CompatibilityReport:
    """Hard-fail on any missing, extra, conflicting, or unequal semantic fact."""

    report = compare_run_a_to_v2(
        run_a,
        receipts,
        v2_legacy_hash_algorithm=v2_legacy_hash_algorithm,
        v2_global_distributions=v2_global_distributions,
    )
    report.require_pass()
    return report


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ContractViolation(f"{label} must be a lowercase SHA-256")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractViolation(f"{label} must be a non-empty string")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractViolation(f"{label} must be a non-negative integer")
    return value


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractViolation(f"{label} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ContractViolation(f"{label} must be a sequence")
    return cast(Sequence[object], value)


def _path_key(relative_path: str) -> DailySemanticKey:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ContractViolation("Run A Catalog contains an unsafe relative path")
    instrument_parts = [part for part in path.parts if part.startswith("instrument=")]
    variant_parts = [part for part in path.parts if part.startswith("variant=")]
    date_parts = [part for part in path.parts if part.startswith("date=")]
    if len(instrument_parts) != 1 or len(variant_parts) != 1 or len(date_parts) != 1:
        raise ContractViolation("Run A Catalog path dimensions are ambiguous")
    instrument = instrument_parts[0].removeprefix("instrument=")
    variant = variant_parts[0].removeprefix("variant=")
    variant_index = path.parts.index(variant_parts[0])
    if variant_index + 1 >= len(path.parts):
        raise ContractViolation("Run A Catalog path is missing its dataset")
    dataset = path.parts[variant_index + 1]
    if any(_SAFE_NAME.fullmatch(value) is None for value in (instrument, variant, dataset)):
        raise ContractViolation("Run A Catalog path contains an invalid semantic dimension")
    try:
        owner_date = date.fromisoformat(date_parts[0].removeprefix("date="))
    except ValueError as exc:
        raise ContractViolation("Run A Catalog contains an invalid UTC owner date") from exc
    key = DailySemanticKey(instrument, variant, dataset, owner_date)
    if (instrument, variant, dataset) not in _FORMAL_GROUPS:
        raise ContractViolation(f"Run A Catalog contains an unapproved dataset: {key.label}")
    if not FORMAL_PERIOD_START <= owner_date < FORMAL_PERIOD_END_EXCLUSIVE:
        raise ContractViolation(
            f"Run A Catalog owner date is outside the frozen period: {key.label}"
        )
    return key


def _formal_owner_dates() -> frozenset[date]:
    count = (FORMAL_PERIOD_END_EXCLUSIVE - FORMAL_PERIOD_START).days
    return frozenset(FORMAL_PERIOD_START + timedelta(days=offset) for offset in range(count))


def _require_complete_group_coverage(
    days_by_group: Mapping[tuple[str, str, str], Mapping[date, _CatalogDay]],
) -> None:
    if set(days_by_group) != _FORMAL_GROUPS:
        missing = sorted(_FORMAL_GROUPS - set(days_by_group))
        extra = sorted(set(days_by_group) - _FORMAL_GROUPS)
        raise ContractViolation(f"Run A group coverage mismatch: {missing=}, {extra=}")
    expected_dates = _formal_owner_dates()
    for group, days in days_by_group.items():
        if set(days) != expected_dates:
            missing_count = len(expected_dates - set(days))
            extra_count = len(set(days) - expected_dates)
            raise ContractViolation(
                f"Run A owner-day coverage mismatch for {group}: "
                f"missing={missing_count}, extra={extra_count}"
            )


def _group_label(instrument: str, variant: str, dataset: str) -> str:
    return f"{instrument}/{variant}/{dataset}"


def _date_hash_mapping(
    value: object,
    *,
    label: str,
    allowed_dates: frozenset[date],
    require_complete: bool,
) -> dict[date, str]:
    raw = _mapping(value, label)
    result: dict[date, str] = {}
    for raw_date, raw_hash in raw.items():
        try:
            owner_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ContractViolation(f"{label} contains an invalid owner date") from exc
        if owner_date not in allowed_dates:
            raise ContractViolation(f"{label} contains an extra owner date")
        result[owner_date] = _require_sha256(raw_hash, f"{label}[{raw_date}]")
    if require_complete and set(result) != allowed_dates:
        raise ContractViolation(f"{label} does not cover every formal owner day")
    return result


def _require_clean_quality(value: object) -> None:
    quality = _mapping(value, "Run A release quality")
    if quality.get("status") != "PASS":
        raise ContractViolation("Run A release Quality is not PASS")
    failures = [name for name, fact in quality.items() if name != "status" and bool(fact)]
    if failures:
        raise ContractViolation(f"Run A release Quality contains failures: {sorted(failures)}")


def _normalize_global_distributions(value: object, *, label: str) -> tuple[GlobalDistribution, ...]:
    raw = _mapping(value, label)
    if not _REQUIRED_GLOBAL_DISTRIBUTIONS.issubset(raw):
        missing = sorted(_REQUIRED_GLOBAL_DISTRIBUTIONS - set(raw))
        raise ContractViolation(f"{label} is missing required fields: {missing}")
    normalized: list[GlobalDistribution] = []
    for name, raw_counts in raw.items():
        if _SAFE_NAME.fullmatch(name) is None:
            raise ContractViolation(f"{label} contains an invalid field name")
        counts = _mapping(raw_counts, f"{label}.{name}")
        normalized_counts: list[tuple[str, int]] = []
        for category, raw_count in counts.items():
            if not category:
                raise ContractViolation(f"{label}.{name} contains an empty category")
            count = _non_negative_int(raw_count, f"{label}.{name}.{category}")
            normalized_counts.append((category, count))
        normalized.append(GlobalDistribution(name=name, counts=tuple(sorted(normalized_counts))))
    return tuple(sorted(normalized))


def _legacy_id_set_from_receipt(receipt: Receipt) -> str | None:
    values = [
        item.value for item in receipt.quality_facts if item.name == LEGACY_ID_SET_QUALITY_FACT
    ]
    if not values:
        return None
    if len(values) != 1:
        raise ContractViolation("V2 receipt contains duplicate legacy ID-set facts")
    return _require_sha256(values[0], "V2 receipt legacy ID-set hash")


def _global_distribution_hash(values: tuple[GlobalDistribution, ...]) -> str:
    payload = {item.name: {category: count for category, count in item.counts} for item in values}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
