"""Canonical binary semantic hashing for V2 Arrow datasets.

Hashing is column-vector based.  It normalizes schema, chunking, null payloads,
byte order, and row order before hashing type-tagged Arrow buffers.  It does not
depend on Parquet bytes or materialize Python row dictionaries.
"""

from __future__ import annotations

import hashlib
import re
import struct
import sys
from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]

from .errors import ContractViolation
from .models import ArrowFieldSpec, DatasetSpec

_HASH_DOMAIN = b"ERA100X/STAGE2/V2/CANONICAL-ARROW-BINARY/2.0"
_DECIMAL_PATTERN = re.compile(r"^decimal(128|256)\(([1-9][0-9]?),(-?[0-9]+)\)$")
_FIXED_BINARY_PATTERN = re.compile(r"^fixed_binary\(([1-9][0-9]*)\)$")


class _Digest(Protocol):
    def update(self, data: bytes | bytearray | memoryview, /) -> object: ...


def _arrow_type(field: ArrowFieldSpec) -> pa.DataType:
    simple: dict[str, pa.DataType] = {
        "null": pa.null(),
        "bool": pa.bool_(),
        "int8": pa.int8(),
        "int16": pa.int16(),
        "int32": pa.int32(),
        "int64": pa.int64(),
        "uint8": pa.uint8(),
        "uint16": pa.uint16(),
        "uint32": pa.uint32(),
        "uint64": pa.uint64(),
        "utf8": pa.string(),
        "large_utf8": pa.large_string(),
        "binary": pa.binary(),
        "large_binary": pa.large_binary(),
        "date32": pa.date32(),
        "timestamp_ns_utc": pa.timestamp("ns", tz="UTC"),
    }
    if field.data_type in simple:
        return simple[field.data_type]
    if field.data_type in {"list", "large_list"}:
        child = field.children[0]
        value_field = pa.field(child.name, _arrow_type(child), nullable=child.nullable)
        return pa.list_(value_field) if field.data_type == "list" else pa.large_list(value_field)
    if field.data_type == "struct":
        return pa.struct(
            [
                pa.field(child.name, _arrow_type(child), nullable=child.nullable)
                for child in field.children
            ]
        )
    decimal_match = _DECIMAL_PATTERN.fullmatch(field.data_type)
    if decimal_match is not None:
        bit_width, precision, scale = (int(value) for value in decimal_match.groups())
        factory = pa.decimal128 if bit_width == 128 else pa.decimal256
        return factory(precision, scale)
    fixed_match = _FIXED_BINARY_PATTERN.fullmatch(field.data_type)
    if fixed_match is not None:
        return pa.binary(int(fixed_match.group(1)))
    raise ContractViolation(f"unsupported canonical type {field.data_type}")


def canonical_arrow_schema(spec: DatasetSpec) -> pa.Schema:
    return pa.schema(
        [pa.field(field.name, _arrow_type(field), nullable=field.nullable) for field in spec.fields]
    )


def _has_nulls(column: pa.ChunkedArray | pa.Array) -> bool:
    return bool(column.null_count > 0)


def _normalize_and_sort(
    table: pa.Table,
    spec: DatasetSpec,
    *,
    sort_fields: Sequence[str],
    require_unique: bool,
) -> pa.Table:
    if not isinstance(table, pa.Table):
        raise ContractViolation("semantic hashing requires a pyarrow.Table")
    expected_names = tuple(field.name for field in spec.fields)
    actual_names = tuple(table.column_names)
    if len(set(actual_names)) != len(actual_names):
        raise ContractViolation("input table has duplicate column names")
    missing = set(expected_names) - set(actual_names)
    extra = set(actual_names) - set(expected_names)
    if missing or extra:
        raise ContractViolation(
            f"table/schema mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    known = set(expected_names)
    if not sort_fields or set(sort_fields) - known:
        raise ContractViolation("sort fields must be a non-empty subset of the dataset schema")

    arrays: list[pa.ChunkedArray] = []
    target_schema = canonical_arrow_schema(spec)
    for field, target_field in zip(spec.fields, target_schema, strict=True):
        source = table[field.name]
        try:
            casted = pc.cast(source, target_field.type, safe=True)
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError) as exc:
            raise ContractViolation(f"cannot safely cast field {field.name}: {exc}") from exc
        if not isinstance(casted, pa.ChunkedArray):
            casted = pa.chunked_array([casted], type=target_field.type)
        if not field.nullable and _has_nulls(casted):
            raise ContractViolation(f"non-nullable field {field.name} contains nulls")
        arrays.append(casted)

    normalized = pa.Table.from_arrays(arrays, schema=target_schema).combine_chunks()
    for name in sort_fields:
        if _has_nulls(normalized[name]):
            raise ContractViolation(f"stable sort field {name} contains nulls")
    if normalized.num_rows:
        indices = pc.sort_indices(
            normalized,
            sort_keys=[(name, "ascending") for name in sort_fields],
        )
        normalized = pc.take(normalized, indices).combine_chunks()

    if require_unique and normalized.num_rows > 1:
        duplicate: pa.Array | pa.ChunkedArray | None = None
        for name in sort_fields:
            left = normalized[name].slice(0, normalized.num_rows - 1)
            right = normalized[name].slice(1, normalized.num_rows - 1)
            equal = pc.equal(left, right)
            duplicate = equal if duplicate is None else pc.and_kleene(duplicate, equal)
        if duplicate is not None and bool(pc.any(duplicate).as_py()):
            raise ContractViolation("stable sort key is not unique")
    return normalized


def normalize_table(table: pa.Table, spec: DatasetSpec) -> pa.Table:
    """Return the canonical schema, chunking, and stable-key row order."""

    normalized = _normalize_and_sort(
        table,
        spec,
        sort_fields=spec.stable_sort_keys,
        require_unique=False,
    )
    if spec.row_multiplicity == "UNIQUE_IDENTITY":
        _require_unique_projection(normalized, spec.identity_fields, "identity")
    return normalized


def _require_unique_projection(
    table: pa.Table,
    fields: Sequence[str],
    label: str,
) -> None:
    if table.num_rows < 2:
        return
    duplicate: pa.Array | pa.ChunkedArray | None = None
    for name in fields:
        left = table[name].slice(0, table.num_rows - 1)
        right = table[name].slice(1, table.num_rows - 1)
        equal = pc.equal(left, right)
        duplicate = equal if duplicate is None else pc.and_kleene(duplicate, equal)
    if duplicate is not None and bool(pc.any(duplicate).as_py()):
        raise ContractViolation(f"{label} is not unique")


def _feed(digest: _Digest, value: bytes | bytearray | memoryview | pa.Buffer) -> None:
    view = memoryview(value)
    digest.update(struct.pack(">Q", len(view)))
    digest.update(view)


def _buffer_view(buffer: pa.Buffer | None, size: int) -> memoryview:
    if size == 0:
        return memoryview(b"")
    if buffer is None or buffer.size < size:
        raise ContractViolation("Arrow produced an undersized canonical value buffer")
    return memoryview(buffer)[:size]


def _validity_bytes(array: pa.Array) -> memoryview:
    validity = pc.cast(pc.is_valid(array), pa.uint8(), safe=True)
    if not isinstance(validity, pa.Array):
        validity = validity.combine_chunks()
    return _buffer_view(validity.buffers()[1], len(array))


def _filled(array: pa.Array, value: object) -> pa.Array:
    result = pc.fill_null(array, pa.scalar(value, type=array.type))
    if isinstance(result, pa.ChunkedArray):
        return result.combine_chunks()
    return result


def _array_components(array: pa.Array) -> tuple[memoryview, ...]:
    """Return canonical validity/value buffers for one normalized Arrow array."""

    length = len(array)
    validity = _validity_bytes(array)
    data_type = array.type
    if pa.types.is_null(data_type):
        return (validity,)
    if pa.types.is_boolean(data_type):
        values = pc.cast(_filled(array, False), pa.uint8(), safe=True)
        if not isinstance(values, pa.Array):
            values = values.combine_chunks()
        return validity, _buffer_view(values.buffers()[1], length)
    if pa.types.is_integer(data_type):
        values = _filled(array, 0)
        return validity, _buffer_view(values.buffers()[1], length * data_type.byte_width)
    if pa.types.is_date32(data_type):
        values = pc.cast(_filled(array, 0), pa.int32(), safe=True)
        if not isinstance(values, pa.Array):
            values = values.combine_chunks()
        return validity, _buffer_view(values.buffers()[1], length * 4)
    if pa.types.is_timestamp(data_type):
        values = pc.cast(_filled(array, 0), pa.int64(), safe=True)
        if not isinstance(values, pa.Array):
            values = values.combine_chunks()
        return validity, _buffer_view(values.buffers()[1], length * 8)
    if pa.types.is_decimal(data_type):
        values = _filled(array, Decimal(0))
        return validity, _buffer_view(values.buffers()[1], length * data_type.byte_width)
    if pa.types.is_fixed_size_binary(data_type):
        values = _filled(array, b"\x00" * data_type.byte_width)
        return validity, _buffer_view(values.buffers()[1], length * data_type.byte_width)
    if pa.types.is_list(data_type) or pa.types.is_large_list(data_type):
        values = _filled(array, [])
        lengths = pc.cast(pc.list_value_length(values), pa.int64(), safe=True)
        flattened = pc.list_flatten(values)
        if isinstance(lengths, pa.ChunkedArray):
            lengths = lengths.combine_chunks()
        if isinstance(flattened, pa.ChunkedArray):
            flattened = flattened.combine_chunks()
        return (
            validity,
            _buffer_view(lengths.buffers()[1], length * 8),
            *_array_components(flattened),
        )
    if pa.types.is_struct(data_type):
        parent_valid = pc.is_valid(array)
        components: list[memoryview] = [validity]
        for index in range(data_type.num_fields):
            child = array.field(index)
            masked = pc.if_else(parent_valid, child, pa.scalar(None, type=child.type))
            if isinstance(masked, pa.ChunkedArray):
                masked = masked.combine_chunks()
            components.extend(_array_components(masked))
        return tuple(components)
    if pa.types.is_string(data_type) or pa.types.is_binary(data_type):
        values = _filled(array, "" if pa.types.is_string(data_type) else b"")
        buffers = values.buffers()
        return (
            validity,
            _buffer_view(buffers[1], (length + 1) * 4),
            _buffer_view(buffers[2], 0 if buffers[2] is None else buffers[2].size),
        )
    if pa.types.is_large_string(data_type) or pa.types.is_large_binary(data_type):
        values = _filled(array, "" if pa.types.is_large_string(data_type) else b"")
        buffers = values.buffers()
        return (
            validity,
            _buffer_view(buffers[1], (length + 1) * 8),
            _buffer_view(buffers[2], 0 if buffers[2] is None else buffers[2].size),
        )
    raise ContractViolation(f"no canonical binary encoder for Arrow type {data_type}")


def _hash_normalized_projection(
    table: pa.Table,
    spec: DatasetSpec,
    *,
    projection_fields: Sequence[str],
    sort_fields: Sequence[str],
    domain: str,
    require_unique: bool,
) -> str:
    if sys.byteorder != "little":
        raise ContractViolation("canonical Arrow V2 currently requires a little-endian host")
    selected = tuple(projection_fields)
    if not selected or len(set(selected)) != len(selected):
        raise ContractViolation("projection fields must be non-empty and unique")
    known = {field.name for field in spec.fields}
    if set(selected) - known:
        raise ContractViolation("projection contains unknown fields")
    # MULTISET_STABLE producers validate that rows sharing the complete stable
    # sort key are byte-for-byte semantically equal.  That permits nested and
    # nullable payload columns to remain outside Arrow's scalar sort keys while
    # preserving multiplicity and deterministic ordering.

    normalized = _normalize_and_sort(
        table,
        spec,
        sort_fields=sort_fields,
        require_unique=require_unique,
    )
    digest = hashlib.sha256()
    _feed(digest, _HASH_DOMAIN)
    _feed(digest, domain.encode("utf-8"))
    _feed(digest, bytes.fromhex(spec.spec_hash))
    _feed(digest, struct.pack(">Q", normalized.num_rows))
    _feed(digest, struct.pack(">I", len(selected)))

    fields_by_name = {field.name: field for field in spec.fields}
    for name in selected:
        field = fields_by_name[name]
        array = normalized[name].combine_chunks()
        _feed(digest, name.encode("utf-8"))
        _feed(digest, field.data_type.encode("ascii"))
        _feed(digest, b"1" if field.nullable else b"0")
        components = _array_components(array)
        _feed(digest, struct.pack(">I", len(components)))
        for component in components:
            _feed(digest, component)
    return digest.hexdigest()


def canonical_projection_hash(
    table: pa.Table,
    spec: DatasetSpec,
    *,
    projection_fields: Sequence[str],
    sort_fields: Sequence[str],
    domain: str,
    require_unique: bool = True,
) -> str:
    """Hash a named logical projection under an explicit ordering contract."""

    return _hash_normalized_projection(
        table,
        spec,
        projection_fields=projection_fields,
        sort_fields=sort_fields,
        domain=domain,
        require_unique=require_unique,
    )


def canonical_semantic_hash(table: pa.Table, spec: DatasetSpec) -> str:
    """Hash every canonical field, independent of row order and physical layout."""

    normalized = normalize_table(table, spec)
    return _hash_normalized_projection(
        normalized,
        spec,
        projection_fields=tuple(field.name for field in spec.fields),
        sort_fields=spec.stable_sort_keys,
        domain="dataset-semantic",
        require_unique=False,
    )
