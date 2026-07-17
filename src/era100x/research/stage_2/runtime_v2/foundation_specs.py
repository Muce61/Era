"""Frozen DatasetSpec definitions for the Stage 2 V2 Feature Foundation."""

from __future__ import annotations

from .models import ArrowFieldSpec, DatasetSpec


def feature_foundation_dataset_specs() -> tuple[DatasetSpec, ...]:
    specs = (
        _contract_price_spec(),
        _price_bar_spec(),
        _trade_row_group_spec(),
        _trade_second_spec(),
    )
    return tuple(sorted(specs, key=lambda item: item.spec_hash))


def _contract_price_spec() -> DatasetSpec:
    return DatasetSpec.seal(
        {
            "dataset_name": "contract_price_1s",
            "dataset_version": "2.0",
            "fields": (
                _field("instrument", "utf8"),
                _field("event_ts_ns", "int64"),
                _field("available_at_ns", "int64"),
                *(_field(name, "decimal128(38,18)") for name in _PRICE_FIELDS),
                _field("source_file_sha256", "utf8"),
            ),
            "stable_sort_keys": ("instrument", "event_ts_ns"),
            "identity_fields": ("instrument", "event_ts_ns"),
            "payload_association_fields": (
                "instrument",
                "event_ts_ns",
                "available_at_ns",
                *_PRICE_FIELDS,
                "source_file_sha256",
            ),
            "ownership_mode": "TIMESTAMP_NS_FIELD",
            "owner_timestamp_ns_field": "event_ts_ns",
            "legacy_hash_algorithm": "NOT_APPLICABLE",
        }
    )


def _price_bar_spec() -> DatasetSpec:
    return DatasetSpec.seal(
        {
            "dataset_name": "causal_price_bars",
            "dataset_version": "2.0",
            "fields": (
                _field("instrument", "utf8"),
                _field("interval_seconds", "int32"),
                _field("event_ts_ns", "int64"),
                _field("available_at_ns", "int64"),
                *(_field(name, "decimal128(38,18)") for name in _PRICE_FIELDS),
                _field("source_file_sha256", "utf8"),
            ),
            "stable_sort_keys": ("instrument", "interval_seconds", "event_ts_ns"),
            "identity_fields": ("instrument", "interval_seconds", "event_ts_ns"),
            "payload_association_fields": (
                "instrument",
                "interval_seconds",
                "event_ts_ns",
                "available_at_ns",
                *_PRICE_FIELDS,
                "source_file_sha256",
            ),
            "ownership_mode": "TIMESTAMP_NS_FIELD",
            "owner_timestamp_ns_field": "event_ts_ns",
            "legacy_hash_algorithm": "NOT_APPLICABLE",
        }
    )


def _trade_second_spec() -> DatasetSpec:
    return DatasetSpec.seal(
        {
            "dataset_name": "trade_second_primitives",
            "dataset_version": "2.0",
            "fields": (
                _field("instrument", "utf8"),
                _field("event_ts_ns", "int64"),
                _field("second_end_ns", "int64"),
                _field("available_at_ns", "int64"),
                _field("trade_count", "uint64"),
                _field("aggressor_buy_count", "uint64"),
                _field("aggressor_sell_count", "uint64"),
                _field("aggressor_buy_qty", "decimal128(38,18)"),
                _field("aggressor_sell_qty", "decimal128(38,18)"),
                _field("signed_qty", "decimal128(38,18)"),
                _field("source_logical_hash", "utf8"),
            ),
            "stable_sort_keys": ("instrument", "event_ts_ns"),
            "identity_fields": ("instrument", "event_ts_ns"),
            "payload_association_fields": (
                "instrument",
                "event_ts_ns",
                "second_end_ns",
                "available_at_ns",
                "trade_count",
                "aggressor_buy_count",
                "aggressor_sell_count",
                "aggressor_buy_qty",
                "aggressor_sell_qty",
                "signed_qty",
                "source_logical_hash",
            ),
            "ownership_mode": "TIMESTAMP_NS_FIELD",
            "owner_timestamp_ns_field": "event_ts_ns",
            "legacy_hash_algorithm": "NOT_APPLICABLE",
        }
    )


def _trade_row_group_spec() -> DatasetSpec:
    return DatasetSpec.seal(
        {
            "dataset_name": "trade_row_group_index",
            "dataset_version": "2.0",
            "fields": (
                _field("instrument", "utf8"),
                _field("partition_date", "date32"),
                _field("source_relative_path", "utf8"),
                _field("source_byte_sha256", "utf8"),
                _field("source_logical_sha256", "utf8"),
                _field("row_group_ordinal", "int32"),
                _field("row_count", "int64"),
                _field("event_start_ns", "int64"),
                _field("event_end_ns_exclusive", "int64"),
            ),
            "stable_sort_keys": (
                "instrument",
                "source_relative_path",
                "row_group_ordinal",
                "partition_date",
            ),
            "identity_fields": (
                "instrument",
                "source_relative_path",
                "row_group_ordinal",
            ),
            "payload_association_fields": (
                "instrument",
                "partition_date",
                "source_relative_path",
                "source_byte_sha256",
                "source_logical_sha256",
                "row_group_ordinal",
                "row_count",
                "event_start_ns",
                "event_end_ns_exclusive",
            ),
            "ownership_mode": "DATE_FIELD",
            "owner_date_field": "partition_date",
            "legacy_hash_algorithm": "NOT_APPLICABLE",
        }
    )


def _field(name: str, data_type: str) -> ArrowFieldSpec:
    return ArrowFieldSpec(name=name, data_type=data_type)


_PRICE_FIELDS = ("open", "high", "low", "close", "volume")
