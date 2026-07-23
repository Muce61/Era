"""CR-2026-006 single-scan, resumable release of an existing staging tree."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl

from era100x.research.stage_2.manifests.models import Stage2ReleaseSupplementManifest
from era100x.research.stage_2.pipelines.candidates.io import atomic_json, records_logical_hash
from era100x.research.stage_2.pipelines.candidates.release import (
    FLOW_DATASETS,
    ID_FIELDS,
    PRICE_DATASETS,
    _candidate_inclusion_mismatches,
    _finalization_summary,
    _inspect_rows,
    _path_dimensions,
)

ReleasePhase = Literal["DEEP_SCAN", "ARTIFACTS_SEALED", "DATA_RENAMED", "PUBLISHED"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hash(root: Path, paths: tuple[str, ...]) -> str:
    """Hash a declared code surface; filesystem ordering cannot affect the result."""

    aggregate = hashlib.sha256()
    for relative in sorted(paths):
        path = root / relative
        aggregate.update(relative.encode())
        aggregate.update(b"\0")
        aggregate.update(hashlib.sha256(path.read_bytes()).digest())
    return aggregate.hexdigest()


def source_inventory(root: Path) -> list[dict[str, Any]]:
    """Enumerate formal partitions without reading their content."""

    paths = sorted(
        (path for path in root.rglob("part-*.parquet") if not path.name.startswith("._")),
        key=lambda path: _inventory_sort_key(root, path),
    )
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        relative = str(path.relative_to(root))
        if relative in seen:
            raise ValueError(f"duplicate release path: {relative}")
        seen.add(relative)
        instrument, variant, dataset, partition = _path_dimensions(relative)
        if instrument not in {"BTCUSDT", "ETHUSDT"} or variant not in {
            "V1_PRICE",
            "V1_FLOW",
        }:
            raise ValueError(f"unexpected release dimensions: {relative}")
        expected = PRICE_DATASETS if variant == "V1_PRICE" else FLOW_DATASETS
        if dataset not in expected:
            raise ValueError(f"unexpected release dataset: {relative}")
        stat = path.stat()
        result.append(
            {
                "path": path,
                "relative_path": relative,
                "instrument": instrument,
                "variant": variant,
                "dataset": dataset,
                "partition": partition,
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return result


def _inventory_sort_key(root: Path, path: Path) -> tuple[str, str, str, str, str]:
    relative = str(path.relative_to(root))
    try:
        instrument, variant, dataset, partition = _path_dimensions(relative)
    except (StopIteration, ValueError):
        return ("~", "~", "~", "~", relative)
    return instrument, variant, dataset, partition, relative


def _fingerprint(items: list[dict[str, Any]]) -> str:
    payload = [[item["relative_path"], item["bytes"], item["mtime_ns"]] for item in items]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def single_scan_release(
    root: Path,
    *,
    run_root: Path,
    expected_partition_count: int,
    checkpoint: dict[str, Any],
    manifest_hash: str,
    progress_path: Path,
    shard_root: Path,
    update_every_files: int = 100,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read each unsealed Parquet once and produce Catalog plus semantic analysis."""

    inventory = source_inventory(root)
    total_bytes = sum(int(item["bytes"]) for item in inventory)
    started = time.monotonic()
    files_done = 0
    bytes_done = 0
    shard_root.mkdir(parents=True, exist_ok=True)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in inventory:
        grouped[(item["instrument"], item["variant"], item["dataset"])].append(item)

    shards: list[dict[str, Any]] = []
    for key, items in sorted(grouped.items()):
        instrument, variant, dataset = key
        shard_path = shard_root / f"{instrument}-{variant}-{dataset}.json"
        fingerprint = _fingerprint(items)
        if shard_path.exists():
            shard = cast(dict[str, Any], json.loads(shard_path.read_text()))
            if shard.get("inventory_fingerprint") != fingerprint:
                raise ValueError(f"sealed shard source changed: {key}")
            files_done += len(items)
            bytes_done += sum(int(item["bytes"]) for item in items)
            shards.append(shard)
            _write_progress(
                progress_path,
                phase="DEEP_SCAN",
                files_done=files_done,
                files_total=len(inventory),
                bytes_done=bytes_done,
                bytes_total=total_bytes,
                started=started,
                instrument=instrument,
                variant=variant,
                dataset=dataset,
                sealed_shards=len(shards),
            )
            continue

        entries: list[dict[str, Any]] = []
        distributions: dict[str, Counter[str]] = defaultdict(Counter)
        candidate_ids: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        role_errors: list[str] = []
        ownership_errors: list[str] = []
        unknown_count = 0
        id_count = 0
        unique_id_count = 0
        partition_id_hashes: dict[str, str] = {}
        id_aggregate = hashlib.sha256()
        for item in items:
            raw = cast(Path, item["path"]).read_bytes()
            if len(raw) != item["bytes"]:
                raise ValueError(f"release file size changed: {item['relative_path']}")
            byte_hash = hashlib.sha256(raw).hexdigest()
            frame = pl.read_parquet(io.BytesIO(raw))
            empty = "empty_partition" in frame.columns
            rows = [] if empty else frame.to_dicts()
            logical_hash = records_logical_hash(rows, dataset)
            entries.append(
                {
                    "relative_path": item["relative_path"],
                    "rows": 0 if empty else frame.height,
                    "bytes": item["bytes"],
                    "byte_sha256": byte_hash,
                    "logical_sha256": logical_hash,
                }
            )
            id_field = ID_FIELDS.get(dataset)
            if id_field and rows:
                ids = sorted(str(row[id_field]) for row in rows)
                unique_ids = sorted(set(ids))
                id_count += len(ids)
                unique_id_count += len(unique_ids)
                part_id_hash = hashlib.sha256("\n".join(unique_ids).encode()).hexdigest()
                partition_id_hashes[item["partition"]] = part_id_hash
                id_aggregate.update(f"{item['partition']}:{part_id_hash}".encode())
            _inspect_rows(
                rows,
                instrument=instrument,
                variant=variant,
                dataset=dataset,
                partition=item["partition"],
                distributions=distributions,
                candidate_ids=candidate_ids,
                role_errors=role_errors,
                ownership_errors=ownership_errors,
            )
            unknown_count += sum(
                1
                for row in rows
                for field, value in row.items()
                if (field == "status" or field.endswith("_status")) and value == "UNKNOWN"
            )
            files_done += 1
            bytes_done += int(item["bytes"])
            if files_done % update_every_files == 0:
                _write_progress(
                    progress_path,
                    phase="DEEP_SCAN",
                    files_done=files_done,
                    files_total=len(inventory),
                    bytes_done=bytes_done,
                    bytes_total=total_bytes,
                    started=started,
                    instrument=instrument,
                    variant=variant,
                    dataset=dataset,
                    sealed_shards=len(shards),
                )
        shard = {
            "schema_name": "stage2-release-sealed-shard-v1",
            "inventory_fingerprint": fingerprint,
            "instrument": instrument,
            "variant": variant,
            "dataset": dataset,
            "entries": entries,
            "distributions": {
                name: dict(sorted(counter.items()))
                for name, counter in sorted(distributions.items())
            },
            "candidate_ids": sorted(candidate_ids[(instrument, variant, dataset)]),
            "role_errors": role_errors,
            "ownership_errors": ownership_errors,
            "unknown_count": unknown_count,
            "id_count": id_count,
            "unique_id_count": unique_id_count,
            "partition_id_hashes": partition_id_hashes,
            "id_set_logical_hash": id_aggregate.hexdigest(),
        }
        atomic_json(shard_path, shard)
        shards.append(shard)
        _write_progress(
            progress_path,
            phase="DEEP_SCAN",
            files_done=files_done,
            files_total=len(inventory),
            bytes_done=bytes_done,
            bytes_total=total_bytes,
            started=started,
            instrument=instrument,
            variant=variant,
            dataset=dataset,
            sealed_shards=len(shards),
        )

    catalog, analysis = _merge_shards(
        shards,
        run_root=run_root,
        checkpoint=checkpoint,
        expected_partition_count=expected_partition_count,
        manifest_hash=manifest_hash,
    )
    _write_progress(
        progress_path,
        phase="ARTIFACTS_SEALED",
        files_done=len(inventory),
        files_total=len(inventory),
        bytes_done=total_bytes,
        bytes_total=total_bytes,
        started=started,
        instrument=None,
        variant=None,
        dataset=None,
        sealed_shards=len(shards),
    )
    return catalog, analysis


def _merge_shards(
    shards: list[dict[str, Any]],
    *,
    run_root: Path,
    checkpoint: dict[str, Any],
    expected_partition_count: int,
    manifest_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    entries = sorted(
        (entry for shard in shards for entry in shard["entries"]),
        key=lambda entry: entry["relative_path"],
    )
    logical_aggregate = hashlib.sha256()
    physical_aggregate = hashlib.sha256()
    for entry in entries:
        logical_aggregate.update(
            json.dumps(
                {
                    "relative_path": entry["relative_path"],
                    "rows": entry["rows"],
                    "logical_sha256": entry["logical_sha256"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        physical_aggregate.update(
            json.dumps(
                {
                    "relative_path": entry["relative_path"],
                    "rows": entry["rows"],
                    "byte_sha256": entry["byte_sha256"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
    catalog = {
        "entries": entries,
        "logical_hash": logical_aggregate.hexdigest(),
        "physical_hash": physical_aggregate.hexdigest(),
    }
    datasets: dict[str, dict[str, Any]] = {}
    distributions: dict[str, Counter[str]] = defaultdict(Counter)
    candidate_ids: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    role_errors: list[str] = []
    ownership_errors: list[str] = []
    unknown_count = 0
    for shard in shards:
        key = f"{shard['instrument']}/{shard['variant']}/{shard['dataset']}"
        shard_entries = shard["entries"]
        datasets[key] = {
            "rows": sum(int(entry["rows"]) for entry in shard_entries),
            "partition_count": len(shard_entries),
            "partition_logical_hashes": {
                _path_dimensions(entry["relative_path"])[3]: entry["logical_sha256"]
                for entry in shard_entries
            },
            "id_count": shard["id_count"],
            "id_unique_count_within_partitions": shard["unique_id_count"],
            "id_duplicate_count_within_partitions": (shard["id_count"] - shard["unique_id_count"]),
            "id_set_logical_hash": shard["id_set_logical_hash"],
            "partition_id_set_hashes": shard["partition_id_hashes"],
        }
        for name, values in shard["distributions"].items():
            distributions[name].update(values)
        candidate_ids[(shard["instrument"], shard["variant"], shard["dataset"])].update(
            shard["candidate_ids"]
        )
        role_errors.extend(shard["role_errors"])
        ownership_errors.extend(shard["ownership_errors"])
        unknown_count += int(shard["unknown_count"])

    expected_keys = {
        f"{instrument}/{variant}/{dataset}"
        for instrument in ("BTCUSDT", "ETHUSDT")
        for variant, names in (("V1_PRICE", PRICE_DATASETS), ("V1_FLOW", FLOW_DATASETS))
        for dataset in names
    }
    missing_datasets = sorted(expected_keys - datasets.keys())
    bad_partition_counts = {
        key: stats["partition_count"]
        for key, stats in datasets.items()
        if key in expected_keys and stats["partition_count"] != expected_partition_count
    }
    finalization = _finalization_summary(run_root / "staging" / "data")
    missing_finalizers = sorted(
        {
            f"{instrument}/{variant}"
            for instrument in ("BTCUSDT", "ETHUSDT")
            for variant in ("V1_PRICE", "V1_FLOW")
        }
        - finalization["by_instrument_variant"].keys()
    )
    quality_errors: dict[str, Any] = {
        "missing_datasets": missing_datasets,
        "bad_partition_counts": bad_partition_counts,
        "role_errors": role_errors,
        "ownership_errors": ownership_errors,
        "candidate_inclusion_mismatches": _candidate_inclusion_mismatches(candidate_ids),
        "incomplete_tasks": sorted(set(checkpoint["planned"]) - set(checkpoint["completed"])),
        "execution_errors": list(checkpoint["failed"]),
        "unknown_count": unknown_count,
        "candidate_duplicate_count": sum(
            message.startswith("duplicate canonical candidate:") for message in role_errors
        ),
        "identity_conflict_count": finalization["identity_conflict_count"],
        "missing_finalization_reports": missing_finalizers,
    }
    passed = not any(
        value if not isinstance(value, int) else value != 0 for value in quality_errors.values()
    )
    analysis = {
        "schema_name": "stage2-group1-release-analysis-v1",
        "manifest_hash": manifest_hash,
        "catalog_logical_hash": catalog["logical_hash"],
        "catalog_physical_hash": catalog["physical_hash"],
        "datasets": datasets,
        "distributions": {
            name: dict(sorted(counter.items())) for name, counter in sorted(distributions.items())
        },
        "finalization": finalization,
        "quality": {"status": "PASS" if passed else "FAIL", **quality_errors},
    }
    return catalog, analysis


def _write_progress(
    path: Path,
    *,
    phase: ReleasePhase,
    files_done: int,
    files_total: int,
    bytes_done: int,
    bytes_total: int,
    started: float,
    instrument: str | None,
    variant: str | None,
    dataset: str | None,
    sealed_shards: int,
) -> None:
    elapsed = max(time.monotonic() - started, 0.001)
    rate = bytes_done / elapsed
    remaining = max(bytes_total - bytes_done, 0)
    atomic_json(
        path,
        {
            "schema_name": "stage2-release-progress-v1",
            "phase": phase,
            "files_done": files_done,
            "files_total": files_total,
            "bytes_done": bytes_done,
            "bytes_total": bytes_total,
            "instrument": instrument,
            "variant": variant,
            "dataset": dataset,
            "sealed_shards": sealed_shards,
            "bytes_per_second": int(rate),
            "eta_seconds": None if rate <= 0 else int(remaining / rate),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


class ReleaseRecovery:
    """State machine for release-only recovery of a sealed candidate run."""

    def __init__(self, run_root: Path, supplement_path: Path) -> None:
        self.root = run_root
        self.supplement_path = supplement_path
        self.supplement = Stage2ReleaseSupplementManifest.model_validate_json(
            supplement_path.read_bytes()
        )
        if self.supplement.manifest_hash != self.supplement.computed_hash():
            raise ValueError("invalid release supplement Manifest")
        if self.supplement.source_run_id != self.root.name:
            raise ValueError("release supplement source run mismatch")

    def release(self, *, expected_partition_count: int) -> dict[str, Any]:
        checkpoint_path = self.root / "checkpoint.json"
        checkpoint = cast(dict[str, Any], json.loads(checkpoint_path.read_text()))
        if sha256_file(checkpoint_path) != self.supplement.source_checkpoint_hash:
            current_supplement = checkpoint.get("release_supplement_hash")
            if current_supplement != self.supplement.manifest_hash:
                raise ValueError("source checkpoint changed before release recovery")
        if (
            len(checkpoint["planned"]) != self.supplement.planned_count
            or len(checkpoint["completed"]) != self.supplement.completed_count
            or len(checkpoint["failed"]) != self.supplement.failed_count
        ):
            raise ValueError("source run is not 9508/9508 cleanly complete")
        self._verify_source_authority()
        state_path = self._state_path()
        state = (
            json.loads(state_path.read_text())
            if state_path.exists()
            else {"phase": "DEEP_SCAN", "supplement_hash": self.supplement.manifest_hash}
        )
        if state["supplement_hash"] != self.supplement.manifest_hash:
            raise ValueError("release state belongs to another supplement")
        if state["phase"] == "PUBLISHED":
            return self.structural_verify()

        staging = self.root / "staging" / "data"
        published = self.root / "published" / "data"
        if state["phase"] in {"DEEP_SCAN", "ARTIFACTS_SEALED"} and published.exists():
            raise ValueError("published data exists before DATA_RENAMED state")
        if state["phase"] == "DEEP_SCAN":
            catalog, analysis = single_scan_release(
                staging,
                run_root=self.root,
                expected_partition_count=expected_partition_count,
                checkpoint=checkpoint,
                manifest_hash=self.supplement.source_execution_manifest_hash,
                progress_path=self.root / "logs" / "release-progress.json",
                shard_root=(
                    self.root / "tmp" / "release-sealed-shards" / self.supplement.manifest_hash
                ),
            )
            if analysis["quality"]["status"] != "PASS":
                self._fail(checkpoint, analysis)
                raise ValueError("Stage 2 Group 1 Quality Report failed")
            self._seal_artifacts(catalog, analysis)
            atomic_json(
                state_path,
                {"phase": "ARTIFACTS_SEALED", "supplement_hash": self.supplement.manifest_hash},
            )
            atomic_json(
                self.root / "logs" / "release-state.json", json.loads(state_path.read_text())
            )
            state["phase"] = "ARTIFACTS_SEALED"
        if state["phase"] == "ARTIFACTS_SEALED":
            os.replace(staging, published)
            atomic_json(
                state_path,
                {"phase": "DATA_RENAMED", "supplement_hash": self.supplement.manifest_hash},
            )
            atomic_json(
                self.root / "logs" / "release-state.json", json.loads(state_path.read_text())
            )
            state["phase"] = "DATA_RENAMED"
        if state["phase"] == "DATA_RENAMED":
            result = self.structural_verify()
            checkpoint["status"] = "PUBLISHED"
            checkpoint["release_supplement_hash"] = self.supplement.manifest_hash
            checkpoint["published_logical_hash"] = result["logical_hash"]
            checkpoint["published_physical_hash"] = result["physical_hash"]
            atomic_json(checkpoint_path, checkpoint)
            atomic_json(
                state_path,
                {"phase": "PUBLISHED", "supplement_hash": self.supplement.manifest_hash},
            )
            atomic_json(
                self.root / "logs" / "release-state.json", json.loads(state_path.read_text())
            )
            progress = json.loads((self.root / "logs" / "release-progress.json").read_text())
            progress["phase"] = "PUBLISHED"
            progress["updated_at"] = datetime.now(UTC).isoformat()
            atomic_json(self.root / "logs" / "release-progress.json", progress)
            return result
        raise ValueError(f"unknown release state: {state['phase']}")

    def prepare(self) -> dict[str, Any]:
        """Freeze the user-stopped fact and validate release-only authority."""

        checkpoint_path = self.root / "checkpoint.json"
        checkpoint = cast(dict[str, Any], json.loads(checkpoint_path.read_text()))
        if sha256_file(checkpoint_path) != self.supplement.source_checkpoint_hash:
            raise ValueError("source checkpoint changed before release recovery")
        if (
            len(checkpoint["planned"]) != 9508
            or len(checkpoint["completed"]) != 9508
            or checkpoint["failed"]
            or (self.root / "published" / "data").exists()
        ):
            raise ValueError("release-only source run is not eligible")
        self._verify_source_authority()
        report = {
            "record_type": "STAGE2_RELEASE_USER_STOP",
            "status": "USER_STOPPED_DURING_PUBLISH",
            "run_id": self.root.name,
            "source_checkpoint_hash": self.supplement.source_checkpoint_hash,
            "completed_count": 9508,
            "planned_count": 9508,
            "published": False,
            "change_request": "CR-2026-006",
            "release_supplement_hash": self.supplement.manifest_hash,
        }
        _write_once(
            self.root
            / "reports"
            / "release-recovery"
            / self.supplement.manifest_hash
            / "user-stopped.json",
            report,
        )
        state_path = self._state_path()
        if not state_path.exists():
            atomic_json(
                state_path,
                {"phase": "DEEP_SCAN", "supplement_hash": self.supplement.manifest_hash},
            )
        atomic_json(self.root / "logs" / "release-state.json", json.loads(state_path.read_text()))
        return {"status": "READY", "phase": "DEEP_SCAN", **report}

    def _state_path(self) -> Path:
        return self.root / "logs" / "release-states" / f"{self.supplement.manifest_hash}.json"

    def _verify_source_authority(self) -> None:
        manifest_path = Path(self.supplement.source_execution_manifest_path)
        if sha256_file(manifest_path) != self.supplement.source_execution_manifest_physical_sha256:
            raise ValueError("source Execution Manifest changed")
        for key, expected in self.supplement.finalization_report_hashes.items():
            instrument, variant = key.split("/")
            path = self.root / "reports" / f"{instrument}-{variant}-candidate-finalization.json"
            if not path.exists() or sha256_file(path) != expected:
                raise ValueError(f"finalization report changed: {key}")

    def _seal_artifacts(self, catalog: dict[str, Any], analysis: dict[str, Any]) -> None:
        _write_once(self.root / "manifests" / "catalog.json", catalog)
        _write_once(self.root / "reports" / "release-analysis.json", analysis)
        _write_once(
            self.root / "reports" / "quality-report.json",
            {
                "schema_name": "stage2-group1-quality-report-v1",
                "status": "PASS",
                "manifest_hash": self.supplement.source_execution_manifest_hash,
                "release_supplement_hash": self.supplement.manifest_hash,
                "catalog_logical_hash": analysis["catalog_logical_hash"],
                "quality": analysis["quality"],
            },
        )
        _write_once(
            self.root / "reports" / "count-summary.json",
            {
                "schema_name": "stage2-group1-count-summary-v1",
                "manifest_hash": self.supplement.source_execution_manifest_hash,
                "release_supplement_hash": self.supplement.manifest_hash,
                "catalog_logical_hash": analysis["catalog_logical_hash"],
                "datasets": {
                    key: {
                        field: value
                        for field, value in stats.items()
                        if not field.startswith("partition_")
                    }
                    for key, stats in analysis["datasets"].items()
                },
                "distributions": analysis["distributions"],
                "finalization": analysis["finalization"],
            },
        )

    def structural_verify(self) -> dict[str, Any]:
        catalog = cast(
            dict[str, Any], json.loads((self.root / "manifests" / "catalog.json").read_text())
        )
        published = self.root / "published" / "data"
        inventory = source_inventory(published)
        actual = {(item["relative_path"], item["bytes"]) for item in inventory}
        expected = {(entry["relative_path"], entry["bytes"]) for entry in catalog["entries"]}
        if actual != expected:
            raise ValueError("published structure differs from sealed Catalog")
        quality = json.loads((self.root / "reports" / "quality-report.json").read_text())
        if quality["status"] != "PASS":
            raise ValueError("sealed Quality Report is not PASS")
        return {
            "entries": len(catalog["entries"]),
            "logical_hash": catalog["logical_hash"],
            "physical_hash": catalog["physical_hash"],
        }

    def _fail(self, checkpoint: dict[str, Any], analysis: dict[str, Any]) -> None:
        checkpoint["status"] = "FAILED_UNPUBLISHED"
        checkpoint["failed"].append({"key": "RELEASE_RECOVERY", "error": analysis["quality"]})
        atomic_json(self.root / "checkpoint.json", checkpoint)
        _write_once(self.root / "reports" / "quality-report-failed-cr-2026-006.json", analysis)


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        existing = json.loads(path.read_text())
        if existing != payload:
            raise FileExistsError(f"append-only artifact exists: {path}")
        return
    atomic_json(path, payload)
