"""Fail-closed production derivation for all Plan v1.9 input bindings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    sha256_file,
)

from .solo_inputs import (
    EXPECTED_PARTITION_COUNT,
    EXPECTED_PARTITION_KEYS,
    REQUIRED_BINDING_RULES,
    REQUIRED_INPUT_BINDINGS,
    SCOPE_END_EXCLUSIVE,
    SCOPE_START,
    InputsLock,
)

RULES_RELATIVE_PATH: Final = Path(
    "configs/research/stage_2/s2p19_production_input_bindings_v1.json"
)
EXPECTED_EXACT_MATCH_FIELDS: Final = [
    "instrument",
    "direction",
    "setup_id",
    "context_model_id",
    "high_timeframe_trend_state",
    "pre_registered_period",
    "evaluation_fold",
    "parameter_set_id",
    "time_combination_id",
    "label_contract_hash",
    "key_level_distance_quintile",
    "binning_snapshot_hash",
]


@dataclass(frozen=True, slots=True)
class ProductionInputSpec:
    entries: dict[str, tuple[Path, str]]
    rules_hash: str


def _safe_json(path: Path, *, label: str) -> dict[str, Any]:
    current = path
    while current != current.parent:
        if current.is_symlink():
            raise ValueError(f"{label} contains a symlink: {path}")
        current = current.parent
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"{label} is missing or unsafe: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return cast(dict[str, Any], value)


def _self_hash(payload: dict[str, Any], field: str, *, label: str) -> str:
    claimed = payload.get(field)
    calculated = canonical_content_hash(
        {key: value for key, value in payload.items() if key != field}
    )
    if claimed != calculated:
        raise ValueError(f"{label} self Hash drift")
    return str(claimed)


def _repository_path(repository_root: Path, raw: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("production binding repository path is unsafe")
    return (repository_root / relative).resolve()


def _external_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("production binding external path must be absolute")
    return path


def _load_rules(repository_root: Path) -> tuple[dict[str, Any], str]:
    path = (repository_root / RULES_RELATIVE_PATH).resolve()
    rules = _safe_json(path, label="production input binding rules")
    rules_hash = _self_hash(rules, "rules_hash", label="production input binding rules")
    if (
        rules.get("schema_name") != "s2p19-production-input-binding-rules"
        or rules.get("schema_version") != "1.0"
        or rules.get("stage_plan_version") != "1.9"
        or rules.get("scope_start_date") != SCOPE_START
        or rules.get("scope_end_date_exclusive") != SCOPE_END_EXCLUSIVE
        or rules.get("historical_execution_claim") is not False
        or rules.get("stage3_locked") is not True
        or rules.get("role_rules") != REQUIRED_BINDING_RULES
    ):
        raise ValueError("production input binding rules drift")
    paths = rules.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("production input binding paths are missing")
    return rules, rules_hash


def _validate_stage1(
    rules: dict[str, Any],
) -> dict[str, tuple[Path, str]]:
    paths = cast(dict[str, str], rules["paths"])
    root = _external_path(paths["stage1_catalog_root"])
    manifest_path = root / "manifest.json"
    quality_path = root / "quality_report.json"
    manifest = _safe_json(manifest_path, label="Stage 1 manifest")
    quality = _safe_json(quality_path, label="Stage 1 quality report")
    manifest_hash = _self_hash(manifest, "manifest_sha256", label="Stage 1 manifest")
    if (
        manifest.get("run_id") != rules["stage1_run_id"]
        or manifest.get("dataset_version") != "stage1-trades-v2"
        or manifest.get("source")
        != "Binance official public USD-M Futures Trades archives"
        or set(cast(dict[str, Any], manifest.get("symbols", {}))) != {
            "BTCUSDT",
            "ETHUSDT",
        }
        or quality.get("status") != "PASS"
        or quality.get("errors") != []
    ):
        raise ValueError("Stage 1 catalog or quality gate drift")

    entries: dict[str, tuple[Path, str]] = {}
    for instrument, role in (
        ("BTCUSDT", "btc_stage1_logical_hash"),
        ("ETHUSDT", "eth_stage1_logical_hash"),
    ):
        catalog_path = root / f"{instrument}.catalog.json"
        catalog = _safe_json(catalog_path, label=f"{instrument} Stage 1 Catalog")
        logical_hash = str(catalog.get("logical_data_hash"))
        quality_symbol = cast(dict[str, Any], quality["symbols"])[instrument]
        manifest_symbol = cast(dict[str, Any], manifest["symbols"])[instrument]
        if (
            catalog.get("status") != "READY_TO_PUBLISH"
            or catalog.get("date_start") != SCOPE_START
            or catalog.get("date_end_inclusive") != "2026-07-03"
            or catalog.get("partitions") != 2376
            or manifest_symbol.get("logical_data_hash") != logical_hash
            or quality_symbol.get("partitions") != catalog.get("partitions")
            or quality_symbol.get("rows") != catalog.get("rows")
        ):
            raise ValueError(f"{instrument} Stage 1 logical binding drift")
        entries[role] = (catalog_path, logical_hash)

    quality_hash = canonical_content_hash(quality)
    entries["canonical_trades_catalog_hash"] = (manifest_path, manifest_hash)
    entries["canonical_trades_verify_hash"] = (quality_path, quality_hash)
    return entries


def _contract_price_catalog_hash(
    partitions: list[dict[str, Any]],
) -> str:
    normalized = sorted(
        (
            {
                "instrument": str(row["instrument"]),
                "date": str(row["date"]),
                "path": str(row["path"]),
                "sha256": str(row["sha256"]),
                "size_bytes": int(row["size_bytes"]),
                "row_count": int(row["row_count"]),
            }
            for row in partitions
        ),
        key=lambda row: (row["instrument"], row["date"]),
    )
    keys = {(row["instrument"], row["date"]) for row in normalized}
    if len(normalized) != EXPECTED_PARTITION_COUNT or keys != EXPECTED_PARTITION_KEYS:
        raise ValueError("Contract Price production partition coverage drift")
    return canonical_content_hash(
        {
            "schema_name": "s2p19-contract-price-catalog-binding-v1",
            "scope_start_date": SCOPE_START,
            "scope_end_date_exclusive": SCOPE_END_EXCLUSIVE,
            "partition_count": len(normalized),
            "partitions": normalized,
        }
    )


def _validate_funding(path: Path) -> str:
    acceptance = _safe_json(path, label="funding acceptance")
    acceptance_hash = _self_hash(
        acceptance,
        "acceptance_hash",
        label="funding acceptance",
    )
    if (
        acceptance.get("schema_name") != "s2p13-funding-local-history-acceptance"
        or acceptance.get("human_accepted") is not True
        or acceptance.get("historical_funding_bound") is not True
        or acceptance.get("legacy_sources_modified") is not False
        or acceptance.get("lifecycle_run_created") is not False
        or acceptance.get("stage3_locked") is not True
    ):
        raise ValueError("funding acceptance gate drift")
    local = acceptance.get("local_history")
    if not isinstance(local, dict) or set(local) != {"BTCUSDT", "ETHUSDT"}:
        raise ValueError("funding acceptance instrument binding drift")
    for instrument, raw in cast(dict[str, dict[str, Any]], local).items():
        source = _external_path(str(raw["path"]))
        if (
            sha256_file(source) != raw.get("sha256")
            or raw.get("start_ts_ms") != 1577836800000
            or int(raw.get("end_ts_ms", 0)) < 1783094400000
            or raw.get("funding_interval_hours") != [8]
        ):
            raise ValueError(f"{instrument} funding source drift")
    return acceptance_hash


def _validate_t10(path: Path, rules: dict[str, Any]) -> str:
    manifest = _safe_json(path, label="T10 manifest")
    manifest_hash = _self_hash(manifest, "manifest_hash", label="T10 manifest")
    if (
        manifest.get("schema_name") != "stage2-v2-execution-manifest"
        or manifest.get("task_id") != "S2-T10"
        or manifest.get("snapshot_id") != rules["t10_snapshot_id"]
    ):
        raise ValueError("T10 manifest binding drift")
    return manifest_hash


def _validate_primary(path: Path) -> str:
    config = _safe_json(path, label="Group 1 primary config")
    primary = config.get("primary")
    if (
        config.get("status") != "BASELINE_RESEARCH_PREREGISTERED"
        or config.get("primary_parameter_set_id") != "G1-PRIMARY-V1"
        or not isinstance(primary, dict)
        or primary.get("timing_id") != "T2"
        or primary.get("sweep_confirmation_bps") != "2"
        or primary.get("reclaim_buffer_bps") != "1"
        or primary.get("hold_failure_buffer_bps") != "1"
        or primary.get("max_sweep_depth_bps") != "25"
    ):
        raise ValueError("Group 1 primary config drift")
    config_hash = config.get("config_hash")
    if not isinstance(config_hash, str) or len(config_hash) != 64:
        raise ValueError("Group 1 declared config Hash is invalid")
    return config_hash


def _validate_matching(path: Path, rules: dict[str, Any]) -> tuple[str, int]:
    authority = _safe_json(path, label="T16 matching Authority")
    authority_hash = _self_hash(
        authority,
        "authority_hash",
        label="T16 matching Authority",
    )
    if (
        authority_hash != rules["matching_authority_hash"]
        or authority.get("schema_name") != "stage2-s2p13-t16-contract-authority"
        or authority.get("controls_per_episode") != 5
        or authority.get("exact_match_fields") != EXPECTED_EXACT_MATCH_FIELDS
        or authority.get("relaxation_order") != ["L0", "L1", "L2", "L3", "L4", "L5"]
        or authority.get("quintile_algorithm_id")
        != "TIE_PRESERVING_NEAREST_CUMULATIVE_V1"
        or authority.get("source_t10_binding_hash") != rules["t10_snapshot_id"]
        or len(cast(list[object], authority.get("combination_order", []))) != 30
        or ["G1-PRIMARY-V1", "T2"]
        not in cast(list[list[str]], authority.get("registered_parameter_timing_pairs", []))
    ):
        raise ValueError("T16 matching contract drift")
    return authority_hash, int(authority["matching_seed"])


def _validate_cluster(path: Path, rules: dict[str, Any]) -> tuple[str, int]:
    authority = _safe_json(path, label="T18 cluster Authority")
    authority_hash = _self_hash(
        authority,
        "authority_hash",
        label="T18 cluster Authority",
    )
    if (
        authority_hash != rules["cluster_authority_hash"]
        or authority.get("schema_name") != "s2p15-t18-authority"
        or authority.get("cluster_contract") != "INSTRUMENT_UTC_MONDAY_WEEK_V1"
        or authority.get("bootstrap_iterations") != 5000
        or authority.get("rng") != "NUMPY_PCG64_DERIVED_GROUP_SEED_V1"
        or authority.get("stage3_locked") is not True
    ):
        raise ValueError("T18 cluster contract drift")
    return authority_hash, int(authority["bootstrap_seed"])


def _validate_fixed_seed(
    *,
    repository_root: Path,
    rules: dict[str, Any],
    matching_seed: int,
    bootstrap_seed: int,
) -> str:
    paths = cast(dict[str, str], rules["paths"])
    placebo = _safe_json(
        _repository_path(repository_root, paths["placebo_config"]),
        label="T17 placebo config",
    )
    final_acceptance = _safe_json(
        _repository_path(repository_root, paths["final_acceptance_config"]),
        label="T20 final acceptance config",
    )
    values = {
        "matching_seed": matching_seed,
        "placebo_seed": int(placebo["placebo_seed"]),
        "bootstrap_seed": bootstrap_seed,
        "event_card_seed": int(final_acceptance["event_card_seed"]),
    }
    if set(values.values()) != {rules["fixed_seed"]}:
        raise ValueError("fixed seed consumers disagree")
    return canonical_content_hash(
        {
            "schema_name": "s2p19-four-consumer-fixed-seed-binding-v1",
            **values,
        }
    )


def _validate_historical_t20(path: Path, rules: dict[str, Any]) -> str:
    verify = _safe_json(path, label="historical T20 Verify")
    verify_hash = _self_hash(verify, "verify_hash", label="historical T20 Verify")
    if (
        verify_hash != rules["historical_t20_verify_hash"]
        or verify.get("schema_name") != "s2p17-t20-verify-record"
        or verify.get("status") != "PASS"
        or verify.get("research_decision") != "STAGE2_NO_GO_CURRENT_EVIDENCE"
        or verify.get("stage3_locked") is not True
    ):
        raise ValueError("historical T20 Verify drift")
    return verify_hash


def build_production_input_spec(
    *,
    repository_root: Path,
    contract_price_partitions: list[dict[str, Any]],
) -> ProductionInputSpec:
    """Derive the twelve production bindings without operator-supplied Hashes."""

    repository_root = repository_root.resolve()
    rules, rules_hash = _load_rules(repository_root)
    paths = cast(dict[str, str], rules["paths"])
    entries = _validate_stage1(rules)

    checkpoint = _external_path(paths["contract_price_source_checkpoint"])
    _safe_json(checkpoint, label="Contract Price source checkpoint")
    entries["contract_price_catalog_hash"] = (
        checkpoint,
        _contract_price_catalog_hash(contract_price_partitions),
    )

    funding_path = _external_path(paths["funding_acceptance"])
    entries["funding_acceptance_hash"] = (
        funding_path,
        _validate_funding(funding_path),
    )
    t10_path = _external_path(paths["t10_manifest"])
    entries["t10_manifest_hash"] = (t10_path, _validate_t10(t10_path, rules))

    primary_path = _repository_path(repository_root, paths["primary_config"])
    entries["primary_config_hash"] = (primary_path, _validate_primary(primary_path))

    matching_path = _external_path(paths["matching_authority"])
    matching_hash, matching_seed = _validate_matching(matching_path, rules)
    entries["matching_contract_hash"] = (matching_path, matching_hash)

    cluster_path = _external_path(paths["cluster_authority"])
    cluster_hash, bootstrap_seed = _validate_cluster(cluster_path, rules)
    entries["cluster_contract_hash"] = (cluster_path, cluster_hash)
    entries["fixed_seed_hash"] = (
        matching_path,
        _validate_fixed_seed(
            repository_root=repository_root,
            rules=rules,
            matching_seed=matching_seed,
            bootstrap_seed=bootstrap_seed,
        ),
    )

    t20_path = _external_path(paths["historical_t20_verify"])
    entries["historical_t20_verify_hash"] = (
        t20_path,
        _validate_historical_t20(t20_path, rules),
    )
    if set(entries) != REQUIRED_INPUT_BINDINGS:
        raise AssertionError("production input builder did not produce twelve exact roles")
    return ProductionInputSpec(entries=entries, rules_hash=rules_hash)


def validate_production_inputs_lock(
    *,
    inputs_lock: InputsLock,
    repository_root: Path,
) -> None:
    """Re-derive every semantic Hash before Authority creation."""

    partitions = [dict(row) for row in inputs_lock.partitions]
    expected = build_production_input_spec(
        repository_root=repository_root,
        contract_price_partitions=partitions,
    )
    if inputs_lock.production_binding_rules_hash != expected.rules_hash:
        raise ValueError("inputs lock production binding rules Hash drift")
    for role, (path, binding_hash) in expected.entries.items():
        actual = inputs_lock.bindings[role]
        if actual.path != path or actual.binding_hash != binding_hash:
            raise ValueError(f"inputs lock production semantic binding drift: {role}")
