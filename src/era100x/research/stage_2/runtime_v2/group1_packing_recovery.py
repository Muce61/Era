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

from .catalog import SealReducerV2
from .checkpoint import CheckpointStore, write_once_model
from .foundation_pipeline import FoundationShardCheckpoint
from .group1_pipeline import (
    GROUP1_BINDINGS,
    Group1MonthCheckpoint,
    Group1MonthlyDatasetSeal,
    PackedFoundationFeatureReader,
)
from .models import (
    ArtifactRef,
    FragmentV2,
    FrozenModel,
    LogicalPartitionKey,
    ManifestV2,
    Receipt,
    SHA256_PATTERN,
    ZERO_SHA256,
    metadata_sha256,
)
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

    source_foundation = tuple(
        FoundationShardCheckpoint.model_validate_json(path.read_bytes())
        for path in (
            _json_paths(source_root / "staging" / "foundation" / "checkpoints")
            + _json_paths(source_root / "staging" / "foundation" / "packed-checkpoints")
        )
    )
    source_months = tuple(
        Group1MonthCheckpoint.model_validate_json(path.read_bytes())
        for path in _json_paths(source_root / "staging" / "group1" / "monthly-checkpoints")
    )
    if len(source_foundation) != EXPECTED_FOUNDATION_CHECKPOINTS:
        raise ValueError("Foundation checkpoint coverage is not 632")
    if len(source_months) != EXPECTED_GROUP1_MONTHS:
        raise ValueError("Group-1 month coverage is not 158")
    source_dataset_paths = _group1_dataset_path_index(source_root)
    if len(source_dataset_paths) != EXPECTED_GROUP1_DATASET_SEALS:
        raise ValueError("Group-1 monthly dataset coverage is not 2,054")
    estimated_total = (
        len(source_foundation) * 3 + len(source_dataset_paths) * 3 + len(source_months)
    )
    progress = PipelineProgressStore(destination_root)
    progress.update(
        name="MONTHLY_RESULT_ADOPTION",
        status="RUNNING",
        done=0,
        total=estimated_total,
        message="monthly adoption started",
    )
    adopted: dict[str, AdoptedFileV1] = {}
    completed = 0
    destination_foundation: list[FoundationShardCheckpoint] = []
    for source in sorted(
        source_foundation,
        key=lambda item: (item.storage_role, item.instrument, item.dataset_name, item.shard_key),
    ):
        adopted_checkpoint, entries = _adopt_foundation_checkpoint(
            source_root=source_root,
            destination_root=destination_root,
            source=source,
            destination_snapshot_id=destination_manifest.snapshot_id,
        )
        destination_foundation.append(adopted_checkpoint)
        _record_adopted(adopted, entries)
        completed += len(entries)
        if completed % 50 == 0:
            progress.update(
                name="MONTHLY_RESULT_ADOPTION",
                status="RUNNING",
                done=completed,
                total=estimated_total,
                current_item=f"foundation:{source.instrument}:{source.dataset_name}:{source.shard_key}",
                message=f"re-signed Foundation evidence ({completed} files)",
            )

    packed_foundation = tuple(
        item for item in destination_foundation if item.storage_role == "PACKED_FINAL"
    )
    reader = PackedFoundationFeatureReader(
        snapshot_id=destination_manifest.snapshot_id,
        catalog_root=destination_root / "staging" / "snapshot",
        checkpoints=packed_foundation,
    )
    dataset_count = 0
    for source_month in sorted(source_months, key=lambda item: (item.instrument, item.owner_start)):
        destination_datasets: list[Group1MonthlyDatasetSeal] = []
        for source_dataset in source_month.datasets:
            key = (
                source_month.instrument,
                source_month.utc_month,
                source_dataset.variant,
                source_dataset.dataset,
            )
            source_dataset_path = source_dataset_paths[key]
            destination_dataset, entries = _adopt_group1_dataset(
                source_root=source_root,
                destination_root=destination_root,
                source=source_dataset,
                source_dataset_relative_path=source_dataset_path.relative_to(source_root),
                destination_snapshot_id=destination_manifest.snapshot_id,
            )
            destination_datasets.append(destination_dataset)
            _record_adopted(adopted, entries)
            dataset_count += 1
            completed += len(entries)
            if dataset_count % 50 == 0:
                progress.update(
                    name="MONTHLY_RESULT_ADOPTION",
                    status="RUNNING",
                    done=completed,
                    total=estimated_total,
                    current_item=(
                        f"{source_month.instrument}:{source_month.utc_month}:"
                        f"{source_dataset.variant}:{source_dataset.dataset}"
                    ),
                    message=f"re-signed {dataset_count}/{EXPECTED_GROUP1_DATASET_SEALS} datasets",
                )
        authority = reader.authority_for_window(
            instrument=source_month.instrument,
            owner_start=source_month.owner_start,
            owner_end_exclusive=source_month.owner_end_exclusive,
        )
        destination_month = Group1MonthCheckpoint.seal_checkpoint(
            {
                **source_month.model_dump(mode="python", exclude={"checkpoint_hash"}),
                "snapshot_id": destination_manifest.snapshot_id,
                "foundation_authority_members": authority,
                "foundation_authority_sha256": metadata_sha256(authority),
                "datasets": tuple(destination_datasets),
            }
        )
        month_relative = Path(
            f"staging/group1/monthly-checkpoints/instrument={source_month.instrument}/"
            f"{source_month.utc_month}.json"
        )
        month_hash = write_once_model(destination_root / month_relative, destination_month)
        _record_adopted(
            adopted,
            (
                AdoptedFileV1(
                    relative_path=month_relative.as_posix(),
                    physical_sha256=month_hash,
                    byte_size=(destination_root / month_relative).stat().st_size,
                    category="GROUP1_MONTH_METADATA",
                ),
            ),
        )
        completed += 1
    ordered = tuple(sorted(adopted.values(), key=lambda item: item.relative_path))
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
        done=completed,
        total=completed,
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


def _adopt_foundation_checkpoint(
    *,
    source_root: Path,
    destination_root: Path,
    source: FoundationShardCheckpoint,
    destination_snapshot_id: str,
) -> tuple[FoundationShardCheckpoint, tuple[AdoptedFileV1, ...]]:
    source_object_root = (
        source_root / "staging" / "foundation" / "monthly-catalog"
        if source.storage_role == "MONTHLY_INTERMEDIATE"
        else source_root / "staging" / "snapshot"
    )
    destination_object_root = (
        destination_root / "staging" / "foundation" / "monthly-catalog"
        if source.storage_role == "MONTHLY_INTERMEDIATE"
        else destination_root / "staging" / "snapshot"
    )
    artifact, receipts, fragments, seal, object_entry = _resign_graph(
        source_root=source_root,
        destination_root=destination_root,
        source_object_root=source_object_root,
        destination_object_root=destination_object_root,
        artifact=source.artifact,
        receipts=source.receipts,
        fragments=source.fragments,
        source_seal_path=source_root / source.seal_relative_path,
        source_seal_file_sha256=source.seal_file_sha256,
        source_shard_id=source.seal.shard_id,
        dataset_spec_hash=source.dataset_spec_hash,
        destination_snapshot_id=destination_snapshot_id,
        object_category="FOUNDATION_OBJECT",
    )
    seal_path = destination_root / source.seal_relative_path
    seal_file_hash = write_once_model(seal_path, seal)
    checkpoint = FoundationShardCheckpoint.seal_checkpoint(
        {
            **source.model_dump(mode="python", exclude={"checkpoint_hash"}),
            "snapshot_id": destination_snapshot_id,
            "artifact": artifact,
            "receipts": receipts,
            "fragments": fragments,
            "seal": seal,
            "seal_file_sha256": seal_file_hash,
        }
    )
    checkpoint_kind = (
        "checkpoints" if source.storage_role == "MONTHLY_INTERMEDIATE" else "packed-checkpoints"
    )
    checkpoint_relative = Path(
        f"staging/foundation/{checkpoint_kind}/instrument={source.instrument}/"
        f"feature={source.dataset_name}/shard={source.shard_key}.json"
    )
    checkpoint_hash = write_once_model(destination_root / checkpoint_relative, checkpoint)
    entries = [
        AdoptedFileV1(
            relative_path=source.seal_relative_path,
            physical_sha256=seal_file_hash,
            byte_size=seal_path.stat().st_size,
            category="FOUNDATION_METADATA",
        ),
        AdoptedFileV1(
            relative_path=checkpoint_relative.as_posix(),
            physical_sha256=checkpoint_hash,
            byte_size=(destination_root / checkpoint_relative).stat().st_size,
            category="FOUNDATION_METADATA",
        ),
    ]
    if object_entry is not None:
        entries.append(object_entry)
    return checkpoint, tuple(entries)


def _adopt_group1_dataset(
    *,
    source_root: Path,
    destination_root: Path,
    source: Group1MonthlyDatasetSeal,
    source_dataset_relative_path: Path,
    destination_snapshot_id: str,
) -> tuple[Group1MonthlyDatasetSeal, tuple[AdoptedFileV1, ...]]:
    artifact, receipts, fragments, seal, object_entry = _resign_graph(
        source_root=source_root,
        destination_root=destination_root,
        source_object_root=source_root / "staging" / "group1" / "monthly-catalog",
        destination_object_root=destination_root / "staging" / "group1" / "monthly-catalog",
        artifact=source.artifact,
        receipts=source.receipts,
        fragments=source.fragments,
        source_seal_path=source_root / source.seal_relative_path,
        source_seal_file_sha256=source.seal_file_sha256,
        source_shard_id=source.seal.shard_id,
        dataset_spec_hash=source.dataset_spec_hash,
        destination_snapshot_id=destination_snapshot_id,
        object_category="GROUP1_MONTH_OBJECT",
    )
    seal_path = destination_root / source.seal_relative_path
    seal_file_hash = write_once_model(seal_path, seal)
    dataset = Group1MonthlyDatasetSeal(
        variant=source.variant,
        dataset=source.dataset,
        dataset_spec_hash=source.dataset_spec_hash,
        artifact=artifact,
        receipts=receipts,
        fragments=fragments,
        seal=seal,
        seal_relative_path=source.seal_relative_path,
        seal_file_sha256=seal_file_hash,
    )
    destination_path = destination_root / source_dataset_relative_path
    dataset_hash = write_once_model(destination_path, dataset)
    entries = [
        AdoptedFileV1(
            relative_path=source.seal_relative_path,
            physical_sha256=seal_file_hash,
            byte_size=seal_path.stat().st_size,
            category="GROUP1_MONTH_METADATA",
        ),
        AdoptedFileV1(
            relative_path=source_dataset_relative_path.as_posix(),
            physical_sha256=dataset_hash,
            byte_size=destination_path.stat().st_size,
            category="GROUP1_MONTH_METADATA",
        ),
    ]
    if object_entry is not None:
        entries.append(object_entry)
    return dataset, tuple(entries)


def _resign_graph(
    *,
    source_root: Path,
    destination_root: Path,
    source_object_root: Path,
    destination_object_root: Path,
    artifact: ArtifactRef | None,
    receipts: tuple[Receipt, ...],
    fragments: tuple[FragmentV2, ...],
    source_seal_path: Path,
    source_seal_file_sha256: str,
    source_shard_id: str,
    dataset_spec_hash: str,
    destination_snapshot_id: str,
    object_category: Literal["FOUNDATION_OBJECT", "GROUP1_MONTH_OBJECT"],
) -> tuple[
    ArtifactRef | None,
    tuple[Receipt, ...],
    tuple[FragmentV2, ...],
    Any,
    AdoptedFileV1 | None,
]:
    if sha256_file(source_seal_path) != source_seal_file_sha256:
        raise ValueError("source Seal physical hash changed")
    destination_artifact: ArtifactRef | None = None
    object_entry: AdoptedFileV1 | None = None
    if artifact is not None:
        source_object = source_object_root / artifact.relative_path
        _validate_object(source_object, artifact.object_sha256, artifact.row_count)
        destination_object = destination_object_root / artifact.relative_path
        _copy_verified(source_object, destination_object, artifact.object_sha256)
        destination_artifact = ArtifactRef.model_validate(
            {**artifact.model_dump(mode="python"), "snapshot_id": destination_snapshot_id}
        )
        object_entry = AdoptedFileV1(
            relative_path=destination_object.relative_to(destination_root).as_posix(),
            physical_sha256=artifact.object_sha256,
            byte_size=artifact.byte_size,
            category=object_category,
        )
    partition_map: dict[str, LogicalPartitionKey] = {}
    for receipt in receipts:
        partition_map[receipt.partition.partition_id] = LogicalPartitionKey.model_validate(
            {
                **receipt.partition.model_dump(mode="python"),
                "snapshot_id": destination_snapshot_id,
            }
        )
    fragment_map: dict[str, FragmentV2] = {}
    destination_fragments: list[FragmentV2] = []
    for fragment in fragments:
        new_fragment = FragmentV2.seal(
            {
                **fragment.model_dump(mode="python", exclude={"fragment_hash"}),
                "snapshot_id": destination_snapshot_id,
                "partition_id": partition_map[fragment.partition_id].partition_id,
                "artifact": destination_artifact,
            }
        )
        fragment_map[fragment.fragment_hash] = new_fragment
        destination_fragments.append(new_fragment)
    destination_receipts = tuple(
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
        for receipt in receipts
    )
    seal = SealReducerV2.reduce(
        snapshot_id=destination_snapshot_id,
        dataset_spec_hash=dataset_spec_hash,
        shard_id=source_shard_id,
        receipts=destination_receipts,
    )
    return (
        destination_artifact,
        destination_receipts,
        tuple(destination_fragments),
        seal,
        object_entry,
    )


def _group1_dataset_path_index(
    source_root: Path,
) -> dict[tuple[str, str, str, str], Path]:
    result: dict[tuple[str, str, str, str], Path] = {}
    for path in _json_paths(source_root / "staging" / "group1" / "monthly-dataset-checkpoints"):
        model = Group1MonthlyDatasetSeal.model_validate_json(path.read_bytes())
        parts = path.relative_to(
            source_root / "staging" / "group1" / "monthly-dataset-checkpoints"
        ).parts
        if len(parts) != 4:
            raise ValueError("unexpected Group-1 monthly dataset path")
        instrument = parts[0].removeprefix("instrument=")
        month = parts[1].removeprefix("utc_month=")
        if parts[2] != f"variant={model.variant}" or parts[3] != f"dataset={model.dataset}.json":
            raise ValueError("Group-1 monthly dataset path disagrees with metadata")
        key = (instrument, month, model.variant, model.dataset)
        if key in result:
            raise ValueError("duplicate Group-1 monthly dataset metadata")
        result[key] = path
    expected_keys = {
        (instrument, month, variant, dataset)
        for instrument in ("BTCUSDT", "ETHUSDT")
        for month in {
            path.parts[-3].removeprefix("utc_month=")
            for path in result.values()
            if path.parts[-4] == f"instrument={instrument}"
        }
        for variant, dataset in GROUP1_BINDINGS
    }
    if set(result) != expected_keys:
        raise ValueError("Group-1 monthly dataset matrix is incomplete")
    return result


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


def _record_adopted(
    adopted: dict[str, AdoptedFileV1],
    entries: tuple[AdoptedFileV1, ...] | list[AdoptedFileV1],
) -> None:
    for entry in entries:
        previous = adopted.setdefault(entry.relative_path, entry)
        if previous != entry:
            raise ValueError(f"adoption path has conflicting evidence: {entry.relative_path}")


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
