"""Single-file immutable inputs lock for the Plan v1.9 solo runtime."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final, cast

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    read_canonical_json,
    sha256_file,
    write_canonical_json_exclusive,
)

INPUTS_LOCK_SCHEMA: Final = "s2p19-inputs-lock-v1"
REQUIRED_INPUT_BINDINGS: Final = frozenset(
    {
        "btc_stage1_logical_hash",
        "eth_stage1_logical_hash",
        "canonical_trades_catalog_hash",
        "canonical_trades_verify_hash",
        "contract_price_catalog_hash",
        "funding_acceptance_hash",
        "t10_manifest_hash",
        "primary_config_hash",
        "matching_contract_hash",
        "cluster_contract_hash",
        "fixed_seed_hash",
        "historical_t20_verify_hash",
    }
)
REQUIRED_BINDING_RULES: Final = {
    "btc_stage1_logical_hash": "STAGE1_INSTRUMENT_LOGICAL_DATA_HASH_V1",
    "eth_stage1_logical_hash": "STAGE1_INSTRUMENT_LOGICAL_DATA_HASH_V1",
    "canonical_trades_catalog_hash": "STAGE1_MANIFEST_SELF_HASH_V1",
    "canonical_trades_verify_hash": "STAGE1_QUALITY_REPORT_CANONICAL_HASH_V1",
    "contract_price_catalog_hash": "FULL_PERIOD_PARTITION_CATALOG_CANONICAL_HASH_V1",
    "funding_acceptance_hash": "FUNDING_ACCEPTANCE_SELF_HASH_V1",
    "t10_manifest_hash": "T10_MANIFEST_SELF_HASH_V1",
    "primary_config_hash": "GROUP1_DECLARED_CONFIG_HASH_V1",
    "matching_contract_hash": "T16_AUTHORITY_SELF_HASH_V1",
    "cluster_contract_hash": "T18_AUTHORITY_SELF_HASH_V1",
    "fixed_seed_hash": "FOUR_CONSUMER_FIXED_SEED_CANONICAL_HASH_V1",
    "historical_t20_verify_hash": "T20_VERIFY_SELF_HASH_V1",
}
HEX64: Final = re.compile(r"^[0-9a-f]{64}$")
SCOPE_START: Final = "2020-01-01"
SCOPE_END_EXCLUSIVE: Final = "2026-07-04"


def _expected_partition_keys() -> frozenset[tuple[str, str]]:
    start = date.fromisoformat(SCOPE_START)
    end = date.fromisoformat(SCOPE_END_EXCLUSIVE)
    keys: set[tuple[str, str]] = set()
    current = start
    while current < end:
        keys.update((instrument, current.isoformat()) for instrument in ("BTCUSDT", "ETHUSDT"))
        current += timedelta(days=1)
    return frozenset(keys)


EXPECTED_PARTITION_KEYS: Final = _expected_partition_keys()
EXPECTED_PARTITION_COUNT: Final = len(EXPECTED_PARTITION_KEYS)


@dataclass(frozen=True, slots=True)
class InputBinding:
    role: str
    path: Path
    sha256: str
    binding_hash: str
    binding_rule: str


@dataclass(frozen=True, slots=True)
class InputsLock:
    path: Path
    inputs_lock_hash: str
    production_binding_rules_hash: str
    source_audit: dict[str, Any]
    partitions: tuple[dict[str, Any], ...]
    bindings: dict[str, InputBinding]

    @property
    def binding_hashes(self) -> dict[str, str]:
        return {role: binding.binding_hash for role, binding in sorted(self.bindings.items())}


def _without_self_hash(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "inputs_lock_hash"}


def _safe_absolute_file(path: Path, *, label: str) -> None:
    current = path
    contains_symlink = False
    while current != current.parent:
        contains_symlink = contains_symlink or current.is_symlink()
        current = current.parent
    if not path.is_absolute() or contains_symlink or not path.is_file():
        raise ValueError(f"{label} must be an absolute regular non-symlink file")


def _validate_source_audit(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("inputs lock source_audit must be an object")
    audit = cast(dict[str, Any], raw)
    if (
        audit.get("schema_name") != "stage2-lifecycle-source-audit"
        or audit.get("schema_version") != "1.1"
        or audit.get("status") != "PASS"
        or audit.get("scope_start_date") != SCOPE_START
        or audit.get("scope_end_date_exclusive") != SCOPE_END_EXCLUSIVE
        or audit.get("source_relationship") != "DISTINCT_BINANCE_ARCHIVE_FAMILIES"
        or audit.get("forward_filled_seconds_forbidden") is not True
        or audit.get("historical_execution_claim") is not False
        or audit.get("canonical_trade_overlay_mode") != "EXACT_KEY_APPEND_ONLY_SUPPLEMENT_V1"
        or audit.get("trade_supplement_instrument") != "BTCUSDT"
        or audit.get("trade_supplement_date") != "2022-03-01"
        or audit.get("legacy_stage1_partition_modified") is not False
        or not isinstance(audit.get("trade_supplement_acceptance_path"), str)
        or not Path(str(audit["trade_supplement_acceptance_path"])).is_absolute()
        or not HEX64.fullmatch(str(audit.get("trade_supplement_file_sha256")))
        or not HEX64.fullmatch(str(audit.get("trade_supplement_acceptance_hash")))
        or audit.get("audit_hash")
        != canonical_content_hash(
            {key: value for key, value in audit.items() if key != "audit_hash"}
        )
    ):
        raise ValueError("inputs lock full-period source audit gate failed")
    audits = audit.get("audits")
    if not isinstance(audits, list) or {
        item.get("instrument") for item in audits if isinstance(item, dict)
    } != {"BTCUSDT", "ETHUSDT"}:
        raise ValueError("inputs lock source audit must keep BTC and ETH separate")
    return audit


def _validate_partition_rows(
    raw: object,
    *,
    verify_files: bool,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, list):
        raise ValueError("inputs lock Contract Price partitions must be a list")
    partitions: list[dict[str, Any]] = []
    keys: set[tuple[str, str]] = set()
    for item in cast(list[object], raw):
        if not isinstance(item, dict) or set(item) != {
            "instrument",
            "date",
            "path",
            "sha256",
            "size_bytes",
            "row_count",
        }:
            raise ValueError("inputs lock Contract Price partition fields drift")
        instrument = str(item["instrument"])
        partition_date = str(item["date"])
        key = (instrument, partition_date)
        path = Path(str(item["path"]))
        if (
            instrument not in {"BTCUSDT", "ETHUSDT"}
            or key in keys
            or not HEX64.fullmatch(str(item["sha256"]))
            or not isinstance(item["size_bytes"], int)
            or int(item["size_bytes"]) <= 0
            or not isinstance(item["row_count"], int)
            or int(item["row_count"]) <= 0
        ):
            raise ValueError("invalid Contract Price partition binding")
        if verify_files:
            _safe_absolute_file(path, label="Contract Price partition")
            if (
                sha256_file(path) != item["sha256"]
                or path.stat().st_size != item["size_bytes"]
                or instrument not in path.name
                or partition_date.replace("-", "") not in path.name
            ):
                raise ValueError(f"Contract Price partition Hash drift: {path}")
        keys.add(key)
        partitions.append(cast(dict[str, Any], item))
    if len(partitions) != EXPECTED_PARTITION_COUNT or keys != EXPECTED_PARTITION_KEYS:
        raise ValueError("inputs lock Contract Price full-period partition coverage drift")
    return tuple(partitions)


def load_inputs_lock(path: Path, *, verify_files: bool = True) -> InputsLock:
    """Load and verify the single formal input object and every bound file."""

    _safe_absolute_file(path, label="Plan v1.9 inputs lock")
    payload = read_canonical_json(path)
    claimed = payload.get("inputs_lock_hash")
    if (
        payload.get("schema_name") != INPUTS_LOCK_SCHEMA
        or payload.get("schema_version") != "1.0"
        or payload.get("stage_plan_version") != "1.9"
        or payload.get("scope_start_date") != SCOPE_START
        or payload.get("scope_end_date_exclusive") != SCOPE_END_EXCLUSIVE
        or not HEX64.fullmatch(str(payload.get("production_binding_rules_hash")))
        or payload.get("historical_execution_claim") is not False
        or payload.get("stage3_locked") is not True
        or not isinstance(claimed, str)
        or path.name != f"inputs-{claimed}.lock.json"
        or claimed != canonical_content_hash(_without_self_hash(payload))
    ):
        raise ValueError("Plan v1.9 inputs lock identity or self Hash drift")
    source_audit = _validate_source_audit(payload.get("source_audit"))
    partitions = _validate_partition_rows(
        payload.get("contract_price_partitions"),
        verify_files=verify_files,
    )
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Plan v1.9 inputs lock entries must be a list")
    bindings: dict[str, InputBinding] = {}
    for raw in cast(list[object], entries):
        if not isinstance(raw, dict) or set(raw) != {
            "role",
            "path",
            "sha256",
            "binding_hash",
            "binding_rule",
        }:
            raise ValueError("Plan v1.9 inputs lock entry fields drift")
        role = str(raw["role"])
        target = Path(str(raw["path"]))
        expected_sha = str(raw["sha256"])
        binding_hash = str(raw["binding_hash"])
        binding_rule = str(raw["binding_rule"])
        if (
            role in bindings
            or role not in REQUIRED_INPUT_BINDINGS
            or not HEX64.fullmatch(expected_sha)
            or not HEX64.fullmatch(binding_hash)
            or REQUIRED_BINDING_RULES.get(role) != binding_rule
        ):
            raise ValueError(f"invalid Plan v1.9 input binding: {role}")
        if verify_files:
            _safe_absolute_file(target, label=f"input binding {role}")
            if sha256_file(target) != expected_sha:
                raise ValueError(f"Plan v1.9 input Hash drift: {role}")
        bindings[role] = InputBinding(
            role=role,
            path=target,
            sha256=expected_sha,
            binding_hash=binding_hash,
            binding_rule=binding_rule,
        )
    if set(bindings) != REQUIRED_INPUT_BINDINGS:
        raise ValueError("Plan v1.9 inputs lock requires twelve exact roles")
    return InputsLock(
        path=path,
        inputs_lock_hash=claimed,
        production_binding_rules_hash=str(payload["production_binding_rules_hash"]),
        source_audit=source_audit,
        partitions=partitions,
        bindings=bindings,
    )


def write_inputs_lock(
    *,
    inputs_root: Path,
    entries: dict[str, tuple[Path, str]],
    source_audit: dict[str, Any],
    contract_price_partitions: list[dict[str, Any]],
    production_binding_rules_hash: str,
) -> Path:
    """Create the one append-only input lock after all source checks pass."""

    if not inputs_root.is_absolute() or any(
        part.is_symlink() for part in (inputs_root, *inputs_root.parents)
    ):
        raise ValueError("Plan v1.9 inputs root must be absolute and non-symlink")
    if set(entries) != REQUIRED_INPUT_BINDINGS:
        raise ValueError("Plan v1.9 inputs lock requires twelve exact roles")
    if not HEX64.fullmatch(production_binding_rules_hash):
        raise ValueError("production binding rules Hash is invalid")
    _validate_source_audit(source_audit)
    _validate_partition_rows(contract_price_partitions, verify_files=True)
    rows: list[dict[str, object]] = []
    for role, (target, binding_hash) in sorted(entries.items()):
        _safe_absolute_file(target, label=f"input binding {role}")
        if not HEX64.fullmatch(binding_hash):
            raise ValueError(f"invalid semantic binding Hash: {role}")
        rows.append(
            {
                "role": role,
                "path": str(target),
                "sha256": sha256_file(target),
                "binding_hash": binding_hash,
                "binding_rule": REQUIRED_BINDING_RULES[role],
            }
        )
    payload: dict[str, Any] = {
        "schema_name": INPUTS_LOCK_SCHEMA,
        "schema_version": "1.0",
        "stage_plan_version": "1.9",
        "scope_start_date": SCOPE_START,
        "scope_end_date_exclusive": SCOPE_END_EXCLUSIVE,
        "production_binding_rules_hash": production_binding_rules_hash,
        "entries": rows,
        "source_audit": source_audit,
        "contract_price_partitions": contract_price_partitions,
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    payload["inputs_lock_hash"] = canonical_content_hash(payload)
    path = inputs_root / f"inputs-{payload['inputs_lock_hash']}.lock.json"
    if path.exists():
        existing = load_inputs_lock(path)
        if existing.inputs_lock_hash != payload["inputs_lock_hash"]:
            raise ValueError("existing inputs lock identity drift")
        return path
    write_canonical_json_exclusive(path, payload)
    load_inputs_lock(path)
    return path
