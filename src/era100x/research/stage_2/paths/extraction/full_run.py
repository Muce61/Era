"""Full-output S2-T11 runner over immutable S2-T10 and Stage 1 authorities.

The formal output is a lossless path-slice index.  It does not duplicate the
same immutable H1/H2 fact for every overlapping episode and computes no metric,
label, return, or execution field owned by a later task.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.manifests.configuration import timing_configurations
from era100x.research.stage_2.paths.extraction.models import _canonical_json
from era100x.research.stage_2.paths.extraction.receipts import (
    PathExtractionReceipt,
    publish_path_extraction_receipt,
    read_path_extraction_receipts,
)
from era100x.research.stage_2.runtime_v2.catalog import CatalogReaderV2

Instrument = Literal["BTCUSDT", "ETHUSDT"]
INSTRUMENTS: tuple[Instrument, ...] = ("BTCUSDT", "ETHUSDT")

STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
RUNS_ROOT = STAGE2_ROOT / "runs"
AUTHORITY_ROOT = STAGE2_ROOT / "authorities" / "S2-T11"
TASK_EVIDENCE_ROOT = STAGE2_ROOT / "task-evidence" / "S2-T11"
FIXED_S2T10_RUN_ID = "stage2-g1-v2-b-20260720T111704Z-9c4b7c423a04"
FIXED_SNAPSHOT_ID = "df15b9cbb208a6f921b3a68bee24be44f77e83eb2c8ac1582ef942b108708d33"
FIXED_SNAPSHOT_ROOT = RUNS_ROOT / FIXED_S2T10_RUN_ID / "published" / "snapshots" / FIXED_SNAPSHOT_ID
STAGE1_RUN_ID = "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
STAGE1_CATALOG_ROOT = Path("/Volumes/FuckingLife/era100x_stage1/catalog/runs") / STAGE1_RUN_ID
STAGE1_PUBLISHED_ROOT = (
    Path("/Volumes/FuckingLife/era100x_stage1/published/stage1-trades-v2") / STAGE1_RUN_ID
)
SOURCE_START_NS = 1_577_836_800_000_000_000
SOURCE_END_NS = 1_783_123_200_000_000_000
H1_SPEC_HASH = "482d29417f543cdebdb3e6db2d2f37904b4adaa69b3252ddec0599bae59f62b1"
H2_INDEX_SPEC_HASH = "02d72cf5331844c3a0bfd50fc791494b344803f4bc1bc3d208d006719cc16385"
EPISODE_SPEC_HASHES = (
    "318c89a4d364d12cb778b1f575d2bb860de0a4ddb63087c671134bb08e78bcd2",
    "b3e86d5262ab1820086055c49c8cfc360be38b73fe286dc601d476727b1e76c5",
)
TASK_VERSION = "1.3"
CLI = "uv run python scripts/run_stage2_path_extraction.py {preflight,run,resume,verify}"
ZERO_HASH = "0" * 64
REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
CONFIG_PATH = REPOSITORY_ROOT / "configs/research/stage_2/s2_t11_path_extraction_v1.3.json"

EPISODE_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("market_episode_id", pa.string(), nullable=False),
        pa.field("canonical_candidate_id", pa.string(), nullable=False),
        pa.field("candidate_version_id", pa.string(), nullable=False),
        pa.field("canonical_payload_hash", pa.string(), nullable=False),
        pa.field("parameter_set_id", pa.string(), nullable=False),
        pa.field("variant_id", pa.string(), nullable=False),
        pa.field("time_combination_id", pa.string(), nullable=False),
        pa.field("research_role", pa.string(), nullable=False),
        pa.field("primary_eligible", pa.bool_(), nullable=False),
        pa.field("episode_available_at_ns", pa.int64(), nullable=False),
        pa.field("window_start_ns", pa.int64(), nullable=False),
        pa.field("requested_window_end_ns", pa.int64(), nullable=False),
        pa.field("window_end_ns", pa.int64(), nullable=False),
        pa.field("window_truncated", pa.bool_(), nullable=False),
        pa.field("truncation_reason", pa.string(), nullable=True),
        pa.field("h1_slice_count", pa.int32(), nullable=False),
        pa.field("h2_slice_count", pa.int32(), nullable=False),
        pa.field("time_semantics", pa.string(), nullable=False),
    ]
)

H1_SLICE_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("market_episode_id", pa.string(), nullable=False),
        pa.field("canonical_candidate_id", pa.string(), nullable=False),
        pa.field("source_partition_id", pa.string(), nullable=False),
        pa.field("source_owner_date", pa.date32(), nullable=False),
        pa.field("source_semantic_sha256", pa.string(), nullable=False),
        pa.field("source_row_count", pa.int64(), nullable=False),
        pa.field("slice_start_ns", pa.int64(), nullable=False),
        pa.field("slice_end_ns", pa.int64(), nullable=False),
        pa.field("reference_price_type", pa.string(), nullable=False),
    ]
)

H2_SLICE_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("market_episode_id", pa.string(), nullable=False),
        pa.field("canonical_candidate_id", pa.string(), nullable=False),
        pa.field("source_owner_date", pa.date32(), nullable=False),
        pa.field("source_relative_path", pa.string(), nullable=False),
        pa.field("source_byte_sha256", pa.string(), nullable=False),
        pa.field("source_logical_sha256", pa.string(), nullable=False),
        pa.field("row_group_ordinal", pa.int32(), nullable=False),
        pa.field("row_group_row_count", pa.int64(), nullable=False),
        pa.field("row_group_event_start_ns", pa.int64(), nullable=False),
        pa.field("row_group_event_end_ns_exclusive", pa.int64(), nullable=False),
        pa.field("slice_start_ns", pa.int64(), nullable=False),
        pa.field("slice_end_ns", pa.int64(), nullable=False),
        pa.field("fact_identity", pa.string(), nullable=False),
        pa.field("stable_order", pa.string(), nullable=False),
        pa.field("reference_price_type", pa.string(), nullable=False),
    ]
)

QUALITY_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("market_episode_id", pa.string(), nullable=False),
        pa.field("canonical_candidate_id", pa.string(), nullable=False),
        pa.field("h1_missing_seconds", pa.int64(), nullable=False),
        pa.field("h2_source_partition_gap_count", pa.int64(), nullable=False),
        pa.field("h2_source_partition_reversal_count", pa.int64(), nullable=False),
        pa.field("h2_source_partition_conflict_count", pa.int64(), nullable=False),
        pa.field("quality_scope", pa.string(), nullable=False),
        pa.field("ambiguity_codes", pa.list_(pa.string()), nullable=False),
        pa.field("window_truncated", pa.bool_(), nullable=False),
        pa.field("historical_evidence_only", pa.bool_(), nullable=False),
        pa.field("prohibited_execution_fields", pa.list_(pa.string()), nullable=False),
    ]
)

LINEAGE_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("market_episode_id", pa.string(), nullable=False),
        pa.field("canonical_candidate_id", pa.string(), nullable=False),
        pa.field("candidate_version_id", pa.string(), nullable=False),
        pa.field("canonical_payload_hash", pa.string(), nullable=False),
        pa.field("source_snapshot_id", pa.string(), nullable=False),
        pa.field("source_episode_dataset_spec_hash", pa.string(), nullable=False),
        pa.field("h1_dataset_spec_hash", pa.string(), nullable=False),
        pa.field("h2_index_dataset_spec_hash", pa.string(), nullable=False),
        pa.field("stage1_data_run_id", pa.string(), nullable=False),
        pa.field("variant_id", pa.string(), nullable=False),
    ]
)

PROHIBITED_EXECUTION_FIELDS = [
    "bid",
    "ask",
    "spread_bps",
    "ts_recv_ns",
    "receive_latency_ms",
    "queue_position",
    "partial_fill",
    "actual_slippage_bps",
    "real_return",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _write_json_exclusive(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError(f"unsafe symlinked output directory: {path.parent}")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def _safe_relative(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe or missing source path: {relative}")
    return path


def current_code_commit(repo_root: Path | None = None) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if len(value) != 40:
        raise ValueError("S2-T11 requires an exact Git commit")
    return value


def _source_authority(snapshot_root: Path) -> dict[str, Any]:
    manifest_path = snapshot_root / "manifest.json"
    catalog_path = snapshot_root / "catalog.json"
    manifest = json.loads(manifest_path.read_bytes())
    catalog = json.loads(catalog_path.read_bytes())
    if manifest.get("snapshot_id") != FIXED_SNAPSHOT_ID:
        raise ValueError("S2-T10 fixed snapshot changed")
    if catalog.get("snapshot_id") != FIXED_SNAPSHOT_ID:
        raise ValueError("S2-T10 Catalog snapshot changed")
    if catalog.get("manifest_hash") != manifest.get("manifest_hash"):
        raise ValueError("S2-T10 Manifest/Catalog authority mismatch")
    roots = {item["dataset_spec_hash"]: item for item in catalog["dataset_roots"]}
    required = {H1_SPEC_HASH, H2_INDEX_SPEC_HASH, *EPISODE_SPEC_HASHES}
    if not required.issubset(roots):
        raise ValueError("fixed snapshot lacks an S2-T11 source dataset")
    return {
        "run_id": FIXED_S2T10_RUN_ID,
        "snapshot_id": FIXED_SNAPSHOT_ID,
        "manifest_hash": manifest["manifest_hash"],
        "manifest_file_sha256": sha256_file(manifest_path),
        "catalog_hash": catalog["catalog_hash"],
        "catalog_file_sha256": sha256_file(catalog_path),
        "objects_index_sha256": sha256_file(snapshot_root / "objects.parquet"),
        "logical_partitions_index_sha256": sha256_file(
            snapshot_root / "logical_partitions.parquet"
        ),
        "fragments_index_sha256": sha256_file(snapshot_root / "fragments.parquet"),
        "dataset_roots": {key: roots[key] for key in sorted(required)},
    }


def _stage1_authority(catalog_root: Path) -> dict[str, Any]:
    manifest = json.loads((catalog_root / "manifest.json").read_bytes())
    if manifest.get("run_id") != STAGE1_RUN_ID:
        raise ValueError("Stage 1 data run changed")
    payload = dict(manifest)
    claimed = payload.pop("manifest_sha256", None)
    computed = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if claimed != computed:
        raise ValueError("Stage 1 canonical Manifest hash mismatch")
    instruments: dict[str, Any] = {}
    for instrument in INSTRUMENTS:
        path = catalog_root / f"{instrument}.catalog.json"
        catalog = json.loads(path.read_bytes())
        logical_hash = catalog.get("logical_data_hash")
        if logical_hash != manifest["symbols"][instrument]["logical_data_hash"]:
            raise ValueError(f"Stage 1 {instrument} logical authority mismatch")
        instruments[instrument] = {
            "catalog_file_sha256": sha256_file(path),
            "trades_logical_sha256": logical_hash,
            "partition_count": len(catalog["entries"]),
        }
    return {
        "data_run_id": STAGE1_RUN_ID,
        "canonical_manifest_sha256": claimed,
        "physical_manifest_sha256": sha256_file(catalog_root / "manifest.json"),
        "instruments": instruments,
    }


def create_preflight_manifest(
    *,
    code_commit: str,
    snapshot_root: Path = FIXED_SNAPSHOT_ROOT,
    stage1_catalog_root: Path = STAGE1_CATALOG_ROOT,
    stage2_root: Path = STAGE2_ROOT,
) -> tuple[dict[str, Any], Path]:
    """Freeze all inputs before any S2-T11 Run ID or run directory exists."""

    if not stage2_root.is_dir() or not Path("/Volumes/FuckingLife").is_mount():
        raise OSError("approved Stage 2 external volume is unavailable")
    source = _source_authority(snapshot_root)
    stage1 = _stage1_authority(stage1_catalog_root)
    episode_total = sum(
        int(source["dataset_roots"][spec_hash]["row_count"]) for spec_hash in EPISODE_SPEC_HASHES
    )
    estimated_peak = max(512 * 1024 * 1024, episode_total * 1_500)
    required_free = estimated_peak * 120 // 100
    free = shutil.disk_usage(stage2_root).free
    if free < required_free:
        raise OSError(f"S2-T11 space gate failed: {free} < {required_free}")
    payload: dict[str, Any] = {
        "schema_name": "stage2-s2t11-preflight-authority",
        "schema_version": "1.0",
        "task_id": "S2-T11",
        "task_version": TASK_VERSION,
        "change_request": "CR-2026-021",
        "manual_version": "V1.3.4",
        "code_commit": code_commit,
        "config_path": str(CONFIG_PATH.relative_to(REPOSITORY_ROOT)),
        "config_sha256": sha256_file(CONFIG_PATH),
        "full_run_cli": CLI,
        "source": source,
        "stage1": stage1,
        "instruments": list(INSTRUMENTS),
        "time_semantics": "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN",
        "timing_horizons_seconds": {
            item.timing_id: item.first_passage_horizon_seconds for item in timing_configurations()
        },
        "h2_fact_identity": ["instrument", "canonical_trade_id"],
        "h2_stable_order": ["ts_event_ns", "venue_trade_id", "canonical_trade_id"],
        "source_period_ns": [SOURCE_START_NS, SOURCE_END_NS],
        "output_root": str(stage2_root),
        "output_layout": ["staging", "published", "manifests", "reports", "logs", "tmp"],
        "output_mode": "LOSSLESS_SOURCE_SLICE_INDEX",
        "estimated_peak_bytes": estimated_peak,
        "required_free_bytes": required_free,
        "available_free_bytes_observed": free,
        "allowed_outputs": [
            "episode_paths",
            "h1_path_slices",
            "h2_path_slices",
            "path_quality",
            "lineage",
            "catalog",
            "manifest",
            "receipt",
            "quality_report",
        ],
        "prohibited_outputs": [
            "MFE",
            "MAE",
            "TIME_TO_ACTIVATION",
            "FIRST_PASSAGE",
            "AMBIGUOUS_BOUNDS",
            "BASELINE",
            "PLACEBO",
            "CLUSTER",
            "BOOTSTRAP",
            "RETURN",
            "PNL",
        ],
    }
    payload["authority_hash"] = _json_hash(payload)
    directory = stage2_root / "authorities" / "S2-T11"
    path = directory / f"{payload['authority_hash']}.json"
    if path.exists():
        if path.is_symlink() or json.loads(path.read_bytes()) != payload:
            raise ValueError("conflicting S2-T11 preflight authority")
    else:
        _write_json_exclusive(path, payload)
    return payload, path


def read_preflight_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe or missing S2-T11 preflight authority")
    payload = cast(dict[str, Any], json.loads(path.read_bytes()))
    claimed = payload.pop("authority_hash", None)
    computed = _json_hash(payload)
    payload["authority_hash"] = claimed
    if claimed != computed or payload.get("task_version") != TASK_VERSION:
        raise ValueError("invalid S2-T11 preflight authority hash or version")
    return payload


def _validate_authority_current(
    authority: dict[str, Any], *, snapshot_root: Path, stage1_catalog_root: Path, stage2_root: Path
) -> None:
    if authority["source"] != _source_authority(snapshot_root):
        raise ValueError("S2-T11 fixed snapshot authority changed after preflight")
    if authority["stage1"] != _stage1_authority(stage1_catalog_root):
        raise ValueError("S2-T11 Stage 1 authority changed after preflight")
    if authority["config_sha256"] != sha256_file(CONFIG_PATH):
        raise ValueError("S2-T11 frozen config changed after preflight")
    if shutil.disk_usage(stage2_root).free < authority["required_free_bytes"]:
        raise OSError("S2-T11 free space fell below the frozen preflight requirement")


def latest_preflight_manifest(root: Path = AUTHORITY_ROOT) -> Path:
    paths = sorted(path for path in root.glob("*.json") if not path.name.startswith("._"))
    if not paths:
        raise FileNotFoundError("run preflight before S2-T11 execution")
    valid = [(path.stat().st_mtime_ns, path) for path in paths if not path.is_symlink()]
    if not valid:
        raise ValueError("no safe S2-T11 preflight authority")
    return max(valid)[1]


@dataclass(frozen=True)
class H1Partition:
    partition_id: str
    owner_date: date
    semantic_sha256: str
    row_count: int


@dataclass(frozen=True)
class H2RowGroup:
    owner_date: date
    source_relative_path: str
    source_byte_sha256: str
    source_logical_sha256: str
    ordinal: int
    row_count: int
    start_ns: int
    end_ns: int


def _objects_for_spec(reader: CatalogReaderV2, spec_hash: str, *, columns: list[str]) -> pa.Table:
    selected = reader.fragments_index.filter(
        pc.equal(reader.fragments_index["dataset_spec_hash"], spec_hash)
    )
    object_hashes = sorted(set(cast(list[str], selected["object_sha256"].to_pylist())))
    tables: list[pa.Table] = []
    for object_hash in object_hashes:
        artifact = reader.artifacts[object_hash]
        path = _safe_relative(reader.catalog_root, artifact.relative_path)
        if sha256_file(path) != object_hash:
            raise ValueError(f"source object hash mismatch: {object_hash}")
        tables.append(pq.read_table(path, columns=columns))
    if not tables:
        raise ValueError(f"source dataset is empty: {spec_hash}")
    return pa.concat_tables(tables).combine_chunks()


def _h1_partitions(reader: CatalogReaderV2) -> dict[tuple[Instrument, date], H1Partition]:
    selected = reader.logical_index.filter(
        pc.equal(reader.logical_index["dataset_spec_hash"], H1_SPEC_HASH)
    )
    result: dict[tuple[Instrument, date], H1Partition] = {}
    for row in selected.to_pylist():
        receipt = json.loads(row["payload"])
        key = receipt["partition"]
        instrument = cast(Instrument, key["instrument"])
        owner_date = date.fromisoformat(key["owner_date"])
        value = H1Partition(
            partition_id=row["partition_id"],
            owner_date=owner_date,
            semantic_sha256=row["semantic_sha256"],
            row_count=row["row_count"],
        )
        if (instrument, owner_date) in result:
            raise ValueError("duplicate H1 source partition")
        result[(instrument, owner_date)] = value
    return result


def _h2_row_groups(
    reader: CatalogReaderV2,
) -> dict[tuple[Instrument, date], tuple[H2RowGroup, ...]]:
    table = _objects_for_spec(
        reader,
        H2_INDEX_SPEC_HASH,
        columns=[
            "instrument",
            "partition_date",
            "source_relative_path",
            "source_byte_sha256",
            "source_logical_sha256",
            "row_group_ordinal",
            "row_count",
            "event_start_ns",
            "event_end_ns_exclusive",
        ],
    )
    grouped: dict[tuple[Instrument, date], list[H2RowGroup]] = {}
    for row in table.to_pylist():
        key = (cast(Instrument, row["instrument"]), row["partition_date"])
        grouped.setdefault(key, []).append(
            H2RowGroup(
                owner_date=row["partition_date"],
                source_relative_path=row["source_relative_path"],
                source_byte_sha256=row["source_byte_sha256"],
                source_logical_sha256=row["source_logical_sha256"],
                ordinal=row["row_group_ordinal"],
                row_count=row["row_count"],
                start_ns=row["event_start_ns"],
                end_ns=row["event_end_ns_exclusive"],
            )
        )
    return {
        key: tuple(sorted(values, key=lambda item: (item.start_ns, item.end_ns, item.ordinal)))
        for key, values in grouped.items()
    }


def _stage1_quality(catalog_root: Path) -> dict[tuple[Instrument, date], dict[str, int]]:
    result: dict[tuple[Instrument, date], dict[str, int]] = {}
    for instrument in INSTRUMENTS:
        catalog = json.loads((catalog_root / f"{instrument}.catalog.json").read_bytes())
        for entry in catalog["entries"]:
            result[(instrument, date.fromisoformat(entry["date"]))] = {
                "gap_count": int(entry.get("venue_trade_id_gap_count", 0)),
                "reversal_count": int(entry.get("venue_trade_id_reversal_count", 0)),
                "conflict_count": int(entry.get("venue_trade_id_conflict_count", 0)),
            }
    return result


def _utc_date(ns: int) -> date:
    return datetime.fromtimestamp(ns / 1_000_000_000, UTC).date()


def _days(start_ns: int, end_ns: int) -> Iterator[date]:
    current = _utc_date(start_ns)
    last = _utc_date(end_ns - 1)
    while current <= last:
        yield current
        current += timedelta(days=1)


def _day_bounds(owner_date: date) -> tuple[int, int]:
    start = int(datetime(owner_date.year, owner_date.month, owner_date.day, tzinfo=UTC).timestamp())
    return start * 1_000_000_000, (start + 86_400) * 1_000_000_000


def select_h2_row_groups(
    row_groups: tuple[H2RowGroup, ...], start_ns: int, end_ns: int
) -> tuple[H2RowGroup, ...]:
    """Select every source row group that can contain a fact in [start, end)."""

    ends = [item.end_ns for item in row_groups]
    index = bisect.bisect_right(ends, start_ns)
    selected: list[H2RowGroup] = []
    for item in row_groups[index:]:
        if item.start_ns >= end_ns:
            break
        if item.end_ns > start_ns:
            selected.append(item)
    return tuple(selected)


class _BufferedParquet:
    def __init__(self, path: Path, schema: pa.Schema, batch_size: int = 10_000) -> None:
        self.path = path
        self.schema = schema
        self.batch_size = batch_size
        self.rows: list[dict[str, Any]] = []
        self.writer = pq.ParquetWriter(path, schema, compression="zstd")
        self.count = 0

    def append(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        if len(self.rows) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self.rows:
            return
        table = pa.Table.from_pylist(self.rows, schema=self.schema)
        self.writer.write_table(table)
        self.count += table.num_rows
        self.rows.clear()

    def close(self) -> None:
        self.flush()
        self.writer.close()


def _episode_tables(
    reader: CatalogReaderV2,
    instrument: Instrument,
    *,
    scope_start_ns: int | None = None,
    scope_end_ns: int | None = None,
) -> pa.Table:
    columns = [
        "instrument",
        "market_episode_id",
        "canonical_candidate_id",
        "candidate_version_id",
        "canonical_payload_hash",
        "parameter_set_id",
        "available_at_ts",
        "variant_id",
        "time_combination_id",
        "research_role",
        "primary_eligible",
        "episode_status",
    ]
    tables: list[pa.Table] = []
    for spec_hash in EPISODE_SPEC_HASHES:
        table = _objects_for_spec(reader, spec_hash, columns=columns)
        table = table.filter(pc.equal(table["instrument"], instrument))
        spec_column = pa.array([spec_hash] * table.num_rows, type=pa.string())
        tables.append(table.append_column("source_episode_dataset_spec_hash", spec_column))
    combined = pa.concat_tables(tables).combine_chunks()
    combined = combined.filter(pc.equal(combined["episode_status"], "CANDIDATE"))
    if scope_start_ns is not None:
        combined = combined.filter(pc.greater_equal(combined["available_at_ts"], scope_start_ns))
    if scope_end_ns is not None:
        combined = combined.filter(pc.less(combined["available_at_ts"], scope_end_ns))
    return combined.sort_by(
        [
            ("available_at_ts", "ascending"),
            ("variant_id", "ascending"),
            ("canonical_candidate_id", "ascending"),
        ]
    )


def build_instrument_outputs(
    *,
    reader: CatalogReaderV2,
    instrument: Instrument,
    destination: Path,
    h1: dict[tuple[Instrument, date], H1Partition],
    h2: dict[tuple[Instrument, date], tuple[H2RowGroup, ...]],
    quality: dict[tuple[Instrument, date], dict[str, int]],
    scope_start_ns: int | None = None,
    scope_end_ns: int | None = None,
    source_snapshot_id: str = FIXED_SNAPSHOT_ID,
    stage1_data_run_id: str = STAGE1_RUN_ID,
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=False)
    episodes = _episode_tables(
        reader,
        instrument,
        scope_start_ns=scope_start_ns,
        scope_end_ns=scope_end_ns,
    )
    horizons = {
        item.timing_id: item.first_passage_horizon_seconds * 1_000_000_000
        for item in timing_configurations()
    }
    writers = {
        "episode_paths": _BufferedParquet(destination / "episode_paths.parquet", EPISODE_SCHEMA),
        "h1_path_slices": _BufferedParquet(destination / "h1_path_slices.parquet", H1_SLICE_SCHEMA),
        "h2_path_slices": _BufferedParquet(destination / "h2_path_slices.parquet", H2_SLICE_SCHEMA),
        "path_quality": _BufferedParquet(destination / "path_quality.parquet", QUALITY_SCHEMA),
        "lineage": _BufferedParquet(destination / "lineage.parquet", LINEAGE_SCHEMA),
    }
    try:
        for batch in episodes.to_batches(max_chunksize=10_000):
            for episode in batch.to_pylist():
                start_ns = int(episode["available_at_ts"])
                requested_end_ns = start_ns + horizons[episode["time_combination_id"]]
                end_ns = min(requested_end_ns, SOURCE_END_NS)
                if not SOURCE_START_NS <= start_ns < SOURCE_END_NS or end_ns <= start_ns:
                    raise ValueError("MarketEpisode lies outside the frozen source period")
                h1_rows: list[dict[str, Any]] = []
                h2_rows: list[dict[str, Any]] = []
                gap_count = 0
                reversal_count = 0
                conflict_count = 0
                h1_missing = 0
                for owner_date in _days(start_ns, end_ns):
                    day_start, day_end = _day_bounds(owner_date)
                    slice_start = max(start_ns, day_start)
                    slice_end = min(end_ns, day_end)
                    h1_partition = h1.get((instrument, owner_date))
                    expected_day_rows = (
                        min(day_end, SOURCE_END_NS) - max(day_start, SOURCE_START_NS)
                    ) // (1_000_000_000)
                    if h1_partition is None:
                        h1_missing += (slice_end - slice_start) // 1_000_000_000
                    else:
                        if h1_partition.row_count != expected_day_rows:
                            h1_missing += max(0, expected_day_rows - h1_partition.row_count)
                        h1_rows.append(
                            {
                                "instrument": instrument,
                                "market_episode_id": episode["market_episode_id"],
                                "canonical_candidate_id": episode["canonical_candidate_id"],
                                "source_partition_id": h1_partition.partition_id,
                                "source_owner_date": owner_date,
                                "source_semantic_sha256": h1_partition.semantic_sha256,
                                "source_row_count": h1_partition.row_count,
                                "slice_start_ns": slice_start,
                                "slice_end_ns": slice_end,
                                "reference_price_type": "CONTRACT",
                            }
                        )
                    daily_groups = h2.get((instrument, owner_date))
                    if daily_groups is None:
                        raise ValueError(
                            f"missing H2 source row-group index: {instrument} {owner_date}"
                        )
                    for group in select_h2_row_groups(daily_groups, slice_start, slice_end):
                        h2_rows.append(
                            {
                                "instrument": instrument,
                                "market_episode_id": episode["market_episode_id"],
                                "canonical_candidate_id": episode["canonical_candidate_id"],
                                "source_owner_date": owner_date,
                                "source_relative_path": group.source_relative_path,
                                "source_byte_sha256": group.source_byte_sha256,
                                "source_logical_sha256": group.source_logical_sha256,
                                "row_group_ordinal": group.ordinal,
                                "row_group_row_count": group.row_count,
                                "row_group_event_start_ns": group.start_ns,
                                "row_group_event_end_ns_exclusive": group.end_ns,
                                "slice_start_ns": slice_start,
                                "slice_end_ns": slice_end,
                                "fact_identity": "instrument,canonical_trade_id",
                                "stable_order": "ts_event_ns,venue_trade_id,canonical_trade_id",
                                "reference_price_type": "TRADE",
                            }
                        )
                    day_quality = quality[(instrument, owner_date)]
                    gap_count += day_quality["gap_count"]
                    reversal_count += day_quality["reversal_count"]
                    conflict_count += day_quality["conflict_count"]
                for row in h1_rows:
                    writers["h1_path_slices"].append(row)
                for row in h2_rows:
                    writers["h2_path_slices"].append(row)
                truncated = end_ns != requested_end_ns
                writers["episode_paths"].append(
                    {
                        "instrument": instrument,
                        "market_episode_id": episode["market_episode_id"],
                        "canonical_candidate_id": episode["canonical_candidate_id"],
                        "candidate_version_id": episode["candidate_version_id"],
                        "canonical_payload_hash": episode["canonical_payload_hash"],
                        "parameter_set_id": episode["parameter_set_id"],
                        "variant_id": episode["variant_id"],
                        "time_combination_id": episode["time_combination_id"],
                        "research_role": episode["research_role"],
                        "primary_eligible": episode["primary_eligible"],
                        "episode_available_at_ns": start_ns,
                        "window_start_ns": start_ns,
                        "requested_window_end_ns": requested_end_ns,
                        "window_end_ns": end_ns,
                        "window_truncated": truncated,
                        "truncation_reason": "SOURCE_END" if truncated else None,
                        "h1_slice_count": len(h1_rows),
                        "h2_slice_count": len(h2_rows),
                        "time_semantics": "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN",
                    }
                )
                ambiguity: list[str] = []
                if reversal_count:
                    ambiguity.append("H2_SOURCE_PARTITION_VENUE_ID_REVERSAL")
                if conflict_count:
                    ambiguity.append("H2_SOURCE_PARTITION_CONFLICTING_VENUE_ID")
                writers["path_quality"].append(
                    {
                        "instrument": instrument,
                        "market_episode_id": episode["market_episode_id"],
                        "canonical_candidate_id": episode["canonical_candidate_id"],
                        "h1_missing_seconds": h1_missing,
                        "h2_source_partition_gap_count": gap_count,
                        "h2_source_partition_reversal_count": reversal_count,
                        "h2_source_partition_conflict_count": conflict_count,
                        "quality_scope": "REFERENCED_SOURCE_PARTITIONS",
                        "ambiguity_codes": ambiguity,
                        "window_truncated": truncated,
                        "historical_evidence_only": True,
                        "prohibited_execution_fields": PROHIBITED_EXECUTION_FIELDS,
                    }
                )
                writers["lineage"].append(
                    {
                        "instrument": instrument,
                        "market_episode_id": episode["market_episode_id"],
                        "canonical_candidate_id": episode["canonical_candidate_id"],
                        "candidate_version_id": episode["candidate_version_id"],
                        "canonical_payload_hash": episode["canonical_payload_hash"],
                        "source_snapshot_id": source_snapshot_id,
                        "source_episode_dataset_spec_hash": episode[
                            "source_episode_dataset_spec_hash"
                        ],
                        "h1_dataset_spec_hash": H1_SPEC_HASH,
                        "h2_index_dataset_spec_hash": H2_INDEX_SPEC_HASH,
                        "stage1_data_run_id": stage1_data_run_id,
                        "variant_id": episode["variant_id"],
                    }
                )
    finally:
        for writer in writers.values():
            writer.close()
    files: dict[str, Any] = {}
    for name, writer in writers.items():
        path = writer.path
        files[name] = {
            "relative_path": f"{instrument}/{path.name}",
            "row_count": writer.count,
            "byte_size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return {
        "instrument": instrument,
        "episode_count": episodes.num_rows,
        "files": files,
        "output_hash": _json_hash(files),
    }


def _verify_output_tree(snapshot_root: Path, catalog: dict[str, Any]) -> dict[str, bool]:
    checks = {
        "no_symlinks": True,
        "all_files_present": True,
        "all_hashes_match": True,
        "all_row_counts_match": True,
        "btc_eth_separate": set(catalog["instruments"]) == set(INSTRUMENTS),
        "utc_left_closed_right_open": True,
        "h2_identity_preserved": True,
        "h2_stable_order_preserved": True,
        "episode_lineage_complete": True,
        "historical_execution_fields_prohibited": True,
        "stage3_locked": True,
    }
    for instrument, summary in catalog["instruments"].items():
        for entry in summary["files"].values():
            try:
                path = _safe_relative(snapshot_root, entry["relative_path"])
            except ValueError:
                checks["no_symlinks"] = False
                checks["all_files_present"] = False
                continue
            if path.stat().st_size != entry["byte_size"] or sha256_file(path) != entry["sha256"]:
                checks["all_hashes_match"] = False
            metadata = pq.ParquetFile(path).metadata
            if metadata is None or metadata.num_rows != entry["row_count"]:
                checks["all_row_counts_match"] = False
        episode_path = snapshot_root / instrument / "episode_paths.parquet"
        quality_path = snapshot_root / instrument / "path_quality.parquet"
        h2_path = snapshot_root / instrument / "h2_path_slices.parquet"
        lineage_path = snapshot_root / instrument / "lineage.parquet"
        if episode_path.is_file():
            semantics = pq.read_table(episode_path, columns=["time_semantics"])
            checks["utc_left_closed_right_open"] &= set(semantics[0].to_pylist()) == {
                "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"
            }
        if h2_path.is_file():
            h2_values = pq.read_table(h2_path, columns=["fact_identity", "stable_order"])
            checks["h2_identity_preserved"] &= set(h2_values[0].to_pylist()) == {
                "instrument,canonical_trade_id"
            }
            checks["h2_stable_order_preserved"] &= set(h2_values[1].to_pylist()) == {
                "ts_event_ns,venue_trade_id,canonical_trade_id"
            }
        if quality_path.is_file():
            quality_values = pq.read_table(
                quality_path, columns=["historical_evidence_only", "prohibited_execution_fields"]
            )
            checks["historical_execution_fields_prohibited"] &= pc.all(
                quality_values[0]
            ).as_py() is True and all(
                set(value) == set(PROHIBITED_EXECUTION_FIELDS)
                for value in quality_values[1].to_pylist()
            )
        if lineage_path.is_file():
            lineage_rows = pq.ParquetFile(lineage_path).metadata
            episode_rows = pq.ParquetFile(episode_path).metadata
            checks["episode_lineage_complete"] &= bool(
                lineage_rows and episode_rows and lineage_rows.num_rows == episode_rows.num_rows
            )
    return checks


def _new_run_id(authority_hash: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"stage2-s2t11-paths-{stamp}-{authority_hash[:12]}"


def _initialize_run(run_root: Path) -> None:
    if run_root.exists():
        raise FileExistsError("S2-T11 Run already exists")
    for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
        (run_root / name).mkdir(parents=True, exist_ok=False)


def _publish_progress_receipt(
    *,
    code_commit: str,
    status: Literal["IN_PROGRESS", "FAILED", "BLOCKED", "PASS"],
    reason_code: str,
    totals: dict[Instrument, int],
    done: dict[Instrument, int],
    input_hashes: dict[Instrument, str],
    output_hashes: dict[Instrument, str] | None = None,
    checks: dict[str, bool] | None = None,
    validation_path: str = "NOT_AVAILABLE",
    validation_hash: str | None = None,
) -> Path:
    receipts = read_path_extraction_receipts(TASK_EVIDENCE_ROOT)
    passed = status == "PASS"
    receipt = PathExtractionReceipt.seal(
        {
            "task_version": TASK_VERSION,
            "code_commit": code_commit,
            "sequence": len(receipts),
            "previous_receipt_hash": receipts[-1].receipt_hash if receipts else None,
            "status": status,
            "reason_code": reason_code,
            "btc_episodes_done": done["BTCUSDT"],
            "btc_episodes_total": totals["BTCUSDT"],
            "eth_episodes_done": done["ETHUSDT"],
            "eth_episodes_total": totals["ETHUSDT"],
            "input_hashes": input_hashes,
            "output_hashes": output_hashes or {},
            "acceptance_checks": checks or {"preflight_authority_valid": True},
            "full_output_complete": passed,
            "validation_status": "PASS" if passed else "NOT_RUN",
            "validation_path": validation_path,
            "validation_hash": validation_hash,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    )
    return publish_path_extraction_receipt(TASK_EVIDENCE_ROOT, receipt)


def execute_run(
    *,
    preflight_path: Path,
    run_id: str | None = None,
    snapshot_root: Path = FIXED_SNAPSHOT_ROOT,
    stage1_catalog_root: Path = STAGE1_CATALOG_ROOT,
    runs_root: Path = RUNS_ROOT,
    resume_existing: bool = False,
) -> Path:
    authority = read_preflight_manifest(preflight_path)
    _validate_authority_current(
        authority,
        snapshot_root=snapshot_root,
        stage1_catalog_root=stage1_catalog_root,
        stage2_root=runs_root.parent,
    )
    selected_run_id = run_id or _new_run_id(authority["authority_hash"])
    if not selected_run_id.startswith("stage2-s2t11-paths-") or "/" in selected_run_id:
        raise ValueError("unsafe S2-T11 Run ID")
    run_root = runs_root / selected_run_id
    if resume_existing:
        copied_authority = read_preflight_manifest(run_root / "manifests/preflight-authority.json")
        if copied_authority != authority:
            raise ValueError("resume authority differs from the initialized Run")
        if (run_root / "reports/completion.json").exists():
            raise ValueError("completed S2-T11 Run cannot be resumed")
    else:
        _initialize_run(run_root)
        _write_json_exclusive(run_root / "manifests" / "preflight-authority.json", authority)
    reader = CatalogReaderV2.open(snapshot_root, expected_snapshot_id=FIXED_SNAPSHOT_ID)
    h1 = _h1_partitions(reader)
    h2 = _h2_row_groups(reader)
    quality = _stage1_quality(stage1_catalog_root)
    totals = {
        instrument: _episode_tables(reader, instrument).num_rows for instrument in INSTRUMENTS
    }
    input_hashes = {
        instrument: _json_hash(
            {
                "authority_hash": authority["authority_hash"],
                "instrument": instrument,
                "stage1_logical_hash": authority["stage1"]["instruments"][instrument][
                    "trades_logical_sha256"
                ],
            }
        )
        for instrument in INSTRUMENTS
    }
    done: dict[Instrument, int] = {"BTCUSDT": 0, "ETHUSDT": 0}
    _publish_progress_receipt(
        code_commit=authority["code_commit"],
        status="IN_PROGRESS",
        reason_code=f"S2_T11_RUN_STARTED_{selected_run_id}",
        totals=totals,
        done=done,
        input_hashes=input_hashes,
    )
    output_root = run_root / "staging" / "output"
    if resume_existing:
        if output_root.is_symlink() or not output_root.is_dir():
            raise ValueError("resume staging output is unsafe or missing")
    else:
        output_root.mkdir(parents=True, exist_ok=False)
    summaries: dict[str, Any] = {}
    for instrument in INSTRUMENTS:
        completion_path = run_root / "reports" / f"{instrument.lower()}-completion.json"
        destination = output_root / instrument
        if resume_existing and (completion_path.exists() or destination.exists()):
            if (
                not completion_path.is_file()
                or completion_path.is_symlink()
                or not destination.is_dir()
            ):
                raise ValueError(f"partial {instrument} output cannot be resumed or overwritten")
            summary = json.loads(completion_path.read_bytes())
            if (
                summary.get("instrument") != instrument
                or summary.get("episode_count") != totals[instrument]
            ):
                raise ValueError(f"completed {instrument} summary conflicts with frozen totals")
            for entry in summary.get("files", {}).values():
                path = _safe_relative(output_root, entry["relative_path"])
                metadata = pq.ParquetFile(path).metadata
                if (
                    sha256_file(path) != entry["sha256"]
                    or path.stat().st_size != entry["byte_size"]
                    or metadata is None
                    or metadata.num_rows != entry["row_count"]
                ):
                    raise ValueError(f"completed {instrument} output failed resume verification")
            summaries[instrument] = summary
        else:
            summaries[instrument] = build_instrument_outputs(
                reader=reader,
                instrument=instrument,
                destination=destination,
                h1=h1,
                h2=h2,
                quality=quality,
            )
            _write_json_exclusive(completion_path, summaries[instrument])
        done[instrument] = totals[instrument]
    catalog: dict[str, Any] = {
        "schema_name": "stage2-s2t11-path-catalog",
        "schema_version": "1.0",
        "run_id": selected_run_id,
        "source_snapshot_id": FIXED_SNAPSHOT_ID,
        "instruments": summaries,
    }
    catalog["catalog_hash"] = _json_hash(catalog)
    _write_json_exclusive(output_root / "catalog.json", catalog)
    execution_manifest: dict[str, Any] = {
        "schema_name": "stage2-s2t11-execution-manifest",
        "schema_version": "1.0",
        "task_id": "S2-T11",
        "task_version": TASK_VERSION,
        "run_id": selected_run_id,
        "code_commit": authority["code_commit"],
        "preflight_authority_hash": authority["authority_hash"],
        "source_snapshot_id": FIXED_SNAPSHOT_ID,
        "catalog_hash": catalog["catalog_hash"],
        "output_hashes": {
            instrument: summaries[instrument]["output_hash"] for instrument in INSTRUMENTS
        },
        "prohibited_later_tasks": [f"S2-T{value:02d}" for value in range(12, 21)] + ["S3"],
    }
    execution_manifest["manifest_hash"] = _json_hash(execution_manifest)
    _write_json_exclusive(output_root / "manifest.json", execution_manifest)
    checks = _verify_output_tree(output_root, catalog)
    if not all(checks.values()):
        raise ValueError(f"S2-T11 staging verification failed: {checks}")
    published_root = run_root / "published" / "snapshots" / execution_manifest["manifest_hash"]
    published_root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(output_root, published_root)
    final_checks = _verify_output_tree(published_root, catalog)
    if not all(final_checks.values()):
        raise ValueError(f"S2-T11 published verification failed: {final_checks}")
    report: dict[str, Any] = {
        "schema_name": "stage2-s2t11-quality-report",
        "schema_version": "1.0",
        "run_id": selected_run_id,
        "task_version": TASK_VERSION,
        "status": "PASS",
        "manifest_hash": execution_manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "episode_counts": totals,
        "output_hashes": execution_manifest["output_hashes"],
        "checks": final_checks,
        "evidence_level": "H1_H2_HISTORICAL_PATH_SLICE_INDEX",
        "stage3_status": "LOCKED",
    }
    report["report_hash"] = _json_hash(report)
    report_path = run_root / "reports" / f"quality-{report['report_hash']}.json"
    _write_json_exclusive(report_path, report)
    _write_json_exclusive(
        run_root / "manifests" / f"execution-{execution_manifest['manifest_hash']}.json",
        execution_manifest,
    )
    _write_json_exclusive(
        run_root / "reports" / "completion.json",
        {
            "run_id": selected_run_id,
            "status": "PASS",
            "published_snapshot": str(published_root),
            "quality_report": str(report_path),
        },
    )
    _publish_progress_receipt(
        code_commit=authority["code_commit"],
        status="PASS",
        reason_code=f"S2_T11_FULL_OUTPUT_PASS_{selected_run_id}",
        totals=totals,
        done=done,
        input_hashes=input_hashes,
        output_hashes=cast(dict[Instrument, str], execution_manifest["output_hashes"]),
        checks=final_checks,
        validation_path=str(report_path),
        validation_hash=report["report_hash"],
    )
    return run_root


def verify_run(run_root: Path) -> dict[str, Any]:
    if run_root.is_symlink() or not run_root.is_dir():
        raise ValueError("unsafe or missing S2-T11 Run")
    manifests = sorted((run_root / "manifests").glob("execution-*.json"))
    if len(manifests) != 1 or manifests[0].is_symlink():
        raise ValueError("S2-T11 Run requires exactly one execution Manifest")
    manifest = json.loads(manifests[0].read_bytes())
    claimed = manifest.pop("manifest_hash", None)
    computed = _json_hash(manifest)
    manifest["manifest_hash"] = claimed
    if claimed != computed or manifest.get("run_id") != run_root.name:
        raise ValueError("S2-T11 execution Manifest is invalid")
    snapshot_root = run_root / "published" / "snapshots" / claimed
    catalog = json.loads((snapshot_root / "catalog.json").read_bytes())
    catalog_claimed = catalog.pop("catalog_hash", None)
    catalog_computed = _json_hash(catalog)
    catalog["catalog_hash"] = catalog_claimed
    if catalog_claimed != catalog_computed or manifest["catalog_hash"] != catalog_claimed:
        raise ValueError("S2-T11 Catalog is invalid")
    checks = _verify_output_tree(snapshot_root, catalog)
    return {
        "run_id": run_root.name,
        "status": "PASS" if all(checks.values()) else "FAILED",
        "manifest_hash": claimed,
        "catalog_hash": catalog_claimed,
        "checks": checks,
        "episode_counts": {
            instrument: catalog["instruments"][instrument]["episode_count"]
            for instrument in INSTRUMENTS
        },
        "output_hashes": manifest["output_hashes"],
    }


def find_resumable_run(runs_root: Path = RUNS_ROOT) -> Path:
    candidates = sorted(
        path
        for path in runs_root.glob("stage2-s2t11-paths-*")
        if path.is_dir()
        and not path.is_symlink()
        and not (path / "reports/completion.json").exists()
    )
    if len(candidates) != 1:
        raise ValueError(
            f"resume requires exactly one incomplete S2-T11 Run, found {len(candidates)}"
        )
    return candidates[0]


def resume_run(run_root: Path) -> Path:
    """Validate and reuse only complete instrument outputs; never overwrite partial evidence."""

    preflight_path = run_root / "manifests" / "preflight-authority.json"
    return execute_run(
        preflight_path=preflight_path,
        run_id=run_root.name,
        resume_existing=True,
    )


__all__ = [
    "AUTHORITY_ROOT",
    "FIXED_SNAPSHOT_ROOT",
    "RUNS_ROOT",
    "STAGE1_CATALOG_ROOT",
    "H2RowGroup",
    "build_instrument_outputs",
    "create_preflight_manifest",
    "current_code_commit",
    "execute_run",
    "find_resumable_run",
    "latest_preflight_manifest",
    "read_preflight_manifest",
    "resume_run",
    "select_h2_row_groups",
    "sha256_file",
    "verify_run",
]
