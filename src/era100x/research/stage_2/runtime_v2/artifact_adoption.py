"""CR-2026-013 verified adoption of immutable Foundation month objects."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Self

import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .catalog import SealReducerV2
from .checkpoint import CheckpointStore, SHA256_PATTERN, write_once_model
from .foundation_pipeline import FoundationShardCheckpoint
from .hashing import canonical_arrow_schema
from .models import (
    ZERO_SHA256,
    ArtifactRef,
    DatasetSpec,
    FragmentV2,
    LogicalPartitionKey,
    ManifestV2,
    Receipt,
    metadata_sha256,
)
from .transition import sha256_file

STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
SOURCE_RUN_ID = "stage2-g1-v2-b-20260718T141137Z-f0c150bfa1c9"
SOURCE_CODE_TREE_SHA256 = "0b4db788ca930f960493f20537bf89170163ca5261b546fca34e6f7b5b442dc2"
EXPECTED_SOURCE_OBJECTS = 316


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ArtifactAdoptionEntry(_FrozenModel):
    dataset_name: str
    instrument: Literal["BTCUSDT"] = "BTCUSDT"
    shard_key: str
    source_checkpoint_relative_path: str
    source_checkpoint_sha256: str = Field(pattern=SHA256_PATTERN)
    source_checkpoint_hash: str = Field(pattern=SHA256_PATTERN)
    source_object_sha256: str = Field(pattern=SHA256_PATTERN)
    destination_checkpoint_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    destination_seal_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    result: Literal["ADOPTED", "REBUILD_REQUIRED"]
    reason: str


class ArtifactAdoptionManifest(_FrozenModel):
    schema_name: Literal["stage2-v2-artifact-adoption-manifest"] = (
        "stage2-v2-artifact-adoption-manifest"
    )
    manifest_version: Literal["1.0"] = "1.0"
    change_request: Literal["CR-2026-013"] = "CR-2026-013"
    source_run_id: Literal["stage2-g1-v2-b-20260718T141137Z-f0c150bfa1c9"] = (
        "stage2-g1-v2-b-20260718T141137Z-f0c150bfa1c9"
    )
    destination_run_id: str
    source_status: Literal["FAILED_UNPUBLISHED"] = "FAILED_UNPUBLISHED"
    source_publication_count: Literal[0] = 0
    source_snapshot_id: str = Field(pattern=SHA256_PATTERN)
    destination_snapshot_id: str = Field(pattern=SHA256_PATTERN)
    source_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    destination_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    source_code_tree_sha256: Literal[
        "0b4db788ca930f960493f20537bf89170163ca5261b546fca34e6f7b5b442dc2"
    ] = "0b4db788ca930f960493f20537bf89170163ca5261b546fca34e6f7b5b442dc2"
    destination_code_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    stage1_data_run_id: str
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    compatibility_basis: Literal["CR-2026-013_RESOURCE_ONLY_DIFF"] = (
        "CR-2026-013_RESOURCE_ONLY_DIFF"
    )
    source_checkpoint_file_sha256: str = Field(pattern=SHA256_PATTERN)
    source_failure_file_sha256: str = Field(pattern=SHA256_PATTERN)
    entries: tuple[ArtifactAdoptionEntry, ...]
    adopted_count: int = Field(ge=0)
    rebuild_required_count: int = Field(ge=0)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        keys = tuple((item.dataset_name, item.shard_key) for item in self.entries)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("artifact adoption entries must be unique and sorted")
        if self.adopted_count != sum(item.result == "ADOPTED" for item in self.entries):
            raise ValueError("adoption count mismatch")
        if self.rebuild_required_count != sum(
            item.result == "REBUILD_REQUIRED" for item in self.entries
        ):
            raise ValueError("rebuild-required count mismatch")
        if self.manifest_hash != ZERO_SHA256 and self.manifest_hash != self.computed_hash():
            raise ValueError("artifact adoption manifest hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "manifest_hash": ZERO_SHA256})
        return provisional.model_copy(update={"manifest_hash": provisional.computed_hash()})


def adopt_btc_foundation_months(
    *,
    destination_run_id: str,
    destination_manifest_path: Path,
    stage2_root: Path = STAGE2_ROOT,
) -> ArtifactAdoptionManifest:
    """Verify and adopt each source month without modifying the failed run."""

    source_root = _bounded_run(stage2_root, SOURCE_RUN_ID)
    destination_root = _bounded_run(stage2_root, destination_run_id)
    destination_manifest = ManifestV2.model_validate_json(destination_manifest_path.read_bytes())
    if destination_manifest.manifest_hash != destination_manifest.computed_hash():
        raise ValueError("destination Runtime Manifest is not sealed")
    destination_checkpoint = CheckpointStore(destination_root).read()
    if destination_checkpoint.status != "PREFLIGHT_PASSED":
        raise ValueError("artifact adoption requires a fresh PREFLIGHT_PASSED destination")
    if destination_checkpoint.manifest_hash != destination_manifest.manifest_hash:
        raise ValueError("destination checkpoint and Manifest differ")

    source_checkpoint_path = source_root / "checkpoint-v2.json"
    source_failure_path = source_root / "reports/failure-foundation-btcusdt-r2.json"
    source_checkpoint = CheckpointStore(source_root).read()
    if (
        source_checkpoint.status != "FAILED_UNPUBLISHED"
        or source_checkpoint.code_tree_sha256 != SOURCE_CODE_TREE_SHA256
        or source_checkpoint.stage1_data_run_id != destination_manifest.stage1_data_run_id
        or source_checkpoint.config_sha256 != destination_manifest.config_sha256
    ):
        raise ValueError("failed source run is not the approved CR-2026-013 authority")
    failure = _read_json(source_failure_path)
    if (
        failure.get("error_type") != "MemoryError"
        or failure.get("publication_status") != "FAILED_UNPUBLISHED"
    ):
        raise ValueError("source failure is not the approved resource-only terminal evidence")
    if any((source_root / "published").iterdir()):
        raise ValueError("failed source run unexpectedly contains published data")

    source_manifest_path = (
        source_root / "manifests" / (f"runtime-{source_checkpoint.manifest_hash}.json")
    )
    source_manifest = ManifestV2.model_validate_json(source_manifest_path.read_bytes())
    if (
        source_manifest.manifest_hash != source_manifest.computed_hash()
        or source_manifest.snapshot_id != source_checkpoint.snapshot_id
        or source_manifest.code_tree_sha256 != SOURCE_CODE_TREE_SHA256
    ):
        raise ValueError("source Runtime Manifest authority changed")
    if _semantic_authority_projection(source_manifest) != _semantic_authority_projection(
        destination_manifest
    ):
        raise ValueError("source/destination semantic authority differs; adoption is forbidden")

    specs = {item.spec_hash: item for item in destination_manifest.dataset_specs}
    checkpoint_root = source_root / "staging/foundation/checkpoints/instrument=BTCUSDT"
    checkpoint_paths = tuple(
        sorted(
            path
            for path in checkpoint_root.glob("feature=*/shard=*.json")
            if path.is_file() and not path.name.startswith("._")
        )
    )
    if len(checkpoint_paths) != EXPECTED_SOURCE_OBJECTS:
        raise ValueError("source run does not expose exactly 316 BTC month checkpoints")

    entries: list[ArtifactAdoptionEntry] = []
    for path in checkpoint_paths:
        relative = path.relative_to(source_root).as_posix()
        source_file_sha = sha256_file(path)
        try:
            source = FoundationShardCheckpoint.model_validate_json(path.read_bytes())
            if (
                source.instrument != "BTCUSDT"
                or source.storage_role != "MONTHLY_INTERMEDIATE"
                or source.artifact is None
            ):
                raise ValueError("source checkpoint is not one BTC monthly object")
            spec = specs.get(source.dataset_spec_hash)
            if spec is None or spec.dataset_name != source.dataset_name:
                raise ValueError("destination DatasetSpec differs")
            adopted = _adopt_checkpoint(
                source_root=source_root,
                destination_root=destination_root,
                source=source,
                destination_snapshot_id=destination_manifest.snapshot_id,
                spec=spec,
                checkpoint_relative_path=relative,
            )
            entries.append(
                ArtifactAdoptionEntry(
                    dataset_name=source.dataset_name,
                    shard_key=source.shard_key,
                    source_checkpoint_relative_path=relative,
                    source_checkpoint_sha256=source_file_sha,
                    source_checkpoint_hash=source.checkpoint_hash,
                    source_object_sha256=source.artifact.object_sha256,
                    destination_checkpoint_hash=adopted.checkpoint_hash,
                    destination_seal_hash=adopted.seal.seal_hash,
                    result="ADOPTED",
                    reason="PHYSICAL_AND_SEMANTIC_AUTHORITY_VERIFIED",
                )
            )
        except (OSError, ValueError) as exc:
            source = FoundationShardCheckpoint.model_validate_json(path.read_bytes())
            object_sha = source.artifact.object_sha256 if source.artifact else "0" * 64
            entries.append(
                ArtifactAdoptionEntry(
                    dataset_name=source.dataset_name,
                    shard_key=source.shard_key,
                    source_checkpoint_relative_path=relative,
                    source_checkpoint_sha256=source_file_sha,
                    source_checkpoint_hash=source.checkpoint_hash,
                    source_object_sha256=object_sha,
                    result="REBUILD_REQUIRED",
                    reason=f"{type(exc).__name__}:{str(exc)[:384]}",
                )
            )

    ordered = tuple(sorted(entries, key=lambda item: (item.dataset_name, item.shard_key)))
    manifest = ArtifactAdoptionManifest.seal(
        {
            "destination_run_id": destination_run_id,
            "source_snapshot_id": source_manifest.snapshot_id,
            "destination_snapshot_id": destination_manifest.snapshot_id,
            "source_manifest_hash": source_manifest.manifest_hash,
            "destination_manifest_hash": destination_manifest.manifest_hash,
            "destination_code_tree_sha256": destination_manifest.code_tree_sha256,
            "stage1_data_run_id": destination_manifest.stage1_data_run_id,
            "config_sha256": destination_manifest.config_sha256,
            "source_checkpoint_file_sha256": sha256_file(source_checkpoint_path),
            "source_failure_file_sha256": sha256_file(source_failure_path),
            "entries": ordered,
            "adopted_count": sum(item.result == "ADOPTED" for item in ordered),
            "rebuild_required_count": sum(item.result == "REBUILD_REQUIRED" for item in ordered),
        }
    )
    write_once_model(
        destination_root / "manifests" / f"artifact-adoption-{manifest.manifest_hash}.json",
        manifest,
    )
    return manifest


def _adopt_checkpoint(
    *,
    source_root: Path,
    destination_root: Path,
    source: FoundationShardCheckpoint,
    destination_snapshot_id: str,
    spec: DatasetSpec,
    checkpoint_relative_path: str,
) -> FoundationShardCheckpoint:
    assert source.artifact is not None
    source_object = (
        source_root / "staging/foundation/monthly-catalog" / source.artifact.relative_path
    )
    if (
        not source_object.is_file()
        or source_object.is_symlink()
        or source_object.stat().st_size != source.artifact.byte_size
        or sha256_file(source_object) != source.artifact.object_sha256
    ):
        raise ValueError("source object physical hash changed")
    parquet = pq.ParquetFile(source_object)
    if parquet.metadata.num_rows != source.artifact.row_count:
        raise ValueError("source object row count differs from ArtifactRef")
    if not parquet.schema_arrow.equals(canonical_arrow_schema(spec), check_metadata=False):
        raise ValueError("source object Schema differs from destination DatasetSpec")

    source_seal_path = source_root / source.seal_relative_path
    if (
        not source_seal_path.is_file()
        or source_seal_path.is_symlink()
        or sha256_file(source_seal_path) != source.seal_file_sha256
    ):
        raise ValueError("source Seal evidence changed")

    artifact = ArtifactRef.model_validate(
        {**source.artifact.model_dump(mode="python"), "snapshot_id": destination_snapshot_id}
    )
    partition_map: dict[str, LogicalPartitionKey] = {}
    for receipt in source.receipts:
        partition_map[receipt.partition.partition_id] = LogicalPartitionKey.model_validate(
            {
                **receipt.partition.model_dump(mode="python"),
                "snapshot_id": destination_snapshot_id,
            }
        )
    fragment_map: dict[str, FragmentV2] = {}
    for fragment in source.fragments:
        partition = partition_map[fragment.partition_id]
        fragment_map[fragment.fragment_hash] = FragmentV2.seal(
            {
                **fragment.model_dump(mode="python", exclude={"fragment_hash"}),
                "snapshot_id": destination_snapshot_id,
                "partition_id": partition.partition_id,
                "artifact": artifact,
            }
        )
    receipts: list[Receipt] = []
    for receipt in source.receipts:
        receipts.append(
            Receipt.seal(
                {
                    **receipt.model_dump(mode="python", exclude={"receipt_hash"}),
                    "snapshot_id": destination_snapshot_id,
                    "partition": partition_map[receipt.partition.partition_id],
                    "fragment_hashes": tuple(
                        fragment_map[value].fragment_hash for value in receipt.fragment_hashes
                    ),
                }
            )
        )
    seal = SealReducerV2.reduce(
        snapshot_id=destination_snapshot_id,
        dataset_spec_hash=source.dataset_spec_hash,
        shard_id=source.seal.shard_id,
        receipts=receipts,
    )

    destination_object = (
        destination_root / "staging/foundation/monthly-catalog" / artifact.relative_path
    )
    _link_verified(source_object, destination_object, artifact.object_sha256)
    destination_seal_path = destination_root / source.seal_relative_path
    seal_file_hash = write_once_model(destination_seal_path, seal)
    adopted = FoundationShardCheckpoint.seal_checkpoint(
        {
            **source.model_dump(mode="python", exclude={"checkpoint_hash"}),
            "snapshot_id": destination_snapshot_id,
            "artifact": artifact,
            "receipts": tuple(receipts),
            "fragments": tuple(fragment_map[item.fragment_hash] for item in source.fragments),
            "seal": seal,
            "seal_file_sha256": seal_file_hash,
        }
    )
    write_once_model(destination_root / checkpoint_relative_path, adopted)
    return adopted


def _semantic_authority_projection(manifest: ManifestV2) -> dict[str, Any]:
    return {
        "stage1_data_run_id": manifest.stage1_data_run_id,
        "preregistration": manifest.preregistration_manifest_sha256,
        "config": manifest.config_sha256,
        "stage1_authorities": tuple(
            (item.name, item.sha256)
            for item in manifest.stage1_authorities
            if not item.name.startswith("runtime_v2_")
        ),
        "dataset_specs": tuple(item.spec_hash for item in manifest.dataset_specs),
    }


def _link_verified(source: Path, destination: Path, digest: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_symlink() or sha256_file(destination) != digest:
            raise FileExistsError("destination adoption object differs")
        return
    os.link(source, destination)
    if sha256_file(destination) != digest:
        raise ValueError("adopted hardlink bytes changed")


def _bounded_run(root: Path, run_id: str) -> Path:
    runs = (root / "runs").resolve(strict=True)
    path = runs / run_id
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(runs) or path.is_symlink():
        raise ValueError("run path escapes the approved Stage 2 root")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value
