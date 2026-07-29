"""Real-input, append-only seven-day rehearsal for the Plan v1.3 chain.

This is deliberately not a formal research run.  It exercises the final
producer schemas and consumers over accepted T10/T13, Stage 1 Trades and
historical funding evidence, but it never creates an Authority, a formal
binning snapshot or a Run ID.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from array import array
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.foundation.filesystem import iter_evidence_files

from era100x.research.stage_2.baselines.conditional.episode_producer import (
    _episode_key,
    _load_t10_bindings,
)
from era100x.research.stage_2.baselines.conditional.full_run import (
    REPOSITORY_ROOT,
    T10_SNAPSHOT,
    T10_SNAPSHOT_ID,
)
from era100x.research.stage_2.baselines.conditional.matrix_matcher import (
    attach_outcome_matrices,
    select_outcome_blind_controls,
)
from era100x.research.stage_2.baselines.conditional.outcomes import (
    H2Trade,
    build_control_outcome_matrix,
    detect_h2_window_gaps,
)
from era100x.research.stage_2.baselines.conditional.production_core import (
    PreparedMarketFeature,
    prepare_daily_features,
)
from era100x.research.stage_2.baselines.conditional.seven_day_audit import (
    run_seven_day_audit,
    verify_seven_day_audit,
)
from era100x.research.stage_2.baselines.conditional.t10_access import FixedT10Reader
from era100x.research.stage_2.baselines.conditional.v14_contracts import (
    BACKWARD_PURGE_SECONDS,
    FORWARD_EMBARGO_SECONDS,
    ControlAnchor,
    OutcomeCell,
    V14ControlCandidate,
    V14PrimaryEpisode,
    canonical_hash,
)
from era100x.research.stage_2.funding import verify_funding_acceptance
from era100x.research.stage_2.lifecycle import (
    CanonicalTradePoint,
    ContractPricePoint,
    CostScenario,
    FundingSettlement,
    FundingTrack,
    LifecycleObservation,
    LifecyclePairResult,
    SourceCoverage,
    assemble_lifecycle_observations,
    evaluate_lifecycle_pair,
    evaluate_dual_track_lifecycle,
    replay_single_position_admission,
)
from era100x.research.stage_2.lifecycle.engine import funding_for_track
from era100x.research.stage_2.lifecycle.source_audit import (
    LifecycleSourceAudit,
    load_source_audit,
)
from era100x.research.stage_2.lifecycle.models import (
    BPS,
    PRIMARY_LANDMARK_SECONDS,
    TICKET_EQUITY,
    USABLE_MARGIN,
)
from era100x.research.stage_2.lifecycle.range_index import DecimalTimeRangeIndex
from era100x.research.stage_2.metrics.path.full_run import (
    _is_v2_stably_ordered,
    _reference_prices,
)
from era100x.research.stage_2.paths.extraction.full_run import _episode_tables
from era100x.research.stage_2.paths.extraction.models import PathGap
from era100x.research.stage_2.runtime_v2.catalog import CatalogReaderV2
from era100x.research.stage_2.runtime_v2.memory import process_current_rss_bytes

from .orchestrator import REHEARSAL_SCHEMA, TASKS, TaskHandoff, current_commit
from .producer_contracts import ExecutionScope, UpstreamArtifact
from .scoped_producers import (
    produce_scoped_ambiguity,
    produce_scoped_first_passage,
    produce_scoped_metrics,
    produce_scoped_paths,
)
from .strict_json import strict_json_bytes, strict_json_value
from .trade_supplement import partition_override

NS = 1_000_000_000
DAY_NS = 86_400 * NS
START_DATE = date(2020, 1, 1)
END_DATE = date(2020, 1, 8)
STAGE1_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/published/stage1-trades-v2/"
    "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
)
STAGE1_CATALOG_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/catalog/runs/"
    "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
)
FUNDING_ACCEPTANCE = Path(
    "/Volumes/FuckingLife/era100x_stage2/funding-evidence/"
    "s2p13-t11-funding-7d-cr-2026-038-v1/acceptance.json"
)
OPERATIONS_ROOT = Path("/Volumes/FuckingLife/era100x_stage2/operations/stage2-plan-v1.3-successor")
PRIMARY_PARAMETER_SET = "G1-PRIMARY-V1"
PRIMARY_TIMING = "T2"
LABEL_CONTRACT_HASH = canonical_hash(
    {"schema": "S2P13_REHEARSAL_LABEL_BINDING_V1", "source": "T13_H2"}
)
REHEARSAL_BIN_HASH = canonical_hash(
    {
        "schema": "REHEARSAL_ONLY_NOT_FORMAL_BINS",
        "purpose": "consumer-schema-and-outcome-blind-order-check",
    }
)


def _json_value(value: Any) -> Any:
    return strict_json_value(value)


def _encoded(value: object) -> bytes:
    return strict_json_bytes(value)


def _canonical_hash(value: object) -> str:
    return canonical_hash(_json_value(value))


def _write_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(_encoded(value))


def _write_atomic_checkpoint(path: Path, value: object) -> None:
    """Replace one mutable operations checkpoint without exposing partial JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(_encoded(value))
    os.replace(temporary, path)


class _RehearsalProgress:
    """Hash-bound, read-only UI projection for one final-code rehearsal."""

    def __init__(
        self,
        *,
        code_commit: str,
        output_root: Path,
        start_date: date,
        end_date_exclusive: date,
        purpose: str,
    ) -> None:
        self.path = OPERATIONS_ROOT / f"seven-day-rehearsal-progress.{code_commit}.json"
        self.payload: dict[str, Any] = {
            "schema_name": "stage2-plan-v13-rehearsal-progress-v1",
            "schema_version": "1.0",
            "status": "IN_PROGRESS",
            "code_commit": code_commit,
            "purpose": purpose,
            "output_root": str(output_root),
            "start_date": start_date.isoformat(),
            "end_date_exclusive": end_date_exclusive.isoformat(),
            "current_task": TASKS[0],
            "completed_task_count": 0,
            "task_count": len(TASKS),
            "overall_progress_percent": "0.00",
            "tasks": {
                task: {
                    "status": "NOT_STARTED",
                    "reason_code": "WAITING_FOR_REHEARSAL",
                    "completed_units": 0,
                    "total_units": 0,
                    "progress_percent": "0.00",
                    "row_count": 0,
                    "verify_status": "NOT_STARTED",
                }
                for task in TASKS
            },
            "stage3_locked": True,
        }
        self.start_task(TASKS[0], reason_code="SOURCE_AUDIT")

    def _publish(self) -> None:
        self.payload["heartbeat_at"] = datetime.now(UTC).isoformat()
        self.payload.pop("checkpoint_hash", None)
        self.payload["checkpoint_hash"] = _canonical_hash(self.payload)
        _write_atomic_checkpoint(self.path, self.payload)

    def start_task(self, task_id: str, *, reason_code: str = "RUNNING") -> None:
        task = cast(dict[str, Any], self.payload["tasks"][task_id])
        task.update({"status": "IN_PROGRESS", "reason_code": reason_code})
        self.payload.update({"status": "IN_PROGRESS", "current_task": task_id})
        self._recalculate(task_id)

    def update_task(
        self,
        task_id: str,
        *,
        completed_units: int,
        total_units: int,
        row_count: int,
        current_instrument: str | None = None,
        current_date: str | None = None,
        reason_code: str = "RUNNING",
    ) -> None:
        task = cast(dict[str, Any], self.payload["tasks"][task_id])
        task.update(
            {
                "status": "IN_PROGRESS",
                "reason_code": reason_code,
                "completed_units": completed_units,
                "total_units": total_units,
                "progress_percent": (
                    format(
                        (Decimal(100) * Decimal(completed_units) / Decimal(total_units)).quantize(
                            Decimal("0.01")
                        ),
                        "f",
                    )
                    if total_units
                    else "0.00"
                ),
                "row_count": row_count,
                "current_instrument": current_instrument,
                "current_date": current_date,
            }
        )
        self.payload.update({"status": "IN_PROGRESS", "current_task": task_id})
        self._recalculate(task_id)

    def pass_task(self, task_id: str, *, row_count: int) -> None:
        task = cast(dict[str, Any], self.payload["tasks"][task_id])
        total_units = max(int(task.get("total_units", 0)), int(task.get("completed_units", 0)), 1)
        task.update(
            {
                "status": "PASS",
                "reason_code": "REHEARSAL_TASK_PASS",
                "completed_units": total_units,
                "total_units": total_units,
                "progress_percent": "100.00",
                "row_count": row_count,
                "verify_status": "PASS",
            }
        )
        self.payload["completed_task_count"] = sum(
            cast(dict[str, Any], item).get("status") == "PASS"
            for item in cast(dict[str, Any], self.payload["tasks"]).values()
        )
        self._recalculate(task_id)

    def verifying(self) -> None:
        self.payload.update(
            {
                "status": "VERIFYING",
                "current_task": TASKS[-1],
                "overall_progress_percent": "100.00",
            }
        )
        self._publish()

    def pending_ui(self) -> None:
        self.payload.update(
            {
                "status": "PENDING_UI_CHECK",
                "current_task": TASKS[-1],
                "overall_progress_percent": "100.00",
            }
        )
        self._publish()

    def failed(self, error: Exception) -> None:
        current = str(self.payload.get("current_task", TASKS[0]))
        task = cast(dict[str, Any], self.payload["tasks"][current])
        task.update({"status": "FAILED", "reason_code": "REHEARSAL_TASK_FAILED"})
        self.payload.update(
            {
                "status": "FAILED",
                "failure_type": type(error).__name__,
                "failure_reason": str(error),
            }
        )
        self._publish()

    def _recalculate(self, task_id: str) -> None:
        task_index = TASKS.index(task_id)
        task = cast(dict[str, Any], self.payload["tasks"][task_id])
        fraction = Decimal(str(task.get("progress_percent", "0.00"))) / Decimal(100)
        self.payload["overall_progress_percent"] = format(
            (Decimal(100) * (Decimal(task_index) + fraction) / Decimal(len(TASKS))).quantize(
                Decimal("0.01")
            ),
            "f",
        )
        self._publish()


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe or missing rehearsal evidence: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("rehearsal JSON root must be an object")
    return cast(dict[str, Any], value)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_clean() -> bool:
    output = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=REPOSITORY_ROOT, text=True
    )
    return not output.strip()


def _safe_new_root(path: Path) -> Path:
    if path.is_symlink() or path.exists():
        raise ValueError(f"append-only rehearsal root already exists or is unsafe: {path}")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ValueError(f"unsafe rehearsal parent: {path.parent}")
    path.mkdir()
    return path


def _date_from_ns(value: int) -> date:
    return datetime.fromtimestamp(value // NS, UTC).date()


@lru_cache(maxsize=2)
def _sealed_trade_catalog_entries(instrument: str) -> dict[str, dict[str, Any]]:
    manifest = _read_json(STAGE1_CATALOG_ROOT / "manifest.json")
    claimed_manifest_hash = manifest.get("manifest_sha256")
    manifest_payload = dict(manifest)
    manifest_payload.pop("manifest_sha256", None)
    if (
        claimed_manifest_hash != _canonical_hash(manifest_payload)
        or manifest.get("run_id") != STAGE1_ROOT.name
    ):
        raise ValueError("Stage 1 sealed Trade Manifest binding drift")

    catalog = _read_json(STAGE1_CATALOG_ROOT / f"{instrument}.catalog.json")
    manifest_symbol = manifest.get("symbols", {}).get(instrument)
    entries = catalog.get("entries")
    if (
        not isinstance(manifest_symbol, dict)
        or not isinstance(entries, list)
        or entries != manifest_symbol.get("entries")
        or catalog.get("logical_data_hash") != manifest_symbol.get("logical_data_hash")
    ):
        raise ValueError(f"Stage 1 sealed Trade Catalog binding drift: {instrument}")

    by_date: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("instrument") != instrument:
            raise ValueError(f"Stage 1 sealed Trade Catalog entry invalid: {instrument}")
        owner_date = str(entry.get("date"))
        if owner_date in by_date and by_date[owner_date] != entry:
            raise ValueError(
                f"conflicting Stage 1 sealed Trade Catalog entries: {instrument} {owner_date}"
            )
        by_date[owner_date] = entry
    return by_date


def _catalog_partition_paths(instrument: str, owner_date: date) -> tuple[Path, Path]:
    raw_date = owner_date.isoformat()
    entry = _sealed_trade_catalog_entries(instrument).get(raw_date)
    if entry is None:
        raise ValueError(f"Stage 1 sealed Trade Catalog coverage missing: {instrument} {raw_date}")
    expected_relative = f"date={raw_date}/part-000.parquet"
    if entry.get("relative_path") != expected_relative or not isinstance(
        entry.get("byte_sha256"), str
    ):
        raise ValueError(f"Stage 1 sealed Trade Catalog path invalid: {instrument} {raw_date}")

    instrument_root = STAGE1_ROOT / instrument
    candidates = (
        instrument_root / f"archive={owner_date:%Y-%m}" / f"date={raw_date}",
        instrument_root / f"archive={raw_date}" / f"date={raw_date}",
    )
    present = [root for root in candidates if root.exists()]
    if not present:
        raise ValueError(
            f"unsafe or missing Catalog-registered Stage 1 Trade partition: {instrument} {raw_date}"
        )

    resolved: list[tuple[Path, Path, str]] = []
    for root in present:
        parquet_path = root / "part-000.parquet"
        receipt_path = root / "partition.json"
        if (
            root.is_symlink()
            or parquet_path.is_symlink()
            or receipt_path.is_symlink()
            or not parquet_path.is_file()
            or not receipt_path.is_file()
        ):
            raise ValueError(
                f"unsafe Catalog-registered Stage 1 Trade partition: {instrument} {raw_date}"
            )
        receipt = _read_json(receipt_path)
        receipt_hash = receipt.get("byte_sha256")
        if (
            receipt.get("instrument") != instrument
            or receipt.get("date") != raw_date
            or receipt_hash != entry["byte_sha256"]
        ):
            raise ValueError(
                f"conflicting Stage 1 Trade partition binding: {instrument} {raw_date}"
            )
        if len(present) > 1 and _file_hash(parquet_path) != receipt_hash:
            raise ValueError(f"conflicting Stage 1 Trade partitions: {instrument} {raw_date}")
        resolved.append((parquet_path, receipt_path, str(receipt_hash)))

    if len({item[2] for item in resolved}) != 1:
        raise ValueError(f"conflicting Stage 1 Trade partitions: {instrument} {raw_date}")
    return resolved[0][0], resolved[0][1]


@lru_cache(maxsize=2)
def _sealed_trade_data_end_ns(instrument: str) -> int:
    entries = _sealed_trade_catalog_entries(instrument)
    if not entries:
        raise ValueError(f"Stage 1 sealed Trade Catalog is empty: {instrument}")
    last_owner_date = max(date.fromisoformat(raw_date) for raw_date in entries)
    end_date_exclusive = last_owner_date + timedelta(days=1)
    return int(datetime.combine(end_date_exclusive, datetime.min.time(), UTC).timestamp()) * NS


def _bounded_lifecycle_source_end(*, instrument: str, start_ns: int) -> tuple[int, SourceCoverage]:
    requested_end_ns = start_ns + 7 * DAY_NS
    data_end_ns = _sealed_trade_data_end_ns(instrument)
    if start_ns >= data_end_ns:
        raise ValueError(f"lifecycle entry is outside sealed Trade coverage: {instrument}")
    if data_end_ns < requested_end_ns:
        return data_end_ns, SourceCoverage.DATA_END
    return requested_end_ns, SourceCoverage.COMPLETE


def _partition_paths(instrument: str, owner_date: date) -> tuple[Path, Path]:
    supplement_value = os.environ.get("ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_PATH")
    supplement_hash = os.environ.get("ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_HASH")
    if supplement_value:
        acceptance_path = Path(supplement_value)
        if (
            not acceptance_path.is_absolute()
            or acceptance_path.is_symlink()
            or not acceptance_path.is_file()
            or not supplement_hash
            or _file_hash(acceptance_path) != supplement_hash
        ):
            raise ValueError("Trade supplement acceptance binding drift")
        override = partition_override(
            acceptance_path=acceptance_path,
            instrument=instrument,
            owner_date=owner_date,
        )
        if override is not None:
            parquet_path, receipt_path, acceptance_hash = override
            if acceptance_hash != json.loads(acceptance_path.read_bytes()).get("acceptance_hash"):
                raise ValueError("Trade supplement acceptance self-hash drift")
            return parquet_path, receipt_path
    return _catalog_partition_paths(instrument, owner_date)


def _verified_trade_window(
    *, instrument: str, start_ns: int, end_ns: int
) -> tuple[tuple[H2Trade, ...], tuple[str, ...], tuple[dict[str, Any], ...]]:
    rows: list[H2Trade] = []
    partition_hashes: list[str] = []
    declared_gaps: list[dict[str, Any]] = []
    cursor = _date_from_ns(start_ns)
    last_date = _date_from_ns(end_ns - 1)
    while cursor <= last_date:
        day = _verified_trade_day(instrument, cursor)
        if day.gap is not None:
            declared_gaps.append(day.gap)
        start = bisect_left(day.timestamps_ns, start_ns)
        end = bisect_left(day.timestamps_ns, end_ns)
        selected = day.table.slice(start, end - start)
        selected_rows = tuple(
            H2Trade(
                ts_event_ns=int(row["ts_event_ns"]),
                venue_trade_id=int(row["venue_trade_id"]),
                canonical_trade_id=str(row["canonical_trade_id"]),
                price=Decimal(row["price"]),
            )
            for row in selected.to_pylist()
        )
        if rows and selected_rows and _trade_key(selected_rows[0]) <= _trade_key(rows[-1]):
            raise ValueError("Stage 1 Trade days violate stable identity order")
        rows.extend(selected_rows)
        partition_hashes.append(day.partition_hash)
        cursor += timedelta(days=1)
    return tuple(rows), tuple(partition_hashes), tuple(declared_gaps)


@lru_cache(maxsize=16)
def _verified_trade_receipt_day(
    instrument: str, owner_date: date
) -> tuple[Path, str, dict[str, Any] | None]:
    parquet_path, receipt_path = _partition_paths(instrument, owner_date)
    receipt = _read_json(receipt_path)
    catalog_entry = _sealed_trade_catalog_entries(instrument)[owner_date.isoformat()]
    input_rows = int(receipt.get("input_rows", -1))
    published_rows = int(receipt.get("rows", -1))
    duplicate_exact_count = int(receipt.get("duplicate_exact_count", -1))
    gap_count = int(receipt.get("venue_trade_id_gap_count", -1))
    reversal_count = int(receipt.get("venue_trade_id_reversal_count", -1))
    receipt_counts_are_valid = (
        input_rows >= 0
        and published_rows >= 0
        and duplicate_exact_count >= 0
        and input_rows == published_rows + duplicate_exact_count
    )
    parquet_rows_are_valid = (
        parquet_path.is_file() and pq.ParquetFile(parquet_path).metadata.num_rows == published_rows
    )
    if (
        parquet_path.is_symlink()
        or not parquet_path.is_file()
        or receipt.get("instrument") != instrument
        or receipt.get("date") != owner_date.isoformat()
        or receipt.get("byte_sha256") != _file_hash(parquet_path)
        or gap_count < 0
        or reversal_count < 0
        or gap_count != int(catalog_entry.get("venue_trade_id_gap_count", -1))
        or reversal_count != int(catalog_entry.get("venue_trade_id_reversal_count", -1))
        or not receipt_counts_are_valid
        or not parquet_rows_are_valid
    ):
        raise ValueError(f"Stage 1 Trade partition Verify failed: {instrument} {owner_date}")
    gap = (
        {
            "instrument": instrument,
            "date": owner_date.isoformat(),
            "venue_trade_id_gap_count": gap_count,
            "venue_trade_id_gap_examples": receipt.get("venue_trade_id_gap_examples", []),
            "venue_trade_id_reversal_count": reversal_count,
            "venue_trade_id_reversal_examples": receipt.get("venue_trade_id_reversal_examples", []),
            "venue_trade_id_conflict_count": int(
                catalog_entry.get("venue_trade_id_conflict_count", 0)
            ),
            "venue_trade_id_conflict_groups": catalog_entry.get(
                "venue_trade_id_conflict_groups", []
            ),
        }
        if gap_count
        else None
    )
    return parquet_path, str(receipt["byte_sha256"]), gap


def _trade_key(row: H2Trade) -> tuple[int, int, str]:
    return row.ts_event_ns, row.venue_trade_id, row.canonical_trade_id


@dataclass(frozen=True, slots=True)
class _VerifiedTradeDay:
    timestamps_ns: memoryview
    table: Any
    partition_hash: str
    gap: dict[str, Any] | None


@lru_cache(maxsize=16)
def _verified_trade_day(instrument: str, owner_date: date) -> _VerifiedTradeDay:
    """Verify and decode one Trade partition once for overlapping lifecycle windows."""

    parquet_path, partition_hash, gap = _verified_trade_receipt_day(instrument, owner_date)
    table = pq.read_table(
        parquet_path,
        columns=["ts_event_ns", "venue_trade_id", "canonical_trade_id", "price"],
    )
    if not _is_v2_stably_ordered(table):
        raise ValueError("Stage 1 Trade day violates unique stable identity order")
    if table.num_rows > 1:
        duplicate = pc.and_(
            pc.equal(
                table["ts_event_ns"].slice(1),
                table["ts_event_ns"].slice(0, table.num_rows - 1),
            ),
            pc.and_(
                pc.equal(
                    table["venue_trade_id"].slice(1),
                    table["venue_trade_id"].slice(0, table.num_rows - 1),
                ),
                pc.equal(
                    table["canonical_trade_id"].slice(1),
                    table["canonical_trade_id"].slice(0, table.num_rows - 1),
                ),
            ),
        )
        if bool(pc.any(duplicate).as_py()):
            raise ValueError("Stage 1 Trade day violates unique stable identity order")
    timestamps = array("q", table["ts_event_ns"].to_pylist())
    return _VerifiedTradeDay(
        timestamps_ns=memoryview(timestamps).toreadonly(),
        table=table,
        partition_hash=partition_hash,
        gap=gap,
    )


@lru_cache(maxsize=8)
def _verified_trade_range_day(instrument: str, owner_date: date) -> DecimalTimeRangeIndex:
    """Build one reusable price-crossing index per verified Trade day."""

    day = _verified_trade_day(instrument, owner_date)
    return DecimalTimeRangeIndex.build(
        tuple(int(value) for value in day.timestamps_ns),
        tuple(Decimal(value) for value in day.table["price"].to_pylist()),
    )


@lru_cache(maxsize=16)
def _verified_trade_gaps_day(instrument: str, owner_date: date) -> tuple[PathGap, ...]:
    day = _verified_trade_day(instrument, owner_date)
    timestamps = day.table["ts_event_ns"].to_pylist()
    venue_ids = day.table["venue_trade_id"].to_pylist()
    gaps: list[PathGap] = []
    for left_index in range(len(venue_ids) - 1):
        right_index = left_index + 1
        left_id = int(venue_ids[left_index])
        right_id = int(venue_ids[right_index])
        if right_id > left_id + 1:
            gaps.append(
                PathGap(
                    evidence_level="H2",
                    reason_code="H2_VENUE_TRADE_ID_GAP",
                    preceding_ts_event_ns=int(timestamps[left_index]),
                    following_ts_event_ns=int(timestamps[right_index]),
                    missing_count=right_id - left_id - 1,
                    preceding_venue_trade_id=left_id,
                    following_venue_trade_id=right_id,
                )
            )
        elif right_id < left_id:
            gaps.append(
                PathGap(
                    evidence_level="H2",
                    reason_code="H2_VENUE_TRADE_ID_REVERSAL",
                    preceding_ts_event_ns=int(timestamps[left_index]),
                    following_ts_event_ns=int(timestamps[right_index]),
                    missing_count=left_id - right_id,
                    preceding_venue_trade_id=left_id,
                    following_venue_trade_id=right_id,
                )
            )
    return tuple(gaps)


def _verified_trade_metadata(
    *, instrument: str, start_ns: int, end_ns: int
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    hashes: list[str] = []
    gaps: list[dict[str, Any]] = []
    cursor = _date_from_ns(start_ns)
    last_date = _date_from_ns(end_ns - 1)
    while cursor <= last_date:
        _, partition_hash, gap = _verified_trade_receipt_day(instrument, cursor)
        hashes.append(partition_hash)
        if gap is not None:
            gaps.append(gap)
        cursor += timedelta(days=1)
    return tuple(hashes), tuple(gaps)


@dataclass(frozen=True, slots=True)
class _FundingSeries:
    """One verified funding source parsed once for bounded window lookup."""

    timestamps_ns: tuple[int, ...]
    signed_rates: tuple[Decimal, ...]

    def between(self, *, start_ns: int, end_ns: int) -> tuple[tuple[int, Decimal], ...]:
        if end_ns < start_ns:
            raise ValueError("funding lookup end precedes start")
        # Preserve the frozen interval contract: start < settlement <= end.
        start = bisect_right(self.timestamps_ns, start_ns)
        end = bisect_right(self.timestamps_ns, end_ns)
        return tuple(zip(self.timestamps_ns[start:end], self.signed_rates[start:end], strict=True))


@dataclass(frozen=True, slots=True)
class _FundingIndex:
    """Verified BTC/ETH funding inputs shared by every lifecycle Episode."""

    series_by_instrument: dict[str, _FundingSeries]

    @classmethod
    def from_acceptance(cls, acceptance: dict[str, Any]) -> _FundingIndex:
        series_by_instrument: dict[str, _FundingSeries] = {}
        local_history = cast(dict[str, Any], acceptance["local_history"])
        for instrument in sorted(local_history):
            entry = cast(dict[str, Any], local_history[instrument])
            path = Path(str(entry["path"]))
            if path.is_symlink() or not path.is_file() or _file_hash(path) != entry["sha256"]:
                raise ValueError(f"accepted funding source drift: {instrument}")
            rows: list[tuple[int, Decimal]] = []
            with path.open(newline="", encoding="utf-8") as handle:
                for raw in csv.DictReader(handle):
                    timestamp_ms = int(raw.get("settlement_ts_ms") or raw.get("calc_time") or 0)
                    rows.append(
                        (
                            timestamp_ms * 1_000_000,
                            Decimal(raw.get("last_funding_rate") or raw["funding_rate"]),
                        )
                    )
            if tuple(rows) != tuple(sorted(rows)):
                raise ValueError("accepted funding rows are not time ordered")
            series_by_instrument[instrument] = _FundingSeries(
                timestamps_ns=tuple(timestamp for timestamp, _ in rows),
                signed_rates=tuple(rate for _, rate in rows),
            )
        return cls(series_by_instrument=series_by_instrument)

    def between(
        self, *, instrument: str, start_ns: int, end_ns: int
    ) -> tuple[tuple[int, Decimal], ...]:
        try:
            series = self.series_by_instrument[instrument]
        except KeyError as error:
            raise ValueError(f"accepted funding source missing: {instrument}") from error
        return series.between(start_ns=start_ns, end_ns=end_ns)


def _funding_rows(
    source: dict[str, Any] | _FundingIndex,
    *,
    instrument: str,
    start_ns: int,
    end_ns: int,
) -> tuple[tuple[int, Decimal], ...]:
    """Return one causal funding window, retaining compatibility for direct callers."""

    index = source if isinstance(source, _FundingIndex) else _FundingIndex.from_acceptance(source)
    return index.between(instrument=instrument, start_ns=start_ns, end_ns=end_ns)


def _selected_t10_rows(
    *, start_date: date = START_DATE, end_date_exclusive: date = END_DATE
) -> dict[str, list[dict[str, Any]]]:
    start_ns = int(datetime.combine(start_date, datetime.min.time(), UTC).timestamp() * NS)
    end_ns = int(datetime.combine(end_date_exclusive, datetime.min.time(), UTC).timestamp() * NS)
    reader = CatalogReaderV2.open(
        T10_SNAPSHOT,
        expected_snapshot_id=T10_SNAPSHOT_ID,
        deep_verify_objects=False,
    )
    references = _reference_prices(
        source_s2t10_snapshot_root=T10_SNAPSHOT,
        source_s2t10_snapshot_id=T10_SNAPSHOT_ID,
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for instrument in ("BTCUSDT", "ETHUSDT"):
        table = _episode_tables(
            reader,
            cast(Any, instrument),
            scope_start_ns=start_ns,
            scope_end_ns=end_ns,
        )
        matches = [
            {
                **row,
                "window_start_ns": int(row["available_at_ts"]),
                "reference_price": references[str(row["canonical_candidate_id"])],
                "source_t10_snapshot_id": T10_SNAPSHOT_ID,
            }
            for row in table.to_pylist()
            if row["parameter_set_id"] == PRIMARY_PARAMETER_SET
            and row["time_combination_id"] == PRIMARY_TIMING
            and bool(row["primary_eligible"])
            and row["variant_id"] == "V1_PRICE"
        ]
        if not matches:
            raise ValueError(f"seven-day window has no Primary T10 Episode: {instrument}")
        result[instrument] = sorted(
            matches,
            key=lambda row: (int(row["window_start_ns"]), str(row["market_episode_id"])),
        )
    return result


def _selected_first_passage_rows(snapshot_root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for instrument in ("BTCUSDT", "ETHUSDT"):
        table = pq.read_table(snapshot_root / instrument / "first_passage.parquet")
        matches = [
            row
            for row in table.to_pylist()
            if row["evidence_level"] == "H2"
            and row["parameter_set_id"] == PRIMARY_PARAMETER_SET
            and row["timing_id"] == PRIMARY_TIMING
            and bool(row["primary_eligible"])
            and row["source_quality_status"] == "COMPLETE"
            and row["variant_id"] == "V1_PRICE"
        ]
        if not matches:
            raise ValueError(f"scoped T14 has no complete Primary H2 Episode: {instrument}")
        result[instrument] = min(matches, key=lambda row: int(row["window_start_ns"]))
    return result


def _contract_prices(
    reader: FixedT10Reader, *, instrument: str, start_ns: int, end_ns: int
) -> tuple[ContractPricePoint, ...]:
    rows: list[ContractPricePoint] = []
    cursor = _date_from_ns(start_ns)
    last_date = _date_from_ns(end_ns - 1)
    while cursor <= last_date:
        day = _contract_price_day(reader, instrument, cursor)
        start = bisect_left(day.timestamps_ns, start_ns)
        end = bisect_left(day.timestamps_ns, end_ns)
        selected = day.table.slice(start, end - start)
        selected_rows = tuple(
            ContractPricePoint(
                event_ts_ns=int(item["event_ts_ns"]),
                available_at_ns=int(item["available_at_ns"]),
                close=Decimal(item["close"]),
                open=Decimal(item["open"]) if item.get("open") is not None else None,
                high=Decimal(item["high"]) if item.get("high") is not None else None,
                low=Decimal(item["low"]) if item.get("low") is not None else None,
                volume=Decimal(item["volume"]) if item.get("volume") is not None else None,
                source_file_sha256=(
                    str(item["source_file_sha256"])
                    if item.get("source_file_sha256") is not None
                    else None
                ),
            )
            for item in selected.to_pylist()
        )
        if rows and selected_rows and selected_rows[0].event_ts_ns <= rows[-1].event_ts_ns:
            raise ValueError("Contract Price days violate timestamp order")
        rows.extend(selected_rows)
        cursor += timedelta(days=1)
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class _ContractPriceDay:
    timestamps_ns: memoryview
    table: Any


@dataclass(frozen=True, slots=True)
class _ContractPriceRangeDay:
    close: DecimalTimeRangeIndex


@lru_cache(maxsize=16)
def _contract_price_day(
    reader: FixedT10Reader, instrument: str, owner_date: date
) -> _ContractPriceDay:
    """Decode one Contract Price day once for overlapping lifecycle windows."""

    table = reader.read(
        dataset_name="contract_price_1s",
        dataset_version="2.0",
        instrument=instrument,
        variant="FOUNDATION",
        owner_date=owner_date,
        columns=[
            "event_ts_ns",
            "available_at_ns",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source_file_sha256",
        ],
    )
    timestamp_array = array("q", table["event_ts_ns"].to_pylist())
    timestamps = memoryview(timestamp_array).toreadonly()
    if any(right <= left for left, right in zip(timestamps, timestamps[1:], strict=False)):
        raise ValueError("Contract Price day violates unique timestamp order")
    return _ContractPriceDay(timestamps_ns=timestamps, table=table)


@lru_cache(maxsize=8)
def _contract_price_range_day(
    reader: FixedT10Reader, instrument: str, owner_date: date
) -> _ContractPriceRangeDay:
    day = _contract_price_day(reader, instrument, owner_date)
    timestamps = tuple(int(value) for value in day.timestamps_ns)
    return _ContractPriceRangeDay(
        close=DecimalTimeRangeIndex.build(
            timestamps,
            tuple(Decimal(value) for value in day.table["close"].to_pylist()),
        ),
    )


@dataclass(frozen=True, slots=True)
class _IndexedHit:
    owner_date: date
    row_index: int
    timestamp_ns: int
    price: Decimal


def _scope_days(start_ns: int, end_ns: int) -> tuple[date, ...]:
    current = _date_from_ns(start_ns)
    last = _date_from_ns(end_ns - 1)
    days: list[date] = []
    while current <= last:
        days.append(current)
        current += timedelta(days=1)
    return tuple(days)


def _first_trade_indexed(
    *,
    instrument: str,
    start_ns: int,
    end_ns: int,
    threshold: Decimal,
    upward: bool,
) -> _IndexedHit | None:
    for owner_date in _scope_days(start_ns, end_ns):
        index = _verified_trade_range_day(instrument, owner_date)
        match = (
            index.first_ge(start_ns, end_ns, threshold)
            if upward
            else index.first_le(start_ns, end_ns, threshold)
        )
        if match is not None:
            timestamp, price, row_index = match
            return _IndexedHit(owner_date, row_index, timestamp, price)
    return None


def _first_contract_indexed(
    *,
    reader: FixedT10Reader,
    instrument: str,
    start_ns: int,
    end_ns: int,
    threshold: Decimal,
) -> _IndexedHit | None:
    for owner_date in _scope_days(start_ns, end_ns):
        index = _contract_price_range_day(reader, instrument, owner_date).close
        match = index.first_le(start_ns, end_ns, threshold)
        if match is not None:
            timestamp, price, row_index = match
            return _IndexedHit(owner_date, row_index, timestamp, price)
    return None


def _max_contract_indexed(
    *,
    reader: FixedT10Reader,
    instrument: str,
    start_ns: int,
    end_ns: int,
) -> _IndexedHit | None:
    best: _IndexedHit | None = None
    for owner_date in _scope_days(start_ns, end_ns):
        index = _contract_price_range_day(reader, instrument, owner_date).close
        match = index.range_max(start_ns, end_ns)
        if match is None:
            continue
        timestamp, price = match
        row_index = bisect_left(index.timestamps_ns, timestamp)
        candidate = _IndexedHit(owner_date, row_index, timestamp, price)
        if (
            best is None
            or candidate.price > best.price
            or (candidate.price == best.price and candidate.timestamp_ns < best.timestamp_ns)
        ):
            best = candidate
    return best


def _contract_point_at(
    reader: FixedT10Reader,
    *,
    instrument: str,
    owner_date: date,
    row_index: int,
) -> ContractPricePoint:
    row = (
        _contract_price_day(reader, instrument, owner_date).table.slice(row_index, 1).to_pylist()[0]
    )
    return ContractPricePoint(
        event_ts_ns=int(row["event_ts_ns"]),
        available_at_ns=int(row["available_at_ns"]),
        close=Decimal(row["close"]),
        open=Decimal(row["open"]),
        high=Decimal(row["high"]),
        low=Decimal(row["low"]),
        volume=Decimal(row["volume"]),
        source_file_sha256=str(row["source_file_sha256"]),
    )


def _contract_point_for_timestamp(
    reader: FixedT10Reader,
    *,
    instrument: str,
    timestamp_ns: int,
) -> ContractPricePoint:
    owner_date = _date_from_ns(timestamp_ns)
    day = _contract_price_day(reader, instrument, owner_date)
    row_index = bisect_left(day.timestamps_ns, timestamp_ns)
    if row_index >= len(day.timestamps_ns) or day.timestamps_ns[row_index] != timestamp_ns:
        raise ValueError("CONTRACT_PRICE_GAP_SECOND_UNAVAILABLE")
    return _contract_point_at(
        reader,
        instrument=instrument,
        owner_date=owner_date,
        row_index=row_index,
    )


def _last_contract_point(
    reader: FixedT10Reader,
    *,
    instrument: str,
    timestamp_ns: int,
) -> ContractPricePoint:
    for owner_date in reversed(_scope_days(timestamp_ns - DAY_NS, timestamp_ns + 1)):
        index = _contract_price_range_day(reader, instrument, owner_date).close
        match = index.last_at_or_before(timestamp_ns)
        if match is not None:
            row_index = bisect_right(index.timestamps_ns, timestamp_ns) - 1
            return _contract_point_at(
                reader,
                instrument=instrument,
                owner_date=owner_date,
                row_index=row_index,
            )
    raise ValueError("funding or landmark has no causal Contract Price")


def _trade_point_at(*, instrument: str, hit: _IndexedHit) -> CanonicalTradePoint:
    row = (
        _verified_trade_day(instrument, hit.owner_date).table.slice(hit.row_index, 1).to_pylist()[0]
    )
    return CanonicalTradePoint(
        ts_event_ns=int(row["ts_event_ns"]),
        venue_trade_id=int(row["venue_trade_id"]),
        canonical_trade_id=str(row["canonical_trade_id"]),
        price=Decimal(row["price"]),
    )


def _indexed_window_gaps(*, instrument: str, start_ns: int, end_ns: int) -> tuple[PathGap, ...]:
    days = _scope_days(start_ns, end_ns)
    gaps_list = [
        gap
        for owner_date in days
        for gap in _verified_trade_gaps_day(instrument, owner_date)
        if gap.preceding_ts_event_ns >= start_ns and gap.following_ts_event_ns < end_ns
    ]
    for left_date, right_date in zip(days, days[1:], strict=False):
        left = _verified_trade_day(instrument, left_date).table
        right = _verified_trade_day(instrument, right_date).table
        if not left.num_rows or not right.num_rows:
            continue
        left_row = left.slice(left.num_rows - 1, 1).to_pylist()[0]
        right_row = right.slice(0, 1).to_pylist()[0]
        left_id = int(left_row["venue_trade_id"])
        right_id = int(right_row["venue_trade_id"])
        if right_id > left_id + 1:
            gaps_list.append(
                PathGap(
                    evidence_level="H2",
                    reason_code="H2_VENUE_TRADE_ID_GAP",
                    preceding_ts_event_ns=int(left_row["ts_event_ns"]),
                    following_ts_event_ns=int(right_row["ts_event_ns"]),
                    missing_count=right_id - left_id - 1,
                    preceding_venue_trade_id=left_id,
                    following_venue_trade_id=right_id,
                )
            )
        elif right_id < left_id:
            gaps_list.append(
                PathGap(
                    evidence_level="H2",
                    reason_code="H2_VENUE_TRADE_ID_REVERSAL",
                    preceding_ts_event_ns=int(left_row["ts_event_ns"]),
                    following_ts_event_ns=int(right_row["ts_event_ns"]),
                    missing_count=left_id - right_id,
                    preceding_venue_trade_id=left_id,
                    following_venue_trade_id=right_id,
                )
            )
    gaps = tuple(gaps_list)
    return tuple(
        sorted(
            gaps,
            key=lambda gap: (
                gap.preceding_ts_event_ns,
                gap.following_ts_event_ns,
                gap.preceding_venue_trade_id or -1,
            ),
        )
    )


def _indexed_lifecycle_inputs(
    *,
    reader: FixedT10Reader,
    instrument: str,
    start_ns: int,
    end_ns: int,
    entry_price: Decimal,
    funding: tuple[tuple[int, Decimal], ...],
    funding_track: FundingTrack,
    scenario: CostScenario,
    stop_bps: Decimal,
) -> tuple[
    tuple[ContractPricePoint, ...],
    tuple[CanonicalTradePoint, ...],
    tuple[PathGap, ...],
]:
    """Reduce one seven-day path to the exact extrema/crossings needed by the scalar engine."""

    landmark_ns = start_ns + PRIMARY_LANDMARK_SECONDS * NS
    quantity = USABLE_MARGIN * Decimal("100") / entry_price
    notional = USABLE_MARGIN * Decimal("100")
    cost = notional * scenario.total_cost_bps / BPS
    stop_price = entry_price * (Decimal(1) - stop_bps / BPS)
    contract_points: dict[int, ContractPricePoint] = {}
    trade_points: dict[tuple[int, int, str], CanonicalTradePoint] = {}

    cumulative_actual = Decimal(0)
    funding_states: list[tuple[int, Decimal]] = [(start_ns, cumulative_actual)]
    for settlement_ns, signed_rate in funding:
        valuation = _last_contract_point(
            reader,
            instrument=instrument,
            timestamp_ns=settlement_ns,
        )
        contract_points[valuation.event_ts_ns] = valuation
        cumulative_actual += quantity * valuation.close * signed_rate
        funding_states.append((settlement_ns, cumulative_actual))
    funding_states.append((end_ns, cumulative_actual))

    for (segment_start, segment_funding), (segment_end, _) in zip(
        funding_states,
        funding_states[1:],
        strict=False,
    ):
        activation_start = max(start_ns, segment_start)
        activation_end = min(landmark_ns + 1, segment_end)
        if activation_start < activation_end:
            maximum = _max_contract_indexed(
                reader=reader,
                instrument=instrument,
                start_ns=activation_start,
                end_ns=activation_end,
            )
            if maximum is not None:
                point = _contract_point_at(
                    reader,
                    instrument=instrument,
                    owner_date=maximum.owner_date,
                    row_index=maximum.row_index,
                )
                contract_points[point.event_ts_ns] = point

        continuation_start = max(landmark_ns, segment_start)
        continuation_end = min(end_ns, segment_end)
        if continuation_start >= continuation_end:
            continue
        transformed_funding = funding_for_track(segment_funding, funding_track)
        target_price = entry_price * (
            Decimal(1) + (TICKET_EQUITY + cost + transformed_funding) / notional
        )
        liquidation_price = entry_price * (
            Decimal(1) + (-USABLE_MARGIN + cost + transformed_funding) / notional
        )
        for upward, threshold in ((True, target_price), (False, stop_price)):
            hit = _first_trade_indexed(
                instrument=instrument,
                start_ns=continuation_start,
                end_ns=continuation_end,
                threshold=threshold,
                upward=upward,
            )
            if hit is not None:
                trade_point = _trade_point_at(instrument=instrument, hit=hit)
                trade_points[
                    (
                        trade_point.ts_event_ns,
                        trade_point.venue_trade_id,
                        trade_point.canonical_trade_id,
                    )
                ] = trade_point
        liquidation = _first_contract_indexed(
            reader=reader,
            instrument=instrument,
            start_ns=continuation_start,
            end_ns=continuation_end,
            threshold=liquidation_price,
        )
        if liquidation is not None:
            contract_point = _contract_point_at(
                reader,
                instrument=instrument,
                owner_date=liquidation.owner_date,
                row_index=liquidation.row_index,
            )
            contract_points[contract_point.event_ts_ns] = contract_point

    landmark = _last_contract_point(
        reader,
        instrument=instrument,
        timestamp_ns=landmark_ns,
    )
    contract_points[landmark.event_ts_ns] = landmark
    gaps = _indexed_window_gaps(
        instrument=instrument,
        start_ns=start_ns,
        end_ns=end_ns,
    )
    for gap in gaps:
        first_second = (gap.preceding_ts_event_ns // NS) * NS
        last_second = (gap.following_ts_event_ns // NS) * NS
        second = first_second
        while second <= last_second:
            point = _contract_point_for_timestamp(
                reader,
                instrument=instrument,
                timestamp_ns=second,
            )
            contract_points[point.event_ts_ns] = point
            second += NS
    return (
        tuple(sorted(contract_points.values(), key=lambda item: item.event_ts_ns)),
        tuple(
            sorted(
                trade_points.values(),
                key=lambda item: (
                    item.ts_event_ns,
                    item.venue_trade_id,
                    item.canonical_trade_id,
                ),
            )
        ),
        gaps,
    )


def _lifecycle_probe(
    *,
    reader: FixedT10Reader,
    row: dict[str, Any],
    acceptance: dict[str, Any],
    funding_index: _FundingIndex | None = None,
) -> tuple[dict[str, Any], tuple[LifecyclePairResult, ...]]:
    instrument = str(row["instrument"])
    start_ns = int(row["window_start_ns"])
    requested_end_ns = start_ns + 7 * DAY_NS
    end_ns, source_coverage = _bounded_lifecycle_source_end(
        instrument=instrument,
        start_ns=start_ns,
    )
    partition_hashes, declared_gaps = _verified_trade_metadata(
        instrument=instrument,
        start_ns=start_ns,
        end_ns=end_ns,
    )
    funding = _funding_rows(
        funding_index if funding_index is not None else acceptance,
        instrument=instrument,
        start_ns=start_ns,
        end_ns=end_ns,
    )
    if declared_gaps:
        source_coverage = SourceCoverage.DECLARED_GAP
    if source_coverage is not SourceCoverage.COMPLETE:
        trades: tuple[H2Trade, ...] = ()
        prices: tuple[ContractPricePoint, ...] = ()
        observations: tuple[LifecycleObservation, ...] = ()
    else:
        trades, _, _ = _verified_trade_window(
            instrument=instrument,
            start_ns=start_ns,
            end_ns=end_ns,
        )
        prices = _contract_prices(reader, instrument=instrument, start_ns=start_ns, end_ns=end_ns)
        observations = assemble_lifecycle_observations(
            entry_price=Decimal(row["reference_price"]),
            contract_prices=prices,
            trades=tuple(
                CanonicalTradePoint(
                    ts_event_ns=trade.ts_event_ns,
                    venue_trade_id=trade.venue_trade_id,
                    canonical_trade_id=trade.canonical_trade_id,
                    price=trade.price,
                )
                for trade in trades
            ),
            funding=tuple(
                FundingSettlement(settlement_ts_ns=timestamp_ns, signed_rate=rate)
                for timestamp_ns, rate in funding
            ),
        )
    scenario = CostScenario(
        scenario_id="PRIMARY_9BP_FEE_2BP_SLIPPAGE_250MS_100PCT",
        round_trip_fee_bps=Decimal(9),
        total_slippage_bps=Decimal(2),
        latency_ms=250,
        initial_fill_ratio=Decimal(1),
    )
    results = [
        evaluate_lifecycle_pair(
            market_episode_id=str(row["market_episode_id"]),
            instrument=instrument,
            entry_ts_ns=start_ns,
            entry_price=Decimal(row["reference_price"]),
            observations=observations,
            source_coverage=source_coverage,
            scenario=scenario,
            funding_track=track,
            historical_funding_source_bound=True,
            stop_bps=Decimal(25),
        )
        for track in FundingTrack
    ]
    return {
        "instrument": instrument,
        "market_episode_id": row["market_episode_id"],
        "source_t10_snapshot_id": row["source_t10_snapshot_id"],
        "entry_ts_ns": start_ns,
        "requested_observation_end_ns": requested_end_ns,
        "available_observation_end_ns": end_ns,
        "entry_reference_price": row["reference_price"],
        "contract_price_observation_count": len(prices),
        "trade_observation_count": len(trades),
        "merged_observation_count": len(observations),
        "stage1_partition_hashes": partition_hashes,
        "declared_source_gaps": declared_gaps,
        "source_coverage": source_coverage.value,
        "funding_settlement_count": len(funding),
        "funding_acceptance_hash": acceptance["acceptance_hash"],
        "funding_tracks": results,
        "strict_consumer_readback": "PASS",
        "historical_execution_claim": False,
    }, tuple(results)


def _lifecycle_probe_v18(
    *,
    reader: FixedT10Reader,
    row: dict[str, Any],
    acceptance: dict[str, Any],
    source_audit_hash: str,
    funding_index: _FundingIndex | None = None,
) -> tuple[dict[str, Any], tuple[LifecyclePairResult, ...]]:
    """Produce separate immutable-Trade and Contract Price OHLC lifecycle tracks."""

    if len(source_audit_hash) != 64:
        raise ValueError("T11 successor Contract Price source audit is not bound")
    instrument = str(row["instrument"])
    start_ns = int(row["window_start_ns"])
    requested_end_ns = start_ns + 7 * DAY_NS
    end_ns, source_coverage = _bounded_lifecycle_source_end(
        instrument=instrument,
        start_ns=start_ns,
    )
    partition_hashes, declared_day_gaps = _verified_trade_metadata(
        instrument=instrument,
        start_ns=start_ns,
        end_ns=end_ns,
    )
    funding = _funding_rows(
        funding_index if funding_index is not None else acceptance,
        instrument=instrument,
        start_ns=start_ns,
        end_ns=end_ns,
    )
    scenario = CostScenario(
        scenario_id="PRIMARY_9BP_FEE_2BP_SLIPPAGE_250MS_100PCT",
        round_trip_fee_bps=Decimal(9),
        total_slippage_bps=Decimal(2),
        latency_ms=250,
        initial_fill_ratio=Decimal(1),
    )
    dual_results = []
    sparse_contract_count = 0
    sparse_trade_count = 0
    exact_gaps: tuple[PathGap, ...] | None = None
    for track in FundingTrack:
        prices, trades, track_gaps = _indexed_lifecycle_inputs(
            reader=reader,
            instrument=instrument,
            start_ns=start_ns,
            end_ns=end_ns,
            entry_price=Decimal(row["reference_price"]),
            funding=funding,
            funding_track=track,
            scenario=scenario,
            stop_bps=Decimal(25),
        )
        if exact_gaps is None:
            exact_gaps = track_gaps
        elif exact_gaps != track_gaps:
            raise ValueError("funding tracks cannot change source-gap identity")
        partition_hash_by_second = {
            point.event_ts_ns: cast(str, point.source_file_sha256) for point in prices
        }
        if len(partition_hash_by_second) != len(prices) or any(
            value is None for value in partition_hash_by_second.values()
        ):
            raise ValueError("Contract Price partition lineage is incomplete")
        sparse_contract_count += len(prices)
        sparse_trade_count += len(trades)
        dual_results.append(
            evaluate_dual_track_lifecycle(
                market_episode_id=str(row["market_episode_id"]),
                instrument=instrument,
                entry_ts_ns=start_ns,
                entry_price=Decimal(row["reference_price"]),
                contract_prices=prices,
                trades=tuple(
                    CanonicalTradePoint(
                        ts_event_ns=trade.ts_event_ns,
                        venue_trade_id=trade.venue_trade_id,
                        canonical_trade_id=trade.canonical_trade_id,
                        price=trade.price,
                    )
                    for trade in trades
                ),
                funding=tuple(
                    FundingSettlement(settlement_ts_ns=timestamp_ns, signed_rate=rate)
                    for timestamp_ns, rate in funding
                ),
                source_gaps=exact_gaps,
                partition_hash_by_second=partition_hash_by_second,
                source_coverage=source_coverage,
                scenario=scenario,
                funding_track=track,
                historical_funding_source_bound=True,
                stop_bps=Decimal(25),
            )
        )
    if exact_gaps is None:
        raise AssertionError("lifecycle funding tracks are empty")
    primary_track_results = tuple(item.contract_price_ohlc_primary for item in dual_results)
    return {
        "instrument": instrument,
        "market_episode_id": row["market_episode_id"],
        "source_t10_snapshot_id": row["source_t10_snapshot_id"],
        "entry_ts_ns": start_ns,
        "requested_observation_end_ns": requested_end_ns,
        "available_observation_end_ns": end_ns,
        "entry_reference_price": row["reference_price"],
        "contract_price_observation_count": sparse_contract_count,
        "trade_observation_count": sparse_trade_count,
        "path_engine": "INDEXED_RANGE_EXTREMA_V1",
        "full_path_materialization": False,
        "stage1_partition_hashes": partition_hashes,
        "declared_day_gap_metadata": declared_day_gaps,
        "window_local_source_gaps": exact_gaps,
        "window_local_source_gap_count": len(exact_gaps),
        "source_coverage": source_coverage.value,
        "funding_settlement_count": len(funding),
        "funding_acceptance_hash": acceptance["acceptance_hash"],
        "contract_price_source_audit_hash": source_audit_hash,
        "pure_trades_comparator": tuple(item.pure_trades_comparator for item in dual_results),
        "contract_price_ohlc_primary": primary_track_results,
        "gap_boundary_decisions": tuple(
            decision for item in dual_results for decision in item.gap_decisions
        ),
        "strict_consumer_readback": "PASS",
        "historical_execution_claim": False,
        "synthetic_execution": False,
    }, primary_track_results


def _event_cells(row: dict[str, Any]) -> tuple[OutcomeCell, ...]:
    return tuple(
        OutcomeCell.model_validate(
            {
                "combination_id": combination_id,
                "label": label,
                "label_reason": reason,
                "strict_target_first": int(strict),
            }
        )
        for combination_id, label, reason, strict in zip(
            row["combination_order"],
            row["labels"],
            row["label_reasons"],
            row["strict_target_first"],
            strict=True,
        )
    )


def _t16_probe(*, reader: FixedT10Reader, row: dict[str, Any]) -> dict[str, Any]:
    instrument = str(row["instrument"])
    anchor_ns = int(row["window_start_ns"])
    bindings = _load_t10_bindings(reader, instrument=instrument)
    binding = bindings[_episode_key(row)]
    episode_context = str(binding["context_state"])
    features: list[PreparedMarketFeature] = []
    for owner_date in (date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)):
        features.extend(
            prepare_daily_features(
                reader,
                instrument=instrument,
                owner_date=owner_date,
                parameter_set_ids=(PRIMARY_PARAMETER_SET,),
            ).valid_rows
        )
    episode_bucket = (anchor_ns // (4 * 3600 * NS)) % 6
    matching = [
        feature
        for feature in features
        if feature.high_timeframe_trend_state == episode_context
        and PRIMARY_PARAMETER_SET in feature.distance_bps_by_parameter
        and feature.anchor_ns + FORWARD_EMBARGO_SECONDS * NS
        <= anchor_ns - BACKWARD_PURGE_SECONDS * NS
    ]
    if len(matching) < 5:
        raise ValueError(f"T16 rehearsal has fewer than five outcome-blind controls: {instrument}")
    episode = V14PrimaryEpisode(
        market_episode_id=str(row["market_episode_id"]),
        source_h2_path_hash=str(row["classification_row_hash"]),
        instrument=cast(Any, instrument),
        anchor_ns=anchor_ns,
        high_timeframe_trend_state=episode_context,
        pre_registered_period="P1",
        evaluation_fold="F0",
        parameter_set_id=PRIMARY_PARAMETER_SET,
        time_combination_id=cast(Any, PRIMARY_TIMING),
        label_contract_hash=LABEL_CONTRACT_HASH,
        volatility_quintile=3,
        activity_quintile=3,
        key_level_distance_quintile=3,
        utc_four_hour_bucket=int(episode_bucket),
        utc_calendar_quarter=1,
        utc_calendar_year=2020,
        binning_snapshot_hash=REHEARSAL_BIN_HASH,
        information_span_start_ns=anchor_ns - BACKWARD_PURGE_SECONDS * NS,
        information_span_end_ns=anchor_ns + FORWARD_EMBARGO_SECONDS * NS,
    )
    candidates: list[V14ControlCandidate] = []
    for feature in matching:
        control_anchor = ControlAnchor.seal(
            {
                "instrument": instrument,
                "candidate_timestamp_ns": feature.anchor_ns,
                "stage1_data_run_id": STAGE1_ROOT.name,
                "t10_snapshot_hash": T10_SNAPSHOT_ID,
            }
        )
        candidates.append(
            V14ControlCandidate.seal(
                {
                    "control_anchor_id": control_anchor.control_anchor_id,
                    "instrument": instrument,
                    "candidate_timestamp_ns": feature.anchor_ns,
                    "high_timeframe_trend_state": feature.high_timeframe_trend_state,
                    "pre_registered_period": "P1",
                    "evaluation_fold": "F0",
                    "parameter_set_id": PRIMARY_PARAMETER_SET,
                    "time_combination_id": PRIMARY_TIMING,
                    "label_contract_hash": LABEL_CONTRACT_HASH,
                    "control_entry_price": feature.reference_price,
                    "entry_price_source_hash": T10_SNAPSHOT_ID,
                    "outcome_contract_hash": LABEL_CONTRACT_HASH,
                    "volatility_quintile": 3,
                    "activity_quintile": 3,
                    "key_level_distance_quintile": 3,
                    "utc_four_hour_bucket": int((feature.anchor_ns // (4 * 3600 * NS)) % 6),
                    "utc_calendar_quarter": 1,
                    "utc_calendar_year": 2020,
                    "binning_snapshot_hash": REHEARSAL_BIN_HASH,
                    "information_span_start_ns": (feature.anchor_ns - BACKWARD_PURGE_SECONDS * NS),
                    "information_span_end_ns": (feature.anchor_ns + FORWARD_EMBARGO_SECONDS * NS),
                    "is_registered_same_family_event": False,
                }
            )
        )
    selection = select_outcome_blind_controls(episode, tuple(candidates))
    if selection.status != "MATCHED":
        raise ValueError(f"T16 rehearsal outcome-blind selection is unmatched: {instrument}")
    by_id = {candidate.control_candidate_id: candidate for candidate in candidates}
    matrices = []
    for candidate_id in selection.control_candidate_ids:
        candidate = by_id[candidate_id]
        trades, partition_hashes, declared_gaps = _verified_trade_window(
            instrument=instrument,
            start_ns=candidate.candidate_timestamp_ns,
            end_ns=candidate.candidate_timestamp_ns + 180 * NS,
        )
        source_hash = canonical_hash(
            {"partition_hashes": partition_hashes, "candidate_id": candidate_id}
        )
        matrices.append(
            build_control_outcome_matrix(
                control_candidate_id=candidate_id,
                time_combination_id=PRIMARY_TIMING,
                reference_price=candidate.control_entry_price,
                trades=trades,
                anchor_ns=candidate.candidate_timestamp_ns,
                source_path_hash=source_hash,
                source_partition_bound=True,
                source_gaps=detect_h2_window_gaps(trades),
            )
        )
    matrix = attach_outcome_matrices(
        selection,
        event_outcomes=_event_cells(row),
        control_matrices=tuple(matrices),
    )
    return {
        "instrument": instrument,
        "status": matrix.status,
        "match_level": matrix.match_level,
        "selected_control_count": len(matrix.control_candidate_ids),
        "outcome_cell_count": len(matrix.event_outcomes)
        + sum(len(item.outcomes) for item in matrices),
        "output_hash": matrix.output_hash,
        "selection_completed_before_outcome_read": True,
        "declared_source_gap_control_count": sum(
            item.outcomes[0].label_reason == "SOURCE_GAP_BEFORE_DECISION" for item in matrices
        ),
        "binning_semantics": "REHEARSAL_ONLY_NOT_FORMAL_BINS",
        "formal_binning_snapshot_created": False,
        "historical_evidence_only": True,
    }


def produce_scoped_lifecycle(
    *,
    start_date: date,
    end_date_exclusive: date,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute the explicit-input lifecycle core for all Primary episodes in scope."""

    rows = _selected_t10_rows(
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
    )
    reader = FixedT10Reader(T10_SNAPSHOT, expected_snapshot_id=T10_SNAPSHOT_ID)
    acceptance = _read_json(FUNDING_ACCEPTANCE)
    funding_index = _FundingIndex.from_acceptance(acceptance)
    lifecycle: list[dict[str, Any]] = []
    admission: list[Any] = []
    total_units = sum(len(rows[instrument]) for instrument in ("BTCUSDT", "ETHUSDT"))
    completed_units = 0
    for instrument in ("BTCUSDT", "ETHUSDT"):
        instrument_results: list[LifecyclePairResult] = []
        entry_by_episode: dict[str, int] = {}
        for row in rows[instrument]:
            probe, results = _lifecycle_probe(
                reader=reader,
                row=row,
                acceptance=acceptance,
                funding_index=funding_index,
            )
            lifecycle.append(probe)
            primary = next(
                item
                for item in results
                if item.funding_track is FundingTrack.PRIMARY_HISTORICAL_ACTUAL
            )
            instrument_results.append(primary)
            entry_by_episode[primary.market_episode_id] = int(row["window_start_ns"])
            completed_units += 1
            if progress_callback is not None:
                progress_callback(
                    {
                        "completed_units": completed_units,
                        "total_units": total_units,
                        "row_count": completed_units * len(FundingTrack),
                        "current_instrument": instrument,
                        "current_date": _date_from_ns(int(row["window_start_ns"])).isoformat(),
                        "phase": "LIFECYCLE",
                        "subphase": "EPISODE_REPLAY",
                        "processed_units": completed_units,
                    }
                )
        admission.extend(
            replay_single_position_admission(
                tuple(instrument_results),
                entry_ts_ns_by_episode=entry_by_episode,
            )
        )
    return {
        "task_id": "S2P13-T11",
        "lifecycle": lifecycle,
        "single_position_admission": admission,
        "funding_source": "HISTORICAL_ACTUAL_PLUS_PREREGISTERED_STRESS",
        "source_t10_snapshot_id": T10_SNAPSHOT_ID,
        "trade_supplement_acceptance_hash": os.environ.get(
            "ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_HASH"
        ),
        "row_count": len(lifecycle) * len(FundingTrack),
    }


def produce_scoped_lifecycle_v18(
    *,
    start_date: date,
    end_date_exclusive: date,
    source_audit_hash: str,
    source_audit_path: Path | None = None,
    source_audit: LifecycleSourceAudit | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute the approved Plan v1.8 dual-track lifecycle core."""

    if (source_audit_path is None) == (source_audit is None):
        raise ValueError("dual-track lifecycle requires exactly one source-audit input")
    verified_audit = (
        load_source_audit(source_audit_path, expected_hash=source_audit_hash)
        if source_audit_path is not None
        else source_audit
    )
    if (
        verified_audit is None
        or verified_audit.status != "PASS"
        or verified_audit.audit_hash != source_audit_hash
    ):
        raise ValueError("dual-track lifecycle source-audit binding drift")
    rows = _selected_t10_rows(
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
    )
    reader = FixedT10Reader(T10_SNAPSHOT, expected_snapshot_id=T10_SNAPSHOT_ID)
    acceptance = _read_json(FUNDING_ACCEPTANCE)
    funding_index = _FundingIndex.from_acceptance(acceptance)
    lifecycle: list[dict[str, Any]] = []
    admission: list[Any] = []
    total_units = sum(len(rows[instrument]) for instrument in ("BTCUSDT", "ETHUSDT"))
    completed_units = 0
    started_at = time.monotonic()
    for instrument in ("BTCUSDT", "ETHUSDT"):
        instrument_results: list[LifecyclePairResult] = []
        entry_by_episode: dict[str, int] = {}
        for row in rows[instrument]:
            probe, results = _lifecycle_probe_v18(
                reader=reader,
                row=row,
                acceptance=acceptance,
                source_audit_hash=source_audit_hash,
                funding_index=funding_index,
            )
            lifecycle.append(probe)
            primary = next(
                item
                for item in results
                if item.funding_track is FundingTrack.PRIMARY_HISTORICAL_ACTUAL
            )
            instrument_results.append(primary)
            entry_by_episode[primary.market_episode_id] = int(row["window_start_ns"])
            completed_units += 1
            if progress_callback is not None:
                elapsed = max(time.monotonic() - started_at, 1e-9)
                throughput = completed_units / elapsed
                remaining = total_units - completed_units
                progress_callback(
                    {
                        "completed_units": completed_units,
                        "total_units": total_units,
                        "percentage": format(
                            Decimal(completed_units) * Decimal(100) / Decimal(total_units),
                            "f",
                        ),
                        "elapsed_seconds": format(Decimal(str(elapsed)), "f"),
                        "throughput_units_per_second": format(Decimal(str(throughput)), "f"),
                        "eta_seconds": (
                            format(Decimal(str(remaining / throughput)), "f")
                            if throughput
                            else None
                        ),
                        "row_count": completed_units * len(FundingTrack) * 2,
                        "current_instrument": instrument,
                        "current_date": _date_from_ns(int(row["window_start_ns"])).isoformat(),
                        "phase": "LIFECYCLE",
                        "subphase": "DUAL_TRACK_EPISODE_REPLAY",
                        "processed_units": completed_units,
                        "verify_state": "PENDING",
                        "rss_bytes": process_current_rss_bytes(),
                    }
                )
        admission.extend(
            replay_single_position_admission(
                tuple(instrument_results),
                entry_ts_ns_by_episode=entry_by_episode,
            )
        )
    return {
        "task_id": "S2P19-T11",
        "lifecycle": lifecycle,
        "single_position_admission": admission,
        "funding_source": "HISTORICAL_ACTUAL_PLUS_PREREGISTERED_STRESS",
        "source_t10_snapshot_id": T10_SNAPSHOT_ID,
        "contract_price_source_audit_hash": source_audit_hash,
        "lifecycle_tracks": [
            "PURE_TRADES_COMPARATOR",
            "CONTRACT_PRICE_OHLC_PRIMARY",
        ],
        "row_count": len(lifecycle) * len(FundingTrack) * 2,
        "historical_execution_claim": False,
        "stage3_locked": True,
    }


def _admission_from_compact(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        instrument_rows = sorted(
            (row for row in rows if row["instrument"] == instrument),
            key=lambda row: (int(row["entry_ts_ns"]), str(row["market_episode_id"])),
        )
        for policy_field in ("immediate_exit", "continue_holding"):
            occupied_until_ns: int | None = None
            right_censored = False
            for row in instrument_rows:
                entry_ts_ns = int(row["entry_ts_ns"])
                policy = cast(dict[str, Any], row[policy_field])
                admitted = not (
                    right_censored
                    or (occupied_until_ns is not None and entry_ts_ns < occupied_until_ns)
                )
                if admitted:
                    if policy["terminal_state"] == "RIGHT_CENSORED":
                        occupied_until_ns = entry_ts_ns + 7 * DAY_NS
                        right_censored = True
                    elif policy["decision_ts_ns"] is None:
                        raise ValueError("flat lifecycle result lacks a decision timestamp")
                    else:
                        occupied_until_ns = int(policy["decision_ts_ns"])
                decisions.append(
                    {
                        "market_episode_id": row["market_episode_id"],
                        "policy_id": policy["policy_id"],
                        "entry_ts_ns": entry_ts_ns,
                        "admitted": admitted,
                        "reason": ("ADMITTED" if admitted else "SKIPPED_SINGLE_POSITION_OCCUPIED"),
                        "occupied_until_ns": occupied_until_ns,
                    }
                )
    return decisions


def produce_scoped_lifecycle_v110(
    *,
    start_date: date,
    end_date_exclusive: date,
    source_audit_hash: str,
    source_audit: LifecycleSourceAudit,
    resume_root: Path,
    resume_state: dict[str, Any] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute T11 in deterministic 64-day-partition resumable batches."""

    if source_audit.status != "PASS" or source_audit.audit_hash != source_audit_hash:
        raise ValueError("dual-track lifecycle source-audit binding drift")
    rows = _selected_t10_rows(
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
    )
    reader = FixedT10Reader(T10_SNAPSHOT, expected_snapshot_id=T10_SNAPSHOT_ID)
    acceptance = _read_json(FUNDING_ACCEPTANCE)
    funding_index = _FundingIndex.from_acceptance(acceptance)
    groups: list[tuple[str, str, list[dict[str, Any]]]] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        by_day: dict[str, list[dict[str, Any]]] = {}
        for row in rows[instrument]:
            day = _date_from_ns(int(row["window_start_ns"])).isoformat()
            by_day.setdefault(day, []).append(row)
        groups.extend((instrument, day, by_day[day]) for day in sorted(by_day))
    batches = [groups[offset : offset + 64] for offset in range(0, len(groups), 64)]
    expected_completed = (
        cast(dict[str, str], resume_state.get("completed_partition_hashes", {}))
        if resume_state is not None
        else {}
    )
    lifecycle: list[dict[str, Any]] = []
    compact_results: list[dict[str, Any]] = []
    completed_hashes: dict[str, str] = {}
    total_units = sum(len(rows[instrument]) for instrument in ("BTCUSDT", "ETHUSDT"))
    completed_units = 0
    started_at = time.monotonic()
    resume_root.mkdir(parents=True, exist_ok=True)
    for batch_number, batch in enumerate(batches, start=1):
        batch_id = f"batch-{batch_number:04d}"
        batch_path = resume_root / f"{batch_id}.json"
        batch_payload: dict[str, Any] | None = None
        if batch_path.is_file():
            candidate = cast(
                dict[str, Any],
                json.loads(batch_path.read_text(encoding="utf-8")),
            )
            claimed = str(candidate.get("batch_hash", ""))
            calculated = hashlib.sha256(
                strict_json_bytes(
                    {key: value for key, value in candidate.items() if key != "batch_hash"}
                )
            ).hexdigest()
            if claimed != calculated:
                raise ValueError("T11 resume batch Hash drift")
            if batch_id in expected_completed and expected_completed[batch_id] != claimed:
                raise ValueError("T11 checkpoint-to-batch Hash drift")
            batch_payload = candidate
        if batch_payload is None:
            batch_lifecycle: list[dict[str, Any]] = []
            batch_compact: list[dict[str, Any]] = []
            for instrument, _, day_rows in batch:
                for row in day_rows:
                    probe, results = _lifecycle_probe_v18(
                        reader=reader,
                        row=row,
                        acceptance=acceptance,
                        source_audit_hash=source_audit_hash,
                        funding_index=funding_index,
                    )
                    batch_lifecycle.append(probe)
                    primary = next(
                        result
                        for result in results
                        if result.funding_track is FundingTrack.PRIMARY_HISTORICAL_ACTUAL
                    )
                    batch_compact.append(
                        cast(
                            dict[str, Any],
                            strict_json_value(
                                {
                                    "instrument": instrument,
                                    "market_episode_id": primary.market_episode_id,
                                    "entry_ts_ns": int(row["window_start_ns"]),
                                    "immediate_exit": primary.immediate_exit,
                                    "continue_holding": primary.continue_holding,
                                }
                            ),
                        )
                    )
            batch_payload = {
                "schema_name": "s2p110-t11-resume-batch-v1",
                "schema_version": "1.0",
                "batch_id": batch_id,
                "deterministic_merge_order": "INSTRUMENT_DATE_EPISODE_ID",
                "lifecycle": batch_lifecycle,
                "compact_primary_results": batch_compact,
            }
            batch_payload["batch_hash"] = hashlib.sha256(
                strict_json_bytes(batch_payload)
            ).hexdigest()
            with batch_path.open("xb") as handle:
                handle.write(strict_json_bytes(batch_payload))
                handle.flush()
                os.fsync(handle.fileno())
        batch_hash = str(batch_payload["batch_hash"])
        completed_hashes[batch_id] = batch_hash
        batch_lifecycle_rows = cast(list[dict[str, Any]], batch_payload["lifecycle"])
        batch_compact_rows = cast(list[dict[str, Any]], batch_payload["compact_primary_results"])
        lifecycle.extend(batch_lifecycle_rows)
        compact_results.extend(batch_compact_rows)
        completed_units += len(batch_compact_rows)
        if progress_callback is not None:
            elapsed = max(time.monotonic() - started_at, 1e-9)
            throughput = completed_units / elapsed
            remaining = total_units - completed_units
            progress_callback(
                {
                    "completed_units": completed_units,
                    "total_units": total_units,
                    "percentage": format(
                        Decimal(completed_units) * Decimal(100) / Decimal(total_units),
                        "f",
                    ),
                    "elapsed_seconds": format(Decimal(str(elapsed)), "f"),
                    "throughput_units_per_second": format(Decimal(str(throughput)), "f"),
                    "eta_seconds": (
                        format(Decimal(str(remaining / throughput)), "f") if throughput else None
                    ),
                    "row_count": completed_units * len(FundingTrack) * 2,
                    "phase": "LIFECYCLE",
                    "subphase": "DUAL_TRACK_EPISODE_BATCH",
                    "processed_units": completed_units,
                    "remaining_units": remaining,
                    "resume_cursor": batch_id,
                    "completed_partition_ids": list(completed_hashes),
                    "completed_partition_hashes": dict(completed_hashes),
                    "producer_state_hash": canonical_hash(completed_hashes),
                    "deterministic_merge_order": "INSTRUMENT_DATE_EPISODE_ID",
                    "verify_state": "PENDING",
                    "rss_bytes": process_current_rss_bytes(),
                }
            )
    if set(expected_completed) - set(completed_hashes):
        raise ValueError("T11 checkpoint references an unknown resume batch")
    return {
        "task_id": "S2P110-T11",
        "lifecycle": lifecycle,
        "single_position_admission": _admission_from_compact(compact_results),
        "funding_source": "HISTORICAL_ACTUAL_PLUS_PREREGISTERED_STRESS",
        "source_t10_snapshot_id": T10_SNAPSHOT_ID,
        "contract_price_source_audit_hash": source_audit_hash,
        "lifecycle_tracks": [
            "PURE_TRADES_COMPARATOR",
            "CONTRACT_PRICE_OHLC_PRIMARY",
        ],
        "resume_batch_count": len(batches),
        "resume_state_hash": canonical_hash(completed_hashes),
        "row_count": len(lifecycle) * len(FundingTrack) * 2,
        "execution_mode": "EXECUTED_NEW",
        "historical_execution_claim": False,
        "stage3_locked": True,
    }


def _declared_gap_t16_probes(source_first_passage_root: Path) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        rows = pq.read_table(
            source_first_passage_root / instrument / "first_passage.parquet"
        ).to_pylist()
        primary = [
            row
            for row in rows
            if row["evidence_level"] == "H2"
            and row["parameter_set_id"] == PRIMARY_PARAMETER_SET
            and row["timing_id"] == PRIMARY_TIMING
            and bool(row["primary_eligible"])
            and row["variant_id"] == "V1_PRICE"
        ]
        complete = [row for row in primary if row["source_quality_status"] == "COMPLETE"]
        gap_rows = [
            row
            for row in primary
            if row["source_quality_status"] == "WITH_GAPS" and row["source_gap_codes"]
        ]
        if complete or not gap_rows:
            raise ValueError(
                f"supplement coverage must exercise only declared-gap exclusion: {instrument}"
            )
        probes.append(
            {
                "instrument": instrument,
                "match_level": "EXCLUDED_SOURCE_GAP",
                "eligible_episode_count": 0,
                "excluded_episode_count": len({str(row["market_episode_id"]) for row in gap_rows}),
                "selected_control_ids": [],
                "outcome_fields_read_before_matching": [],
                "historical_evidence_only": True,
            }
        )
    return probes


def produce_scoped_conditional_baseline(
    *,
    source_first_passage_root: Path,
    coverage_mode: str = "MATCH_COMPLETE",
) -> dict[str, Any]:
    """Run the outcome-blind T16 rehearsal consumer on the current T14 handoff."""

    if coverage_mode == "MATCH_COMPLETE":
        reader = FixedT10Reader(T10_SNAPSHOT, expected_snapshot_id=T10_SNAPSHOT_ID)
        rows = _selected_first_passage_rows(source_first_passage_root)
        probes = [_t16_probe(reader=reader, row=rows[item]) for item in ("BTCUSDT", "ETHUSDT")]
    elif coverage_mode == "EXCLUDE_DECLARED_GAP":
        probes = _declared_gap_t16_probes(source_first_passage_root)
    else:
        raise ValueError("unsupported T16 rehearsal coverage mode")
    return {
        "task_id": "S2P13-T16",
        "probes": probes,
        "row_count": len(probes),
        "formal_binning_snapshot_created": False,
        "binning_semantics": "REHEARSAL_ONLY_NOT_FORMAL_BINS",
        "coverage_mode": coverage_mode,
    }


def _governance_binding() -> dict[str, str]:
    relative = (
        "docs/spec/system_manual_v1.3.5_final.md",
        "docs/development/plans/stage_2_plan_v1.3.md",
        "docs/development/tasks/stage_2/S2P13-T11-lifecycle.md",
        "docs/development/changes/CR-2026-035.md",
        "docs/development/changes/CR-2026-038.md",
        "docs/development/changes/CR-2026-040.md",
    )
    return {name: _file_hash(REPOSITORY_ROOT / name) for name in relative}


def _rehearsal_receipt_schema(purpose: str) -> str:
    return {
        "TRADE_SUPPLEMENT_COVERAGE": "stage2-trade-supplement-rehearsal-v1",
        "SEALED_RECEIPT_COVERAGE": "stage2-sealed-receipt-rehearsal-v1",
        "ARCHIVE_LAYOUT_BOUNDARY_COVERAGE": "stage2-archive-layout-boundary-rehearsal-v1",
    }[purpose]


def _handoff(
    task_id: str,
    evidence_id: str,
    payload: object,
    row_count: int,
    *,
    root: Path,
    execution_scope_hash: str,
    upstream_handoffs: dict[str, dict[str, Any]] | None = None,
) -> TaskHandoff:
    task_root = root / "task-handoffs" / task_id
    task_root.mkdir(parents=True, exist_ok=True)
    output_hash = _canonical_hash(payload)
    manifest = {
        "schema_name": "stage2-plan-v13-rehearsal-task-manifest-v2",
        "stage_plan_version": "1.3",
        "task_id": task_id,
        "execution_mode": "REHEARSAL",
        "evidence_id": evidence_id,
        "output_hash": output_hash,
        "row_count": row_count,
        "execution_scope_hash": execution_scope_hash,
        "upstream_handoffs": upstream_handoffs or {},
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    manifest_path = task_root / "manifest.json"
    _write_exclusive(manifest_path, manifest)
    catalog = {
        "schema_name": "stage2-plan-v13-rehearsal-task-catalog-v2",
        "stage_plan_version": "1.3",
        "task_id": task_id,
        "manifest_hash": manifest["manifest_hash"],
        "files": [
            {
                "relative_path": str(path.relative_to(task_root)),
                "sha256": _file_hash(path),
                "byte_size": path.stat().st_size,
            }
            for path in iter_evidence_files(task_root)
            if path.name not in {"manifest.json", "catalog.json"}
        ],
    }
    catalog["catalog_hash"] = _canonical_hash(catalog)
    catalog_path = task_root / "catalog.json"
    _write_exclusive(catalog_path, catalog)
    producer_receipt_hash = _canonical_hash(
        {
            "manifest_hash": manifest["manifest_hash"],
            "catalog_hash": catalog["catalog_hash"],
            "output_hash": output_hash,
        }
    )
    return TaskHandoff(
        task_id=task_id,
        execution_mode="REHEARSAL",
        chain_id=evidence_id,
        run_id=None,
        evidence_id=evidence_id,
        artifact_root=str(task_root),
        snapshot_id=f"{task_id.lower()}-{output_hash}",
        manifest_path=str(manifest_path),
        manifest_hash=str(manifest["manifest_hash"]),
        catalog_path=str(catalog_path),
        catalog_hash=str(catalog["catalog_hash"]),
        output_hash=output_hash,
        row_count=row_count,
        execution_scope_hash=execution_scope_hash,
        producer_receipt_hash=producer_receipt_hash,
        consumer_readback="PASS",
        reconciliation="PASS",
        verify_status="PASS",
    )


def _run_final_code_rehearsal(
    *,
    output_root: Path,
    start_date: date = START_DATE,
    purpose: str = "FINAL_CODE_RELEASE_GATE",
    progress: _RehearsalProgress,
) -> tuple[dict[str, Any], Path]:
    """Run the isolated real-input rehearsal and leave UI finalization pending."""

    if purpose not in {
        "FINAL_CODE_RELEASE_GATE",
        "TRADE_SUPPLEMENT_COVERAGE",
        "SEALED_RECEIPT_COVERAGE",
        "ARCHIVE_LAYOUT_BOUNDARY_COVERAGE",
    }:
        raise ValueError("unsupported seven-day rehearsal purpose")
    if purpose == "FINAL_CODE_RELEASE_GATE" and start_date != START_DATE:
        raise ValueError("release-gate seven-day scope drift")
    if purpose == "SEALED_RECEIPT_COVERAGE" and start_date != date(2022, 4, 12):
        raise ValueError("sealed receipt seven-day scope drift")
    if purpose == "ARCHIVE_LAYOUT_BOUNDARY_COVERAGE" and start_date != date(2026, 6, 27):
        raise ValueError("archive-layout boundary seven-day scope drift")
    end_date_exclusive = start_date + timedelta(days=7)
    if not _git_clean():
        raise ValueError("final-code rehearsal requires a clean committed repository")
    root = _safe_new_root(output_root)
    commit = current_commit(REPOSITORY_ROOT)
    funding_verify = verify_funding_acceptance(FUNDING_ACCEPTANCE.parent)
    if funding_verify.get("status") != "PASS":
        raise ValueError("accepted funding Verify is not PASS")
    with tempfile.TemporaryDirectory(prefix="s2p13-final-code-7d-", dir="/private/tmp") as temp:
        temporary_audit_root = Path(temp) / "source-audit"
        source_audit, source_report_path = run_seven_day_audit(
            output_root=temporary_audit_root,
            start_date=start_date,
            audit_mode=("SOURCE_BOUNDARY" if purpose == "FINAL_CODE_RELEASE_GATE" else purpose),
        )
        verify_seven_day_audit(report_path=source_report_path)
        durable_audit_root = root / "source-audit"
        shutil.copytree(temporary_audit_root, durable_audit_root)
    source_report_path = durable_audit_root / "seven-day-audit-report.json"
    source_verify = verify_seven_day_audit(report_path=source_report_path)
    if (
        source_audit["feature_availability"]["status"] != "PASS"
        or source_audit["raw_path_non_pollution"]["status"] != "PASS"
        or source_verify["status"] != "PASS"
    ):
        raise ValueError("real seven-day source audit did not pass executable scopes")
    progress.start_task("S2P13-T11", reason_code="LIFECYCLE")
    lifecycle_payload = produce_scoped_lifecycle(
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
        progress_callback=lambda update: progress.update_task("S2P13-T11", **update),
    )
    lifecycle = cast(list[dict[str, Any]], lifecycle_payload["lifecycle"])
    evidence_id = f"rehearsal-7d-{commit[:12]}"
    execution_scope_hash = ExecutionScope.seal(
        mode="SEVEN_DAY",
        start_date=start_date.isoformat(),
        end_date_exclusive=end_date_exclusive.isoformat(),
    ).execution_scope_hash
    handoffs: list[TaskHandoff] = []
    t11_payload = lifecycle_payload
    handoffs.append(
        _handoff(
            "S2P13-T11",
            evidence_id,
            t11_payload,
            int(lifecycle_payload["row_count"]),
            root=root,
            execution_scope_hash=execution_scope_hash,
        )
    )
    progress.pass_task("S2P13-T11", row_count=int(lifecycle_payload["row_count"]))
    progress.start_task("S2P13-T12")
    t12_data = root / "task-handoffs/S2P13-T12/data"
    t12 = produce_scoped_paths(
        output_root=t12_data,
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
    )
    handoffs.append(
        _handoff(
            "S2P13-T12",
            evidence_id,
            t12,
            int(t12["row_count"]),
            root=root,
            execution_scope_hash=execution_scope_hash,
            upstream_handoffs={"S2P13-T11": handoffs[0].payload()},
        )
    )
    progress.pass_task("S2P13-T12", row_count=int(t12["row_count"]))
    progress.start_task("S2P13-T13")
    t13_data = root / "task-handoffs/S2P13-T13/data"
    t13 = produce_scoped_metrics(
        output_root=t13_data,
        source_paths_root=t12_data,
        source_snapshot_id=handoffs[1].snapshot_id,
        source_manifest_hash=handoffs[1].manifest_hash,
        source_catalog_hash=handoffs[1].catalog_hash,
    )
    handoffs.append(
        _handoff(
            "S2P13-T13",
            evidence_id,
            t13,
            int(t13["row_count"]),
            root=root,
            execution_scope_hash=execution_scope_hash,
            upstream_handoffs={"S2P13-T12": handoffs[1].payload()},
        )
    )
    progress.pass_task("S2P13-T13", row_count=int(t13["row_count"]))
    progress.start_task("S2P13-T14")
    t14_data = root / "task-handoffs/S2P13-T14/data"
    t14 = produce_scoped_first_passage(
        output_root=t14_data,
        source_paths_root=t12_data,
        source_snapshot_id=handoffs[1].snapshot_id,
        source_manifest_hash=handoffs[1].manifest_hash,
        source_catalog_hash=handoffs[1].catalog_hash,
    )
    handoffs.append(
        _handoff(
            "S2P13-T14",
            evidence_id,
            t14,
            int(t14["row_count"]),
            root=root,
            execution_scope_hash=execution_scope_hash,
            upstream_handoffs={"S2P13-T12": handoffs[1].payload()},
        )
    )
    progress.pass_task("S2P13-T14", row_count=int(t14["row_count"]))
    progress.start_task("S2P13-T15")
    t15_data = root / "task-handoffs/S2P13-T15/data"
    t15 = produce_scoped_ambiguity(
        output_root=t15_data,
        source_first_passage_root=t14_data,
    )
    handoffs.append(
        _handoff(
            "S2P13-T15",
            evidence_id,
            t15,
            int(t15["row_count"]),
            root=root,
            execution_scope_hash=execution_scope_hash,
            upstream_handoffs={"S2P13-T14": handoffs[3].payload()},
        )
    )
    progress.pass_task("S2P13-T15", row_count=int(t15["row_count"]))
    progress.start_task("S2P13-T16")
    t16_payload = produce_scoped_conditional_baseline(
        source_first_passage_root=t14_data,
        coverage_mode=(
            "MATCH_COMPLETE" if purpose == "FINAL_CODE_RELEASE_GATE" else "EXCLUDE_DECLARED_GAP"
        ),
    )
    t16 = cast(list[dict[str, Any]], t16_payload["probes"])
    handoffs.append(
        _handoff(
            "S2P13-T16",
            evidence_id,
            t16_payload,
            int(t16_payload["row_count"]),
            root=root,
            execution_scope_hash=execution_scope_hash,
            upstream_handoffs={
                task: handoffs[index].payload()
                for task, index in (
                    ("S2P13-T11", 0),
                    ("S2P13-T13", 2),
                    ("S2P13-T15", 4),
                )
            },
        )
    )
    progress.pass_task("S2P13-T16", row_count=int(t16_payload["row_count"]))
    report: dict[str, Any] = {
        "schema_name": "stage2-plan-v13-seven-day-rehearsal-report-v1",
        "status": "PASS",
        "purpose": purpose,
        "start_date": start_date.isoformat(),
        "end_date_exclusive": end_date_exclusive.isoformat(),
        "day_count": 7,
        "code_commit": commit,
        "governance_binding": _governance_binding(),
        "preregistration_first": True,
        "preregistration_binding_hash": _canonical_hash(_governance_binding()),
        "source_audit_report_hash": source_audit["report_hash"],
        "funding_acceptance_hash": funding_verify["acceptance_hash"],
        "lifecycle": lifecycle,
        "conditional_baseline_probe": t16,
        "handoffs": [item.payload() for item in handoffs],
        "producer_serialization": "PASS",
        "strict_consumer_readback": "PASS",
        "reconciliation": "PASS",
        "verify": "PASS",
        "ui_projection": "PENDING_EXTERNAL_BROWSER_CHECK",
        "authority_created": False,
        "formal_binning_snapshot_created": False,
        "formal_run_id_created": False,
        "published": False,
        "later_tasks_executed": False,
        "stage3_locked": True,
        "research_result": "NOT_PRODUCED_REHEARSAL_ONLY",
        "simulated_acceptance_criteria": {
            "all_six_tasks_use_successor_core": True,
            "t12_reads_t10_and_only_binds_t11_gate": True,
            "t13_t14_share_t12_but_are_independent": True,
            "declared_gap_is_right_censored_not_win_loss": True,
            "all_handoffs_strict_readback": True,
            "all_counts_reconcile": True,
            "ui_must_observe_exact_commit": True,
            "formal_authority_bins_run_created": False,
            "stage3_locked": True,
        },
    }
    report["report_hash"] = _canonical_hash(report)
    report_path = root / "seven-day-rehearsal-report.json"
    _write_exclusive(report_path, report)
    pending = {
        "schema_name": REHEARSAL_SCHEMA,
        "status": "PENDING_UI_CHECK",
        "tasks": list(TASKS),
        "code_commit": commit,
        "day_count": 7,
        "report_path": str(report_path),
        "report_hash": report["report_hash"],
        "producer_serialization": "PASS",
        "strict_consumer_readback": "PASS",
        "reconciliation": "PASS",
        "verify": "PASS",
        "ui_projection": "PENDING",
        "authority_created": False,
        "formal_binning_snapshot_created": False,
        "formal_run_id_created": False,
    }
    pending["receipt_hash"] = _canonical_hash(pending)
    if purpose == "FINAL_CODE_RELEASE_GATE":
        pending_path = OPERATIONS_ROOT / f"seven-day-rehearsal-receipt.{commit}.pending.json"
        _write_exclusive(pending_path, pending)
    else:
        supplement_receipt = {
            **pending,
            "schema_name": _rehearsal_receipt_schema(purpose),
            "status": "PASS",
            "ui_projection": "NOT_REQUIRED_READ_ONLY_PROJECTION",
            "purpose": purpose,
            "start_date": start_date.isoformat(),
            "end_date_exclusive": end_date_exclusive.isoformat(),
            "trade_supplement_acceptance_hash": os.environ.get(
                "ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_HASH"
            ),
        }
        supplement_receipt.pop("receipt_hash", None)
        supplement_receipt["receipt_hash"] = _canonical_hash(supplement_receipt)
        receipt_prefix = {
            "TRADE_SUPPLEMENT_COVERAGE": "trade-supplement",
            "SEALED_RECEIPT_COVERAGE": "sealed-receipt",
            "ARCHIVE_LAYOUT_BOUNDARY_COVERAGE": "archive-boundary",
        }[purpose]
        _write_exclusive(
            OPERATIONS_ROOT / f"{receipt_prefix}-rehearsal-receipt.{commit}.json",
            supplement_receipt,
        )
    progress.verifying()
    verify_final_code_rehearsal(report_path)
    progress.pending_ui()
    return report, report_path


def run_final_code_rehearsal(
    *,
    output_root: Path,
    start_date: date = START_DATE,
    purpose: str = "FINAL_CODE_RELEASE_GATE",
) -> tuple[dict[str, Any], Path]:
    """Run the isolated rehearsal while publishing a live, hash-bound checkpoint."""

    allowed_purposes = {
        "FINAL_CODE_RELEASE_GATE",
        "TRADE_SUPPLEMENT_COVERAGE",
        "SEALED_RECEIPT_COVERAGE",
        "ARCHIVE_LAYOUT_BOUNDARY_COVERAGE",
    }
    if purpose not in allowed_purposes:
        raise ValueError("unsupported seven-day rehearsal purpose")
    if purpose == "FINAL_CODE_RELEASE_GATE" and start_date != START_DATE:
        raise ValueError("release-gate seven-day scope drift")
    if purpose == "SEALED_RECEIPT_COVERAGE" and start_date != date(2022, 4, 12):
        raise ValueError("sealed receipt seven-day scope drift")
    if purpose == "ARCHIVE_LAYOUT_BOUNDARY_COVERAGE" and start_date != date(2026, 6, 27):
        raise ValueError("archive-layout boundary seven-day scope drift")
    progress = _RehearsalProgress(
        code_commit=current_commit(REPOSITORY_ROOT),
        output_root=output_root,
        start_date=start_date,
        end_date_exclusive=start_date + timedelta(days=7),
        purpose=purpose,
    )
    try:
        return _run_final_code_rehearsal(
            output_root=output_root,
            start_date=start_date,
            purpose=purpose,
            progress=progress,
        )
    except Exception as exc:
        progress.failed(exc)
        raise


def finalize_ui_projection(
    *, report_path: Path, observed_repo_commit: str, observed_gate: str
) -> Path:
    """Append the browser-observed UI result and create the final gate receipt."""

    report = verify_final_code_rehearsal(report_path)
    if observed_repo_commit != report["code_commit"] or observed_gate != "PENDING":
        raise ValueError("browser UI did not show the pending rehearsal for this exact commit")
    final_report = {
        **report,
        "ui_projection": "PASS",
        "ui_observation": {
            "repo_commit": observed_repo_commit,
            "gate_before_finalization": observed_gate,
        },
    }
    final_report.pop("report_hash", None)
    final_report["report_hash"] = _canonical_hash(final_report)
    final_report_path = report_path.parent / "seven-day-rehearsal-report-ui-verified.json"
    _write_exclusive(final_report_path, final_report)
    receipt: dict[str, Any] = {
        "schema_name": REHEARSAL_SCHEMA,
        "status": "PASS",
        "tasks": list(TASKS),
        "code_commit": report["code_commit"],
        "day_count": 7,
        "report_path": str(final_report_path),
        "report_hash": final_report["report_hash"],
        "producer_serialization": "PASS",
        "strict_consumer_readback": "PASS",
        "reconciliation": "PASS",
        "verify": "PASS",
        "ui_projection": "PASS",
        "authority_created": False,
        "formal_binning_snapshot_created": False,
        "formal_run_id_created": False,
    }
    receipt["receipt_hash"] = _canonical_hash(receipt)
    final_path = OPERATIONS_ROOT / (f"seven-day-rehearsal-receipt.{report['code_commit']}.json")
    _write_exclusive(final_path, receipt)
    return final_path


def verify_final_code_rehearsal(report_path: Path) -> dict[str, Any]:
    """Strictly read back all task handoffs and the no-formal-run boundary."""

    report = _read_json(report_path)
    if report.get("report_hash") != _canonical_hash(
        {key: value for key, value in report.items() if key != "report_hash"}
    ):
        raise ValueError("seven-day rehearsal report hash mismatch")
    if (
        report.get("status") != "PASS"
        or report.get("day_count") != 7
        or tuple(item["task_id"] for item in report.get("handoffs", ())) != TASKS
        or any(
            item.get("consumer_readback") != "PASS"
            or item.get("reconciliation") != "PASS"
            or item.get("verify_status") != "PASS"
            for item in report.get("handoffs", ())
        )
        or report.get("authority_created") is not False
        or report.get("formal_binning_snapshot_created") is not False
        or report.get("formal_run_id_created") is not False
        or report.get("later_tasks_executed") is not False
        or report.get("stage3_locked") is not True
        or report.get("simulated_acceptance_criteria")
        != {
            "all_six_tasks_use_successor_core": True,
            "t12_reads_t10_and_only_binds_t11_gate": True,
            "t13_t14_share_t12_but_are_independent": True,
            "declared_gap_is_right_censored_not_win_loss": True,
            "all_handoffs_strict_readback": True,
            "all_counts_reconcile": True,
            "ui_must_observe_exact_commit": True,
            "formal_authority_bins_run_created": False,
            "stage3_locked": True,
        }
    ):
        raise ValueError("seven-day rehearsal report reconciliation failed")
    counts = Counter(item["task_id"] for item in report["handoffs"])
    if counts != Counter(TASKS):
        raise ValueError("seven-day rehearsal task handoff universe mismatch")
    for raw_handoff in cast(list[dict[str, Any]], report["handoffs"]):
        handoff = UpstreamArtifact.from_payload(
            str(raw_handoff["task_id"]),
            raw_handoff,
        )
        manifest = _read_json(handoff.manifest_path)
        catalog = _read_json(handoff.catalog_path)
        if (
            manifest.get("output_hash") != handoff.output_hash
            or int(manifest.get("row_count", -1)) != handoff.row_count
        ):
            raise ValueError("rehearsal Manifest output reconciliation drift")
        for item in cast(list[dict[str, Any]], catalog.get("files", [])):
            path = handoff.artifact_root / str(item["relative_path"])
            if (
                path.is_symlink()
                or not path.is_file()
                or _file_hash(path) != item.get("sha256")
                or path.stat().st_size != int(item.get("byte_size", -1))
            ):
                raise ValueError("rehearsal Catalog file read-back drift")
    return report
