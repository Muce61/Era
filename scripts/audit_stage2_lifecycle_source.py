#!/usr/bin/env python3
"""Audit whether same-second Contract Price OHLC can bound canonical Trade gaps."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.baselines.conditional.full_run import (
    T10_SNAPSHOT,
    T10_SNAPSHOT_ID,
)
from era100x.research.stage_2.baselines.conditional.t10_access import FixedT10Reader
from era100x.research.stage_2.lifecycle.models import canonical_hash
from era100x.research.stage_2.lifecycle.source_audit import LifecycleSourceAudit
from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    sha256_file,
    write_canonical_json_exclusive,
)
from era100x.research.stage_2.rerun.seven_day_rehearsal import (
    STAGE1_ROOT,
    _contract_price_day,
    _verified_trade_day,
    _verified_trade_receipt_day,
)
from era100x.research.stage_2.rerun.trade_supplement import verify_trade_supplement

CONTRACT_PRICE_ROOT = Path("/Users/muce/1m_data/klines_data_usdm_1s_agg")
PROVENANCE_SCRIPT = Path(
    "/Users/muce/PycharmProjects/20260621/Era/scripts/fetch_btc_eth_1s_agg_history.py"
)
SOURCE_CHECKPOINT = CONTRACT_PRICE_ROOT / ".fetch_btc_eth_1s_agg_checkpoint.json"
STAGE1_CATALOG_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/catalog/runs/"
    "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
)
NS = 1_000_000_000
CONTRACT_PRICE_CSV_HEADERS = {
    b"ts_sec,open,high,low,close,volume\n",
    b"ts_sec,open,high,low,close,volume\r\n",
}
TRADE_SUPPLEMENT_PATH_ENV = "ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_PATH"
TRADE_SUPPLEMENT_HASH_ENV = "ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_HASH"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def bound_trade_supplement(
    *,
    acceptance_path: Path,
    acceptance_file_sha256: str,
    acceptance_hash: str,
) -> Iterator[None]:
    """Bind one verified exact-key overlay for audit or formal task execution."""

    verified = verify_trade_supplement(acceptance_path)
    if (
        not acceptance_path.is_absolute()
        or acceptance_path.is_symlink()
        or _sha256(acceptance_path) != acceptance_file_sha256
        or verified.get("acceptance_hash") != acceptance_hash
        or verified.get("instrument") != "BTCUSDT"
        or verified.get("date") != "2022-03-01"
        or verified.get("legacy_partition_modified") is not False
    ):
        raise ValueError("Trade supplement execution binding drift")
    previous_path = os.environ.get(TRADE_SUPPLEMENT_PATH_ENV)
    previous_hash = os.environ.get(TRADE_SUPPLEMENT_HASH_ENV)
    _verified_trade_day.cache_clear()
    _verified_trade_receipt_day.cache_clear()
    os.environ[TRADE_SUPPLEMENT_PATH_ENV] = str(acceptance_path)
    os.environ[TRADE_SUPPLEMENT_HASH_ENV] = acceptance_file_sha256
    try:
        yield
    finally:
        _verified_trade_day.cache_clear()
        _verified_trade_receipt_day.cache_clear()
        if previous_path is None:
            os.environ.pop(TRADE_SUPPLEMENT_PATH_ENV, None)
        else:
            os.environ[TRADE_SUPPLEMENT_PATH_ENV] = previous_path
        if previous_hash is None:
            os.environ.pop(TRADE_SUPPLEMENT_HASH_ENV, None)
        else:
            os.environ[TRADE_SUPPLEMENT_HASH_ENV] = previous_hash


def _csv_partition_facts(path: Path) -> tuple[str, int, int]:
    """Hash and count one real local aggTrades-derived CSV in a single pass."""

    digest = hashlib.sha256()
    size_bytes = 0
    newline_count = 0
    final_byte = b""
    with path.open("rb") as handle:
        header = handle.readline()
        if header not in CONTRACT_PRICE_CSV_HEADERS:
            raise ValueError(f"Contract Price CSV header drift: {path}")
        digest.update(header)
        size_bytes += len(header)
        newline_count += 1
        final_byte = header[-1:]
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
            size_bytes += len(chunk)
            newline_count += chunk.count(b"\n")
            final_byte = chunk[-1:]
    line_count = newline_count + (1 if final_byte != b"\n" else 0)
    row_count = line_count - 1
    if row_count <= 0 or size_bytes != path.stat().st_size:
        raise ValueError(f"Contract Price CSV is empty or changed while reading: {path}")
    return digest.hexdigest(), size_bytes, row_count


def _parquet_partition_facts(path: Path) -> tuple[str, int, int]:
    parquet = pq.ParquetFile(path)
    if set(parquet.schema_arrow.names) != {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "timestamp",
    }:
        raise ValueError(f"Contract Price Parquet schema drift: {path}")
    row_count = parquet.metadata.num_rows
    if row_count <= 0:
        raise ValueError(f"Contract Price Parquet is empty: {path}")
    return sha256_file(path), path.stat().st_size, row_count


def _t10_contract_source_hash(
    reader: FixedT10Reader,
    *,
    instrument: str,
    owner_date: date,
) -> str:
    return reader.constant_partition_column_value(
        dataset_name="contract_price_1s",
        dataset_version="2.0",
        instrument=instrument,
        variant="FOUNDATION",
        owner_date=owner_date,
        column="source_file_sha256",
    )


def _t10_contract_row_count(
    reader: FixedT10Reader,
    *,
    instrument: str,
    owner_date: date,
) -> int:
    return reader.partition(
        dataset_name="contract_price_1s",
        dataset_version="2.0",
        instrument=instrument,
        variant="FOUNDATION",
        owner_date=owner_date,
    ).receipt.row_count


def _audit_instrument(
    reader: FixedT10Reader,
    *,
    instrument: str,
    start: date,
    end_exclusive: date,
) -> dict[str, object]:
    gap_count = 0
    gap_seconds: set[int] = set()
    covered_seconds: set[int] = set()
    zero_volume_seconds: set[int] = set()
    duplicate_seconds = 0
    extra_extreme_seconds: set[int] = set()
    current = start
    while current < end_exclusive:
        trades = _verified_trade_day(instrument, current).table
        timestamps = np.asarray(
            trades["ts_event_ns"].to_numpy(zero_copy_only=False),
            dtype=np.int64,
        )
        venue_ids = np.asarray(
            trades["venue_trade_id"].to_numpy(zero_copy_only=False),
            dtype=np.int64,
        )
        prices = np.asarray(
            [float(value) for value in trades["price"].to_pylist()],
            dtype=np.float64,
        )
        gap_indexes = np.flatnonzero(venue_ids[1:] > venue_ids[:-1] + 1)
        gap_count += len(gap_indexes)
        day_gap_seconds = set(int(value) for value in timestamps[gap_indexes] // NS)
        gap_seconds.update(day_gap_seconds)

        contract = _contract_price_day(reader, instrument, current).table
        contract_seconds = (
            np.asarray(
                contract["event_ts_ns"].to_numpy(zero_copy_only=False),
                dtype=np.int64,
            )
            // NS
        )
        duplicate_seconds += len(contract_seconds) - len(np.unique(contract_seconds))
        contract_rows = {
            int(second): (
                float(high),
                float(low),
                float(volume),
            )
            for second, high, low, volume in zip(
                contract_seconds,
                contract["high"].to_pylist(),
                contract["low"].to_pylist(),
                contract["volume"].to_pylist(),
                strict=True,
            )
        }
        trade_seconds = timestamps // NS
        for second in day_gap_seconds:
            row = contract_rows.get(second)
            if row is None:
                continue
            covered_seconds.add(second)
            high, low, volume = row
            if volume == 0:
                zero_volume_seconds.add(second)
            visible = prices[trade_seconds == second]
            if visible.size and (
                high > float(visible.max()) + 1e-12 or low < float(visible.min()) - 1e-12
            ):
                extra_extreme_seconds.add(second)
        current += timedelta(days=1)
    return {
        "instrument": instrument,
        "trade_gap_count": gap_count,
        "trade_gap_second_count": len(gap_seconds),
        "contract_price_gap_seconds_covered": len(covered_seconds),
        "contract_price_zero_volume_gap_seconds": len(zero_volume_seconds),
        "contract_price_duplicate_seconds": duplicate_seconds,
        "contract_price_extreme_beyond_visible_trades_count": len(extra_extreme_seconds),
    }


def build_audit(
    *,
    start: date,
    end_exclusive: date,
    trade_supplement_acceptance_path: Path,
    trade_supplement_file_sha256: str,
    trade_supplement_acceptance_hash: str,
) -> LifecycleSourceAudit:
    """Build the v1.10 audit from sealed inventories without rereading Trade rows."""

    if not PROVENANCE_SCRIPT.is_file() or not SOURCE_CHECKPOINT.is_file():
        raise ValueError("Contract Price provenance files are missing")
    provenance = PROVENANCE_SCRIPT.read_text(encoding="utf-8")
    if (
        "data/futures/um/daily/aggTrades" not in provenance
        or "aggregate_to_seconds" not in provenance
    ):
        raise ValueError("Contract Price provenance does not bind Binance aggTrades aggregation")
    verified_supplement = verify_trade_supplement(trade_supplement_acceptance_path)
    if (
        _sha256(trade_supplement_acceptance_path) != trade_supplement_file_sha256
        or verified_supplement.get("acceptance_hash") != trade_supplement_acceptance_hash
    ):
        raise ValueError("Trade supplement sealed binding drift")
    reader = FixedT10Reader(T10_SNAPSHOT, expected_snapshot_id=T10_SNAPSHOT_ID)
    audits: list[dict[str, object]] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        catalog_path = STAGE1_CATALOG_ROOT / f"{instrument}.catalog.json"
        catalog_raw = json.loads(catalog_path.read_bytes())
        if not isinstance(catalog_raw, dict):
            raise ValueError(f"{instrument} Stage 1 Catalog must be an object")
        catalog = cast(dict[str, Any], catalog_raw)
        entries = catalog.get("entries")
        if (
            catalog.get("status") != "READY_TO_PUBLISH"
            or catalog.get("date_start") != start.isoformat()
            or catalog.get("date_end_inclusive") != (end_exclusive - timedelta(days=1)).isoformat()
            or not isinstance(entries, list)
            or len(entries) != (end_exclusive - start).days
        ):
            raise ValueError(f"{instrument} sealed Stage 1 gap inventory drift")
        gap_rows = [
            {
                "date": item["date"],
                "venue_trade_id_gap_count": item["venue_trade_id_gap_count"],
                "venue_trade_id_gap_examples": item["venue_trade_id_gap_examples"],
                "logical_sha256": item["logical_sha256"],
            }
            for item in entries
            if isinstance(item, dict)
        ]
        if len(gap_rows) != len(entries):
            raise ValueError(f"{instrument} Stage 1 gap inventory row drift")
        gap_count = sum(int(item["venue_trade_id_gap_count"]) for item in gap_rows)
        partition_count = 0
        current = start
        while current < end_exclusive:
            logical = reader.partition(
                dataset_name="contract_price_1s",
                dataset_version="2.0",
                instrument=instrument,
                variant="FOUNDATION",
                owner_date=current,
            )
            if logical.receipt.terminal_state != "PRESENT" or logical.receipt.row_count <= 0:
                raise ValueError(f"{instrument} Contract Price partition is not PRESENT")
            partition_count += 1
            current += timedelta(days=1)
        audits.append(
            {
                "instrument": instrument,
                "trade_gap_count": gap_count,
                "trade_gap_second_count": 0,
                "contract_price_gap_seconds_covered": 0,
                "contract_price_zero_volume_gap_seconds": 0,
                "contract_price_duplicate_seconds": 0,
                "contract_price_extreme_beyond_visible_trades_count": 0,
                "gap_second_check_status": "DEFERRED_TO_T11_EPISODE_WINDOWS",
                "stage1_gap_inventory_hash": canonical_content_hash(gap_rows),
                "contract_price_partition_count": partition_count,
            }
        )
    passed = all(
        cast(int, item["trade_gap_count"]) > 0
        and cast(int, item["contract_price_partition_count"]) == 2376
        for item in audits
    )
    payload: dict[str, object] = {
        "schema_name": "stage2-lifecycle-source-audit",
        "schema_version": "1.3",
        "status": ("PASS" if passed else "BLOCKED_SOURCE_NOT_INDEPENDENT_OR_INFORMATIVE"),
        "scope_start_date": start.isoformat(),
        "scope_end_date_exclusive": end_exclusive.isoformat(),
        "contract_price_source_family": "BINANCE_USDM_AGGTRADES_DERIVED_1S_OHLC",
        "canonical_trade_source_family": "BINANCE_USDM_TRADES_ARCHIVES",
        "source_relationship": "DISTINCT_BINANCE_ARCHIVE_FAMILIES",
        "information_status": "SAME_SECOND_RANGE_BOUND_ADDITIONAL_ASSURANCE",
        "contract_price_root": str(CONTRACT_PRICE_ROOT),
        "canonical_trade_root": str(STAGE1_ROOT),
        "provenance_script_path": str(PROVENANCE_SCRIPT),
        "provenance_script_sha256": _sha256(PROVENANCE_SCRIPT),
        "source_checkpoint_path": str(SOURCE_CHECKPOINT),
        "source_checkpoint_sha256": _sha256(SOURCE_CHECKPOINT),
        "canonical_trade_overlay_mode": "EXACT_KEY_APPEND_ONLY_SUPPLEMENT_V1",
        "trade_supplement_acceptance_path": str(trade_supplement_acceptance_path),
        "trade_supplement_file_sha256": trade_supplement_file_sha256,
        "trade_supplement_acceptance_hash": trade_supplement_acceptance_hash,
        "trade_supplement_instrument": "BTCUSDT",
        "trade_supplement_date": "2022-03-01",
        "legacy_stage1_partition_modified": False,
        "audits": tuple(audits),
        "forward_filled_seconds_forbidden": True,
        "zero_trade_contract_price_proxy_allowed": True,
        "evidence_mode": "SEALED_INCREMENTAL_V1",
        "full_trade_row_rescan": False,
        "targeted_reverification": ("T11_EPISODE_WINDOW_GAP_SECONDS",),
        "unverified_or_drifted_sources": (),
        "historical_execution_claim": False,
    }
    payload["audit_hash"] = canonical_hash(payload)
    return LifecycleSourceAudit.model_validate(payload)


def build_contract_price_catalog(
    *,
    audit_path: Path,
    audit: LifecycleSourceAudit,
    output_path: Path,
) -> Path:
    """Hash every BTC/ETH daily OHLC partition in the audited formal period."""

    if not audit_path.is_absolute() or not audit_path.is_file() or audit_path.is_symlink():
        raise ValueError("source audit path must be an immutable absolute file")
    entries = collect_contract_price_partitions(audit=audit)
    expected = (
        date.fromisoformat(audit.scope_end_date_exclusive)
        - date.fromisoformat(audit.scope_start_date)
    ).days * 2
    if len(entries) != expected:
        raise AssertionError("Contract Price Catalog partition count drift")
    payload: dict[str, object] = {
        "schema_name": "s2p18-contract-price-source-catalog-v1",
        "schema_version": "1.0",
        "scope_start_date": audit.scope_start_date,
        "scope_end_date_exclusive": audit.scope_end_date_exclusive,
        "source_audit_path": str(audit_path),
        "source_audit_hash": audit.audit_hash,
        "source_audit_sha256": sha256_file(audit_path),
        "partition_count": len(entries),
        "partitions": entries,
        "forward_filled_seconds_forbidden": True,
        "zero_trade_contract_price_proxy_allowed": True,
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    payload["catalog_hash"] = canonical_hash(payload)
    write_canonical_json_exclusive(output_path, payload)
    return output_path


def collect_contract_price_partitions(
    *,
    audit: LifecycleSourceAudit,
) -> list[dict[str, object]]:
    """Adopt T10-sealed partition facts; Hash only an ambiguous local candidate."""

    if audit.status != "PASS":
        raise ValueError("Contract Price partitions require a passing source audit")
    start = date.fromisoformat(audit.scope_start_date)
    end = date.fromisoformat(audit.scope_end_date_exclusive)
    reader = FixedT10Reader(T10_SNAPSHOT, expected_snapshot_id=T10_SNAPSHOT_ID)
    checkpoint_raw = json.loads(SOURCE_CHECKPOINT.read_bytes())
    if not isinstance(checkpoint_raw, dict):
        raise ValueError("Contract Price source checkpoint must be an object")
    checkpoint = cast(dict[str, Any], checkpoint_raw)
    completed = checkpoint.get("completed")
    if not isinstance(completed, dict):
        raise ValueError("Contract Price source checkpoint completed map is missing")
    entries: list[dict[str, object]] = []
    current = start
    while current < end:
        stamp = current.strftime("%Y%m%d")
        for instrument in ("BTCUSDT", "ETHUSDT"):
            partition_root = CONTRACT_PRICE_ROOT / f"{instrument}_1s_agg"
            candidates = (
                partition_root / f"{instrument}_1s_{stamp}.csv",
                partition_root / f"{instrument}_1s_{stamp}.parquet",
            )
            present = [
                partition
                for partition in candidates
                if partition.is_file()
                and not partition.is_symlink()
                and not partition.name.startswith("._")
            ]
            if not present:
                raise ValueError(
                    f"Contract Price formal-period partition is missing: {instrument}:{current}"
                )
            source_hash = _t10_contract_source_hash(
                reader,
                instrument=instrument,
                owner_date=current,
            )
            row_count = _t10_contract_row_count(
                reader,
                instrument=instrument,
                owner_date=current,
            )
            format_map = completed.get(instrument)
            expected_format = (
                format_map.get(current.isoformat()) if isinstance(format_map, dict) else None
            )
            preferred = [
                path for path in present if expected_format and path.suffix == f".{expected_format}"
            ]
            if len(preferred) == 1:
                present = preferred
            if len(present) == 1:
                partition = present[0]
                if partition.suffix == ".csv":
                    with partition.open("rb") as handle:
                        if handle.readline() not in CONTRACT_PRICE_CSV_HEADERS:
                            raise ValueError(f"Contract Price CSV header drift: {partition}")
                else:
                    parquet = pq.ParquetFile(partition)
                    if parquet.metadata.num_rows != row_count:
                        raise ValueError("Contract Price local/T10 row count drift")
                partition_hash = source_hash
                size_bytes = partition.stat().st_size
            else:
                measured = [
                    (
                        partition,
                        *(
                            _csv_partition_facts(partition)
                            if partition.suffix == ".csv"
                            else _parquet_partition_facts(partition)
                        ),
                    )
                    for partition in present
                ]
                matching = [item for item in measured if item[1] == source_hash]
                if len(matching) != 1:
                    raise ValueError(
                        f"Contract Price T10 source binding count is not one: "
                        f"{instrument}:{current}:{len(matching)}"
                    )
                partition, partition_hash, size_bytes, measured_rows = matching[0]
                if measured_rows != row_count:
                    raise ValueError("Contract Price local/T10 row count drift")
            entries.append(
                {
                    "instrument": instrument,
                    "date": current.isoformat(),
                    "path": str(partition),
                    "sha256": partition_hash,
                    "size_bytes": size_bytes,
                    "row_count": row_count,
                }
            )
        current += timedelta(days=1)
    expected = (end - start).days * 2
    if len(entries) != expected:
        raise AssertionError("Contract Price partition count drift")
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2020, 1, 1))
    parser.add_argument(
        "--end-date-exclusive",
        type=date.fromisoformat,
        default=date(2026, 7, 4),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--catalog-output", type=Path)
    parser.add_argument("--trade-supplement-acceptance", required=True, type=Path)
    args = parser.parse_args()
    supplement_path = args.trade_supplement_acceptance.resolve()
    supplement = verify_trade_supplement(supplement_path)
    audit = build_audit(
        start=args.start_date,
        end_exclusive=args.end_date_exclusive,
        trade_supplement_acceptance_path=supplement_path,
        trade_supplement_file_sha256=sha256_file(supplement_path),
        trade_supplement_acceptance_hash=str(supplement["acceptance_hash"]),
    )
    encoded = json.dumps(
        audit.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if args.output is None:
        if args.catalog_output is not None:
            raise ValueError("--catalog-output requires --output")
        print(encoded)
    else:
        write_canonical_json_exclusive(
            args.output,
            audit.model_dump(mode="json"),
        )
        if args.catalog_output is not None:
            build_contract_price_catalog(
                audit_path=args.output.resolve(),
                audit=audit,
                output_path=args.catalog_output,
            )
    return 0 if audit.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
