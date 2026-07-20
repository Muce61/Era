"""CR-2026-015 audited adoption of completed V2 monthly results.

This module deliberately adopts only immutable Foundation and Group-1 monthly
evidence.  Packed Group-1 objects, partials and processing caches are excluded,
so the corrected code must rebuild the final packing graph before release.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final, Literal, Self

import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import Field, model_validator

from .checkpoint import CheckpointStore, write_once_model
from .foundation_pipeline import FoundationShardCheckpoint
from .group1_pipeline import Group1MonthCheckpoint, Group1MonthlyDatasetSeal
from .models import FrozenModel, ManifestV2, SHA256_PATTERN, ZERO_SHA256, metadata_sha256
from .progress import PipelineProgressStore
from .transition import sha256_file

EXPECTED_FOUNDATION_CHECKPOINTS: Final[Literal[632]] = 632
EXPECTED_GROUP1_MONTHS: Final[Literal[158]] = 158
EXPECTED_GROUP1_DATASET_SEALS: Final[Literal[2054]] = 2_054


class AdoptedFileV1(FrozenModel):
    relative_path: str
    physical_sha256: str = Field(pattern=SHA256_PATTERN)
    byte_size: int = Field(ge=0)
    category: Literal[
        "FOUNDATION_METADATA",
        "FOUNDATION_OBJECT",
        "GROUP1_MONTH_METADATA",
        "GROUP1_MONTH_OBJECT",
    ]


class Group1MonthlyAdoptionManifestV1(FrozenModel):
    schema_name: Literal["stage2-v2-group1-monthly-adoption-manifest"] = (
        "stage2-v2-group1-monthly-adoption-manifest"
    )
    manifest_version: Literal["1.0"] = "1.0"
    change_request: Literal["CR-2026-015"] = "CR-2026-015"
    source_run_id: str
    destination_run_id: str
    source_status: Literal["FAILED_INTEGRITY"] = "FAILED_INTEGRITY"
    source_snapshot_id: str = Field(pattern=SHA256_PATTERN)
    destination_snapshot_id: str = Field(pattern=SHA256_PATTERN)
    source_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    destination_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    stage1_data_run_id: str
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    source_checkpoint_sha256: str = Field(pattern=SHA256_PATTERN)
    source_failure_sha256: str = Field(pattern=SHA256_PATTERN)
    foundation_checkpoint_count: Literal[632] = EXPECTED_FOUNDATION_CHECKPOINTS
    group1_month_count: Literal[158] = EXPECTED_GROUP1_MONTHS
    group1_dataset_count: Literal[2054] = EXPECTED_GROUP1_DATASET_SEALS
    adopted_files: tuple[AdoptedFileV1, ...]
    excluded_prefixes: tuple[str, ...]
    adopted_file_count: int = Field(ge=0)
    adopted_byte_count: int = Field(ge=0)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    @model_validator(mode="after")
    def valid_manifest(self) -> Self:
        paths = tuple(item.relative_path for item in self.adopted_files)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("adopted files must be unique and sorted")
        if self.adopted_file_count != len(self.adopted_files):
            raise ValueError("adopted file count mismatch")
        if self.adopted_byte_count != sum(item.byte_size for item in self.adopted_files):
            raise ValueError("adopted byte count mismatch")
        if self.manifest_hash != ZERO_SHA256 and self.manifest_hash != self.computed_hash():
            raise ValueError("monthly adoption manifest hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "manifest_hash": ZERO_SHA256})
        return provisional.model_copy(update={"manifest_hash": provisional.computed_hash()})


class PackedArtifactAuditV1(FrozenModel):
    schema_name: Literal["stage2-v2-packed-artifact-audit"] = "stage2-v2-packed-artifact-audit"
    audit_version: Literal["1.0"] = "1.0"
    change_request: Literal["CR-2026-015"] = "CR-2026-015"
    source_run_id: str
    source_checkpoint_sha256: str = Field(pattern=SHA256_PATTERN)
    source_failure_sha256: str = Field(pattern=SHA256_PATTERN)
    packed_seal_count: int = Field(ge=0)
    packed_object_count: int = Field(ge=0)
    unique_object_hash_count: int = Field(ge=0)
    duplicate_object_hashes: tuple[str, ...]
    diagnosis: Literal["SORT_ORDER_CONTRACT_MISMATCH_NO_DUPLICATE_ARTIFACT"]
    audit_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))

    @model_validator(mode="after")
    def valid_audit(self) -> Self:
        if self.duplicate_object_hashes:
            raise ValueError("approved recovery requires zero duplicate packed objects")
        if self.packed_object_count != self.unique_object_hash_count:
            raise ValueError("packed object uniqueness mismatch")
        if self.audit_hash != ZERO_SHA256 and self.audit_hash != self.computed_hash():
            raise ValueError("packed artifact audit hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "audit_hash": ZERO_SHA256})
        return provisional.model_copy(update={"audit_hash": provisional.computed_hash()})


def audit_failed_packing(source_root: Path) -> PackedArtifactAuditV1:
    checkpoint_path = source_root / "checkpoint-v2.json"
    checkpoint = CheckpointStore(source_root).read()
    if checkpoint.status != "FAILED_INTEGRITY":
        raise ValueError("source run is not the approved terminal integrity failure")
    failure_paths = tuple(sorted((source_root / "reports").glob("failure-group1-*.json")))
    if len(failure_paths) != 1:
        raise ValueError("source run must expose exactly one Group-1 failure report")
    failure_path = failure_paths[0]
    failure = failure_path.read_text(encoding="utf-8")
    if "evidence components must be unique and sorted" not in failure:
        raise ValueError("source failure is not the approved component-order defect")
    foundation_hashes = _foundation_packed_object_hashes(source_root)
    snapshot_objects = tuple(
        sorted(
            path
            for path in (source_root / "staging" / "snapshot" / "objects").glob("*/*.parquet")
            if path.is_file() and not path.name.startswith("._") and not path.is_symlink()
        )
    )
    group1_objects = tuple(path for path in snapshot_objects if path.stem not in foundation_hashes)
    hashes = tuple(path.stem for path in group1_objects)
    duplicates = tuple(sorted({value for value in hashes if hashes.count(value) > 1}))
    seal_count = len(
        tuple(
            path
            for path in (source_root / "staging" / "group1" / "packed-seals").rglob("*.json")
            if path.is_file() and not path.name.startswith("._") and not path.is_symlink()
        )
    )
    if seal_count != len(group1_objects):
        raise ValueError("packed seal/object count mismatch in failed evidence")
    audit = PackedArtifactAuditV1.seal(
        {
            "source_run_id": source_root.name,
            "source_checkpoint_sha256": sha256_file(checkpoint_path),
            "source_failure_sha256": sha256_file(failure_path),
            "packed_seal_count": seal_count,
            "packed_object_count": len(group1_objects),
            "unique_object_hash_count": len(set(hashes)),
            "duplicate_object_hashes": duplicates,
            "diagnosis": "SORT_ORDER_CONTRACT_MISMATCH_NO_DUPLICATE_ARTIFACT",
        }
    )
    write_once_model(source_root / "reports" / "cr-2026-015-packed-artifact-audit.json", audit)
    return audit


def adopt_completed_monthly_results(
    *,
    source_root: Path,
    destination_root: Path,
    destination_manifest_path: Path,
) -> Group1MonthlyAdoptionManifestV1:
    audit_failed_packing(source_root)
    destination_manifest = ManifestV2.model_validate_json(destination_manifest_path.read_bytes())
    destination_checkpoint = CheckpointStore(destination_root).read()
    source_checkpoint = CheckpointStore(source_root).read()
    if destination_checkpoint.status != "PREFLIGHT_PASSED":
        raise ValueError("destination must be a fresh PREFLIGHT_PASSED run")
    if destination_checkpoint.manifest_hash != destination_manifest.manifest_hash:
        raise ValueError("destination checkpoint and Runtime Manifest differ")
    if source_checkpoint.snapshot_id != destination_manifest.snapshot_id:
        raise ValueError("source and destination snapshots differ")
    if source_checkpoint.stage1_data_run_id != destination_manifest.stage1_data_run_id:
        raise ValueError("source and destination Stage 1 authorities differ")
    if source_checkpoint.config_sha256 != destination_manifest.config_sha256:
        raise ValueError("source and destination config differ")
    if any((source_root / "published").iterdir()):
        raise ValueError("failed source unexpectedly contains published data")
    failure_path = next((source_root / "reports").glob("failure-group1-*.json"))
    source_manifest_path = (
        source_root / "manifests" / f"runtime-{source_checkpoint.manifest_hash}.json"
    )
    source_manifest = ManifestV2.model_validate_json(source_manifest_path.read_bytes())
    if _semantic_authority(source_manifest) != _semantic_authority(destination_manifest):
        raise ValueError("source and destination semantic authorities differ")

    files = _validated_adoption_files(source_root)
    progress = PipelineProgressStore(destination_root)
    progress.update(
        name="MONTHLY_RESULT_ADOPTION",
        status="RUNNING",
        done=0,
        total=len(files),
        message="monthly adoption started",
    )
    adopted: list[AdoptedFileV1] = []
    for ordinal, (relative, category) in enumerate(files, start=1):
        source = source_root / relative
        destination = destination_root / relative
        digest = sha256_file(source)
        _copy_verified(source, destination, digest)
        adopted.append(
            AdoptedFileV1(
                relative_path=relative.as_posix(),
                physical_sha256=digest,
                byte_size=source.stat().st_size,
                category=category,
            )
        )
        if ordinal == len(files) or ordinal % 50 == 0:
            progress.update(
                name="MONTHLY_RESULT_ADOPTION",
                status="RUNNING",
                done=ordinal,
                total=len(files),
                current_item=relative.as_posix(),
                message=f"verified and copied {ordinal}/{len(files)} files",
            )
    ordered = tuple(sorted(adopted, key=lambda item: item.relative_path))
    manifest = Group1MonthlyAdoptionManifestV1.seal(
        {
            "source_run_id": source_root.name,
            "destination_run_id": destination_root.name,
            "source_snapshot_id": source_manifest.snapshot_id,
            "destination_snapshot_id": destination_manifest.snapshot_id,
            "source_manifest_hash": source_manifest.manifest_hash,
            "destination_manifest_hash": destination_manifest.manifest_hash,
            "stage1_data_run_id": destination_manifest.stage1_data_run_id,
            "config_sha256": destination_manifest.config_sha256,
            "source_checkpoint_sha256": sha256_file(source_root / "checkpoint-v2.json"),
            "source_failure_sha256": sha256_file(failure_path),
            "adopted_files": ordered,
            "excluded_prefixes": (
                "staging/group1/packed-seals",
                "staging/group1/partials",
                "staging/group1/processing-day-cache",
                "staging/snapshot/objects/group1-packed",
            ),
            "adopted_file_count": len(ordered),
            "adopted_byte_count": sum(item.byte_size for item in ordered),
        }
    )
    write_once_model(
        destination_root / "manifests" / f"group1-monthly-adoption-{manifest.manifest_hash}.json",
        manifest,
    )
    progress.update(
        name="MONTHLY_RESULT_ADOPTION",
        status="PASS",
        done=len(files),
        total=len(files),
        message="all completed monthly results adopted; packed Group-1 artifacts excluded",
    )
    return manifest


def _validated_adoption_files(
    source_root: Path,
) -> tuple[
    tuple[
        Path,
        Literal[
            "FOUNDATION_METADATA",
            "FOUNDATION_OBJECT",
            "GROUP1_MONTH_METADATA",
            "GROUP1_MONTH_OBJECT",
        ],
    ],
    ...,
]:
    selected: dict[
        Path,
        Literal[
            "FOUNDATION_METADATA",
            "FOUNDATION_OBJECT",
            "GROUP1_MONTH_METADATA",
            "GROUP1_MONTH_OBJECT",
        ],
    ] = {}
    foundation_checkpoints = _json_paths(
        source_root / "staging" / "foundation" / "checkpoints"
    ) + _json_paths(source_root / "staging" / "foundation" / "packed-checkpoints")
    if len(foundation_checkpoints) != EXPECTED_FOUNDATION_CHECKPOINTS:
        raise ValueError("Foundation checkpoint coverage is not 632")
    for path in foundation_checkpoints:
        model = FoundationShardCheckpoint.model_validate_json(path.read_bytes())
        _select(selected, path.relative_to(source_root), "FOUNDATION_METADATA")
        seal = source_root / model.seal_relative_path
        if sha256_file(seal) != model.seal_file_sha256:
            raise ValueError("Foundation Seal file hash changed")
        _select(selected, seal.relative_to(source_root), "FOUNDATION_METADATA")
        if model.artifact is not None:
            root = (
                source_root / "staging" / "foundation" / "monthly-catalog"
                if model.storage_role == "MONTHLY_INTERMEDIATE"
                else source_root / "staging" / "snapshot"
            )
            obj = root / model.artifact.relative_path
            _validate_object(obj, model.artifact.object_sha256, model.artifact.row_count)
            _select(selected, obj.relative_to(source_root), "FOUNDATION_OBJECT")

    month_paths = _json_paths(source_root / "staging" / "group1" / "monthly-checkpoints")
    dataset_paths = _json_paths(source_root / "staging" / "group1" / "monthly-dataset-checkpoints")
    if len(month_paths) != EXPECTED_GROUP1_MONTHS:
        raise ValueError("Group-1 month coverage is not 158")
    if len(dataset_paths) != EXPECTED_GROUP1_DATASET_SEALS:
        raise ValueError("Group-1 monthly dataset coverage is not 2,054")
    for path in month_paths:
        Group1MonthCheckpoint.model_validate_json(path.read_bytes())
        _select(selected, path.relative_to(source_root), "GROUP1_MONTH_METADATA")
    for path in dataset_paths:
        dataset_seal = Group1MonthlyDatasetSeal.model_validate_json(path.read_bytes())
        _select(selected, path.relative_to(source_root), "GROUP1_MONTH_METADATA")
        seal = source_root / dataset_seal.seal_relative_path
        if sha256_file(seal) != dataset_seal.seal_file_sha256:
            raise ValueError("Group-1 monthly Seal file hash changed")
        _select(selected, seal.relative_to(source_root), "GROUP1_MONTH_METADATA")
        if dataset_seal.artifact is not None:
            obj = (
                source_root
                / "staging"
                / "group1"
                / "monthly-catalog"
                / dataset_seal.artifact.relative_path
            )
            _validate_object(
                obj, dataset_seal.artifact.object_sha256, dataset_seal.artifact.row_count
            )
            _select(selected, obj.relative_to(source_root), "GROUP1_MONTH_OBJECT")
    return tuple(sorted(selected.items(), key=lambda item: item[0].as_posix()))


def _semantic_authority(manifest: ManifestV2) -> tuple[Any, ...]:
    return (
        manifest.snapshot_id,
        manifest.stage1_data_run_id,
        manifest.preregistration_manifest_sha256,
        manifest.config_sha256,
        tuple(item.spec_hash for item in manifest.dataset_specs),
        tuple(
            (item.name, item.sha256)
            for item in manifest.stage1_authorities
            if not item.name.startswith("runtime_v2_")
        ),
    )


def _foundation_packed_object_hashes(source_root: Path) -> set[str]:
    result: set[str] = set()
    for path in _json_paths(source_root / "staging" / "foundation" / "packed-checkpoints"):
        checkpoint = FoundationShardCheckpoint.model_validate_json(path.read_bytes())
        if checkpoint.artifact is not None:
            result.add(checkpoint.artifact.object_sha256)
    return result


def _json_paths(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in root.rglob("*.json")
            if path.is_file() and not path.name.startswith("._") and not path.is_symlink()
        )
    )


def _validate_object(path: Path, digest: str, row_count: int) -> None:
    if not path.is_file() or path.is_symlink() or path.name.startswith("._"):
        raise ValueError(f"adoption object is missing or unsafe: {path}")
    if path.stem != digest or sha256_file(path) != digest:
        raise ValueError(f"adoption object physical hash changed: {path}")
    if pq.ParquetFile(path).metadata.num_rows != row_count:
        raise ValueError(f"adoption object row count changed: {path}")


def _select(
    selected: dict[
        Path,
        Literal[
            "FOUNDATION_METADATA",
            "FOUNDATION_OBJECT",
            "GROUP1_MONTH_METADATA",
            "GROUP1_MONTH_OBJECT",
        ],
    ],
    path: Path,
    category: Literal[
        "FOUNDATION_METADATA", "FOUNDATION_OBJECT", "GROUP1_MONTH_METADATA", "GROUP1_MONTH_OBJECT"
    ],
) -> None:
    previous = selected.setdefault(path, category)
    if previous != category:
        raise ValueError(f"adoption path has conflicting categories: {path}")


def _copy_verified(source: Path, destination: Path, digest: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_symlink() or sha256_file(destination) != digest:
            raise FileExistsError(f"destination adoption file differs: {destination}")
        return
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        hasher = __import__("hashlib").sha256()
        with source.open("rb") as reader, temporary.open("xb") as writer:
            while block := reader.read(16 * 1024 * 1024):
                writer.write(block)
                hasher.update(block)
            writer.flush()
            os.fsync(writer.fileno())
        if hasher.hexdigest() != digest:
            raise ValueError("streamed adoption copy hash mismatch")
        os.replace(temporary, destination)
        if sha256_file(destination) != digest:
            raise ValueError("adopted destination hash mismatch")
    finally:
        temporary.unlink(missing_ok=True)
