#!/usr/bin/env python3
"""Audit whether same-second Contract Price OHLC can bound canonical Trade gaps."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

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
    sha256_file,
    write_canonical_json_exclusive,
)
from era100x.research.stage_2.rerun.seven_day_rehearsal import (
    STAGE1_ROOT,
    _contract_price_day,
    _verified_trade_day,
)

CONTRACT_PRICE_ROOT = Path("/Users/muce/1m_data/klines_data_usdm_1s_agg")
PROVENANCE_SCRIPT = Path(
    "/Users/muce/PycharmProjects/20260621/Era/scripts/fetch_btc_eth_1s_agg_history.py"
)
SOURCE_CHECKPOINT = CONTRACT_PRICE_ROOT / ".fetch_btc_eth_1s_agg_checkpoint.json"
NS = 1_000_000_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        contract_seconds = np.asarray(
            contract["event_ts_ns"].to_numpy(zero_copy_only=False),
            dtype=np.int64,
        ) // NS
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
                high > float(visible.max()) + 1e-12
                or low < float(visible.min()) - 1e-12
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


def build_audit(*, start: date, end_exclusive: date) -> LifecycleSourceAudit:
    if not PROVENANCE_SCRIPT.is_file() or not SOURCE_CHECKPOINT.is_file():
        raise ValueError("Contract Price provenance files are missing")
    provenance = PROVENANCE_SCRIPT.read_text(encoding="utf-8")
    if (
        "data/futures/um/daily/aggTrades" not in provenance
        or "aggregate_to_seconds" not in provenance
    ):
        raise ValueError("Contract Price provenance does not bind Binance aggTrades aggregation")
    reader = FixedT10Reader(T10_SNAPSHOT, expected_snapshot_id=T10_SNAPSHOT_ID)
    audits = tuple(
        _audit_instrument(
            reader,
            instrument=instrument,
            start=start,
            end_exclusive=end_exclusive,
        )
        for instrument in ("BTCUSDT", "ETHUSDT")
    )
    passed = all(
        isinstance(item["trade_gap_second_count"], int)
        and item["trade_gap_second_count"] > 0
        and item["contract_price_gap_seconds_covered"] == item["trade_gap_second_count"]
        and item["contract_price_zero_volume_gap_seconds"] == 0
        and item["contract_price_duplicate_seconds"] == 0
        for item in audits
    )
    payload: dict[str, object] = {
        "schema_name": "stage2-lifecycle-source-audit",
        "schema_version": "1.0",
        "status": (
            "PASS" if passed else "BLOCKED_SOURCE_NOT_INDEPENDENT_OR_INFORMATIVE"
        ),
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
        "audits": audits,
        "forward_filled_seconds_forbidden": True,
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

    if audit.status != "PASS":
        raise ValueError("Contract Price Catalog requires a passing source audit")
    if not audit_path.is_absolute() or not audit_path.is_file() or audit_path.is_symlink():
        raise ValueError("source audit path must be an immutable absolute file")
    start = date.fromisoformat(audit.scope_start_date)
    end = date.fromisoformat(audit.scope_end_date_exclusive)
    entries: list[dict[str, object]] = []
    current = start
    while current < end:
        stamp = current.strftime("%Y%m%d")
        for instrument in ("BTCUSDT", "ETHUSDT"):
            partition = (
                CONTRACT_PRICE_ROOT
                / f"{instrument}_1s_agg"
                / f"{instrument}_1s_{stamp}.parquet"
            )
            if (
                not partition.is_file()
                or partition.is_symlink()
                or partition.name.startswith("._")
            ):
                raise ValueError(
                    f"Contract Price formal-period partition is missing: "
                    f"{instrument}:{current}"
                )
            metadata = pq.ParquetFile(partition).metadata
            entries.append(
                {
                    "instrument": instrument,
                    "date": current.isoformat(),
                    "path": str(partition),
                    "sha256": sha256_file(partition),
                    "size_bytes": partition.stat().st_size,
                    "row_count": metadata.num_rows,
                }
            )
        current += timedelta(days=1)
    expected = (end - start).days * 2
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
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    payload["catalog_hash"] = canonical_hash(payload)
    write_canonical_json_exclusive(output_path, payload)
    return output_path


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
    args = parser.parse_args()
    audit = build_audit(start=args.start_date, end_exclusive=args.end_date_exclusive)
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
