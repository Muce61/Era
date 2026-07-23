#!/usr/bin/env python3
"""Formal 61,776-partition bounded compatibility comparison RSS diagnostic."""

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

from era100x.research.stage_2.runtime_v2.compatibility import (
    LEGACY_HASH_ALGORITHM,
    V2_RECEIPT_LEGACY_HASH_ALGORITHM,
    DailySemanticKey,
    DailySemanticRecord,
    GlobalDistribution,
    RunAProjection,
    compare_run_a_to_v2_sorted_stream,
)
from era100x.research.stage_2.runtime_v2.dataset_specs import FLOW_DATASETS, PRICE_DATASETS
from era100x.research.stage_2.runtime_v2.catalog import SealReducerV2
from era100x.research.stage_2.runtime_v2.models import (
    MAX_PROCESS_RSS_BYTES,
    ArtifactRef,
    FragmentV2,
    LogicalPartitionKey,
    Receipt,
    metadata_sha256,
)
from era100x.research.stage_2.runtime_v2.production_backend import TaskAggregateEvidence

SNAPSHOT_ID = "1" * 64
START = date(2020, 1, 1)
FORMAL_DAYS = 2_376
FORMAL_PARTITIONS = 61_776
GLOBAL_DISTRIBUTIONS = {
    "ownership_status": {"OWNED": FORMAL_PARTITIONS},
    "parameter_set_id": {"G1-PRIMARY-V1": FORMAL_PARTITIONS},
    "reason_code": {"CANONICAL_INCLUDED": FORMAL_PARTITIONS},
    "research_role": {"PRIMARY": FORMAL_PARTITIONS},
    "time_combination_id": {"T2": FORMAL_PARTITIONS},
}


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _groups() -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (instrument, variant, dataset)
            for instrument in ("BTCUSDT", "ETHUSDT")
            for variant, datasets in (("V1_PRICE", PRICE_DATASETS), ("V1_FLOW", FLOW_DATASETS))
            for dataset in datasets
        )
    )


def _logical_hash(instrument: str, variant: str, dataset: str, owner_date: date) -> str:
    return hashlib.sha256(
        f"{instrument}/{variant}/{dataset}/{owner_date.isoformat()}".encode()
    ).hexdigest()


def _partition(
    instrument: str, variant: str, dataset: str, owner_date: date
) -> LogicalPartitionKey:
    return LogicalPartitionKey(
        snapshot_id=SNAPSHOT_ID,
        dataset_name=dataset,
        dataset_version="1.0",
        dataset_spec_hash=hashlib.sha256(dataset.encode()).hexdigest(),
        setup_id="GROUP1",
        context_id="DIAGNOSTIC",
        instrument=instrument,
        variant=variant,
        owner_date=owner_date,
    )


def _receipt(
    instrument: str,
    variant: str,
    dataset: str,
    owner_date: date,
    fragment: FragmentV2,
) -> Receipt:
    logical_hash = _logical_hash(instrument, variant, dataset, owner_date)
    return Receipt.seal(
        {
            "snapshot_id": SNAPSHOT_ID,
            "shard_id": "compare-rss-diagnostic",
            "partition": _partition(instrument, variant, dataset, owner_date),
            "terminal_state": "PRESENT",
            "row_count": 1,
            "legacy_hash_algorithm": V2_RECEIPT_LEGACY_HASH_ALGORITHM,
            "legacy_logical_sha256": logical_hash,
            "semantic_sha256": logical_hash,
            "identity_multiset_sha256": logical_hash,
            "payload_association_sha256": logical_hash,
            "fragment_hashes": (fragment.fragment_hash,),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    samples: list[dict[str, int | str]] = []
    groups = _groups()
    records = tuple(
        DailySemanticRecord(
            key=DailySemanticKey(
                instrument=instrument,
                variant=variant,
                dataset=dataset,
                owner_date=START + timedelta(days=offset),
            ),
            row_count=1,
            empty=False,
            legacy_logical_sha256=_logical_hash(
                instrument, variant, dataset, START + timedelta(days=offset)
            ),
            legacy_id_set_sha256=None,
        )
        for instrument, variant, dataset in groups
        for offset in range(FORMAL_DAYS)
    )
    run_a = RunAProjection(
        source_run_id="diagnostic-run-a",
        legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        records=records,
        global_distributions=tuple(
            GlobalDistribution(name=name, counts=tuple(sorted(values.items())))
            for name, values in sorted(GLOBAL_DISTRIBUTIONS.items())
        ),
    )
    samples.append({"phase": "RUN_A_PROJECTION_READY", "peak_rss_bytes": _rss_bytes()})

    def receipt_stream() -> Iterator[Receipt]:
        for instrument in ("BTCUSDT", "ETHUSDT"):
            for variant, datasets in (("V1_FLOW", FLOW_DATASETS), ("V1_PRICE", PRICE_DATASETS)):
                artifacts: list[ArtifactRef] = []
                fragments: list[FragmentV2] = []
                receipts: list[Receipt] = []
                seals = []
                for dataset in sorted(datasets):
                    object_sha256 = hashlib.sha256(
                        f"{instrument}/{variant}/{dataset}/object".encode()
                    ).hexdigest()
                    artifact = ArtifactRef(
                        snapshot_id=SNAPSHOT_ID,
                        dataset_spec_hash=hashlib.sha256(dataset.encode()).hexdigest(),
                        object_sha256=object_sha256,
                        relative_path=f"objects/{object_sha256[:2]}/{object_sha256}.parquet",
                        byte_size=1,
                        row_count=FORMAL_DAYS,
                        semantic_sha256=object_sha256,
                    )
                    artifacts.append(artifact)
                    dataset_receipts: list[Receipt] = []
                    for offset in range(FORMAL_DAYS):
                        owner_date = START + timedelta(days=offset)
                        partition = _partition(instrument, variant, dataset, owner_date)
                        fragment = FragmentV2.seal(
                            {
                                "snapshot_id": SNAPSHOT_ID,
                                "dataset_spec_hash": artifact.dataset_spec_hash,
                                "partition_id": partition.partition_id,
                                "artifact": artifact,
                                "fragment_ordinal": 0,
                                "row_offset": offset,
                                "row_count": 1,
                                "semantic_sha256": _logical_hash(
                                    instrument, variant, dataset, owner_date
                                ),
                            }
                        )
                        receipt = _receipt(instrument, variant, dataset, owner_date, fragment)
                        fragments.append(fragment)
                        receipts.append(receipt)
                        dataset_receipts.append(receipt)
                    seals.append(
                        SealReducerV2.reduce(
                            snapshot_id=SNAPSHOT_ID,
                            dataset_spec_hash=artifact.dataset_spec_hash,
                            shard_id="compare-rss-diagnostic",
                            receipts=dataset_receipts,
                        )
                    )
                task_id = f"GROUP1:{instrument}:{variant}"
                evidence = TaskAggregateEvidence.seal(
                    {
                        "task_id": task_id,
                        "snapshot_id": SNAPSHOT_ID,
                        "manifest_hash": "9" * 64,
                        "artifacts": tuple(sorted(artifacts, key=lambda item: item.object_sha256)),
                        "receipts": tuple(
                            sorted(receipts, key=lambda item: item.partition.semantic_order_key())
                        ),
                        "fragments": tuple(sorted(fragments, key=lambda item: item.fragment_hash)),
                        "seals": tuple(sorted(seals, key=lambda item: item.seal_hash)),
                        "max_inflight_bytes_observed": 0,
                        "peak_process_rss_bytes": _rss_bytes(),
                        "quality_status": "PASS",
                    }
                )
                samples.append(
                    {
                        "phase": f"COMPONENT_{instrument}_{variant}_READY",
                        "partition_count": len(evidence.receipts),
                        "peak_rss_bytes": _rss_bytes(),
                    }
                )
                yield from evidence.receipts

    report = compare_run_a_to_v2_sorted_stream(
        run_a,
        receipt_stream(),
        v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        v2_global_distributions=GLOBAL_DISTRIBUTIONS,
    )
    report.require_pass()
    peak = _rss_bytes()
    payload = {
        "schema_name": "stage2-v2-compare-rss-evidence-v1",
        "diagnostic_only": True,
        "pid": os.getpid(),
        "partition_count": len(records),
        "matched_partition_count": report.matched_partition_count,
        "peak_process_rss_bytes": peak,
        "rss_hard_limit_bytes": MAX_PROCESS_RSS_BYTES,
        "rss_gate_pass": peak <= MAX_PROCESS_RSS_BYTES,
        "elapsed_milliseconds": int((time.monotonic() - started) * 1000),
        "samples": samples,
    }
    if payload["partition_count"] != FORMAL_PARTITIONS:
        raise RuntimeError("diagnostic matrix does not equal 61,776 partitions")
    payload["evidence_sha256"] = metadata_sha256(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
