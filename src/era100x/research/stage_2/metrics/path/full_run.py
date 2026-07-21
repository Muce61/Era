"""Append-only full statistics runner for the approved S2-T12 v1.3 contract."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from bisect import bisect_left
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path, PurePosixPath
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.contracts.models import Instrument
from era100x.research.stage_2.paths.extraction.full_run import (
    EPISODE_SPEC_HASHES,
    FIXED_S2T10_RUN_ID,
    FIXED_SNAPSHOT_ID,
    RUNS_ROOT as RUNS_ROOT,
    STAGE1_PUBLISHED_ROOT,
    _objects_for_spec,
)
from era100x.research.stage_2.runtime_v2.catalog import CatalogReaderV2

from .models import ACTIVATION_SEMANTICS

REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
STAGE2_ROOT = RUNS_ROOT.parent
CONFIG_PATH = REPOSITORY_ROOT / "configs/research/stage_2/s2_t12_path_metrics_v1.3.json"
AUTHORITY_ROOT = STAGE2_ROOT / "authorities" / "S2-T12"
SOURCE_S2T11_RUN_ID = "stage2-s2t11-paths-20260721T023117Z-029707f3c111"
SOURCE_S2T11_SNAPSHOT_ID = "d4d6a2f5c72a9fb8c964585a009d2c11048b1baa34432d3d16fb68ee9ff3979c"
SOURCE_S2T11_RUN_ROOT = RUNS_ROOT / SOURCE_S2T11_RUN_ID
SOURCE_S2T11_SNAPSHOT_ROOT = (
    SOURCE_S2T11_RUN_ROOT / "published" / "snapshots" / SOURCE_S2T11_SNAPSHOT_ID
)
SOURCE_S2T10_SNAPSHOT_ROOT = (
    RUNS_ROOT / FIXED_S2T10_RUN_ID / "published" / "snapshots" / FIXED_SNAPSHOT_ID
)
PRICE_TRIGGER_SPEC_HASH = "d55bb37a136adf0e1559d88dbfffd25c5a1c0964ae8790492e5534a18be29962"
TASK_VERSION = "1.3"
CLI = "uv run python scripts/run_stage2_path_metrics.py {preflight,run,resume,verify}"
INSTRUMENTS: tuple[Instrument, ...] = ("BTCUSDT", "ETHUSDT")
DECIMAL_TYPE = pa.decimal128(38, 18)
ZERO = Decimal(0)
ONE = Decimal(1)
BPS = Decimal(10_000)
BPS_QUANTUM = Decimal("0.000000000000000001")

METRICS_SCHEMA = pa.schema(
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
        pa.field("evidence_level", pa.string(), nullable=False),
        pa.field("reference_price_type", pa.string(), nullable=False),
        pa.field("reference_price", DECIMAL_TYPE, nullable=False),
        pa.field("window_start_ns", pa.int64(), nullable=False),
        pa.field("window_end_ns", pa.int64(), nullable=False),
        pa.field("window_truncated", pa.bool_(), nullable=False),
        pa.field("observation_count", pa.int64(), nullable=False),
        pa.field("metric_status", pa.string(), nullable=False),
        pa.field("mfe_bps", DECIMAL_TYPE, nullable=True),
        pa.field("mae_bps", DECIMAL_TYPE, nullable=True),
        pa.field("mfe_first_ts_event_ns", pa.int64(), nullable=True),
        pa.field("mae_first_ts_event_ns", pa.int64(), nullable=True),
        pa.field("last_observation_ts_event_ns", pa.int64(), nullable=True),
        pa.field("time_since_mfe_ns", pa.int64(), nullable=True),
        pa.field("activation_thresholds_bps", pa.list_(DECIMAL_TYPE), nullable=False),
        pa.field("activated", pa.list_(pa.bool_()), nullable=False),
        pa.field(
            "first_activation_ts_event_ns",
            pa.list_(pa.field("item", pa.int64(), nullable=True)),
            nullable=False,
        ),
        pa.field(
            "time_to_activation_ns",
            pa.list_(pa.field("item", pa.int64(), nullable=True)),
            nullable=False,
        ),
        pa.field("activation_semantics", pa.string(), nullable=False),
        pa.field("source_quality_status", pa.string(), nullable=False),
        pa.field("source_gap_codes", pa.list_(pa.string()), nullable=False),
        pa.field("source_ambiguity_codes", pa.list_(pa.string()), nullable=False),
        pa.field("historical_evidence_only", pa.bool_(), nullable=False),
        pa.field("source_s2t11_snapshot_id", pa.string(), nullable=False),
        pa.field("source_s2t11_manifest_hash", pa.string(), nullable=False),
        pa.field("source_s2t11_catalog_hash", pa.string(), nullable=False),
        pa.field("source_s2t10_snapshot_id", pa.string(), nullable=False),
        pa.field("source_stage1_data_run_id", pa.string(), nullable=False),
        pa.field("metric_row_hash", pa.string(), nullable=False),
    ]
)


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, float):
        raise TypeError("binary floats are forbidden in path metric evidence")
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_exclusive(path: Path, payload: Any) -> None:
    data = _json_bytes(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError(f"conflicting append-only evidence: {path}")
        return
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _safe_relative(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"unsafe source path: {relative_path}")
    result = root.joinpath(*relative.parts)
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"source path escapes the frozen root: {relative_path}")
    return result


def current_code_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_authority() -> dict[str, str]:
    manifest_path = SOURCE_S2T11_SNAPSHOT_ROOT / "manifest.json"
    catalog_path = SOURCE_S2T11_SNAPSHOT_ROOT / "catalog.json"
    execution_path = (
        SOURCE_S2T11_RUN_ROOT / "manifests" / f"execution-{SOURCE_S2T11_SNAPSHOT_ID}.json"
    )
    for path in (manifest_path, catalog_path, execution_path, CONFIG_PATH):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or unsafe frozen input: {path}")
    manifest = json.loads(manifest_path.read_bytes())
    catalog = json.loads(catalog_path.read_bytes())
    if manifest["manifest_hash"] != SOURCE_S2T11_SNAPSHOT_ID:
        raise ValueError("S2-T11 manifest hash no longer matches the accepted snapshot")
    if catalog["run_id"] != SOURCE_S2T11_RUN_ID:
        raise ValueError("S2-T11 catalog run ID mismatch")
    return {
        "source_s2t11_manifest_hash": manifest["manifest_hash"],
        "source_s2t11_catalog_hash": catalog["catalog_hash"],
        "source_s2t11_manifest_sha256": sha256_file(manifest_path),
        "source_s2t11_catalog_sha256": sha256_file(catalog_path),
        "source_s2t11_execution_sha256": sha256_file(execution_path),
        "config_sha256": sha256_file(CONFIG_PATH),
    }


def create_preflight_manifest(*, code_commit: str) -> tuple[dict[str, Any], Path]:
    config = json.loads(CONFIG_PATH.read_bytes())
    if config["task_version"] != TASK_VERSION:
        raise ValueError("S2-T12 config version mismatch")
    thresholds = tuple(Decimal(value) for value in config["activation_thresholds_bps"])
    if thresholds != tuple(sorted(set(thresholds))) or any(value <= 0 for value in thresholds):
        raise ValueError("activation threshold domain is not unique, ascending and positive")
    source = _source_authority()
    payload: dict[str, Any] = {
        "schema_name": "stage2-s2t12-preflight-authority",
        "schema_version": "1.0",
        "task_id": "S2-T12",
        "task_version": TASK_VERSION,
        "manual_version": "V1.3.4",
        "code_commit": code_commit,
        "full_run_cli": CLI,
        "instruments": list(INSTRUMENTS),
        "activation_thresholds_bps": list(thresholds),
        "activation_semantics": ACTIVATION_SEMANTICS,
        "source_s2t11_run_id": SOURCE_S2T11_RUN_ID,
        "source_s2t11_snapshot_id": SOURCE_S2T11_SNAPSHOT_ID,
        "source_s2t10_run_id": FIXED_S2T10_RUN_ID,
        "source_s2t10_snapshot_id": FIXED_SNAPSHOT_ID,
        "time_semantics": "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN",
        "output_root": str(STAGE2_ROOT),
        "output_layout": ["staging", "published", "manifests", "reports", "logs", "tmp"],
        "allowed_outputs": ["path_metrics", "descriptive_summary", "quality", "lineage"],
        "prohibited_outputs": [
            "PNL",
            "RETURN",
            "REAL_RETURN",
            "LIVE_PROTECTION_ACTIVATION",
            "FIRST_PASSAGE",
            "TARGET_FIRST",
            "STOP_FIRST",
            "AMBIGUOUS_BOUNDS",
            "BASELINE",
            "PLACEBO",
            "CLUSTER",
            "BOOTSTRAP",
            "CI",
        ],
        **source,
    }
    payload["authority_hash"] = _json_hash(payload)
    path = AUTHORITY_ROOT / f"{payload['authority_hash']}.json"
    _write_json_exclusive(path, payload)
    return payload, path


def latest_preflight_manifest() -> Path:
    paths = tuple(path for path in AUTHORITY_ROOT.glob("*.json") if not path.name.startswith("._"))
    if not paths:
        raise ValueError("no S2-T12 preflight authority exists")
    return max(paths, key=lambda path: (path.stat().st_mtime_ns, path.name))


def read_preflight_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe or missing S2-T12 preflight authority")
    payload = cast(dict[str, Any], json.loads(path.read_bytes()))
    expected = payload.pop("authority_hash", None)
    actual = _json_hash(payload)
    payload["authority_hash"] = expected
    if expected != actual:
        raise ValueError("S2-T12 preflight authority hash mismatch")
    if _source_authority() != {
        key: payload[key]
        for key in (
            "source_s2t11_manifest_hash",
            "source_s2t11_catalog_hash",
            "source_s2t11_manifest_sha256",
            "source_s2t11_catalog_sha256",
            "source_s2t11_execution_sha256",
            "config_sha256",
        )
    }:
        raise ValueError("S2-T12 frozen source authority changed")
    return payload


@dataclass(slots=True)
class _MetricState:
    episode: dict[str, Any]
    quality: dict[str, Any]
    lineage: dict[str, Any]
    reference_price: Decimal
    thresholds: tuple[Decimal, ...]
    evidence_level: str
    observation_count: int = 0
    mfe_price: Decimal = field(init=False)
    mae_price: Decimal = field(init=False)
    mfe_ts: int = field(init=False)
    mae_ts: int = field(init=False)
    last_ts: int | None = None
    activation_ts: list[int | None] = field(init=False)

    def __post_init__(self) -> None:
        self.mfe_price = self.reference_price
        self.mae_price = self.reference_price
        self.mfe_ts = int(self.episode["window_start_ns"])
        self.mae_ts = int(self.episode["window_start_ns"])
        self.activation_ts = [None] * len(self.thresholds)

    def update(
        self,
        timestamps: list[int],
        favorable: pa.Array | pa.ChunkedArray,
        adverse: pa.Array | pa.ChunkedArray,
    ) -> None:
        if not timestamps:
            return
        self.observation_count += len(timestamps)
        self.last_ts = timestamps[-1] if self.last_ts is None else max(self.last_ts, timestamps[-1])
        max_scalar = pc.max(favorable)
        min_scalar = pc.min(adverse)
        max_price = cast(Decimal, max_scalar.as_py())
        min_price = cast(Decimal, min_scalar.as_py())
        if max_price > self.mfe_price:
            index = cast(int, pc.index(favorable, max_scalar).as_py())
            self.mfe_price = max_price
            self.mfe_ts = timestamps[index]
        if min_price < self.mae_price:
            index = cast(int, pc.index(adverse, min_scalar).as_py())
            self.mae_price = min_price
            self.mae_ts = timestamps[index]
        max_move = (max_price / self.reference_price - ONE) * BPS
        for index, threshold in enumerate(self.thresholds):
            if self.activation_ts[index] is not None or max_move < threshold:
                continue
            threshold_price = self.reference_price * (ONE + threshold / BPS)
            mask = pc.greater_equal(favorable, pa.scalar(threshold_price, type=DECIMAL_TYPE))
            first = cast(int, pc.index(mask, pa.scalar(True)).as_py())
            if first < 0:
                raise ValueError("activation max/first-crossing contradiction")
            self.activation_ts[index] = timestamps[first]

    def output(self, source: dict[str, str]) -> dict[str, Any]:
        computed = self.observation_count > 0
        mfe = (self.mfe_price / self.reference_price - ONE) * BPS if computed else None
        mae = (self.mae_price / self.reference_price - ONE) * BPS if computed else None
        gap_codes: list[str] = []
        if int(self.quality["h1_missing_seconds"]) > 0:
            gap_codes.append("H1_MISSING_SECONDS")
        if int(self.quality["h2_source_partition_gap_count"]) > 0:
            gap_codes.append("H2_VENUE_TRADE_ID_GAP")
        if int(self.quality["h2_source_partition_reversal_count"]) > 0:
            gap_codes.append("H2_VENUE_TRADE_ID_REVERSAL")
        ambiguity = list(self.quality["ambiguity_codes"])
        has_gaps = bool(gap_codes)
        if has_gaps and ambiguity:
            quality_status = "WITH_GAPS_AND_AMBIGUITY"
        elif has_gaps:
            quality_status = "WITH_GAPS"
        elif ambiguity:
            quality_status = "AMBIGUOUS"
        else:
            quality_status = "COMPLETE"
        window_start = int(self.episode["window_start_ns"])
        row: dict[str, Any] = {
            "instrument": self.episode["instrument"],
            "market_episode_id": self.episode["market_episode_id"],
            "canonical_candidate_id": self.episode["canonical_candidate_id"],
            "candidate_version_id": self.episode["candidate_version_id"],
            "canonical_payload_hash": self.episode["canonical_payload_hash"],
            "parameter_set_id": self.episode["parameter_set_id"],
            "variant_id": self.episode["variant_id"],
            "time_combination_id": self.episode["time_combination_id"],
            "research_role": self.episode["research_role"],
            "primary_eligible": self.episode["primary_eligible"],
            "evidence_level": self.evidence_level,
            "reference_price_type": "CONTRACT" if self.evidence_level == "H1" else "TRADE",
            "reference_price": self.reference_price,
            "window_start_ns": window_start,
            "window_end_ns": self.episode["window_end_ns"],
            "window_truncated": self.episode["window_truncated"],
            "observation_count": self.observation_count,
            "metric_status": "COMPUTED" if computed else "NO_OBSERVATIONS",
            "mfe_bps": (
                max(ZERO, cast(Decimal, mfe)).quantize(BPS_QUANTUM, rounding=ROUND_HALF_EVEN)
                if computed
                else None
            ),
            "mae_bps": (
                min(ZERO, cast(Decimal, mae)).quantize(BPS_QUANTUM, rounding=ROUND_HALF_EVEN)
                if computed
                else None
            ),
            "mfe_first_ts_event_ns": self.mfe_ts if computed else None,
            "mae_first_ts_event_ns": self.mae_ts if computed else None,
            "last_observation_ts_event_ns": self.last_ts,
            "time_since_mfe_ns": self.last_ts - self.mfe_ts if computed and self.last_ts else None,
            "activation_thresholds_bps": list(self.thresholds),
            "activated": [value is not None for value in self.activation_ts],
            "first_activation_ts_event_ns": self.activation_ts,
            "time_to_activation_ns": [
                None if value is None else value - window_start for value in self.activation_ts
            ],
            "activation_semantics": ACTIVATION_SEMANTICS,
            "source_quality_status": quality_status,
            "source_gap_codes": sorted(set(gap_codes)),
            "source_ambiguity_codes": sorted(ambiguity),
            "historical_evidence_only": True,
            "source_s2t11_snapshot_id": SOURCE_S2T11_SNAPSHOT_ID,
            "source_s2t11_manifest_hash": source["source_s2t11_manifest_hash"],
            "source_s2t11_catalog_hash": source["source_s2t11_catalog_hash"],
            "source_s2t10_snapshot_id": self.lineage["source_snapshot_id"],
            "source_stage1_data_run_id": self.lineage["stage1_data_run_id"],
        }
        row["metric_row_hash"] = _json_hash(row)
        return row


class _MetricsWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.writer = pq.ParquetWriter(path, METRICS_SCHEMA, compression="zstd")
        self.rows: list[dict[str, Any]] = []
        self.count = 0
        self.status = Counter[str]()
        self.quality = Counter[str]()
        self.evidence = Counter[str]()
        self.activation = Counter[str]()

    def append(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        self.count += 1
        self.status[str(row["metric_status"])] += 1
        self.quality[str(row["source_quality_status"])] += 1
        self.evidence[str(row["evidence_level"])] += 1
        for threshold, activated in zip(
            row["activation_thresholds_bps"], row["activated"], strict=True
        ):
            if activated:
                self.activation[format(threshold, "f")] += 1
        if len(self.rows) >= 10_000:
            self.flush()

    def flush(self) -> None:
        if not self.rows:
            return
        self.writer.write_table(pa.Table.from_pylist(self.rows, schema=METRICS_SCHEMA))
        self.rows.clear()

    def close(self) -> None:
        self.flush()
        self.writer.close()

    def summary(self) -> dict[str, Any]:
        return {
            "row_count": self.count,
            "metric_status_counts": dict(sorted(self.status.items())),
            "quality_status_counts": dict(sorted(self.quality.items())),
            "evidence_level_counts": dict(sorted(self.evidence.items())),
            "activation_counts_by_threshold_bps": dict(sorted(self.activation.items())),
        }


def _load_inputs(
    instrument: Instrument,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    root = SOURCE_S2T11_SNAPSHOT_ROOT / instrument
    episodes = pq.read_table(root / "episode_paths.parquet").to_pylist()
    quality_rows = pq.read_table(root / "path_quality.parquet").to_pylist()
    lineage_rows = pq.read_table(root / "lineage.parquet").to_pylist()
    h1_slices = pq.read_table(root / "h1_path_slices.parquet").to_pylist()
    h2_slices = pq.read_table(root / "h2_path_slices.parquet").to_pylist()
    quality = {str(row["canonical_candidate_id"]): row for row in quality_rows}
    lineage = {str(row["canonical_candidate_id"]): row for row in lineage_rows}
    if len(quality) != len(episodes) or len(lineage) != len(episodes):
        raise ValueError("S2-T11 quality/lineage is not one-to-one with Episode paths")
    episodes.sort(key=lambda row: (row["window_start_ns"], row["canonical_candidate_id"]))
    return episodes, quality, lineage, h1_slices, h2_slices


def _reference_prices() -> dict[str, Decimal]:
    reader = CatalogReaderV2.open(
        SOURCE_S2T10_SNAPSHOT_ROOT,
        expected_snapshot_id=FIXED_SNAPSHOT_ID,
        deep_verify_objects=False,
    )
    triggers = _objects_for_spec(
        reader,
        PRICE_TRIGGER_SPEC_HASH,
        columns=["trigger_id", "reference_price"],
    )
    trigger_prices: dict[str, Decimal] = {}
    for row in triggers.to_pylist():
        key = str(row["trigger_id"])
        value = Decimal(str(row["reference_price"]))
        previous = trigger_prices.setdefault(key, value)
        if previous != value:
            raise ValueError("PriceTrigger reference price conflict")
    result: dict[str, Decimal] = {}
    columns = ["canonical_candidate_id", "trigger_id", "parameter_set_id", "episode_status"]
    for spec_hash in EPISODE_SPEC_HASHES:
        episodes = _objects_for_spec(reader, spec_hash, columns=columns)
        for row in episodes.to_pylist():
            if row["episode_status"] != "CANDIDATE":
                continue
            key = str(row["trigger_id"])
            price = trigger_prices.get(key)
            if price is None:
                raise ValueError("MarketEpisode has no frozen PriceTrigger reference price")
            candidate = str(row["canonical_candidate_id"])
            previous = result.setdefault(candidate, price)
            if previous != price:
                raise ValueError("candidate reference price conflict")
    return result


def _states(
    episodes: list[dict[str, Any]],
    quality: dict[str, dict[str, Any]],
    lineage: dict[str, dict[str, Any]],
    references: dict[str, Decimal],
    thresholds: tuple[Decimal, ...],
    evidence_level: str,
) -> dict[str, _MetricState]:
    result: dict[str, _MetricState] = {}
    for episode in episodes:
        candidate = str(episode["canonical_candidate_id"])
        reference = references.get(candidate)
        if reference is None:
            raise ValueError(f"missing reference price for candidate {candidate}")
        if candidate in result:
            raise ValueError("duplicate canonical_candidate_id in S2-T11 path index")
        result[candidate] = _MetricState(
            episode=episode,
            quality=quality[candidate],
            lineage=lineage[candidate],
            reference_price=reference,
            thresholds=thresholds,
            evidence_level=evidence_level,
        )
    return result


def _process_h1(
    states: dict[str, _MetricState],
    slices: list[dict[str, Any]],
    reader: CatalogReaderV2,
) -> None:
    slices.sort(
        key=lambda row: (
            row["source_owner_date"],
            row["slice_start_ns"],
            row["canonical_candidate_id"],
        )
    )
    current_partition = ""
    timestamps: list[int] = []
    highs: pa.Array | pa.ChunkedArray = pa.array([], type=DECIMAL_TYPE)
    lows: pa.Array | pa.ChunkedArray = pa.array([], type=DECIMAL_TYPE)
    artifact_cache: OrderedDict[str, pa.Table] = OrderedDict()
    verified_objects: set[str] = set()
    for item in slices:
        partition = str(item["source_partition_id"])
        if partition != current_partition:
            receipt = reader.receipt(partition)
            if receipt.terminal_state == "EMPTY":
                raise ValueError("T11 H1 slice references an empty source partition")
            if receipt.semantic_sha256 != item["source_semantic_sha256"]:
                raise ValueError("T11 H1 source semantic hash mismatch")
            if receipt.row_count != int(item["source_row_count"]):
                raise ValueError("T11 H1 source row count mismatch")
            pieces: list[pa.Table] = []
            for fragment_hash in receipt.fragment_hashes:
                fragment = reader._fragment(fragment_hash)
                artifact = reader.artifacts.get(fragment.artifact.object_sha256)
                if artifact is None or artifact != fragment.artifact:
                    raise ValueError("H1 fragment references a conflicting object")
                physical = artifact_cache.get(artifact.object_sha256)
                if physical is None:
                    path = _safe_relative(reader.catalog_root, artifact.relative_path)
                    if artifact.object_sha256 not in verified_objects:
                        if sha256_file(path) != artifact.object_sha256:
                            raise ValueError("H1 packed object byte hash mismatch")
                        verified_objects.add(artifact.object_sha256)
                    physical = pq.read_table(path, columns=["event_ts_ns", "high", "low"])
                    artifact_cache[artifact.object_sha256] = physical
                    artifact_cache.move_to_end(artifact.object_sha256)
                    while len(artifact_cache) > 4:
                        artifact_cache.popitem(last=False)
                else:
                    artifact_cache.move_to_end(artifact.object_sha256)
                piece = physical.slice(fragment.row_offset, fragment.row_count)
                if piece.num_rows != fragment.row_count:
                    raise ValueError("H1 fragment range is outside its packed object")
                pieces.append(piece)
            table = pa.concat_tables(pieces).combine_chunks()
            if table.num_rows != receipt.row_count:
                raise ValueError("H1 fragment row count does not match its receipt")
            timestamps = cast(list[int], table["event_ts_ns"].to_pylist())
            highs = table["high"]
            lows = table["low"]
            current_partition = partition
        start = bisect_left(timestamps, int(item["slice_start_ns"]))
        end = bisect_left(timestamps, int(item["slice_end_ns"]))
        state = states[str(item["canonical_candidate_id"])]
        state.update(
            timestamps[start:end], highs.slice(start, end - start), lows.slice(start, end - start)
        )


def _process_h2(states: dict[str, _MetricState], slices: list[dict[str, Any]]) -> None:
    slices.sort(
        key=lambda row: (
            row["source_owner_date"],
            row["source_relative_path"],
            row["row_group_ordinal"],
            row["slice_start_ns"],
            row["canonical_candidate_id"],
        )
    )
    current_group: tuple[str, int] | None = None
    timestamps: list[int] = []
    prices: pa.Array | pa.ChunkedArray = pa.array([], type=DECIMAL_TYPE)
    for item in slices:
        group = (str(item["source_relative_path"]), int(item["row_group_ordinal"]))
        if group != current_group:
            path = _safe_relative(STAGE1_PUBLISHED_ROOT, group[0])
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"unsafe or missing H2 source: {path}")
            table = pq.ParquetFile(path).read_row_group(
                group[1], columns=["ts_event_ns", "venue_trade_id", "canonical_trade_id", "price"]
            )
            expected = table.sort_by(
                [
                    ("ts_event_ns", "ascending"),
                    ("venue_trade_id", "ascending"),
                    ("canonical_trade_id", "ascending"),
                ]
            )
            if not table.equals(expected):
                raise ValueError("H2 row group violates the V2 stable order")
            timestamps = cast(list[int], table["ts_event_ns"].to_pylist())
            prices = table["price"]
            current_group = group
        start = bisect_left(timestamps, int(item["slice_start_ns"]))
        end = bisect_left(timestamps, int(item["slice_end_ns"]))
        state = states[str(item["canonical_candidate_id"])]
        selected = prices.slice(start, end - start)
        state.update(timestamps[start:end], selected, selected)


def _build_instrument(
    instrument: Instrument,
    destination: Path,
    *,
    thresholds: tuple[Decimal, ...],
    source: dict[str, str],
    references: dict[str, Decimal],
) -> dict[str, Any]:
    episodes, quality, lineage, h1_slices, h2_slices = _load_inputs(instrument)
    source_reader = CatalogReaderV2.open(
        SOURCE_S2T10_SNAPSHOT_ROOT,
        expected_snapshot_id=FIXED_SNAPSHOT_ID,
        deep_verify_objects=False,
    )
    destination.parent.mkdir(parents=True, exist_ok=False)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    writer = _MetricsWriter(temporary)
    try:
        h1_states = _states(episodes, quality, lineage, references, thresholds, "H1")
        _process_h1(h1_states, h1_slices, source_reader)
        for candidate in sorted(h1_states):
            writer.append(h1_states[candidate].output(source))
        del h1_states
        h2_states = _states(episodes, quality, lineage, references, thresholds, "H2")
        _process_h2(h2_states, h2_slices)
        for candidate in sorted(h2_states):
            writer.append(h2_states[candidate].output(source))
        writer.close()
    except BaseException:
        writer.writer.close()
        raise
    os.replace(temporary, destination)
    summary = {
        "instrument": instrument,
        "episode_count": len(episodes),
        "path_metrics": writer.summary(),
        "byte_size": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }
    _write_json_exclusive(destination.with_suffix(".summary.json"), summary)
    return summary


def _run_id() -> str:
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"stage2-s2t12-metrics-{now}-{uuid.uuid4().hex[:12]}"


def execute_run(*, preflight_path: Path, run_id: str | None = None) -> Path:
    authority = read_preflight_manifest(preflight_path)
    selected_run_id = run_id or _run_id()
    run_root = RUNS_ROOT / selected_run_id
    if run_root.exists():
        raise ValueError(f"S2-T12 run already exists: {selected_run_id}")
    for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
        (run_root / name).mkdir(parents=True, exist_ok=False)
    _write_json_exclusive(run_root / "manifests" / "preflight-authority.json", authority)
    execution = {
        **authority,
        "run_id": selected_run_id,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "execution_manifest_hash": "",
    }
    execution["execution_manifest_hash"] = _json_hash(
        {key: value for key, value in execution.items() if key != "execution_manifest_hash"}
    )
    _write_json_exclusive(
        run_root / "manifests" / f"execution-{execution['execution_manifest_hash']}.json",
        execution,
    )
    return resume_run(run_root)


def resume_run(run_root: Path) -> Path:
    if not run_root.is_dir():
        raise ValueError("S2-T12 run root does not exist")
    manifests = sorted((run_root / "manifests").glob("execution-*.json"))
    if len(manifests) != 1:
        raise ValueError("S2-T12 run requires exactly one execution manifest")
    execution = json.loads(manifests[0].read_bytes())
    source = _source_authority()
    thresholds = tuple(Decimal(value) for value in execution["activation_thresholds_bps"])
    references = _reference_prices()
    summaries: dict[str, Any] = {}
    for instrument in INSTRUMENTS:
        path = run_root / "staging" / instrument / "path_metrics.parquet"
        summary_path = path.with_suffix(".summary.json")
        if path.is_file() and summary_path.is_file():
            summary = json.loads(summary_path.read_bytes())
            if summary["sha256"] != sha256_file(path):
                raise ValueError("existing S2-T12 staging output hash mismatch")
        else:
            if path.exists() or summary_path.exists():
                raise ValueError("incomplete S2-T12 staging evidence is retained; start a new run")
            summary = _build_instrument(
                instrument,
                path,
                thresholds=thresholds,
                source=source,
                references=references,
            )
        summaries[instrument] = summary
        _write_json_exclusive(
            run_root / "reports" / f"{instrument.lower()}-completion.json", summary
        )
    catalog_payload = {
        "schema_name": "stage2-s2t12-path-metrics-catalog",
        "schema_version": "1.0",
        "run_id": run_root.name,
        "source_s2t11_snapshot_id": SOURCE_S2T11_SNAPSHOT_ID,
        "instruments": summaries,
    }
    snapshot_id = _json_hash(catalog_payload)
    snapshot_staging = run_root / "staging" / "snapshot"
    snapshot_staging.mkdir(exist_ok=False)
    for instrument in INSTRUMENTS:
        source_dir = run_root / "staging" / instrument
        destination = snapshot_staging / instrument
        os.replace(source_dir, destination)
    catalog_payload["snapshot_id"] = snapshot_id
    catalog_payload["catalog_hash"] = _json_hash(catalog_payload)
    manifest_payload = {
        "schema_name": "stage2-s2t12-path-metrics-manifest",
        "schema_version": "1.0",
        "run_id": run_root.name,
        "snapshot_id": snapshot_id,
        "execution_manifest_hash": execution["execution_manifest_hash"],
        "source_s2t11_manifest_hash": source["source_s2t11_manifest_hash"],
        "source_s2t11_catalog_hash": source["source_s2t11_catalog_hash"],
        "code_commit": execution["code_commit"],
        "config_sha256": execution["config_sha256"],
        "activation_semantics": ACTIVATION_SEMANTICS,
        "historical_evidence_only": True,
    }
    manifest_payload["manifest_hash"] = _json_hash(manifest_payload)
    _write_json_exclusive(snapshot_staging / "catalog.json", catalog_payload)
    _write_json_exclusive(snapshot_staging / "manifest.json", manifest_payload)
    published = run_root / "published" / "snapshots" / snapshot_id
    published.parent.mkdir(parents=True, exist_ok=True)
    if published.exists():
        raise ValueError("S2-T12 immutable snapshot already exists")
    os.replace(snapshot_staging, published)
    completion = {
        "status": "PASS",
        "run_id": run_root.name,
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest_payload["manifest_hash"],
        "catalog_hash": catalog_payload["catalog_hash"],
        "instruments": summaries,
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    _write_json_exclusive(run_root / "reports" / "completion.json", completion)
    return run_root


def find_resumable_run() -> Path:
    candidates = sorted(
        path
        for path in RUNS_ROOT.glob("stage2-s2t12-metrics-*")
        if path.is_dir() and not (path / "reports" / "completion.json").exists()
    )
    if len(candidates) != 1:
        raise ValueError("expected exactly one resumable S2-T12 run")
    return candidates[0]


def verify_run(run_root: Path) -> dict[str, Any]:
    completion_path = run_root / "reports" / "completion.json"
    if completion_path.is_symlink() or not completion_path.is_file():
        return {"status": "FAIL", "reason": "missing completion report"}
    completion = json.loads(completion_path.read_bytes())
    snapshot = run_root / "published" / "snapshots" / completion["snapshot_id"]
    if snapshot.is_symlink() or not snapshot.is_dir():
        return {"status": "FAIL", "reason": "missing immutable snapshot"}
    try:
        source = _source_authority()
        manifest = json.loads((snapshot / "manifest.json").read_bytes())
        catalog = json.loads((snapshot / "catalog.json").read_bytes())
        if manifest["source_s2t11_manifest_hash"] != source["source_s2t11_manifest_hash"]:
            raise ValueError("source manifest lineage mismatch")
        if manifest["source_s2t11_catalog_hash"] != source["source_s2t11_catalog_hash"]:
            raise ValueError("source catalog lineage mismatch")
        for instrument in INSTRUMENTS:
            path = snapshot / instrument / "path_metrics.parquet"
            summary = catalog["instruments"][instrument]
            if path.is_symlink() or not path.is_file():
                raise ValueError("missing path metrics file")
            metadata = pq.read_metadata(path)
            if metadata.num_rows != summary["path_metrics"]["row_count"]:
                raise ValueError("path metrics row count mismatch")
            if (
                path.stat().st_size != summary["byte_size"]
                or sha256_file(path) != summary["sha256"]
            ):
                raise ValueError("path metrics file hash mismatch")
            table = pq.read_table(
                path,
                columns=[
                    "instrument",
                    "evidence_level",
                    "historical_evidence_only",
                    "activation_semantics",
                ],
            )
            if pc.all(pc.equal(table["instrument"], instrument)).as_py() is not True:
                raise ValueError("instrument isolation failed")
            if set(table["evidence_level"].to_pylist()) != {"H1", "H2"}:
                raise ValueError("H1/H2 evidence coverage failed")
            if pc.all(table["historical_evidence_only"]).as_py() is not True:
                raise ValueError("historical evidence boundary failed")
            if (
                pc.all(pc.equal(table["activation_semantics"], ACTIVATION_SEMANTICS)).as_py()
                is not True
            ):
                raise ValueError("activation semantics mismatch")
    except (OSError, ValueError, KeyError, pa.ArrowException) as exc:
        return {"status": "FAIL", "reason": str(exc), "run_id": run_root.name}
    return {
        "status": "PASS",
        "run_id": run_root.name,
        "snapshot_id": completion["snapshot_id"],
        "manifest_hash": completion["manifest_hash"],
        "catalog_hash": completion["catalog_hash"],
        "instrument_rows": {
            instrument: completion["instruments"][instrument]["path_metrics"]["row_count"]
            for instrument in INSTRUMENTS
        },
        "historical_evidence_only": True,
        "stage3_locked": True,
    }


def remove_unpublished_empty_run(run_root: Path) -> None:
    """Test helper: remove only an empty, never-published run root."""

    if (run_root / "published").exists() and any((run_root / "published").iterdir()):
        raise ValueError("published S2-T12 evidence cannot be removed")
    shutil.rmtree(run_root)
