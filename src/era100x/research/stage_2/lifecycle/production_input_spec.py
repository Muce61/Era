"""Fail-closed production derivation for Plan v1.10 sealed inputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    sha256_file,
)
from era100x.research.stage_2.rerun.trade_supplement import (
    verify_trade_supplement,
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
from .sealed_adoption import SealedAdoptionBundle, load_sealed_adoption_bundle

RULES_RELATIVE_PATH: Final = Path(
    "configs/research/stage_2/s2p110_production_input_bindings_v1.json"
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
    adoption_bundle: SealedAdoptionBundle
    trade_supplement: ProductionTradeSupplement


@dataclass(frozen=True, slots=True)
class ProductionTradeSupplement:
    acceptance_path: Path
    file_sha256: str
    acceptance_hash: str
    manifest_hash: str
    catalog_hash: str
    instrument: str
    owner_date: str
    partition_byte_sha256: str
    partition_logical_sha256: str
    row_count: int


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
        rules.get("schema_name") != "s2p110-production-input-binding-rules"
        or rules.get("schema_version") != "1.1"
        or rules.get("stage_plan_version") != "1.10"
        or rules.get("scope_start_date") != SCOPE_START
        or rules.get("scope_end_date_exclusive") != SCOPE_END_EXCLUSIVE
        or rules.get("historical_execution_claim") is not False
        or rules.get("stage3_locked") is not True
        or rules.get("role_rules") != REQUIRED_BINDING_RULES
        or rules.get("trade_supplement_rule")
        != "EXACT_KEY_ACCEPTANCE_AND_SEALED_RECEIPT_EQUALITY_V1"
        or rules.get("trade_supplement_key") != {"instrument": "BTCUSDT", "date": "2022-03-01"}
    ):
        raise ValueError("production input binding rules drift")
    paths = rules.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("production input binding paths are missing")
    return rules, rules_hash


def _validate_trade_supplement(
    rules: dict[str, Any],
) -> ProductionTradeSupplement:
    paths = cast(dict[str, str], rules["paths"])
    acceptance_path = _external_path(paths["trade_supplement_acceptance"])
    acceptance = _safe_json(
        acceptance_path,
        label="Trade supplement acceptance",
    )
    verified = verify_trade_supplement(acceptance_path)
    manifest_path = _external_path(str(acceptance.get("manifest_path", "")))
    manifest = _safe_json(manifest_path, label="Trade supplement Manifest")
    instrument = str(verified.get("instrument", ""))
    owner_date = str(verified.get("date", ""))
    expected_published_root = _external_path(paths["stage1_published_root"])
    expected_partition_root = (
        expected_published_root / instrument / f"archive={owner_date[:7]}" / f"date={owner_date}"
    )
    original_receipt_path = expected_partition_root / "partition.json"
    original_receipt = _safe_json(
        original_receipt_path,
        label="original Stage 1 Trade receipt",
    )
    catalog_root = _external_path(paths["stage1_catalog_root"])
    catalog = _safe_json(
        catalog_root / f"{instrument}.catalog.json",
        label="Stage 1 supplement instrument Catalog",
    )
    matching_entries = [
        item
        for item in cast(list[object], catalog.get("entries", []))
        if isinstance(item, dict) and item.get("date") == owner_date
    ]
    if len(matching_entries) != 1:
        raise ValueError("Trade supplement sealed Catalog key is not unique")
    catalog_entry = cast(dict[str, Any], matching_entries[0])
    acceptance_hash = str(verified.get("acceptance_hash", ""))
    partition_byte_hash = str(verified.get("partition_byte_sha256", ""))
    partition_logical_hash = str(verified.get("partition_logical_sha256", ""))
    if (
        acceptance.get("append_only") is not True
        or acceptance.get("legacy_partition_modified") is not False
        or instrument != "BTCUSDT"
        or owner_date != "2022-03-01"
        or manifest.get("change_request") != "CR-2026-043"
        or manifest.get("decision") != "ADR-S2-020"
        or manifest.get("source_archive_path") != paths["trade_supplement_source_archive"]
        or manifest.get("source_checksum_path") != paths["trade_supplement_source_checksum"]
        or manifest.get("original_partition_root") != str(expected_partition_root)
        or manifest.get("original_receipt_path") != str(original_receipt_path)
        or manifest.get("original_expected_byte_sha256") != partition_byte_hash
        or catalog_entry.get("byte_sha256") != partition_byte_hash
        or original_receipt.get("byte_sha256") != partition_byte_hash
        or original_receipt.get("logical_sha256") != partition_logical_hash
        or original_receipt.get("rows") != verified.get("row_count")
        or acceptance.get("acceptance_hash") != acceptance_hash
    ):
        raise ValueError("Trade supplement exact-key sealed binding drift")
    return ProductionTradeSupplement(
        acceptance_path=acceptance_path,
        file_sha256=sha256_file(acceptance_path),
        acceptance_hash=acceptance_hash,
        manifest_hash=str(verified["manifest_hash"]),
        catalog_hash=str(verified["catalog_hash"]),
        instrument=instrument,
        owner_date=owner_date,
        partition_byte_sha256=partition_byte_hash,
        partition_logical_sha256=partition_logical_hash,
        row_count=int(verified["row_count"]),
    )


def load_production_trade_supplement(
    repository_root: Path,
) -> ProductionTradeSupplement:
    """Derive the only production Trade overlay from the committed rules."""

    rules, _ = _load_rules(repository_root.resolve())
    return _validate_trade_supplement(rules)


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
        or manifest.get("source") != "Binance official public USD-M Futures Trades archives"
        or set(cast(dict[str, Any], manifest.get("symbols", {})))
        != {
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
            "schema_name": "s2p110-contract-price-catalog-binding-v1",
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
        or authority.get("quintile_algorithm_id") != "TIE_PRESERVING_NEAREST_CUMULATIVE_V1"
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
            "schema_name": "s2p110-four-consumer-fixed-seed-binding-v1",
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
    trade_supplement = _validate_trade_supplement(rules)
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
    adoption_bundle = load_sealed_adoption_bundle(
        repository_root,
        current_bindings={role: binding_hash for role, (_, binding_hash) in entries.items()},
    )
    return ProductionInputSpec(
        entries=entries,
        rules_hash=rules_hash,
        adoption_bundle=adoption_bundle,
        trade_supplement=trade_supplement,
    )


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
    if inputs_lock.adoption_bundle_hash != expected.adoption_bundle.bundle_hash:
        raise ValueError("inputs lock adoption bundle Hash drift")
    audit = inputs_lock.source_audit
    supplement = expected.trade_supplement
    if (
        audit.get("schema_version") != "1.2"
        or audit.get("evidence_mode") != "SEALED_INCREMENTAL_V1"
        or audit.get("full_trade_row_rescan") is not False
        or audit.get("canonical_trade_overlay_mode") != "EXACT_KEY_APPEND_ONLY_SUPPLEMENT_V1"
        or audit.get("trade_supplement_acceptance_path") != str(supplement.acceptance_path)
        or audit.get("trade_supplement_file_sha256") != supplement.file_sha256
        or audit.get("trade_supplement_acceptance_hash") != supplement.acceptance_hash
        or audit.get("trade_supplement_instrument") != supplement.instrument
        or audit.get("trade_supplement_date") != supplement.owner_date
        or audit.get("legacy_stage1_partition_modified") is not False
    ):
        raise ValueError("inputs lock Trade supplement binding drift")
    if tuple(expected.adoption_bundle.lock_payload()) != inputs_lock.adopted_task_bindings:
        raise ValueError("inputs lock sealed adoption bindings drift")
    for role, (path, binding_hash) in expected.entries.items():
        actual = inputs_lock.bindings[role]
        if actual.path != path or actual.binding_hash != binding_hash:
            raise ValueError(f"inputs lock production semantic binding drift: {role}")
