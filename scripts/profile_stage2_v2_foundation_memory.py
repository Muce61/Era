#!/usr/bin/env python3
"""Read-only, one-day Runtime V2 Foundation memory profiler for CR-2026-011."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.runtime_v2.foundation_build import (
    aggregate_price_bars,
    aggregate_trade_seconds,
    normalize_contract_price_day,
)
from era100x.research.stage_2.runtime_v2.foundation_specs import (
    feature_foundation_dataset_specs,
)
from era100x.research.stage_2.runtime_v2.hashing import canonical_semantic_hash
from era100x.research.stage_2.runtime_v2.memory import (
    process_current_rss_bytes,
    process_peak_rss_bytes,
)
from era100x.research.stage_2.runtime_v2.source_authority import (
    ContractPriceInventoryManifestV2,
    Stage1ResolvedSourceIndexV2,
    load_sealed_source_manifest,
)

Instrument = Literal["BTCUSDT", "ETHUSDT"]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-root", type=Path, required=True)
    parser.add_argument("--instrument", choices=("BTCUSDT", "ETHUSDT"), required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _sample(
    phase: str,
    *,
    baseline_current: int,
    baseline_peak: int,
    arrow_table_bytes: int,
    row_count: int,
    semantic_sha256: str | None = None,
) -> dict[str, Any]:
    current = process_current_rss_bytes()
    peak = process_peak_rss_bytes()
    return {
        "phase": phase,
        "baseline_rss_bytes": baseline_current,
        "baseline_peak_rss_bytes": baseline_peak,
        "current_rss_bytes": current,
        "peak_rss_bytes": peak,
        "current_rss_delta_bytes": max(0, current - baseline_current),
        "peak_rss_delta_bytes": max(0, peak - baseline_peak),
        "arrow_table_bytes": arrow_table_bytes,
        "row_count": row_count,
        "semantic_sha256": semantic_sha256,
    }


def _release(*tables: pa.Table) -> None:
    del tables
    gc.collect()
    pa.default_memory_pool().release_unused()


def main() -> int:
    args = _arguments()
    authority_root = args.authority_root.resolve()
    manifests = authority_root / "manifests"
    price_manifest_path = manifests / "contract-price-inventory-v2.json"
    trades_manifest_path = manifests / "stage1-trades-resolved-index-v2.json"
    price_manifest = load_sealed_source_manifest(
        price_manifest_path, ContractPriceInventoryManifestV2
    )
    trades_manifest = load_sealed_source_manifest(trades_manifest_path, Stage1ResolvedSourceIndexV2)
    price_index = price_manifest.to_index(root=Path(price_manifest.root_authority))
    trades_index = trades_manifest.to_index(
        published_root=Path(trades_manifest.published_root_authority)
    )
    instrument = cast(Instrument, args.instrument)
    owner_date = cast(date, args.date)
    price_partition = next(
        item
        for item in price_index.partitions
        if item.instrument == instrument and item.partition_date == owner_date
    )
    trade_partition = next(
        item
        for item in trades_index.partitions
        if item.instrument == instrument and item.partition_date == owner_date
    )
    parquet = pq.ParquetFile(trade_partition.path)
    expected_trade_rows = sum(
        parquet.metadata.row_group(index).num_rows
        for index in range(parquet.metadata.num_row_groups)
    )
    specs = {item.dataset_name: item for item in feature_foundation_dataset_specs()}
    baseline_current = process_current_rss_bytes()
    baseline_peak = process_peak_rss_bytes()
    samples: list[dict[str, Any]] = [
        _sample(
            "BASELINE",
            baseline_current=baseline_current,
            baseline_peak=baseline_peak,
            arrow_table_bytes=0,
            row_count=0,
        )
    ]

    prices = normalize_contract_price_day(
        path=price_partition.path,
        instrument=instrument,
        expected_source_sha256=price_partition.byte_sha256,
    )
    price_hash = canonical_semantic_hash(prices, specs["contract_price_1s"])
    samples.append(
        _sample(
            "CONTRACT_PRICE_NORMALIZED",
            baseline_current=baseline_current,
            baseline_peak=baseline_peak,
            arrow_table_bytes=prices.nbytes,
            row_count=prices.num_rows,
            semantic_sha256=price_hash,
        )
    )
    bars = aggregate_price_bars(prices)
    bars_hash = canonical_semantic_hash(bars, specs["causal_price_bars"])
    samples.append(
        _sample(
            "CAUSAL_BARS_DERIVED",
            baseline_current=baseline_current,
            baseline_peak=baseline_peak,
            arrow_table_bytes=prices.nbytes + bars.nbytes,
            row_count=bars.num_rows,
            semantic_sha256=bars_hash,
        )
    )
    price_arrow_bytes = prices.nbytes
    bars_arrow_bytes = bars.nbytes
    del prices, bars
    _release()
    samples.append(
        _sample(
            "PRICE_TABLES_RELEASED",
            baseline_current=baseline_current,
            baseline_peak=baseline_peak,
            arrow_table_bytes=0,
            row_count=0,
        )
    )

    trade_seconds = aggregate_trade_seconds(
        path=trade_partition.path,
        instrument=instrument,
        source_logical_hash=trade_partition.logical_sha256,
        expected_source_rows=expected_trade_rows,
    )
    trade_hash = canonical_semantic_hash(trade_seconds, specs["trade_second_primitives"])
    samples.append(
        _sample(
            "TRADE_SECONDS_ROW_GROUP_STREAMED",
            baseline_current=baseline_current,
            baseline_peak=baseline_peak,
            arrow_table_bytes=trade_seconds.nbytes,
            row_count=trade_seconds.num_rows,
            semantic_sha256=trade_hash,
        )
    )
    trade_arrow_bytes = trade_seconds.nbytes
    trade_second_rows = trade_seconds.num_rows
    del trade_seconds
    _release()
    samples.append(
        _sample(
            "TRADE_SECONDS_RELEASED",
            baseline_current=baseline_current,
            baseline_peak=baseline_peak,
            arrow_table_bytes=0,
            row_count=0,
        )
    )

    payload = {
        "schema_name": "stage2-v2-foundation-memory-profile",
        "schema_version": "1.0",
        "change_request": "CR-2026-011",
        "read_only": True,
        "instrument": instrument,
        "owner_date": owner_date.isoformat(),
        "authority_run_id": authority_root.name,
        "authority_manifest_hashes": {
            "contract_price": price_manifest.manifest_hash,
            "trades": trades_manifest.manifest_hash,
        },
        "source": {
            "price_path": price_partition.path.as_posix(),
            "price_bytes": price_partition.byte_size,
            "price_sha256": price_partition.byte_sha256,
            "trade_path": trade_partition.path.as_posix(),
            "trade_bytes": trade_partition.path.stat().st_size,
            "trade_sha256": trade_partition.byte_sha256,
            "trade_logical_sha256": trade_partition.logical_sha256,
            "trade_row_groups": parquet.metadata.num_row_groups,
            "trade_rows": expected_trade_rows,
        },
        "result": {
            "price_arrow_bytes": price_arrow_bytes,
            "bars_arrow_bytes": bars_arrow_bytes,
            "trade_second_arrow_bytes": trade_arrow_bytes,
            "trade_second_rows": trade_second_rows,
            "price_semantic_sha256": price_hash,
            "bars_semantic_sha256": bars_hash,
            "trade_second_semantic_sha256": trade_hash,
            "max_current_rss_bytes": max(item["current_rss_bytes"] for item in samples),
            "max_peak_rss_bytes": max(item["peak_rss_bytes"] for item in samples),
            "max_current_rss_delta_bytes": max(item["current_rss_delta_bytes"] for item in samples),
            "max_peak_rss_delta_bytes": max(item["peak_rss_delta_bytes"] for item in samples),
            "max_arrow_table_bytes": max(item["arrow_table_bytes"] for item in samples),
        },
        "samples": samples,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    print(
        json.dumps(
            {
                "output": args.output.as_posix(),
                "sha256": hashlib.sha256(encoded).hexdigest(),
                **payload["result"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
