"""Frozen Runtime V2 schemas for the approved Stage 2 Group-1 projection.

The registry contains one binding for every formal ``variant/dataset`` pair
published by the V1 Group-1 generator (ten PRICE and three FLOW bindings).
It deliberately describes only the existing approved records; it is not an
event-plugin registry and cannot introduce another setup or variant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from .models import ArrowFieldSpec, DatasetSpec

Group1Variant = Literal["V1_PRICE", "V1_FLOW"]

GROUP1_SETUP_ID = "KEY_LOW_SWEEP_RECLAIM_HOLD_V1"
GROUP1_CONTEXT_ID = "CAUSAL_EMA20_1H"
GROUP1_DATASET_VERSION = "1.0"

PRICE_DATASETS = (
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
)
FLOW_DATASETS = ("flow_features", "market_episodes", "candidate_inclusion")
LEGACY_ID_FIELDS = {
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


@dataclass(frozen=True, slots=True)
class Group1DatasetBinding:
    """A fail-closed binding between one approved variant and one schema."""

    variant: Group1Variant
    dataset: str
    spec: DatasetSpec
    legacy_id_field: str | None


def _field(
    name: str,
    data_type: str,
    *,
    nullable: bool = False,
    children: tuple[ArrowFieldSpec, ...] = (),
) -> ArrowFieldSpec:
    return ArrowFieldSpec(
        name=name,
        data_type=data_type,
        nullable=nullable,
        children=children,
    )


def _list(name: str) -> ArrowFieldSpec:
    return _field(
        name,
        "large_list",
        children=(_field("item", "utf8"),),
    )


def _struct(name: str, *children: ArrowFieldSpec) -> ArrowFieldSpec:
    return _field(name, "struct", children=tuple(children))


LINEAGE_FIELDS = (
    _field("instrument", "utf8"),
    _field("data_run_id", "utf8"),
    _field("dataset_logical_hash", "utf8"),
    _field("config_hash", "utf8"),
    _field("code_version", "utf8"),
    _field("parameter_set_id", "utf8"),
    _field("available_at_ts", "int64"),
)


def _spec(
    *,
    dataset: str,
    variant: Group1Variant,
    fields: tuple[ArrowFieldSpec, ...],
    identity_fields: tuple[str, ...],
    ownership_mode: Literal["DATE_FIELD", "TIMESTAMP_NS_FIELD", "PARTITION_KEY_ONLY"],
    owner_date_field: str | None = None,
    owner_timestamp_ns_field: str | None = None,
    distribution_fields: tuple[str, ...] = (),
    row_multiplicity: Literal["UNIQUE_IDENTITY", "MULTISET_STABLE"] = "UNIQUE_IDENTITY",
) -> DatasetSpec:
    # Variant-specific dataset versions make the approved PRICE/FLOW isolation
    # part of the schema hash while retaining the formal V1 dataset name.
    dataset_version = f"group1-{variant.lower().replace('_', '-')}-v1"
    stable_sort_keys = identity_fields + tuple(
        field.name
        for field in fields
        if field.name not in identity_fields
        and not field.nullable
        and field.data_type not in {"list", "large_list", "struct"}
    )
    return DatasetSpec.seal(
        {
            "dataset_name": dataset,
            "dataset_version": dataset_version,
            "fields": fields,
            "stable_sort_keys": stable_sort_keys,
            "identity_fields": identity_fields,
            "payload_association_fields": tuple(field.name for field in fields),
            "distribution_fields": distribution_fields,
            "row_multiplicity": row_multiplicity,
            "ownership_mode": ownership_mode,
            "owner_date_field": owner_date_field,
            "owner_timestamp_ns_field": owner_timestamp_ns_field,
            "legacy_hash_algorithm": "ERA_CANONICAL_JSON_ROW_V1",
        }
    )


RAW_KEY_LEVEL_FIELDS = LINEAGE_FIELDS + (
    _field("raw_key_level_id", "utf8"),
    _field("level_type", "utf8"),
    _field("source_type", "utf8"),
    _field("source_id", "utf8"),
    _field("source_timeframe", "utf8"),
    _field("source_start_ts", "int64"),
    _field("source_end_ts", "int64"),
    _field("level_price", "utf8"),
    _field("priority", "int64"),
    _field("quality_status", "utf8"),
    _field("rejection_reason", "utf8", nullable=True),
    _struct("metadata", _field("closed_bar_count", "int64")),
)

CANONICAL_KEY_LEVEL_FIELDS = LINEAGE_FIELDS + (
    _field("key_level_id", "utf8"),
    _field("level_type", "utf8"),
    _field("source_type", "utf8"),
    _field("source_id", "utf8"),
    _field("source_timeframe", "utf8"),
    _field("source_start_ts", "int64"),
    _field("source_end_ts", "int64"),
    _field("level_price", "utf8"),
    _field("priority", "int64"),
    _field("normalization_group", "utf8"),
    _list("member_key_level_ids"),
    _field("formed_at_ns", "int64"),
    _field("expires_at_ns", "int64"),
    _field("status", "utf8"),
    _field("reason_code", "utf8"),
    _struct(
        "metadata",
        _field("member_count", "int64"),
        _field("merge_tolerance_bps", "utf8"),
        _field("winner_raw_key_level_id", "utf8"),
    ),
    _field("event_parameter_set_id", "utf8"),
)

ARBITRATION_FIELDS = (
    _field("key_level_id", "utf8"),
    _field("normalization_group", "utf8"),
    _list("member_key_level_ids"),
    _field("reason_code", "utf8"),
    _field("event_parameter_set_id", "utf8"),
)

SWEEP_FIELDS = LINEAGE_FIELDS + (
    _field("sweep_id", "utf8"),
    _field("key_level_id", "utf8"),
    _field("direction", "utf8"),
    _field("sweep_start_ts", "int64"),
    _field("sweep_detection_ts", "int64"),
    _field("sweep_extreme_ts", "int64"),
    _field("sweep_extreme_price", "utf8"),
    _field("sweep_depth", "utf8"),
    _field("sweep_depth_unit", "utf8"),
    _field("pre_sweep_reference", "utf8"),
    _field("status", "utf8"),
    _field("reason_code", "utf8"),
    _struct("metadata", _field("confirmation_bps", "utf8")),
    _field("event_parameter_set_id", "utf8"),
)

RECLAIM_FIELDS = LINEAGE_FIELDS + (
    _field("reclaim_id", "utf8"),
    _field("sweep_id", "utf8"),
    _field("reclaim_ts", "int64"),
    _field("reclaim_price", "utf8"),
    _field("status", "utf8"),
    _field("reason_code", "utf8"),
    _field("event_parameter_set_id", "utf8"),
)

HOLD_FIELDS = LINEAGE_FIELDS + (
    _field("hold_id", "utf8"),
    _field("reclaim_id", "utf8"),
    _field("sweep_id", "utf8"),
    _field("hold_start_ts", "int64"),
    _field("hold_end_ts", "int64"),
    _field("hold_result", "utf8"),
    _field("failure_reason", "utf8", nullable=True),
    _field("event_parameter_set_id", "utf8"),
)

PRICE_TRIGGER_FIELDS = LINEAGE_FIELDS + (
    _field("trigger_id", "utf8"),
    _field("hold_id", "utf8"),
    _field("sweep_id", "utf8"),
    _field("trigger_version", "utf8"),
    _field("detection_ts", "int64"),
    _field("reference_price", "utf8"),
    _field("context_state", "utf8"),
    _field("status", "utf8"),
    _field("reason_code", "utf8"),
    _field("event_parameter_set_id", "utf8"),
)

MARKET_EPISODE_FIELDS = LINEAGE_FIELDS + (
    _field("market_episode_id", "utf8"),
    _field("canonical_candidate_id", "utf8"),
    _field("candidate_version_id", "utf8"),
    _field("canonical_payload_hash", "utf8"),
    _field("venue", "utf8"),
    _field("direction", "utf8"),
    _field("canonical_key_level_id", "utf8"),
    _field("sweep_id", "utf8"),
    _field("reclaim_id", "utf8"),
    _field("hold_id", "utf8"),
    _field("trigger_id", "utf8"),
    _field("flow_feature_set_id", "utf8", nullable=True),
    _field("variant", "utf8"),
    _field("variant_id", "utf8"),
    _field("time_combination_id", "utf8"),
    _field("research_role", "utf8"),
    _field("primary_eligible", "bool"),
    _field("sweep_start_ns", "int64"),
    _field("episode_status", "utf8"),
    _field("consumed", "bool"),
    _field("consumed_by_intent_id", "utf8", nullable=True),
    _field("rearm_eligible_at_ns", "int64", nullable=True),
)

CANDIDATE_INCLUSION_FIELDS = LINEAGE_FIELDS + (
    _field("inclusion_id", "utf8"),
    _field("market_episode_id", "utf8"),
    _field("canonical_candidate_id", "utf8"),
    _field("candidate_version_id", "utf8"),
    _field("canonical_payload_hash", "utf8"),
    _field("variant_id", "utf8"),
    _field("time_combination_id", "utf8"),
    _field("research_role", "utf8"),
    _field("primary_eligible", "bool"),
    _field("included", "bool"),
    _field("reason_code", "utf8"),
    _field("deduplication_key", "utf8"),
    _field("ownership_status", "utf8"),
    _field("duplicate_of_candidate_id", "utf8", nullable=True),
    _field("source_processing_partition", "utf8", nullable=True),
    _field("source_row_ordinal", "int64", nullable=True),
    _field("source_file_logical_path", "utf8", nullable=True),
    _field("excluded_reason", "utf8", nullable=True),
    _field("owner_partition", "utf8"),
)

FLOW_WINDOW_FIELDS = LINEAGE_FIELDS + (
    _field("direction", "utf8"),
    _field("canonical_key_level_id", "utf8"),
    _field("sweep_id", "utf8"),
    _field("reclaim_id", "utf8"),
    _field("hold_id", "utf8"),
    _field("trigger_id", "utf8"),
    _field("time_combination_id", "utf8"),
    _field("venue", "utf8"),
    _field("sweep_start_ns", "int64"),
    _field("market_episode_id", "utf8"),
    _field("canonical_candidate_id", "utf8"),
    _field("canonical_payload_hash", "utf8"),
    _field("variant_id", "utf8"),
    _field("research_role", "utf8"),
    _field("primary_eligible", "bool"),
    _field("candidate_version_id", "utf8"),
    _field("trigger_available_at_ts", "int64"),
    _field("window_start_ts", "int64"),
    _field("window_end_ts", "int64"),
    _field("event_parameter_set_id", "utf8"),
    _field("owner_partition", "utf8"),
)

FLOW_FEATURE_FIELDS = (
    _field("flow_feature_set_id", "utf8"),
    _field("instrument", "utf8"),
    _field("window_start_ts", "int64"),
    _field("window_end_ts", "int64"),
    _field("buy_quantity", "utf8"),
    _field("sell_quantity", "utf8"),
    _field("signed_quantity_imbalance", "utf8", nullable=True),
    _field("latest_1s_trade_count", "int64"),
    _field("previous_4s_per_second_mean", "utf8"),
    _field("status", "utf8"),
    _list("unavailable_fields"),
    _field("reason_code", "utf8"),
    _field("market_episode_id", "utf8"),
    _field("event_parameter_set_id", "utf8"),
    _field("variant_id", "utf8"),
    _field("time_combination_id", "utf8"),
    _field("research_role", "utf8"),
    _field("primary_eligible", "bool"),
)


def _build_bindings() -> tuple[Group1DatasetBinding, ...]:
    definitions: tuple[
        tuple[
            Group1Variant,
            str,
            tuple[ArrowFieldSpec, ...],
            tuple[str, ...],
            Literal["DATE_FIELD", "TIMESTAMP_NS_FIELD", "PARTITION_KEY_ONLY"],
            str | None,
            str | None,
            tuple[str, ...],
        ],
        ...,
    ] = (
        (
            "V1_PRICE",
            "raw_key_levels",
            RAW_KEY_LEVEL_FIELDS,
            ("raw_key_level_id",),
            "PARTITION_KEY_ONLY",
            None,
            None,
            ("parameter_set_id", "source_type", "source_timeframe", "quality_status"),
        ),
        (
            "V1_PRICE",
            "canonical_key_levels",
            CANONICAL_KEY_LEVEL_FIELDS,
            ("key_level_id", "event_parameter_set_id"),
            "PARTITION_KEY_ONLY",
            None,
            None,
            ("parameter_set_id", "event_parameter_set_id", "status", "reason_code"),
        ),
        (
            "V1_PRICE",
            "arbitration",
            ARBITRATION_FIELDS,
            ("key_level_id", "event_parameter_set_id"),
            "PARTITION_KEY_ONLY",
            None,
            None,
            ("event_parameter_set_id", "reason_code"),
        ),
        (
            "V1_PRICE",
            "sweeps",
            SWEEP_FIELDS,
            ("sweep_id", "event_parameter_set_id"),
            "PARTITION_KEY_ONLY",
            None,
            None,
            ("parameter_set_id", "event_parameter_set_id", "status", "reason_code"),
        ),
        (
            "V1_PRICE",
            "reclaims",
            RECLAIM_FIELDS,
            ("reclaim_id", "event_parameter_set_id"),
            "PARTITION_KEY_ONLY",
            None,
            None,
            ("parameter_set_id", "event_parameter_set_id", "status", "reason_code"),
        ),
        (
            "V1_PRICE",
            "holds",
            HOLD_FIELDS,
            ("hold_id", "event_parameter_set_id"),
            "PARTITION_KEY_ONLY",
            None,
            None,
            ("parameter_set_id", "event_parameter_set_id", "hold_result"),
        ),
        (
            "V1_PRICE",
            "price_triggers",
            PRICE_TRIGGER_FIELDS,
            ("trigger_id", "event_parameter_set_id"),
            "PARTITION_KEY_ONLY",
            None,
            None,
            ("parameter_set_id", "event_parameter_set_id", "status", "reason_code"),
        ),
        (
            "V1_PRICE",
            "market_episodes",
            MARKET_EPISODE_FIELDS,
            ("canonical_candidate_id",),
            "TIMESTAMP_NS_FIELD",
            None,
            "available_at_ts",
            (
                "parameter_set_id",
                "variant_id",
                "time_combination_id",
                "research_role",
                "primary_eligible",
                "episode_status",
            ),
        ),
        (
            "V1_PRICE",
            "candidate_inclusion",
            CANDIDATE_INCLUSION_FIELDS,
            ("canonical_candidate_id",),
            "DATE_FIELD",
            "owner_partition",
            None,
            (
                "parameter_set_id",
                "variant_id",
                "time_combination_id",
                "research_role",
                "primary_eligible",
                "reason_code",
                "ownership_status",
            ),
        ),
        (
            "V1_PRICE",
            "flow_windows",
            FLOW_WINDOW_FIELDS,
            ("canonical_candidate_id",),
            "DATE_FIELD",
            "owner_partition",
            None,
            (
                "parameter_set_id",
                "event_parameter_set_id",
                "variant_id",
                "time_combination_id",
                "research_role",
                "primary_eligible",
            ),
        ),
        (
            "V1_FLOW",
            "flow_features",
            FLOW_FEATURE_FIELDS,
            ("flow_feature_set_id",),
            "TIMESTAMP_NS_FIELD",
            None,
            "window_end_ts",
            (
                "event_parameter_set_id",
                "variant_id",
                "time_combination_id",
                "research_role",
                "primary_eligible",
                "status",
                "reason_code",
            ),
        ),
        (
            "V1_FLOW",
            "market_episodes",
            MARKET_EPISODE_FIELDS,
            ("canonical_candidate_id",),
            "TIMESTAMP_NS_FIELD",
            None,
            "available_at_ts",
            (
                "parameter_set_id",
                "variant_id",
                "time_combination_id",
                "research_role",
                "primary_eligible",
                "episode_status",
            ),
        ),
        (
            "V1_FLOW",
            "candidate_inclusion",
            CANDIDATE_INCLUSION_FIELDS,
            ("canonical_candidate_id",),
            "DATE_FIELD",
            "owner_partition",
            None,
            (
                "parameter_set_id",
                "variant_id",
                "time_combination_id",
                "research_role",
                "primary_eligible",
                "reason_code",
                "ownership_status",
            ),
        ),
    )
    return tuple(
        Group1DatasetBinding(
            variant=variant,
            dataset=dataset,
            spec=_spec(
                dataset=dataset,
                variant=variant,
                fields=fields,
                identity_fields=identity,
                ownership_mode=ownership_mode,
                owner_date_field=owner_date_field,
                owner_timestamp_ns_field=owner_timestamp_ns_field,
                distribution_fields=distributions,
                row_multiplicity=(
                    "MULTISET_STABLE"
                    if variant == "V1_PRICE" and dataset in {"canonical_key_levels", "arbitration"}
                    else "UNIQUE_IDENTITY"
                ),
            ),
            legacy_id_field=LEGACY_ID_FIELDS.get(dataset),
        )
        for (
            variant,
            dataset,
            fields,
            identity,
            ownership_mode,
            owner_date_field,
            owner_timestamp_ns_field,
            distributions,
        ) in definitions
    )


GROUP1_DATASET_BINDINGS = _build_bindings()
_BINDING_INDEX = {
    (binding.variant, binding.dataset): binding for binding in GROUP1_DATASET_BINDINGS
}


def group1_dataset_binding(variant: str, dataset: str) -> Group1DatasetBinding:
    """Return one approved binding; unknown variant/dataset pairs fail closed."""

    try:
        key = cast(tuple[Group1Variant, str], (variant, dataset))
        return _BINDING_INDEX[key]
    except KeyError as exc:
        raise ValueError(f"unapproved Group-1 dataset binding: {variant}/{dataset}") from exc


def group1_dataset_specs() -> tuple[DatasetSpec, ...]:
    """Return the 13 variant-specific immutable DatasetSpec contracts."""

    return tuple(binding.spec for binding in GROUP1_DATASET_BINDINGS)
