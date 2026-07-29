"""Immutable path-to-Hash bindings for the Plan v1.8 formal chain."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    read_canonical_json,
    sha256_file,
    write_canonical_json_exclusive,
)

INPUT_CATALOG_SCHEMA: Final = "s2p18-input-catalog-v1"
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
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class InputBinding:
    role: str
    path: Path
    sha256: str
    binding_hash: str


@dataclass(frozen=True, slots=True)
class InputCatalog:
    path: Path
    catalog_hash: str
    bindings: dict[str, InputBinding]

    @property
    def binding_hashes(self) -> dict[str, str]:
        return {
            role: binding.binding_hash
            for role, binding in sorted(self.bindings.items())
        }


def _self_hash(payload: dict[str, Any]) -> str:
    return canonical_content_hash(
        {key: value for key, value in payload.items() if key != "input_catalog_hash"}
    )


def load_input_catalog(path: Path) -> InputCatalog:
    """Read and fully verify every immutable input evidence object."""

    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("Plan v1.8 input Catalog path must be an absolute regular file")
    payload = read_canonical_json(path)
    claimed = payload.get("input_catalog_hash")
    raw_entries = payload.get("entries")
    if (
        payload.get("schema_name") != INPUT_CATALOG_SCHEMA
        or payload.get("schema_version") != "1.0"
        or payload.get("stage_plan_version") != "1.8"
        or payload.get("historical_execution_claim") is not False
        or payload.get("stage3_locked") is not True
        or not isinstance(claimed, str)
        or claimed != _self_hash(payload)
        or not isinstance(raw_entries, list)
    ):
        raise ValueError("Plan v1.8 input Catalog identity or self Hash drift")
    bindings: dict[str, InputBinding] = {}
    for raw in cast(list[object], raw_entries):
        if not isinstance(raw, dict) or set(raw) != {
            "role",
            "path",
            "sha256",
            "binding_hash",
        }:
            raise ValueError("Plan v1.8 input Catalog entry fields drift")
        role = str(raw["role"])
        target = Path(str(raw["path"]))
        expected_sha = str(raw["sha256"])
        binding_hash = str(raw["binding_hash"])
        if (
            role in bindings
            or role not in REQUIRED_INPUT_BINDINGS
            or not target.is_absolute()
            or target.is_symlink()
            or not target.is_file()
            or not HEX64.fullmatch(expected_sha)
            or not HEX64.fullmatch(binding_hash)
            or sha256_file(target) != expected_sha
        ):
            raise ValueError(f"Plan v1.8 input binding drift: {role}")
        bindings[role] = InputBinding(
            role=role,
            path=target,
            sha256=expected_sha,
            binding_hash=binding_hash,
        )
    if set(bindings) != REQUIRED_INPUT_BINDINGS:
        raise ValueError("Plan v1.8 input Catalog is incomplete")
    return InputCatalog(path=path, catalog_hash=claimed, bindings=bindings)


def write_input_catalog(
    *,
    path: Path,
    entries: dict[str, tuple[Path, str]],
) -> Path:
    """Seal exact evidence paths plus their semantic binding Hashes."""

    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Plan v1.8 input Catalog output path must be absolute")
    if set(entries) != REQUIRED_INPUT_BINDINGS:
        raise ValueError("Plan v1.8 input Catalog requires twelve exact roles")
    rows: list[dict[str, str]] = []
    for role, (target, binding_hash) in sorted(entries.items()):
        if (
            not target.is_absolute()
            or target.is_symlink()
            or not target.is_file()
            or not HEX64.fullmatch(binding_hash)
        ):
            raise ValueError(f"unsafe input Catalog source: {role}")
        rows.append(
            {
                "role": role,
                "path": str(target),
                "sha256": sha256_file(target),
                "binding_hash": binding_hash,
            }
        )
    payload: dict[str, object] = {
        "schema_name": INPUT_CATALOG_SCHEMA,
        "schema_version": "1.0",
        "stage_plan_version": "1.8",
        "entries": rows,
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    payload["input_catalog_hash"] = canonical_content_hash(payload)
    write_canonical_json_exclusive(path, payload)
    load_input_catalog(path)
    return path
