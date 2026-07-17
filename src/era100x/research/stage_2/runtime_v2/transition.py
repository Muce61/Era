"""Append-only authority records for the S2-T10 v1.8 hybrid cut-over."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from era100x.research.stage_2.manifests.models import canonical_json, sha256_text

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class OrchestrationSupersessionRecord(_FrozenModel):
    schema_name: Literal["stage2-orchestration-supersession-v1"]
    status: Literal["SUPERSEDED_AFTER_RUN_A_PUBLISHED"]
    scope: Literal["S2_T10_V1_7_DUAL_RUN_ORCHESTRATION_ONLY"]
    run_a_id: str
    run_a_status: Literal["PUBLISHED_VALID_SOURCE_ONLY"]
    legacy_run_b_status: Literal["NOT_CREATED"]
    comparison_status: Literal["NOT_RUN"]
    s2_t10_acceptance: Literal[False]
    candidate_semantics_invalidated: Literal[False]
    published_mutation_authorized: Literal[False]
    reason_code: Literal["PHYSICAL_PUBLICATION_LAYOUT_SCALABILITY"]
    successor_change_requests: tuple[Literal["CR-2026-007", "CR-2026-008"], ...]
    successor_task: Literal["S2-T10-v1.8"]
    approved_by: Literal["Muce"]
    approved_at: str


class RunAPublishedSourceProtectionManifest(_FrozenModel):
    schema_name: Literal["stage2-run-a-source-protection-v1"]
    manifest_version: Literal["1.0"]
    role: Literal["IMMUTABLE_V2_MIGRATION_SOURCE"]
    source_run_id: str
    checkpoint_status: Literal["PUBLISHED"]
    release_state: Literal["PUBLISHED"]
    planned_count: Literal[9508]
    completed_count: Literal[9508]
    failed_count: Literal[0]
    catalog_entry_count: Literal[61776]
    execution_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    release_supplement_hash: str = Field(pattern=SHA256_PATTERN)
    generator_commit: str = Field(min_length=40, max_length=40)
    checkpoint_sha256: str = Field(pattern=SHA256_PATTERN)
    catalog_sha256: str = Field(pattern=SHA256_PATTERN)
    catalog_logical_hash: str = Field(pattern=SHA256_PATTERN)
    catalog_physical_hash: str = Field(pattern=SHA256_PATTERN)
    quality_report_sha256: str = Field(pattern=SHA256_PATTERN)
    count_summary_sha256: str = Field(pattern=SHA256_PATTERN)
    release_analysis_sha256: str = Field(pattern=SHA256_PATTERN)
    preregistration_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    config_hash: str = Field(pattern=SHA256_PATTERN)
    stage1_data_run_id: str
    stage1_logical_hashes: dict[Literal["BTCUSDT", "ETHUSDT"], str]
    protected_relative_paths: tuple[str, ...]
    recorded_at: str
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"manifest_hash"})
        return sha256_text(canonical_json(payload))

    @model_validator(mode="after")
    def hash_matches(self) -> Self:
        if self.manifest_hash != "0" * 64 and self.manifest_hash != self.computed_hash():
            raise ValueError("Run A protection manifest hash mismatch")
        if any(len(value) != 64 for value in self.stage1_logical_hashes.values()):
            raise ValueError("invalid Stage 1 logical hash")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "manifest_hash": "0" * 64})
        return provisional.model_copy(update={"manifest_hash": provisional.computed_hash()})


class V2MigrationManifest(_FrozenModel):
    schema_name: Literal["stage2-v2-migration-manifest-v1"]
    manifest_version: Literal["1.0"]
    operation: Literal["BUILD_V2_FOUNDATION_AND_RECONSTRUCT_GROUP1"]
    change_requests: tuple[Literal["CR-2026-007", "CR-2026-008"], ...]
    source_protection_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    source_run_id: str
    destination_run_id: str
    destination_root: str
    v2_code_commit: str = Field(min_length=40, max_length=40)
    v2_code_tree_hash: str = Field(pattern=SHA256_PATTERN)
    catalog_schema_version: Literal["2.0"]
    semantic_hash_algorithm: Literal["era-canonical-binary-v2"]
    legacy_hash_algorithm: Literal["era-canonical-json-row-v1"]
    snapshot_reader_mode: Literal["EXPLICIT_SNAPSHOT_ID_ONLY"]
    source_delete_allowed: Literal[False]
    run_a_artifact_reuse_allowed: Literal[False]
    same_volume_atomic_publish: Literal[True]
    contract_price_inventory_manifest_path: str
    contract_price_inventory_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    contract_price_inventory_source_sha256: str = Field(pattern=SHA256_PATTERN)
    stage1_resolved_source_index_path: str
    stage1_resolved_source_index_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    stage1_resolved_source_index_source_sha256: str = Field(pattern=SHA256_PATTERN)
    recorded_at: str
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"manifest_hash"})
        return sha256_text(canonical_json(payload))

    @model_validator(mode="after")
    def hash_matches(self) -> Self:
        if self.manifest_hash != "0" * 64 and self.manifest_hash != self.computed_hash():
            raise ValueError("V2 migration manifest hash mismatch")
        for value in (
            self.contract_price_inventory_manifest_path,
            self.stage1_resolved_source_index_path,
        ):
            if not Path(value).is_absolute():
                raise ValueError("V2 source authority path must be absolute")
        for digest in (
            self.contract_price_inventory_manifest_hash,
            self.contract_price_inventory_source_sha256,
            self.stage1_resolved_source_index_manifest_hash,
            self.stage1_resolved_source_index_source_sha256,
        ):
            if digest == "0" * 64:
                raise ValueError("V2 source authority digest must be sealed")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "manifest_hash": "0" * 64})
        return provisional.model_copy(update={"manifest_hash": provisional.computed_hash()})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def freeze_run_a_protection(
    *,
    run_a_root: Path,
    transition_run_root: Path,
    execution_manifest_path: Path,
    release_supplement_path: Path,
    legacy_run_b_paths: tuple[Path, ...] = (),
    approved_at: str | None = None,
) -> tuple[OrchestrationSupersessionRecord, RunAPublishedSourceProtectionManifest]:
    """Validate formal V1 publication and write evidence outside the source run."""

    if any(path.exists() for path in legacy_run_b_paths):
        raise ValueError("legacy Run B exists; NOT_CREATED assertion is false")
    checkpoint_path = run_a_root / "checkpoint.json"
    release_state_path = run_a_root / "logs" / "release-state.json"
    catalog_path = run_a_root / "manifests" / "catalog.json"
    quality_path = run_a_root / "reports" / "quality-report.json"
    counts_path = run_a_root / "reports" / "count-summary.json"
    analysis_path = run_a_root / "reports" / "release-analysis.json"
    required = (
        checkpoint_path,
        release_state_path,
        catalog_path,
        quality_path,
        counts_path,
        analysis_path,
        execution_manifest_path,
        release_supplement_path,
        run_a_root / "published" / "data",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Run A publication evidence missing: {missing}")

    checkpoint = _read_object(checkpoint_path)
    release_state = _read_object(release_state_path)
    catalog = _read_object(catalog_path)
    quality = _read_object(quality_path)
    analysis = _read_object(analysis_path)
    execution = _read_object(execution_manifest_path)
    supplement = _read_object(release_supplement_path)
    if checkpoint.get("status") != "PUBLISHED" or release_state.get("phase") != "PUBLISHED":
        raise ValueError("Run A is not terminal PUBLISHED")
    if len(checkpoint.get("planned", [])) != 9508:
        raise ValueError("Run A planned count is not 9508")
    if len(checkpoint.get("completed", [])) != 9508 or checkpoint.get("failed"):
        raise ValueError("Run A is not 9508/9508 with zero failures")
    if len(catalog.get("entries", [])) != 61776:
        raise ValueError("Run A Catalog entry count is not 61776")
    if quality.get("status") != "PASS" or analysis.get("quality", {}).get("status") != "PASS":
        raise ValueError("Run A quality is not PASS")
    if analysis.get("catalog_logical_hash") != catalog.get("logical_hash"):
        raise ValueError("Run A Catalog/release-analysis logical hash mismatch")
    if analysis.get("catalog_physical_hash") != catalog.get("physical_hash"):
        raise ValueError("Run A Catalog/release-analysis physical hash mismatch")
    if checkpoint.get("release_supplement_hash") != supplement.get("manifest_hash"):
        raise ValueError("Run A checkpoint/release supplement mismatch")

    timestamp = approved_at or datetime.now(UTC).isoformat()
    supersession = OrchestrationSupersessionRecord(
        schema_name="stage2-orchestration-supersession-v1",
        status="SUPERSEDED_AFTER_RUN_A_PUBLISHED",
        scope="S2_T10_V1_7_DUAL_RUN_ORCHESTRATION_ONLY",
        run_a_id=run_a_root.name,
        run_a_status="PUBLISHED_VALID_SOURCE_ONLY",
        legacy_run_b_status="NOT_CREATED",
        comparison_status="NOT_RUN",
        s2_t10_acceptance=False,
        candidate_semantics_invalidated=False,
        published_mutation_authorized=False,
        reason_code="PHYSICAL_PUBLICATION_LAYOUT_SCALABILITY",
        successor_change_requests=("CR-2026-007", "CR-2026-008"),
        successor_task="S2-T10-v1.8",
        approved_by="Muce",
        approved_at=timestamp,
    )
    protection = RunAPublishedSourceProtectionManifest.seal(
        {
            "schema_name": "stage2-run-a-source-protection-v1",
            "manifest_version": "1.0",
            "role": "IMMUTABLE_V2_MIGRATION_SOURCE",
            "source_run_id": run_a_root.name,
            "checkpoint_status": "PUBLISHED",
            "release_state": "PUBLISHED",
            "planned_count": 9508,
            "completed_count": 9508,
            "failed_count": 0,
            "catalog_entry_count": 61776,
            "execution_manifest_hash": execution["manifest_hash"],
            "release_supplement_hash": supplement["manifest_hash"],
            "generator_commit": supplement["generator_commit"],
            "checkpoint_sha256": sha256_file(checkpoint_path),
            "catalog_sha256": sha256_file(catalog_path),
            "catalog_logical_hash": catalog["logical_hash"],
            "catalog_physical_hash": catalog["physical_hash"],
            "quality_report_sha256": sha256_file(quality_path),
            "count_summary_sha256": sha256_file(counts_path),
            "release_analysis_sha256": sha256_file(analysis_path),
            "preregistration_manifest_hash": execution["preregistration_manifest_hash"],
            "config_hash": execution["config_hash"],
            "stage1_data_run_id": execution["stage1_data_run_id"],
            "stage1_logical_hashes": execution["stage1_logical_hashes"],
            "protected_relative_paths": tuple(
                str(path.relative_to(run_a_root)) for path in required
            ),
            "recorded_at": timestamp,
        }
    )
    for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
        (transition_run_root / name).mkdir(parents=True, exist_ok=True)
    _write_once_json(
        transition_run_root / "reports" / "orchestration-supersession.json",
        supersession.model_dump(mode="json"),
    )
    _write_once_json(
        transition_run_root / "manifests" / f"{protection.manifest_hash}.json",
        protection.model_dump(mode="json"),
    )
    return supersession, protection


def freeze_v2_migration_manifest(
    *,
    protection: RunAPublishedSourceProtectionManifest,
    transition_run_root: Path,
    destination_run_id: str,
    destination_root: Path,
    v2_code_commit: str,
    v2_code_tree_hash: str,
    contract_price_inventory_manifest_path: Path,
    stage1_resolved_source_index_path: Path,
    recorded_at: str | None = None,
) -> V2MigrationManifest:
    from .source_authority import (
        ContractPriceInventoryManifestV2,
        Stage1ResolvedSourceIndexV2,
        load_sealed_source_manifest,
    )

    contract_price_manifest_path = contract_price_inventory_manifest_path.resolve()
    trades_index_path = stage1_resolved_source_index_path.resolve()
    transition_manifests = transition_run_root.resolve() / "manifests"
    if not contract_price_manifest_path.is_relative_to(
        transition_manifests
    ) or not trades_index_path.is_relative_to(transition_manifests):
        raise ValueError("resolved source authorities must be append-only transition manifests")
    contract_price_manifest = load_sealed_source_manifest(
        contract_price_manifest_path, ContractPriceInventoryManifestV2
    )
    trades_index = load_sealed_source_manifest(trades_index_path, Stage1ResolvedSourceIndexV2)
    manifest = V2MigrationManifest.seal(
        {
            "schema_name": "stage2-v2-migration-manifest-v1",
            "manifest_version": "1.0",
            "operation": "BUILD_V2_FOUNDATION_AND_RECONSTRUCT_GROUP1",
            "change_requests": ("CR-2026-007", "CR-2026-008"),
            "source_protection_manifest_hash": protection.manifest_hash,
            "source_run_id": protection.source_run_id,
            "destination_run_id": destination_run_id,
            "destination_root": str(destination_root),
            "v2_code_commit": v2_code_commit,
            "v2_code_tree_hash": v2_code_tree_hash,
            "catalog_schema_version": "2.0",
            "semantic_hash_algorithm": "era-canonical-binary-v2",
            "legacy_hash_algorithm": "era-canonical-json-row-v1",
            "snapshot_reader_mode": "EXPLICIT_SNAPSHOT_ID_ONLY",
            "source_delete_allowed": False,
            "run_a_artifact_reuse_allowed": False,
            "same_volume_atomic_publish": True,
            "contract_price_inventory_manifest_path": str(contract_price_manifest_path),
            "contract_price_inventory_manifest_hash": contract_price_manifest.manifest_hash,
            "contract_price_inventory_source_sha256": sha256_file(contract_price_manifest_path),
            "stage1_resolved_source_index_path": str(trades_index_path),
            "stage1_resolved_source_index_manifest_hash": trades_index.manifest_hash,
            "stage1_resolved_source_index_source_sha256": sha256_file(trades_index_path),
            "recorded_at": recorded_at or datetime.now(UTC).isoformat(),
        }
    )
    _write_once_json(
        transition_run_root / "manifests" / f"{manifest.manifest_hash}.json",
        manifest.model_dump(mode="json"),
    )
    return manifest


def verify_run_a_protection(
    *,
    protection: RunAPublishedSourceProtectionManifest,
    run_a_root: Path,
    execution_manifest_path: Path,
    release_supplement_path: Path,
) -> None:
    """Re-prove the bound source before every V2 preflight or resume."""

    expected = {
        run_a_root / "checkpoint.json": protection.checkpoint_sha256,
        run_a_root / "manifests" / "catalog.json": protection.catalog_sha256,
        run_a_root / "reports" / "quality-report.json": protection.quality_report_sha256,
        run_a_root / "reports" / "count-summary.json": protection.count_summary_sha256,
        run_a_root / "reports" / "release-analysis.json": protection.release_analysis_sha256,
    }
    for path, digest in expected.items():
        if not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f"protected Run A artifact changed: {path}")
    if not (run_a_root / "published" / "data").is_dir():
        raise ValueError("protected Run A published data is missing")
    execution = _read_object(execution_manifest_path)
    supplement = _read_object(release_supplement_path)
    if execution.get("manifest_hash") != protection.execution_manifest_hash:
        raise ValueError("protected Run A Execution Manifest changed")
    if supplement.get("manifest_hash") != protection.release_supplement_hash:
        raise ValueError("protected Run A release supplement changed")
    catalog = _read_object(run_a_root / "manifests" / "catalog.json")
    if (
        catalog.get("logical_hash") != protection.catalog_logical_hash
        or catalog.get("physical_hash") != protection.catalog_physical_hash
        or len(catalog.get("entries", [])) != protection.catalog_entry_count
    ):
        raise ValueError("protected Run A Catalog authority changed")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return cast(dict[str, Any], value)


def _write_once_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        if _read_object(path) != payload:
            raise FileExistsError(f"append-only artifact already differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    os.replace(temporary, path)
