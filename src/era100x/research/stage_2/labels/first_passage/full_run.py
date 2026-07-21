"""Append-only full runner for the approved S2-T13 v1.3 first-passage contract."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from bisect import bisect_left
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.contracts.models import Instrument
from era100x.research.stage_2.metrics.path.full_run import (
    CONFIG_PATH as SOURCE_RECOVERY_CONFIG_PATH,
)
from era100x.research.stage_2.metrics.path.full_run import (
    DECIMAL_TYPE,
    INSTRUMENTS,
    RUNS_ROOT,
    SOURCE_S2T10_SNAPSHOT_ROOT,
    SOURCE_S2T11_RUN_ID,
    SOURCE_S2T11_SNAPSHOT_ID,
    SOURCE_S2T11_SNAPSHOT_ROOT,
    STAGE2_ROOT,
    _json_hash,
    _load_inputs,
    _reference_prices,
    _safe_relative,
    _source_authority,
    _write_json_exclusive,
    current_code_commit,
    sha256_file,
)
from era100x.research.stage_2.paths.extraction.full_run import STAGE1_PUBLISHED_ROOT
from era100x.research.stage_2.runtime_v2.catalog import CatalogReaderV2

from .models import (
    PROHIBITED_INTERPRETATIONS,
    REGISTERED_HORIZONS_SECONDS,
    REGISTERED_STOP_BPS,
    REGISTERED_TARGET_BPS,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
AUTHORITY_ROOT = STAGE2_ROOT / "authorities" / "S2-T13"
TASK_VERSION = "1.3"
CLI = "uv run python scripts/run_stage2_first_passage.py {preflight,run,resume,verify}"
RUN_PREFIX = "stage2-s2t13-first-passage-"
SAFE_RUN_ID = re.compile(r"^stage2-s2t13-first-passage-\d{8}T\d{6}Z-[0-9a-f]{12}$")
NANOSECONDS_PER_SECOND = 1_000_000_000
BPS = Decimal(10_000)
DECIMAL_QUANTUM = Decimal("0.000000000000000001")
BPS_QUANTUM = Decimal("0.01")
COMBINATIONS_PER_PATH = len(REGISTERED_TARGET_BPS) * len(REGISTERED_STOP_BPS)
COMBINATION_ORDER = tuple(
    f"target={format(target, 'f')}|stop={format(stop, 'f')}"
    for target in REGISTERED_TARGET_BPS
    for stop in REGISTERED_STOP_BPS
)

_NULLABLE_INT_LIST = pa.list_(pa.field("item", pa.int64(), nullable=True))
_NULLABLE_STRING_LIST = pa.list_(pa.field("item", pa.string(), nullable=True))
_BPS_TYPE = pa.decimal128(10, 2)
FIRST_PASSAGE_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("market_episode_id", pa.string(), nullable=False),
        pa.field("canonical_candidate_id", pa.string(), nullable=False),
        pa.field("candidate_version_id", pa.string(), nullable=False),
        pa.field("canonical_payload_hash", pa.string(), nullable=False),
        pa.field("parameter_set_id", pa.string(), nullable=False),
        pa.field("variant_id", pa.string(), nullable=False),
        pa.field("research_role", pa.string(), nullable=False),
        pa.field("primary_eligible", pa.bool_(), nullable=False),
        pa.field("evidence_level", pa.string(), nullable=False),
        pa.field("reference_price_type", pa.string(), nullable=False),
        pa.field("reference_price", DECIMAL_TYPE, nullable=False),
        pa.field("timing_id", pa.string(), nullable=False),
        pa.field("horizon_seconds", pa.int32(), nullable=False),
        pa.field("window_start_ns", pa.int64(), nullable=False),
        pa.field("requested_window_end_ns", pa.int64(), nullable=False),
        pa.field("source_window_end_ns", pa.int64(), nullable=False),
        pa.field("window_complete", pa.bool_(), nullable=False),
        pa.field("observation_count", pa.int64(), nullable=False),
        pa.field("target_domain_bps", pa.list_(_BPS_TYPE), nullable=False),
        pa.field("stop_domain_bps", pa.list_(_BPS_TYPE), nullable=False),
        pa.field("combination_order", pa.list_(pa.string()), nullable=False),
        pa.field("classification_count", pa.int32(), nullable=False),
        pa.field("labels", pa.list_(pa.string()), nullable=False),
        pa.field("label_reasons", pa.list_(pa.string()), nullable=False),
        pa.field("conservative_main_labels", _NULLABLE_STRING_LIST, nullable=False),
        pa.field("strict_target_first", pa.list_(pa.bool_()), nullable=False),
        pa.field("decision_ts_event_ns", _NULLABLE_INT_LIST, nullable=False),
        pa.field("target_touch_ts_event_ns", _NULLABLE_INT_LIST, nullable=False),
        pa.field("stop_touch_ts_event_ns", _NULLABLE_INT_LIST, nullable=False),
        pa.field("source_quality_status", pa.string(), nullable=False),
        pa.field("source_gap_codes", pa.list_(pa.string()), nullable=False),
        pa.field("source_ambiguity_codes", pa.list_(pa.string()), nullable=False),
        pa.field("observed_uncertainty_before_order", pa.int64(), nullable=True),
        pa.field("time_semantics", pa.string(), nullable=False),
        pa.field("stable_order", pa.list_(pa.string()), nullable=False),
        pa.field("historical_evidence_only", pa.bool_(), nullable=False),
        pa.field("prohibited_interpretations", pa.list_(pa.string()), nullable=False),
        pa.field("source_s2t11_snapshot_id", pa.string(), nullable=False),
        pa.field("source_s2t11_manifest_hash", pa.string(), nullable=False),
        pa.field("source_s2t11_catalog_hash", pa.string(), nullable=False),
        pa.field("source_s2t10_snapshot_id", pa.string(), nullable=False),
        pa.field("source_stage1_data_run_id", pa.string(), nullable=False),
        pa.field("classification_row_hash", pa.string(), nullable=False),
    ]
)


def _source_binding() -> dict[str, str]:
    source = _source_authority()
    return {
        "source_s2t11_manifest_hash": source["source_s2t11_manifest_hash"],
        "source_s2t11_catalog_hash": source["source_s2t11_catalog_hash"],
        "source_s2t11_manifest_sha256": source["source_s2t11_manifest_sha256"],
        "source_s2t11_catalog_sha256": source["source_s2t11_catalog_sha256"],
        "source_s2t11_execution_sha256": source["source_s2t11_execution_sha256"],
        "source_recovery_config_sha256": source["config_sha256"],
        "recovery_overlay_authority_hash": source["recovery_overlay_authority_hash"],
    }


def _episode_counts_and_timings() -> tuple[dict[str, int], dict[str, int]]:
    counts: dict[str, int] = {}
    timings: Counter[str] = Counter()
    for instrument in INSTRUMENTS:
        path = SOURCE_S2T11_SNAPSHOT_ROOT / instrument / "episode_paths.parquet"
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or unsafe S2-T11 episode paths: {instrument}")
        table = pq.read_table(
            path,
            columns=[
                "time_combination_id",
                "window_start_ns",
                "requested_window_end_ns",
                "window_end_ns",
            ],
        )
        counts[instrument] = table.num_rows
        for row in table.to_pylist():
            timing = str(row["time_combination_id"])
            horizon = REGISTERED_HORIZONS_SECONDS.get(timing)
            if horizon is None:
                raise ValueError("S2-T11 contains an unregistered timing ID")
            expected = int(row["window_start_ns"]) + horizon * NANOSECONDS_PER_SECOND
            if int(row["requested_window_end_ns"]) != expected:
                raise ValueError("S2-T11 path horizon does not match preregistration")
            if int(row["window_end_ns"]) > expected:
                raise ValueError("S2-T11 source window exceeds its registered horizon")
            timings[timing] += 1
    if set(timings) != set(REGISTERED_HORIZONS_SECONDS):
        raise ValueError("T1-T4 are not all represented in the accepted S2-T11 snapshot")
    return counts, dict(sorted(timings.items()))


def create_preflight_manifest(*, code_commit: str) -> tuple[dict[str, Any], Path]:
    if code_commit != current_code_commit():
        raise ValueError("preflight code commit is not current HEAD")
    counts, timings = _episode_counts_and_timings()
    path_rows = sum(counts.values()) * len(("H1", "H2"))
    classification_count = path_rows * COMBINATIONS_PER_PATH
    estimated_output_bytes = path_rows * 4096
    required_free_bytes = estimated_output_bytes * 3 // 2
    available_free_bytes = shutil.disk_usage(STAGE2_ROOT).free
    if available_free_bytes < required_free_bytes:
        raise ValueError("insufficient Stage 2 free space for S2-T13 full output")
    payload: dict[str, Any] = {
        "schema_name": "stage2-s2t13-preflight-authority",
        "schema_version": "1.0",
        "task_id": "S2-T13",
        "task_version": TASK_VERSION,
        "manual_version": "V1.3.4",
        "change_request": "CR-2026-023",
        "code_commit": code_commit,
        "full_run_cli": CLI,
        "instruments": list(INSTRUMENTS),
        "evidence_levels": ["H1", "H2"],
        "target_domain_bps": list(REGISTERED_TARGET_BPS),
        "stop_domain_bps": list(REGISTERED_STOP_BPS),
        "timing_horizons_seconds": REGISTERED_HORIZONS_SECONDS,
        "combination_order": list(COMBINATION_ORDER),
        "per_episode_timing_semantics": "USE_FROZEN_TIME_COMBINATION_ID_ONLY",
        "episode_counts": counts,
        "timing_episode_counts": timings,
        "expected_path_rows": path_rows,
        "expected_classification_count": classification_count,
        "estimated_output_bytes": estimated_output_bytes,
        "required_free_bytes": required_free_bytes,
        "available_free_bytes_at_preflight": available_free_bytes,
        "source_s2t11_run_id": SOURCE_S2T11_RUN_ID,
        "source_s2t11_snapshot_id": SOURCE_S2T11_SNAPSHOT_ID,
        "source_s2t10_snapshot_root": str(SOURCE_S2T10_SNAPSHOT_ROOT),
        "source_recovery_config": str(SOURCE_RECOVERY_CONFIG_PATH),
        "output_root": str(STAGE2_ROOT),
        "time_semantics": "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN",
        "allowed_outputs": ["FIRST_PASSAGE_LABEL_MATRIX", "QUALITY", "LINEAGE"],
        "prohibited_outputs": list(PROHIBITED_INTERPRETATIONS)
        + ["T14_OPTIMISTIC_BOUND", "T14_PESSIMISTIC_BOUND"],
        "historical_evidence_only": True,
        "stage3_locked": True,
        **_source_binding(),
    }
    payload["authority_hash"] = _json_hash(payload)
    path = AUTHORITY_ROOT / f"{payload['authority_hash']}.json"
    _write_json_exclusive(path, payload)
    return payload, path


def latest_preflight_manifest() -> Path:
    candidates = tuple(
        path for path in AUTHORITY_ROOT.glob("*.json") if not path.name.startswith("._")
    )
    if not candidates:
        raise ValueError("no S2-T13 preflight Authority exists")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def read_preflight_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe or missing S2-T13 preflight Authority")
    payload = cast(dict[str, Any], json.loads(path.read_bytes()))
    expected_hash = payload.pop("authority_hash", None)
    actual_hash = _json_hash(payload)
    payload["authority_hash"] = expected_hash
    if expected_hash != actual_hash:
        raise ValueError("S2-T13 preflight Authority hash mismatch")
    if payload.get("task_version") != TASK_VERSION:
        raise ValueError("S2-T13 preflight Authority version mismatch")
    if payload.get("code_commit") != current_code_commit():
        raise ValueError("S2-T13 Authority code commit is not current HEAD")
    if payload.get("target_domain_bps") != [format(value, "f") for value in REGISTERED_TARGET_BPS]:
        raise ValueError("S2-T13 target domain changed")
    if payload.get("stop_domain_bps") != [format(value, "f") for value in REGISTERED_STOP_BPS]:
        raise ValueError("S2-T13 stop domain changed")
    current_source = _source_binding()
    if any(payload.get(key) != value for key, value in current_source.items()):
        raise ValueError("S2-T13 frozen source binding changed")
    if shutil.disk_usage(STAGE2_ROOT).free < int(payload["required_free_bytes"]):
        raise ValueError("S2-T13 free-space gate no longer passes")
    return payload


def _first_true(mask: pa.Array | pa.ChunkedArray) -> int | None:
    index = cast(int, pc.index(mask, pa.scalar(True)).as_py())
    return index if index >= 0 else None


@dataclass(slots=True)
class _PassageState:
    episode: dict[str, Any]
    quality: dict[str, Any]
    lineage: dict[str, Any]
    reference_price: Decimal
    evidence_level: Literal["H1", "H2"]
    observation_count: int = 0
    target_touch_ts: list[int | None] = field(
        default_factory=lambda: [None] * len(REGISTERED_TARGET_BPS)
    )
    stop_touch_ts: list[int | None] = field(
        default_factory=lambda: [None] * len(REGISTERED_STOP_BPS)
    )
    target_touch_order: list[int | None] = field(
        default_factory=lambda: [None] * len(REGISTERED_TARGET_BPS)
    )
    stop_touch_order: list[int | None] = field(
        default_factory=lambda: [None] * len(REGISTERED_STOP_BPS)
    )
    earliest_uncertainty_order: int | None = None
    first_h1_ts: int | None = None
    last_h1_ts: int | None = None
    last_h2_id: int | None = None
    observed_gap_codes: set[str] = field(default_factory=set)
    observed_ambiguity_codes: set[str] = field(default_factory=set)

    def _note_uncertainty(self, order: int, code: str, *, ambiguity: bool = False) -> None:
        if self.earliest_uncertainty_order is None:
            self.earliest_uncertainty_order = order
        else:
            self.earliest_uncertainty_order = min(self.earliest_uncertainty_order, order)
        target = self.observed_ambiguity_codes if ambiguity else self.observed_gap_codes
        target.add(code)

    def _update_touches(
        self,
        timestamps: list[int],
        favorable: pa.Array | pa.ChunkedArray,
        adverse: pa.Array | pa.ChunkedArray,
    ) -> None:
        if not timestamps:
            return
        batch_start = self.observation_count
        maximum = cast(Decimal, pc.max(favorable).as_py())
        minimum = cast(Decimal, pc.min(adverse).as_py())
        for index, threshold in enumerate(REGISTERED_TARGET_BPS):
            if self.target_touch_ts[index] is not None:
                continue
            price = self.reference_price * (Decimal(1) + threshold / BPS)
            if maximum < price:
                continue
            offset = _first_true(pc.greater_equal(favorable, pa.scalar(price, type=DECIMAL_TYPE)))
            if offset is None:
                raise ValueError("target maximum/first-passage contradiction")
            self.target_touch_ts[index] = timestamps[offset]
            self.target_touch_order[index] = batch_start + offset
        for index, threshold in enumerate(REGISTERED_STOP_BPS):
            if self.stop_touch_ts[index] is not None:
                continue
            price = self.reference_price * (Decimal(1) - threshold / BPS)
            if minimum > price:
                continue
            offset = _first_true(pc.less_equal(adverse, pa.scalar(price, type=DECIMAL_TYPE)))
            if offset is None:
                raise ValueError("stop minimum/first-passage contradiction")
            self.stop_touch_ts[index] = timestamps[offset]
            self.stop_touch_order[index] = batch_start + offset
        self.observation_count += len(timestamps)

    def update_h1(
        self,
        timestamps: list[int],
        highs: pa.Array | pa.ChunkedArray,
        lows: pa.Array | pa.ChunkedArray,
    ) -> None:
        if not timestamps:
            return
        batch_start = self.observation_count
        expected = (
            int(self.episode["window_start_ns"])
            if self.last_h1_ts is None
            else self.last_h1_ts + NANOSECONDS_PER_SECOND
        )
        if timestamps[0] != expected:
            self._note_uncertainty(batch_start, "H1_MISSING_SECONDS")
        if (
            self.earliest_uncertainty_order is None
            and timestamps[-1] - timestamps[0] != (len(timestamps) - 1) * NANOSECONDS_PER_SECOND
        ):
            for offset, (previous, current) in enumerate(
                zip(timestamps, timestamps[1:], strict=False), start=1
            ):
                if current != previous + NANOSECONDS_PER_SECOND:
                    self._note_uncertainty(batch_start + offset, "H1_MISSING_SECONDS")
                    break
        self.first_h1_ts = timestamps[0] if self.first_h1_ts is None else self.first_h1_ts
        self.last_h1_ts = timestamps[-1]
        self._update_touches(timestamps, highs, lows)

    def update_h2(
        self,
        timestamps: list[int],
        venue_ids: pa.Array | pa.ChunkedArray,
        prices: pa.Array | pa.ChunkedArray,
    ) -> None:
        if not timestamps:
            return
        batch_start = self.observation_count
        first_id = cast(int, venue_ids[0].as_py())
        if self.last_h2_id is not None and first_id != self.last_h2_id + 1:
            code = (
                "H2_VENUE_TRADE_ID_GAP"
                if first_id > self.last_h2_id + 1
                else "H2_VENUE_TRADE_ID_REVERSAL_OR_CONFLICT"
            )
            self._note_uncertainty(
                batch_start,
                code,
                ambiguity=first_id <= self.last_h2_id,
            )
        if len(timestamps) > 1 and self.earliest_uncertainty_order is None:
            left = venue_ids.slice(0, len(timestamps) - 1)
            right = venue_ids.slice(1, len(timestamps) - 1)
            differences = pc.subtract(right, left)
            offset = _first_true(pc.not_equal(differences, pa.scalar(1, type=differences.type)))
            if offset is not None:
                delta = cast(int, differences[offset].as_py())
                self._note_uncertainty(
                    batch_start + offset + 1,
                    "H2_VENUE_TRADE_ID_GAP"
                    if delta > 1
                    else "H2_VENUE_TRADE_ID_REVERSAL_OR_CONFLICT",
                    ambiguity=delta <= 0,
                )
        self.last_h2_id = cast(int, venue_ids[len(timestamps) - 1].as_py())
        self._update_touches(timestamps, prices, prices)

    def _finish_h1_gaps(self) -> None:
        if self.evidence_level != "H1" or self.observation_count == 0:
            return
        source_end = int(self.episode["window_end_ns"])
        expected_last = source_end - NANOSECONDS_PER_SECOND
        if self.last_h1_ts is not None and self.last_h1_ts < expected_last:
            self._note_uncertainty(self.observation_count, "H1_MISSING_SECONDS")

    def _classification(
        self,
        target_index: int,
        stop_index: int,
    ) -> tuple[str, str, str | None, bool, int | None]:
        target_ts = self.target_touch_ts[target_index]
        stop_ts = self.stop_touch_ts[stop_index]
        target_order = self.target_touch_order[target_index]
        stop_order = self.stop_touch_order[stop_index]
        orders = [value for value in (target_order, stop_order) if value is not None]
        first_order = min(orders) if orders else None
        if (
            first_order is not None
            and self.earliest_uncertainty_order is not None
            and self.earliest_uncertainty_order <= first_order
        ):
            return "AMBIGUOUS", "SOURCE_GAP_BEFORE_DECISION", None, False, None
        if self.evidence_level == "H1" and target_ts is not None and target_ts == stop_ts:
            return "AMBIGUOUS", "H1_SAME_EVENT_TARGET_AND_STOP", "STOP_FIRST", False, target_ts
        if target_order is not None and (stop_order is None or target_order < stop_order):
            return "TARGET_FIRST", "TARGET_OBSERVED_FIRST", "TARGET_FIRST", True, target_ts
        if stop_order is not None:
            return "STOP_FIRST", "STOP_OBSERVED_FIRST", "STOP_FIRST", False, stop_ts
        if self.observation_count == 0:
            return "AMBIGUOUS", "NO_OBSERVATIONS", None, False, None
        if self.earliest_uncertainty_order is not None:
            return "AMBIGUOUS", "SOURCE_GAP_BEFORE_DECISION", None, False, None
        if bool(self.episode["window_truncated"]):
            return "AMBIGUOUS", "WINDOW_TRUNCATED_BEFORE_DECISION", None, False, None
        return "EXPIRED", "HORIZON_EXPIRED_WITHOUT_TOUCH", "EXPIRED", False, None

    def output(self, source: dict[str, str]) -> dict[str, Any]:
        self._finish_h1_gaps()
        timing = str(self.episode["time_combination_id"])
        horizon = REGISTERED_HORIZONS_SECONDS.get(timing)
        if horizon is None:
            raise ValueError("unregistered timing ID in S2-T11 Episode")
        requested_end = int(self.episode["window_start_ns"]) + horizon * NANOSECONDS_PER_SECOND
        if requested_end != int(self.episode["requested_window_end_ns"]):
            raise ValueError("Episode requested window disagrees with frozen timing")
        labels: list[str] = []
        reasons: list[str] = []
        conservative: list[str | None] = []
        strict: list[bool] = []
        decisions: list[int | None] = []
        for target_index, _target in enumerate(REGISTERED_TARGET_BPS):
            for stop_index, _stop in enumerate(REGISTERED_STOP_BPS):
                label, reason, main, strict_flag, decision = self._classification(
                    target_index,
                    stop_index,
                )
                labels.append(label)
                reasons.append(reason)
                conservative.append(main)
                strict.append(strict_flag)
                decisions.append(decision)
        gap_codes: set[str] = set(self.observed_gap_codes)
        if self.evidence_level == "H1" and int(self.quality["h1_missing_seconds"]) > 0:
            gap_codes.add("H1_MISSING_SECONDS")
        if self.evidence_level == "H2" and int(self.quality["h2_source_partition_gap_count"]) > 0:
            gap_codes.add("H2_VENUE_TRADE_ID_GAP")
        ambiguity_codes = set(map(str, self.quality["ambiguity_codes"]))
        ambiguity_codes.update(self.observed_ambiguity_codes)
        if gap_codes and ambiguity_codes:
            quality_status = "WITH_GAPS_AND_AMBIGUITY"
        elif gap_codes:
            quality_status = "WITH_GAPS"
        elif ambiguity_codes:
            quality_status = "AMBIGUOUS"
        else:
            quality_status = "COMPLETE"
        row: dict[str, Any] = {
            "instrument": self.episode["instrument"],
            "market_episode_id": self.episode["market_episode_id"],
            "canonical_candidate_id": self.episode["canonical_candidate_id"],
            "candidate_version_id": self.episode["candidate_version_id"],
            "canonical_payload_hash": self.episode["canonical_payload_hash"],
            "parameter_set_id": self.episode["parameter_set_id"],
            "variant_id": self.episode["variant_id"],
            "research_role": self.episode["research_role"],
            "primary_eligible": self.episode["primary_eligible"],
            "evidence_level": self.evidence_level,
            "reference_price_type": "CONTRACT" if self.evidence_level == "H1" else "TRADE",
            "reference_price": self.reference_price.quantize(DECIMAL_QUANTUM),
            "timing_id": timing,
            "horizon_seconds": horizon,
            "window_start_ns": self.episode["window_start_ns"],
            "requested_window_end_ns": requested_end,
            "source_window_end_ns": self.episode["window_end_ns"],
            "window_complete": not bool(self.episode["window_truncated"]),
            "observation_count": self.observation_count,
            "target_domain_bps": [value.quantize(BPS_QUANTUM) for value in REGISTERED_TARGET_BPS],
            "stop_domain_bps": [value.quantize(BPS_QUANTUM) for value in REGISTERED_STOP_BPS],
            "combination_order": list(COMBINATION_ORDER),
            "classification_count": COMBINATIONS_PER_PATH,
            "labels": labels,
            "label_reasons": reasons,
            "conservative_main_labels": conservative,
            "strict_target_first": strict,
            "decision_ts_event_ns": decisions,
            "target_touch_ts_event_ns": self.target_touch_ts,
            "stop_touch_ts_event_ns": self.stop_touch_ts,
            "source_quality_status": quality_status,
            "source_gap_codes": sorted(gap_codes),
            "source_ambiguity_codes": sorted(ambiguity_codes),
            "observed_uncertainty_before_order": self.earliest_uncertainty_order,
            "time_semantics": "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN",
            "stable_order": (
                ["ts_event_ns", "source_row_hash"]
                if self.evidence_level == "H1"
                else ["ts_event_ns", "venue_trade_id", "canonical_trade_id"]
            ),
            "historical_evidence_only": True,
            "prohibited_interpretations": list(PROHIBITED_INTERPRETATIONS),
            "source_s2t11_snapshot_id": SOURCE_S2T11_SNAPSHOT_ID,
            "source_s2t11_manifest_hash": source["source_s2t11_manifest_hash"],
            "source_s2t11_catalog_hash": source["source_s2t11_catalog_hash"],
            "source_s2t10_snapshot_id": self.lineage["source_snapshot_id"],
            "source_stage1_data_run_id": self.lineage["stage1_data_run_id"],
        }
        row["classification_row_hash"] = _json_hash(row)
        return row


def _states(
    episodes: list[dict[str, Any]],
    quality: dict[str, dict[str, Any]],
    lineage: dict[str, dict[str, Any]],
    references: dict[str, Decimal],
    evidence_level: Literal["H1", "H2"],
) -> dict[str, _PassageState]:
    result: dict[str, _PassageState] = {}
    for episode in episodes:
        candidate = str(episode["canonical_candidate_id"])
        reference = references.get(candidate)
        if reference is None:
            raise ValueError(f"missing frozen reference price for {candidate}")
        if candidate in result:
            raise ValueError("duplicate canonical candidate in S2-T11 paths")
        result[candidate] = _PassageState(
            episode=episode,
            quality=quality[candidate],
            lineage=lineage[candidate],
            reference_price=reference,
            evidence_level=evidence_level,
        )
    return result


def _process_h1(
    states: dict[str, _PassageState],
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
    cache: OrderedDict[str, pa.Table] = OrderedDict()
    verified: set[str] = set()
    for item in slices:
        partition = str(item["source_partition_id"])
        if partition != current_partition:
            receipt = reader.receipt(partition)
            if receipt.terminal_state == "EMPTY":
                raise ValueError("T11 H1 slice references an empty partition")
            if receipt.semantic_sha256 != item["source_semantic_sha256"]:
                raise ValueError("T11 H1 semantic hash mismatch")
            if receipt.row_count != int(item["source_row_count"]):
                raise ValueError("T11 H1 source row count mismatch")
            pieces: list[pa.Table] = []
            for fragment_hash in receipt.fragment_hashes:
                fragment = reader._fragment(fragment_hash)
                artifact = reader.artifacts.get(fragment.artifact.object_sha256)
                if artifact is None or artifact != fragment.artifact:
                    raise ValueError("H1 fragment references a conflicting object")
                physical = cache.get(artifact.object_sha256)
                if physical is None:
                    path = _safe_relative(reader.catalog_root, artifact.relative_path)
                    if artifact.object_sha256 not in verified:
                        if sha256_file(path) != artifact.object_sha256:
                            raise ValueError("H1 packed object byte hash mismatch")
                        verified.add(artifact.object_sha256)
                    physical = pq.read_table(path, columns=["event_ts_ns", "high", "low"])
                    cache[artifact.object_sha256] = physical
                    while len(cache) > 4:
                        cache.popitem(last=False)
                else:
                    cache.move_to_end(artifact.object_sha256)
                pieces.append(physical.slice(fragment.row_offset, fragment.row_count))
            table = pa.concat_tables(pieces).combine_chunks()
            if table.num_rows != receipt.row_count:
                raise ValueError("H1 fragment row count does not match its receipt")
            timestamps = cast(list[int], table["event_ts_ns"].to_pylist())
            highs = table["high"]
            lows = table["low"]
            current_partition = partition
        start = bisect_left(timestamps, int(item["slice_start_ns"]))
        end = bisect_left(timestamps, int(item["slice_end_ns"]))
        states[str(item["canonical_candidate_id"])].update_h1(
            timestamps[start:end],
            highs.slice(start, end - start),
            lows.slice(start, end - start),
        )


def _recovery_overlays() -> dict[str, dict[str, Any]]:
    config = json.loads(SOURCE_RECOVERY_CONFIG_PATH.read_bytes())
    return {
        str(item["source_relative_path"]): cast(dict[str, Any], item)
        for item in config.get("read_only_recovery_overlays", [])
    }


def _process_h2(states: dict[str, _PassageState], slices: list[dict[str, Any]]) -> None:
    overlays = _recovery_overlays()
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
    venue_ids: pa.Array | pa.ChunkedArray = pa.array([], type=pa.int64())
    prices: pa.Array | pa.ChunkedArray = pa.array([], type=DECIMAL_TYPE)
    for item in slices:
        group = (str(item["source_relative_path"]), int(item["row_group_ordinal"]))
        if group != current_group:
            overlay = overlays.get(group[0])
            path = (
                _safe_relative(STAGE1_PUBLISHED_ROOT, group[0])
                if overlay is None
                else Path(str(overlay["overlay_path"]))
            )
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"unsafe or missing H2 source: {path}")
            table = pq.ParquetFile(path).read_row_group(
                group[1],
                columns=["ts_event_ns", "venue_trade_id", "canonical_trade_id", "price"],
            )
            expected = table.sort_by(
                [
                    ("ts_event_ns", "ascending"),
                    ("venue_trade_id", "ascending"),
                    ("canonical_trade_id", "ascending"),
                ]
            )
            if not table.equals(expected):
                raise ValueError("H2 row group violates V2 stable order")
            timestamps = cast(list[int], table["ts_event_ns"].to_pylist())
            venue_ids = table["venue_trade_id"]
            prices = table["price"]
            current_group = group
        start = bisect_left(timestamps, int(item["slice_start_ns"]))
        end = bisect_left(timestamps, int(item["slice_end_ns"]))
        states[str(item["canonical_candidate_id"])].update_h2(
            timestamps[start:end],
            venue_ids.slice(start, end - start),
            prices.slice(start, end - start),
        )


class _Writer:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.writer = pq.ParquetWriter(path, FIRST_PASSAGE_SCHEMA, compression="zstd")
        self.rows: list[dict[str, Any]] = []
        self.row_count = 0
        self.classification_count = 0
        self.labels: Counter[str] = Counter()
        self.reasons: Counter[str] = Counter()
        self.evidence: Counter[str] = Counter()
        self.timings: Counter[str] = Counter()

    def append(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        self.row_count += 1
        self.classification_count += int(row["classification_count"])
        self.labels.update(map(str, row["labels"]))
        self.reasons.update(map(str, row["label_reasons"]))
        self.evidence[str(row["evidence_level"])] += 1
        self.timings[str(row["timing_id"])] += 1
        if len(self.rows) >= 2_000:
            self.flush()

    def flush(self) -> None:
        if not self.rows:
            return
        self.writer.write_table(pa.Table.from_pylist(self.rows, schema=FIRST_PASSAGE_SCHEMA))
        self.rows.clear()

    def close(self) -> None:
        self.flush()
        self.writer.close()

    def summary(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "classification_count": self.classification_count,
            "label_counts": dict(sorted(self.labels.items())),
            "label_reason_counts": dict(sorted(self.reasons.items())),
            "evidence_level_counts": dict(sorted(self.evidence.items())),
            "timing_id_counts": dict(sorted(self.timings.items())),
        }


def _build_instrument(
    instrument: Instrument,
    destination: Path,
    *,
    source: dict[str, str],
    references: dict[str, Decimal],
) -> dict[str, Any]:
    episodes, quality, lineage, h1_slices, h2_slices = _load_inputs(instrument)
    reader = CatalogReaderV2.open(
        SOURCE_S2T10_SNAPSHOT_ROOT,
        expected_snapshot_id=SOURCE_S2T10_SNAPSHOT_ROOT.name,
        deep_verify_objects=False,
    )
    destination.parent.mkdir(parents=True, exist_ok=False)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    writer = _Writer(temporary)
    try:
        h1_states = _states(episodes, quality, lineage, references, "H1")
        _process_h1(h1_states, h1_slices, reader)
        for candidate in sorted(h1_states):
            writer.append(h1_states[candidate].output(source))
        del h1_states
        h2_states = _states(episodes, quality, lineage, references, "H2")
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
        "first_passage": writer.summary(),
        "byte_size": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }
    _write_json_exclusive(destination.with_suffix(".summary.json"), summary)
    return summary


def _new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{RUN_PREFIX}{stamp}-{uuid.uuid4().hex[:12]}"


def _initialize_run(run_root: Path) -> None:
    if run_root.exists():
        raise ValueError(f"S2-T13 run already exists: {run_root.name}")
    for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
        (run_root / name).mkdir(parents=True, exist_ok=False)


def execute_run(*, preflight_path: Path, run_id: str | None = None) -> Path:
    authority = read_preflight_manifest(preflight_path)
    selected = run_id or _new_run_id()
    if SAFE_RUN_ID.fullmatch(selected) is None:
        raise ValueError("unsafe S2-T13 Run ID")
    run_root = RUNS_ROOT / selected
    _initialize_run(run_root)
    _write_json_exclusive(run_root / "manifests/preflight-authority.json", authority)
    execution = {
        **authority,
        "run_id": selected,
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
    try:
        return resume_run(run_root)
    except BaseException as exc:
        _write_json_exclusive(
            run_root / "reports/failure.json",
            {
                "task_id": "S2-T13",
                "task_version": TASK_VERSION,
                "run_id": selected,
                "status": "FAILED_UNPUBLISHED",
                "failure_class": type(exc).__name__,
                "reason": str(exc),
                "resume_allowed": False,
                "published": False,
                "created_at_utc": datetime.now(UTC).isoformat(),
            },
        )
        raise


def resume_run(run_root: Path) -> Path:
    if run_root.is_symlink() or not run_root.is_dir():
        raise ValueError("S2-T13 run root is unsafe or missing")
    if (run_root / "reports/failure.json").exists():
        raise ValueError("failed S2-T13 Run is immutable and cannot resume")
    manifests = sorted((run_root / "manifests").glob("execution-*.json"))
    if len(manifests) != 1 or manifests[0].is_symlink():
        raise ValueError("S2-T13 Run requires exactly one execution Manifest")
    execution = json.loads(manifests[0].read_bytes())
    authority = read_preflight_manifest(run_root / "manifests/preflight-authority.json")
    if execution.get("authority_hash") != authority["authority_hash"]:
        raise ValueError("S2-T13 execution/Authority mismatch")
    source = _source_binding()
    references = _reference_prices()
    summaries: dict[str, Any] = {}
    for instrument in INSTRUMENTS:
        output = run_root / "staging" / instrument / "first_passage.parquet"
        summary_path = output.with_suffix(".summary.json")
        if output.is_file() and summary_path.is_file():
            summary = json.loads(summary_path.read_bytes())
            if summary.get("sha256") != sha256_file(output):
                raise ValueError("existing S2-T13 staging output hash mismatch")
        else:
            if output.exists() or summary_path.exists():
                raise ValueError("partial S2-T13 staging output cannot be overwritten")
            summary = _build_instrument(
                instrument,
                output,
                source=source,
                references=references,
            )
        summaries[instrument] = summary
        _write_json_exclusive(
            run_root / "reports" / f"{instrument.lower()}-completion.json",
            summary,
        )
    catalog_base = {
        "schema_name": "stage2-s2t13-first-passage-catalog",
        "schema_version": "1.0",
        "run_id": run_root.name,
        "source_s2t11_snapshot_id": SOURCE_S2T11_SNAPSHOT_ID,
        "combination_order": list(COMBINATION_ORDER),
        "instruments": summaries,
    }
    snapshot_id = _json_hash(catalog_base)
    catalog = {**catalog_base, "snapshot_id": snapshot_id}
    catalog["catalog_hash"] = _json_hash(catalog)
    manifest = {
        "schema_name": "stage2-s2t13-first-passage-manifest",
        "schema_version": "1.0",
        "task_id": "S2-T13",
        "task_version": TASK_VERSION,
        "run_id": run_root.name,
        "snapshot_id": snapshot_id,
        "execution_manifest_hash": execution["execution_manifest_hash"],
        "authority_hash": authority["authority_hash"],
        "source_s2t11_manifest_hash": source["source_s2t11_manifest_hash"],
        "source_s2t11_catalog_hash": source["source_s2t11_catalog_hash"],
        "code_commit": execution["code_commit"],
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    manifest["manifest_hash"] = _json_hash(manifest)
    snapshot_staging = run_root / "staging/snapshot"
    snapshot_staging.mkdir(exist_ok=False)
    for instrument in INSTRUMENTS:
        os.replace(run_root / "staging" / instrument, snapshot_staging / instrument)
    _write_json_exclusive(snapshot_staging / "catalog.json", catalog)
    _write_json_exclusive(snapshot_staging / "manifest.json", manifest)
    published = run_root / "published/snapshots" / snapshot_id
    published.parent.mkdir(parents=True, exist_ok=True)
    if published.exists():
        raise ValueError("S2-T13 immutable snapshot already exists")
    os.replace(snapshot_staging, published)
    completion = {
        "status": "PASS",
        "task_id": "S2-T13",
        "task_version": TASK_VERSION,
        "run_id": run_root.name,
        "authority_hash": authority["authority_hash"],
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "instruments": summaries,
        "total_path_rows": sum(value["first_passage"]["row_count"] for value in summaries.values()),
        "total_classification_count": sum(
            value["first_passage"]["classification_count"] for value in summaries.values()
        ),
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    _write_json_exclusive(run_root / "reports/completion.json", completion)
    return run_root


def find_resumable_run() -> Path:
    candidates = sorted(
        path
        for path in RUNS_ROOT.glob(f"{RUN_PREFIX}*")
        if path.is_dir()
        and not path.is_symlink()
        and not (path / "reports/completion.json").exists()
        and not (path / "reports/failure.json").exists()
    )
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one resumable S2-T13 Run, found {len(candidates)}")
    return candidates[0]


def _self_hash_matches(payload: dict[str, Any], field: str) -> bool:
    expected = payload.pop(field, None)
    actual = _json_hash(payload)
    payload[field] = expected
    return bool(expected == actual)


def _verify_output(path: Path, instrument: str, summary: dict[str, Any]) -> dict[str, Any]:
    metadata = pq.read_metadata(path)
    expected_rows = int(summary["first_passage"]["row_count"])
    if metadata.num_rows != expected_rows:
        raise ValueError("S2-T13 row count mismatch")
    if path.stat().st_size != int(summary["byte_size"]) or sha256_file(path) != summary["sha256"]:
        raise ValueError("S2-T13 file size/hash mismatch")
    prohibited_fields = {
        "pnl",
        "return",
        "round_success",
        "ambiguous_bounds",
        "optimistic_bound",
        "pessimistic_bound",
    }
    if prohibited_fields.intersection(name.lower() for name in metadata.schema.names):
        raise ValueError("S2-T13 emitted a prohibited later-task field")
    labels: Counter[str] = Counter()
    classifications = 0
    row_count = 0
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=2_000):
        for row in batch.to_pylist():
            claimed_hash = row.pop("classification_row_hash")
            if claimed_hash != _json_hash(row):
                raise ValueError("S2-T13 classification row hash mismatch")
            if row["instrument"] != instrument or row["historical_evidence_only"] is not True:
                raise ValueError("S2-T13 instrument/historical boundary mismatch")
            timing = row["timing_id"]
            if row["horizon_seconds"] != REGISTERED_HORIZONS_SECONDS[timing]:
                raise ValueError("S2-T13 timing/horizon mismatch")
            if row["target_domain_bps"] != list(REGISTERED_TARGET_BPS):
                raise ValueError("S2-T13 target domain mismatch")
            if row["stop_domain_bps"] != list(REGISTERED_STOP_BPS):
                raise ValueError("S2-T13 stop domain mismatch")
            if row["combination_order"] != list(COMBINATION_ORDER):
                raise ValueError("S2-T13 combination order mismatch")
            lengths = {
                len(row["labels"]),
                len(row["label_reasons"]),
                len(row["conservative_main_labels"]),
                len(row["strict_target_first"]),
                len(row["decision_ts_event_ns"]),
            }
            if (
                lengths != {COMBINATIONS_PER_PATH}
                or row["classification_count"] != COMBINATIONS_PER_PATH
            ):
                raise ValueError("S2-T13 classification matrix is incomplete")
            if any(
                flag != (label == "TARGET_FIRST")
                for flag, label in zip(row["strict_target_first"], row["labels"], strict=True)
            ):
                raise ValueError("S2-T13 strict target-first flag mismatch")
            labels.update(map(str, row["labels"]))
            classifications += int(row["classification_count"])
            row_count += 1
    if row_count != expected_rows:
        raise ValueError("S2-T13 verified row count mismatch")
    if classifications != int(summary["first_passage"]["classification_count"]):
        raise ValueError("S2-T13 verified classification count mismatch")
    if dict(sorted(labels.items())) != summary["first_passage"]["label_counts"]:
        raise ValueError("S2-T13 label distribution mismatch")
    return {
        "row_count": row_count,
        "classification_count": classifications,
        "label_counts": dict(sorted(labels.items())),
    }


def verify_run(run_root: Path) -> dict[str, Any]:
    if run_root.is_symlink() or not run_root.is_dir():
        return {"status": "FAIL", "reason": "unsafe or missing S2-T13 Run"}
    try:
        completion = json.loads((run_root / "reports/completion.json").read_bytes())
        snapshot = run_root / "published/snapshots" / completion["snapshot_id"]
        manifest = json.loads((snapshot / "manifest.json").read_bytes())
        catalog = json.loads((snapshot / "catalog.json").read_bytes())
        if not _self_hash_matches(manifest, "manifest_hash"):
            raise ValueError("S2-T13 manifest hash mismatch")
        if not _self_hash_matches(catalog, "catalog_hash"):
            raise ValueError("S2-T13 catalog hash mismatch")
        if manifest["run_id"] != run_root.name or catalog["run_id"] != run_root.name:
            raise ValueError("S2-T13 terminal Run ID mismatch")
        if manifest["snapshot_id"] != completion["snapshot_id"]:
            raise ValueError("S2-T13 snapshot lineage mismatch")
        source = _source_binding()
        if manifest["source_s2t11_manifest_hash"] != source["source_s2t11_manifest_hash"]:
            raise ValueError("S2-T13 source manifest lineage mismatch")
        verified = {
            instrument: _verify_output(
                snapshot / instrument / "first_passage.parquet",
                instrument,
                catalog["instruments"][instrument],
            )
            for instrument in INSTRUMENTS
        }
        total_rows = sum(item["row_count"] for item in verified.values())
        total_classifications = sum(item["classification_count"] for item in verified.values())
        if total_rows != completion["total_path_rows"]:
            raise ValueError("S2-T13 completion path-row count mismatch")
        if total_classifications != completion["total_classification_count"]:
            raise ValueError("S2-T13 completion classification count mismatch")
    except (OSError, ValueError, KeyError, pa.ArrowException) as exc:
        return {"status": "FAIL", "run_id": run_root.name, "reason": str(exc)}
    return {
        "status": "PASS",
        "run_id": run_root.name,
        "authority_hash": completion["authority_hash"],
        "snapshot_id": completion["snapshot_id"],
        "manifest_hash": completion["manifest_hash"],
        "catalog_hash": completion["catalog_hash"],
        "instruments": verified,
        "total_path_rows": total_rows,
        "total_classification_count": total_classifications,
        "historical_evidence_only": True,
        "stage3_locked": True,
    }


__all__ = [
    "AUTHORITY_ROOT",
    "COMBINATION_ORDER",
    "COMBINATIONS_PER_PATH",
    "RUNS_ROOT",
    "create_preflight_manifest",
    "current_code_commit",
    "execute_run",
    "find_resumable_run",
    "latest_preflight_manifest",
    "read_preflight_manifest",
    "resume_run",
    "verify_run",
]
