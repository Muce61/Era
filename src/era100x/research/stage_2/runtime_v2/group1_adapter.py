"""Generation-time adapter from approved Group-1 records to Runtime V2.

The adapter consumes in-memory daily records emitted by the existing Group-1
builders.  It never discovers or reads Run-A artifacts.  Both the historical
``records_logical_hash`` and the V2 canonical Arrow digest are computed before
the records are handed to the compactor, so publication does not need to
decode the generated Parquet again.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]

from era100x.research.stage_2.manifests.configuration import (
    parameter_sets,
    research_classification,
)
from era100x.research.stage_2.pipelines.candidates.io import records_logical_hash

from .catalog import PartitionBatch
from .dataset_specs import (
    GROUP1_CONTEXT_ID,
    GROUP1_SETUP_ID,
    Group1DatasetBinding,
    group1_dataset_binding,
)
from .errors import ContractViolation
from .hashing import canonical_arrow_schema, canonical_semantic_hash, normalize_table
from .models import ArrowFieldSpec, LogicalPartitionKey, QualityFact

DAY_NS = 86_400_000_000_000
KEY_LEVEL_PARAMETER_SET_ID = "KEYLEVEL-BASE-V1"
_REGISTERED_PARAMETERS = {item.parameter_set_id: item for item in parameter_sets()}


@dataclass(frozen=True, slots=True)
class PreparedGroup1Partition:
    """A generation-sealed owner day ready for ``CatalogCompactorV2``."""

    binding: Group1DatasetBinding
    batch: PartitionBatch
    row_count: int
    legacy_logical_sha256: str
    v2_semantic_sha256: str


def prepare_group1_partition(
    *,
    snapshot_id: str,
    instrument: str,
    variant: str,
    dataset: str,
    owner_date: date,
    records: Sequence[Mapping[str, Any]],
    setup_id: str = GROUP1_SETUP_ID,
    context_id: str = GROUP1_CONTEXT_ID,
) -> PreparedGroup1Partition:
    """Validate and seal one approved daily projection without artifact reads.

    Empty days still produce a ``PartitionBatch`` and therefore a receipt, but
    the table has zero rows.  ``CatalogCompactorV2`` consequently creates no
    empty Parquet object for that day.
    """

    if setup_id != GROUP1_SETUP_ID or context_id != GROUP1_CONTEXT_ID:
        raise ContractViolation("S2-T10 v1.8 only permits the approved Group-1 setup/context")
    if instrument not in {"BTCUSDT", "ETHUSDT"}:
        raise ContractViolation(f"unapproved Group-1 instrument: {instrument}")
    try:
        binding = group1_dataset_binding(variant, dataset)
    except ValueError as exc:
        raise ContractViolation(str(exc)) from exc

    source_records = [dict(record) for record in records]
    normalized_rows = [
        _normalize_record(
            record,
            binding=binding,
            instrument=instrument,
            owner_date=owner_date,
        )
        for record in source_records
    ]
    if binding.spec.row_multiplicity == "MULTISET_STABLE":
        _validate_stable_multiset(normalized_rows, binding)
    schema = canonical_arrow_schema(binding.spec)
    table = pa.Table.from_pylist(normalized_rows, schema=schema)
    table = normalize_table(table, binding.spec)
    legacy_digest = records_logical_hash(source_records, dataset)
    v2_digest = canonical_semantic_hash(table, binding.spec)
    partition = LogicalPartitionKey(
        snapshot_id=snapshot_id,
        dataset_name=binding.spec.dataset_name,
        dataset_version=binding.spec.dataset_version,
        dataset_spec_hash=binding.spec.spec_hash,
        setup_id=setup_id,
        context_id=context_id,
        instrument=instrument,
        variant=variant,
        owner_date=owner_date,
    )
    quality_facts = [
        QualityFact(name="generation_time_dual_hash", value=True),
        QualityFact(name="group1_semantics_reused", value=True),
        QualityFact(name="source_record_count", value=len(source_records)),
    ]
    if binding.legacy_id_field is not None and source_records:
        ids = sorted({str(record[binding.legacy_id_field]) for record in source_records})
        quality_facts.append(
            QualityFact(
                name="legacy_id_set_sha256",
                value=hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest(),
            )
        )
    if binding.spec.row_multiplicity == "MULTISET_STABLE":
        quality_facts.append(QualityFact(name="stable_multiset_validated", value=True))
    batch = PartitionBatch(
        key=partition,
        table=table,
        legacy_hash_algorithm="ERA_CANONICAL_JSON_ROW_V1",
        legacy_logical_sha256=legacy_digest,
        quality_facts=tuple(sorted(quality_facts, key=lambda item: item.name)),
    )
    return PreparedGroup1Partition(
        binding=binding,
        batch=batch,
        row_count=table.num_rows,
        legacy_logical_sha256=legacy_digest,
        v2_semantic_sha256=v2_digest,
    )


def prepare_group1_arrow_partition(
    *,
    snapshot_id: str,
    instrument: str,
    variant: str,
    dataset: str,
    owner_date: date,
    table: pa.Table,
    source_record_count: int,
    legacy_logical_sha256: str,
    setup_id: str = GROUP1_SETUP_ID,
    context_id: str = GROUP1_CONTEXT_ID,
) -> PreparedGroup1Partition:
    """Seal one day assembled from already validated bounded Arrow batches.

    ``prepare_group1_partition`` remains the validation boundary for every
    bounded producer batch.  This path performs the cross-batch invariants and
    avoids reconstructing a complete UTC day as Python mappings merely to seal
    the partition.
    """

    if setup_id != GROUP1_SETUP_ID or context_id != GROUP1_CONTEXT_ID:
        raise ContractViolation("S2-T10 v1.8 only permits the approved Group-1 setup/context")
    if instrument not in {"BTCUSDT", "ETHUSDT"}:
        raise ContractViolation(f"unapproved Group-1 instrument: {instrument}")
    try:
        binding = group1_dataset_binding(variant, dataset)
    except ValueError as exc:
        raise ContractViolation(str(exc)) from exc
    if source_record_count < 0 or source_record_count != table.num_rows:
        raise ContractViolation("Arrow partition source-record count changed")
    if len(legacy_logical_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in legacy_logical_sha256
    ):
        raise ContractViolation("legacy logical hash must be lowercase SHA-256")

    normalized = normalize_table(table, binding.spec)
    if binding.spec.row_multiplicity == "MULTISET_STABLE":
        _validate_arrow_stable_multiset(normalized, binding)
    legacy_id_hash = _legacy_id_set_hash(normalized, binding)
    v2_digest = canonical_semantic_hash(normalized, binding.spec)
    partition = LogicalPartitionKey(
        snapshot_id=snapshot_id,
        dataset_name=binding.spec.dataset_name,
        dataset_version=binding.spec.dataset_version,
        dataset_spec_hash=binding.spec.spec_hash,
        setup_id=setup_id,
        context_id=context_id,
        instrument=instrument,
        variant=variant,
        owner_date=owner_date,
    )
    quality_facts = [
        QualityFact(name="generation_time_dual_hash", value=True),
        QualityFact(name="group1_semantics_reused", value=True),
        QualityFact(name="source_record_count", value=source_record_count),
    ]
    if legacy_id_hash is not None:
        quality_facts.append(QualityFact(name="legacy_id_set_sha256", value=legacy_id_hash))
    if binding.spec.row_multiplicity == "MULTISET_STABLE":
        quality_facts.append(QualityFact(name="stable_multiset_validated", value=True))
    batch = PartitionBatch(
        key=partition,
        table=normalized,
        legacy_hash_algorithm="ERA_CANONICAL_JSON_ROW_V1",
        legacy_logical_sha256=legacy_logical_sha256,
        quality_facts=tuple(sorted(quality_facts, key=lambda item: item.name)),
    )
    return PreparedGroup1Partition(
        binding=binding,
        batch=batch,
        row_count=normalized.num_rows,
        legacy_logical_sha256=legacy_logical_sha256,
        v2_semantic_sha256=v2_digest,
    )


def _validate_arrow_stable_multiset(table: pa.Table, binding: Group1DatasetBinding) -> None:
    """Reject one stable key associated with different Arrow payloads."""

    if table.num_rows < 2:
        return
    duplicate: pa.Array | pa.ChunkedArray | None = None
    for name in binding.spec.stable_sort_keys:
        left = table[name].slice(0, table.num_rows - 1)
        right = table[name].slice(1, table.num_rows - 1)
        equal = pc.equal(left, right)
        duplicate = equal if duplicate is None else pc.and_kleene(duplicate, equal)
    if duplicate is None:
        return
    for offset in range(table.num_rows - 1):
        if not bool(duplicate[offset].as_py()):
            continue
        if any(
            not table[name][offset].equals(table[name][offset + 1]) for name in table.column_names
        ):
            raise ContractViolation(
                "stable multiset key maps to different semantic payloads; "
                "an approved identity/schema change is required"
            )


def _legacy_id_set_hash(table: pa.Table, binding: Group1DatasetBinding) -> str | None:
    field = binding.legacy_id_field
    if field is None or table.num_rows == 0:
        return None
    unique = pc.unique(table[field].combine_chunks())
    ordered = pc.take(unique, pc.sort_indices(unique))
    digest = hashlib.sha256()
    first = True
    for offset in range(len(ordered)):
        value = ordered[offset].as_py()
        if value is None:
            raise ContractViolation("legacy identity cannot be null")
        if not first:
            digest.update(b"\n")
        digest.update(str(value).encode("utf-8"))
        first = False
    return digest.hexdigest()


def _normalize_record(
    record: Mapping[str, Any],
    *,
    binding: Group1DatasetBinding,
    instrument: str,
    owner_date: date,
) -> dict[str, Any]:
    fields = binding.spec.fields
    expected = {field.name for field in fields}
    actual = set(record)
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        raise ContractViolation(
            f"{binding.variant}/{binding.dataset} record/schema mismatch; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    _reject_binary_floats(record)
    _validate_semantic_isolation(
        record,
        binding=binding,
        instrument=instrument,
        owner_date=owner_date,
    )
    return {field.name: _coerce(record[field.name], field) for field in fields}


def _validate_stable_multiset(
    rows: Sequence[Mapping[str, Any]], binding: Group1DatasetBinding
) -> None:
    """Allow multiplicity only when equal stable keys describe identical rows."""

    by_stable_key: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for row in rows:
        key = tuple(row[name] for name in binding.spec.stable_sort_keys)
        previous = by_stable_key.setdefault(key, row)
        if previous != row:
            raise ContractViolation(
                "stable multiset key maps to different semantic payloads; "
                "an approved identity/schema change is required"
            )


def _validate_semantic_isolation(
    record: Mapping[str, Any],
    *,
    binding: Group1DatasetBinding,
    instrument: str,
    owner_date: date,
) -> None:
    row_instrument = record.get("instrument")
    if row_instrument is not None and row_instrument != instrument:
        raise ContractViolation("Group-1 partition cannot mix BTC and ETH")
    for field in ("variant", "variant_id"):
        value = record.get(field)
        if value is not None and value != binding.variant:
            raise ContractViolation(f"{field} does not match the logical variant partition")

    event_parameter = record.get("event_parameter_set_id")
    if event_parameter is not None:
        if event_parameter not in _REGISTERED_PARAMETERS:
            raise ContractViolation(f"unregistered Group-1 parameter set: {event_parameter}")
        lineage_parameter = record.get("parameter_set_id")
        if lineage_parameter not in (None, KEY_LEVEL_PARAMETER_SET_ID, event_parameter):
            raise ContractViolation("event and lineage parameter-set identities disagree")

    timing = record.get("time_combination_id")
    if timing is not None:
        effective_parameter = event_parameter or record.get("parameter_set_id")
        if effective_parameter not in _REGISTERED_PARAMETERS:
            raise ContractViolation("timed Group-1 record lacks a registered parameter set")
        try:
            expected_role, expected_eligible = research_classification(
                str(effective_parameter), str(timing)
            )
        except ValueError as exc:
            raise ContractViolation(str(exc)) from exc
        if record.get("research_role") != expected_role:
            raise ContractViolation("Primary/Exploratory research role mismatch")
        if record.get("primary_eligible") is not expected_eligible:
            raise ContractViolation("Primary eligibility mismatch")

    if binding.dataset == "market_episodes":
        if record.get("candidate_version_id") != record.get("canonical_candidate_id"):
            raise ContractViolation("candidate_version_id must preserve canonical identity")
        if binding.variant == "V1_PRICE" and record.get("flow_feature_set_id") is not None:
            raise ContractViolation("V1_PRICE cannot consume a Flow fact")
        if binding.variant == "V1_FLOW" and record.get("flow_feature_set_id") is None:
            raise ContractViolation("V1_FLOW requires its existing Flow fact")
        if record.get("consumed") is not False or record.get("consumed_by_intent_id") is not None:
            raise ContractViolation("research inclusion cannot become EntryIntent consumption")
    if binding.dataset == "candidate_inclusion":
        if record.get("included") is not True:
            raise ContractViolation("formal candidate data may contain only canonical inclusion")
        if record.get("ownership_status") != "OWNED":
            raise ContractViolation("out-of-partition context cannot enter formal candidate data")

    start_ns = _day_start_ns(owner_date)
    end_ns = start_ns + DAY_NS
    if binding.spec.ownership_mode == "DATE_FIELD":
        date_field = binding.spec.owner_date_field
        if date_field is None or _date_text(record[date_field]) != owner_date.isoformat():
            raise ContractViolation("record owner date differs from logical partition")
    elif binding.spec.ownership_mode == "TIMESTAMP_NS_FIELD":
        timestamp_field = binding.spec.owner_timestamp_ns_field
        if timestamp_field is None:
            raise ContractViolation("timestamp-owned dataset lacks its ownership field")
        timestamp = record[timestamp_field]
        if not isinstance(timestamp, int) or isinstance(timestamp, bool):
            raise ContractViolation("owner timestamp must be integer UTC nanoseconds")
        if not start_ns <= timestamp < end_ns:
            raise ContractViolation("record is outside its left-closed/right-open owner day")


def _coerce(value: Any, field: ArrowFieldSpec) -> Any:
    if value is None:
        if not field.nullable:
            raise ContractViolation(f"non-nullable field {field.name} is null")
        return None
    if isinstance(value, Enum):
        value = value.value
    if field.data_type in {"utf8", "large_utf8"}:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, date):
            return value.isoformat()
        if not isinstance(value, str):
            raise ContractViolation(f"field {field.name} must be text")
        return value
    if field.data_type == "bool":
        if not isinstance(value, bool):
            raise ContractViolation(f"field {field.name} must be bool")
        return value
    if field.data_type == "int64":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ContractViolation(f"field {field.name} must be int64")
        return value
    if field.data_type in {"list", "large_list"}:
        if not isinstance(value, (list, tuple)):
            raise ContractViolation(f"field {field.name} must be a list")
        child = field.children[0]
        return [_coerce(item, child) for item in value]
    if field.data_type == "struct":
        if not isinstance(value, Mapping):
            raise ContractViolation(f"field {field.name} must be a struct")
        children = {child.name: child for child in field.children}
        if set(value) != set(children):
            raise ContractViolation(
                f"field {field.name} struct keys differ; "
                f"expected={sorted(children)}, actual={sorted(value)}"
            )
        return {name: _coerce(value[name], child) for name, child in children.items()}
    raise ContractViolation(f"Group-1 adapter does not support field type {field.data_type}")


def _reject_binary_floats(value: Any) -> None:
    if isinstance(value, float):
        raise ContractViolation("binary floats are forbidden in Group-1 V2 semantic records")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_binary_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_binary_floats(item)


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise ContractViolation("owner date must be an ISO date")


def _day_start_ns(value: date) -> int:
    start = datetime(value.year, value.month, value.day, tzinfo=UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return (start - epoch) // timedelta(microseconds=1) * 1_000
