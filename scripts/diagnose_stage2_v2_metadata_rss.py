#!/usr/bin/env python3
"""Formal-scale Runtime V2 metadata publication RSS diagnostic.

This creates no research run ID and consumes no Stage 1 data.  It builds an
80,784-partition metadata graph with one fragment per partition, feeds six
bounded task components to the real Catalog V2 streaming publisher, reopens
the merged Catalog, and fails if process peak RSS exceeds the production
900 MiB threshold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sys
import time
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

from era100x.research.stage_2.runtime_v2.catalog import (
    CatalogComponentV2,
    CatalogPublisherV2,
    CatalogReaderV2,
    SealReducerV2,
)
from era100x.research.stage_2.runtime_v2.models import (
    MAX_PROCESS_RSS_BYTES,
    ArrowFieldSpec,
    ArtifactRef,
    DatasetPlan,
    DatasetSpec,
    DigestBinding,
    FragmentV2,
    LogicalPartitionKey,
    ManifestV2,
    Receipt,
    canonical_metadata_bytes,
    metadata_sha256,
)
from era100x.research.stage_2.runtime_v2.production_backend import TaskAggregateEvidence

SNAPSHOT_ID = "1" * 64
SEMANTIC_HASH = "2" * 64
IDENTITY_HASH = "3" * 64
PAYLOAD_HASH = "4" * 64
START = date(2020, 1, 1)
FORMAL_DAYS = 2_376
FORMAL_GROUPS = 34
FORMAL_COMPONENTS = 6
# Two Foundation tasks own four datasets each.  Group-1 then owns the actual
# 10 PRICE / 3 FLOW datasets independently for BTC and ETH.
FORMAL_COMPONENT_GROUP_COUNTS = (4, 4, 10, 3, 10, 3)


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _spec(group: int) -> DatasetSpec:
    return DatasetSpec.seal(
        {
            "dataset_name": f"metadata_group_{group:02d}",
            "dataset_version": "2.0",
            "fields": (ArrowFieldSpec(name="id", data_type="int64", nullable=False),),
            "stable_sort_keys": ("id",),
            "identity_fields": ("id",),
            "payload_association_fields": ("id",),
            "ownership_mode": "PARTITION_KEY_ONLY",
            "legacy_hash_algorithm": "NOT_APPLICABLE",
        }
    )


def _key(spec: DatasetSpec, group: int, offset: int) -> LogicalPartitionKey:
    return LogicalPartitionKey(
        snapshot_id=SNAPSHOT_ID,
        dataset_name=spec.dataset_name,
        dataset_version=spec.dataset_version,
        dataset_spec_hash=spec.spec_hash,
        setup_id="METADATA_STRESS",
        context_id="NO_RESEARCH_DATA",
        instrument="BTCUSDT" if group % 2 == 0 else "ETHUSDT",
        variant=f"COMPONENT_{group % FORMAL_COMPONENTS}",
        owner_date=START + timedelta(days=offset),
    )


def _write_artifact(root: Path, spec: DatasetSpec, group: int, rows: int) -> ArtifactRef:
    payload = f"stage2-v2-metadata-stress/{group}/{rows}\n".encode()
    physical = hashlib.sha256(payload).hexdigest()
    relative = f"objects/{physical[:2]}/{physical}.parquet"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return ArtifactRef(
        snapshot_id=SNAPSHOT_ID,
        dataset_spec_hash=spec.spec_hash,
        object_sha256=physical,
        relative_path=relative,
        byte_size=len(payload),
        row_count=rows,
        semantic_sha256=metadata_sha256((spec.spec_hash, rows)),
    )


def _manifest(specs: tuple[DatasetSpec, ...], days: int) -> ManifestV2:
    plans = []
    for group, spec in enumerate(specs):
        plans.append(
            DatasetPlan(
                dataset_spec_hash=spec.spec_hash,
                expected_partition_ids=tuple(
                    sorted(_key(spec, group, offset).partition_id for offset in range(days))
                ),
            )
        )
    return ManifestV2.seal(
        {
            "snapshot_id": SNAPSHOT_ID,
            "stage1_data_run_id": "DIAGNOSTIC_NO_STAGE1_READ",
            "stage1_authorities": (DigestBinding(name="diagnostic_authority", sha256="5" * 64),),
            "preregistration_manifest_sha256": "6" * 64,
            "config_sha256": "7" * 64,
            "code_tree_sha256": "8" * 64,
            "dataset_specs": tuple(sorted(specs, key=lambda item: item.spec_hash)),
            "dataset_plans": tuple(sorted(plans, key=lambda item: item.dataset_spec_hash)),
            "invalidation_conditions": ("DIAGNOSTIC_ONLY",),
        }
    )


def _components(
    root: Path,
    specs: tuple[DatasetSpec, ...],
    days: int,
    samples: list[dict[str, int | str]],
) -> Iterator[CatalogComponentV2]:
    group_start = 0
    for component_ordinal in range(FORMAL_COMPONENTS):
        group_end = group_start + FORMAL_COMPONENT_GROUP_COUNTS[component_ordinal]
        artifacts: list[ArtifactRef] = []
        receipts: list[Receipt] = []
        fragments: list[FragmentV2] = []
        seals = []
        for group, spec in enumerate(specs[group_start:group_end], start=group_start):
            artifact = _write_artifact(root, spec, group, days)
            artifacts.append(artifact)
            shard_receipts: list[Receipt] = []
            for offset in range(days):
                key = _key(spec, group, offset)
                fragment = FragmentV2.seal(
                    {
                        "snapshot_id": SNAPSHOT_ID,
                        "dataset_spec_hash": spec.spec_hash,
                        "partition_id": key.partition_id,
                        "artifact": artifact,
                        "fragment_ordinal": 0,
                        "row_offset": offset,
                        "row_count": 1,
                        "semantic_sha256": SEMANTIC_HASH,
                    }
                )
                receipt = Receipt.seal(
                    {
                        "snapshot_id": SNAPSHOT_ID,
                        "shard_id": f"metadata-group-{group:02d}",
                        "partition": key,
                        "terminal_state": "PRESENT",
                        "row_count": 1,
                        "legacy_hash_algorithm": "NOT_APPLICABLE",
                        "legacy_logical_sha256": None,
                        "semantic_sha256": SEMANTIC_HASH,
                        "identity_multiset_sha256": IDENTITY_HASH,
                        "payload_association_sha256": PAYLOAD_HASH,
                        "fragment_hashes": (fragment.fragment_hash,),
                    }
                )
                fragments.append(fragment)
                receipts.append(receipt)
                shard_receipts.append(receipt)
            seals.append(
                SealReducerV2.reduce(
                    snapshot_id=SNAPSHOT_ID,
                    dataset_spec_hash=spec.spec_hash,
                    shard_id=f"metadata-group-{group:02d}",
                    receipts=shard_receipts,
                )
            )
        component = CatalogComponentV2(
            artifacts=tuple(sorted(artifacts, key=lambda item: item.object_sha256)),
            receipts=tuple(sorted(receipts, key=lambda item: item.partition.semantic_order_key())),
            fragments=tuple(sorted(fragments, key=lambda item: item.fragment_hash)),
            seals=tuple(sorted(seals, key=lambda item: item.seal_hash)),
        )
        evidence = TaskAggregateEvidence.seal(
            {
                "task_id": "GROUP1:BTCUSDT:V1_PRICE",
                "snapshot_id": SNAPSHOT_ID,
                "manifest_hash": "9" * 64,
                "artifacts": component.artifacts,
                "receipts": component.receipts,
                "fragments": component.fragments,
                "seals": component.seals,
                "max_inflight_bytes_observed": 0,
                "peak_process_rss_bytes": _rss_bytes(),
                "quality_status": "PASS",
            }
        )
        serialized_evidence = canonical_metadata_bytes(evidence)
        samples.append(
            {
                "phase": f"COMPONENT_{component_ordinal}_TASK_EVIDENCE_SERIALIZED",
                "peak_rss_bytes": _rss_bytes(),
                "task_partition_count": len(component.receipts),
                "task_evidence_bytes": len(serialized_evidence),
            }
        )
        del serialized_evidence, evidence
        yield component
        group_start = group_end


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, default=FORMAL_DAYS)
    parser.add_argument("--groups", type=int, default=FORMAL_GROUPS)
    parser.add_argument("--mode", choices=("build", "read"), default="build")
    args = parser.parse_args()
    if args.days <= 0 or args.groups != FORMAL_GROUPS:
        raise ValueError("diagnostic requires positive days and the fixed 34-group matrix")
    if args.mode == "read":
        started = time.monotonic()
        reader = CatalogReaderV2.open(args.work_root, expected_snapshot_id=SNAPSHOT_ID)
        peak = _rss_bytes()
        payload = {
            "schema_name": "stage2-v2-metadata-rss-evidence-v1",
            "diagnostic_only": True,
            "mode": "fresh_process_catalog_read",
            "pid": os.getpid(),
            "receipt_count": reader.logical_index.num_rows,
            "fragment_count": reader.fragments_index.num_rows,
            "peak_process_rss_bytes": peak,
            "rss_hard_limit_bytes": MAX_PROCESS_RSS_BYTES,
            "rss_gate_pass": peak <= MAX_PROCESS_RSS_BYTES,
            "elapsed_milliseconds": int((time.monotonic() - started) * 1000),
            "catalog_hash": reader.catalog.catalog_hash,
        }
        payload["evidence_sha256"] = metadata_sha256(payload)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["rss_gate_pass"] else 2
    if args.work_root.exists() and any(args.work_root.iterdir()):
        raise FileExistsError("diagnostic work root must be new or empty")

    started = time.monotonic()
    samples: list[dict[str, int | str]] = []
    specs = tuple(_spec(group) for group in range(args.groups))
    manifest = _manifest(specs, args.days)
    samples.append(
        {
            "phase": "MANIFEST_READY",
            "peak_rss_bytes": _rss_bytes(),
        }
    )
    catalog = CatalogPublisherV2(args.work_root).publish_components(
        manifest,
        components=_components(args.work_root, specs, args.days, samples),
    )
    samples.append(
        {
            "phase": "CATALOG_PUBLISHED",
            "peak_rss_bytes": _rss_bytes(),
        }
    )
    samples.append(
        {
            "phase": "CATALOG_PUBLISH_COMPLETE",
            "peak_rss_bytes": _rss_bytes(),
        }
    )
    peak = _rss_bytes()
    payload = {
        "schema_name": "stage2-v2-metadata-rss-evidence-v1",
        "diagnostic_only": True,
        "mode": "streaming_catalog_build",
        "pid": os.getpid(),
        "days": args.days,
        "group_count": args.groups,
        "component_count": FORMAL_COMPONENTS,
        "receipt_count": catalog.logical_partitions_index.row_count,
        "fragment_count": catalog.fragments_index.row_count,
        "object_count": catalog.objects_index.row_count,
        "peak_process_rss_bytes": peak,
        "rss_hard_limit_bytes": MAX_PROCESS_RSS_BYTES,
        "rss_gate_pass": peak <= MAX_PROCESS_RSS_BYTES,
        "elapsed_milliseconds": int((time.monotonic() - started) * 1000),
        "catalog_hash": catalog.catalog_hash,
        "samples": samples,
    }
    payload["evidence_sha256"] = metadata_sha256(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["rss_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
