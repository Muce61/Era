"""Prepare every sealed T13 H2 Episode for outcome-blind T15 matching."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .features import NS, PERIOD_BLOCK_BOUNDARIES, ROLLING_FOLDS, information_span_is_eligible
from .production_core import EpisodeFeatureRequest, prepare_episode_features
from .t10_access import FixedT10Reader
from .v14_contracts import COMBINATION_ORDER, EXPECTED_H2_PATHS, canonical_hash

DECIMAL_TYPE = pa.decimal128(38, 18)
EPISODE_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("market_episode_id", pa.string(), nullable=False),
        pa.field("classification_row_hash", pa.string(), nullable=False),
        pa.field("parameter_set_id", pa.string(), nullable=False),
        pa.field("time_combination_id", pa.string(), nullable=False),
        pa.field("variant_id", pa.string(), nullable=False),
        pa.field("canonical_key_level_id", pa.string(), nullable=False),
        pa.field("anchor_ns", pa.int64(), nullable=False),
        pa.field("requested_window_end_ns", pa.int64(), nullable=False),
        pa.field("reference_price", DECIMAL_TYPE, nullable=False),
        pa.field("pre_registered_period", pa.string(), nullable=True),
        pa.field("evaluation_fold", pa.string(), nullable=True),
        pa.field("episode_status", pa.string(), nullable=False),
        pa.field("exclusion_reason", pa.string(), nullable=True),
        pa.field("high_timeframe_trend_state", pa.string(), nullable=True),
        pa.field("volatility_rms_bps", DECIMAL_TYPE, nullable=True),
        pa.field("activity_count_60s", pa.int64(), nullable=True),
        pa.field("key_level_distance_bps", DECIMAL_TYPE, nullable=True),
        pa.field("labels", pa.list_(pa.string()), nullable=False),
        pa.field("label_reasons", pa.list_(pa.string()), nullable=False),
        pa.field("strict_target_first", pa.list_(pa.bool_()), nullable=False),
        pa.field("source_quality_status", pa.string(), nullable=False),
        pa.field("source_gap_codes", pa.list_(pa.string()), nullable=False),
        pa.field("source_ambiguity_codes", pa.list_(pa.string()), nullable=False),
    ]
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_date(timestamp_ns: int) -> date:
    return datetime.fromtimestamp(timestamp_ns / NS, UTC).date()


def _period_block(anchor_ns: int) -> tuple[str, int] | None:
    for period, boundaries in PERIOD_BLOCK_BOUNDARIES.items():
        for index in range(5):
            if boundaries[index] <= anchor_ns < boundaries[index + 1]:
                return period, index
    return None


def _episode_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    timing = row.get("time_combination_id", row.get("timing_id"))
    if timing is None:
        raise ValueError("Episode binding lacks timing identity")
    return (
        str(row["market_episode_id"]),
        str(row["parameter_set_id"]),
        str(timing),
        str(row["variant_id"]),
    )


def _load_t10_bindings(
    reader: FixedT10Reader, *, instrument: str
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    trigger_rows = reader.read_physical_dataset(
        dataset_name="price_triggers",
        dataset_version="group1-v1-price-v1",
        instrument=instrument,
        variant="V1_PRICE",
        columns=["trigger_id", "event_parameter_set_id", "context_state", "status"],
    ).to_pylist()
    trigger_contexts: dict[tuple[str, str], tuple[str, str]] = {}
    for row in trigger_rows:
        trigger_key = (str(row["trigger_id"]), str(row["event_parameter_set_id"]))
        value = (str(row["context_state"]), str(row["status"]))
        existing_trigger = trigger_contexts.get(trigger_key)
        if existing_trigger is not None and existing_trigger != value:
            raise ValueError("T10 price-trigger composite Context binding conflict")
        trigger_contexts[trigger_key] = value
    result: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    columns = [
        "market_episode_id",
        "parameter_set_id",
        "time_combination_id",
        "variant_id",
        "canonical_key_level_id",
        "available_at_ts",
        "trigger_id",
    ]
    for version, variant in (
        ("group1-v1-price-v1", "V1_PRICE"),
        ("group1-v1-flow-v1", "V1_FLOW"),
    ):
        table = reader.read_physical_dataset(
            dataset_name="market_episodes",
            dataset_version=version,
            instrument=instrument,
            variant=variant,
            columns=columns,
        )
        for row in table.to_pylist():
            trigger_key = (str(row["trigger_id"]), str(row["parameter_set_id"]))
            context = trigger_contexts.get(trigger_key)
            if context is None:
                raise ValueError("T10 Episode lacks its sealed price-trigger Context")
            if context != ("UP", "PASS"):
                raise ValueError("T10 Episode binds a non-PASS or non-UP price trigger")
            row["context_state"] = context[0]
            key = _episode_key(row)
            existing = result.get(key)
            if existing is not None and existing != row:
                raise ValueError("T10 Episode composite binding conflict")
            result[key] = row
    return result


def _h2_rows(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe or missing T13 first-passage evidence")
    columns = [
        "instrument",
        "market_episode_id",
        "parameter_set_id",
        "timing_id",
        "variant_id",
        "evidence_level",
        "reference_price",
        "window_start_ns",
        "requested_window_end_ns",
        "combination_order",
        "labels",
        "label_reasons",
        "strict_target_first",
        "source_quality_status",
        "source_gap_codes",
        "source_ambiguity_codes",
        "classification_row_hash",
    ]
    table = pq.read_table(path, columns=columns)
    table = table.filter(pc.equal(table["evidence_level"], "H2"))
    rows = cast(list[dict[str, Any]], table.to_pylist())
    if len({str(row["classification_row_hash"]) for row in rows}) != len(rows):
        raise ValueError("duplicate T13 H2 classification row identity")
    return rows


def prepare_episode_evidence(
    *,
    reader: FixedT10Reader,
    t13_snapshot: Path,
    output_root: Path,
) -> tuple[dict[str, Any], Path]:
    """Produce one exact row for every sealed H2 path, with no control outcome read."""

    output = output_root / "prepared-episodes.parquet"
    report_path = output_root / "prepared-episodes.report.json"
    if output.exists() or report_path.exists():
        if output.is_symlink() or report_path.is_symlink():
            raise ValueError("symlinked prepared Episode evidence cannot be resumed")
        if not output.is_file() or not report_path.is_file():
            raise ValueError("partial prepared Episode evidence cannot be resumed")
        existing_payload = cast(dict[str, Any], json.loads(report_path.read_text(encoding="utf-8")))
        claimed_hash = existing_payload.get("report_hash")
        if (
            canonical_hash(
                {key: value for key, value in existing_payload.items() if key != "report_hash"}
            )
            != claimed_hash
        ):
            raise ValueError("prepared Episode report hash drift on resume")
        if (
            existing_payload.get("status") != "PASS"
            or existing_payload.get("parquet_sha256") != _sha256_file(output)
            or int(existing_payload.get("parquet_row_count", -1))
            != pq.ParquetFile(output).metadata.num_rows
            or int(existing_payload.get("source_h2_path_count", -1)) != EXPECTED_H2_PATHS
            or existing_payload.get("control_outcome_fields_read") != []
        ):
            raise ValueError("prepared Episode evidence failed resume validation")
        return existing_payload, output
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.partial")
    writer = pq.ParquetWriter(temporary, EPISODE_SCHEMA, compression="zstd")
    source_count = 0
    train_only_count = 0
    exclusion_counts: Counter[str] = Counter()
    eligible_count = 0
    try:
        for instrument in ("BTCUSDT", "ETHUSDT"):
            t13_rows = _h2_rows(t13_snapshot / instrument / "first_passage.parquet")
            bindings = _load_t10_bindings(reader, instrument=instrument)
            if len(bindings) != len(t13_rows):
                raise ValueError("T10/T13 Episode composite universe count drift")
            if {_episode_key(row) for row in t13_rows} != set(bindings):
                raise ValueError("T10/T13 Episode composite universe mismatch")
            source_count += len(t13_rows)
            grouped: dict[date, list[dict[str, Any]]] = {}
            finalized: list[dict[str, Any]] = []
            for row in t13_rows:
                if tuple(row["combination_order"]) != COMBINATION_ORDER:
                    raise ValueError("T13 event combination order drift")
                binding = bindings[_episode_key(row)]
                anchor_ns = int(row["window_start_ns"])
                if int(binding["available_at_ts"]) != anchor_ns:
                    raise ValueError("T10/T13 Episode anchor binding drift")
                block = _period_block(anchor_ns)
                base: dict[str, Any] = {
                    "instrument": instrument,
                    "market_episode_id": row["market_episode_id"],
                    "classification_row_hash": row["classification_row_hash"],
                    "parameter_set_id": row["parameter_set_id"],
                    "time_combination_id": row["timing_id"],
                    "variant_id": row["variant_id"],
                    "canonical_key_level_id": binding["canonical_key_level_id"],
                    "anchor_ns": anchor_ns,
                    "requested_window_end_ns": int(row["requested_window_end_ns"]),
                    "reference_price": row["reference_price"],
                    "pre_registered_period": block[0] if block is not None else None,
                    "evaluation_fold": (
                        f"F{block[1] - 1}" if block is not None and block[1] else None
                    ),
                    "episode_status": "PENDING",
                    "exclusion_reason": None,
                    "high_timeframe_trend_state": None,
                    "volatility_rms_bps": None,
                    "activity_count_60s": None,
                    "key_level_distance_bps": None,
                    "labels": row["labels"],
                    "label_reasons": row["label_reasons"],
                    "strict_target_first": row["strict_target_first"],
                    "source_quality_status": row["source_quality_status"],
                    "source_gap_codes": row["source_gap_codes"],
                    "source_ambiguity_codes": row["source_ambiguity_codes"],
                }
                if block is None:
                    base["episode_status"] = "EXCLUDED"
                    base["exclusion_reason"] = "OUTSIDE_SPLIT_INFORMATION_SPAN"
                    exclusion_counts[str(base["exclusion_reason"])] += 1
                    finalized.append(base)
                elif block[1] == 0:
                    base["episode_status"] = "TRAIN_ONLY_NOT_EVALUATED"
                    train_only_count += 1
                    finalized.append(base)
                else:
                    fold = f"F{block[1] - 1}"
                    contract = next(
                        item
                        for item in ROLLING_FOLDS
                        if item.period == block[0] and item.fold == fold
                    )
                    if not information_span_is_eligible(anchor_ns, contract):
                        base["episode_status"] = "EXCLUDED"
                        base["exclusion_reason"] = "OUTSIDE_SPLIT_INFORMATION_SPAN"
                        exclusion_counts[str(base["exclusion_reason"])] += 1
                        finalized.append(base)
                    else:
                        base["_request"] = EpisodeFeatureRequest(
                            episode_row_id=str(row["classification_row_hash"]),
                            anchor_ns=anchor_ns,
                            parameter_set_id=str(row["parameter_set_id"]),
                            canonical_key_level_id=str(binding["canonical_key_level_id"]),
                            reference_price=Decimal(row["reference_price"]),
                            high_timeframe_trend_state=str(binding["context_state"]),
                        )
                        grouped.setdefault(_utc_date(anchor_ns), []).append(base)
            for owner_date, rows in sorted(grouped.items()):
                requests = tuple(cast(EpisodeFeatureRequest, row["_request"]) for row in rows)
                prepared, excluded = prepare_episode_features(
                    reader,
                    instrument=instrument,
                    owner_date=owner_date,
                    requests=requests,
                )
                for base in rows:
                    request = cast(EpisodeFeatureRequest, base.pop("_request"))
                    feature = prepared.get(request.episode_row_id)
                    if feature is None:
                        reason = excluded[request.episode_row_id]
                        base["episode_status"] = "EXCLUDED"
                        base["exclusion_reason"] = reason
                        exclusion_counts[reason] += 1
                    else:
                        base.update(
                            {
                                "episode_status": "ELIGIBLE",
                                "high_timeframe_trend_state": feature.high_timeframe_trend_state,
                                "volatility_rms_bps": feature.volatility_rms_bps,
                                "activity_count_60s": feature.activity_count_60s,
                                "key_level_distance_bps": feature.key_level_distance_bps,
                            }
                        )
                        eligible_count += 1
                    finalized.append(base)
            writer.write_table(pa.Table.from_pylist(finalized, schema=EPISODE_SCHEMA))
    finally:
        writer.close()
    os.replace(temporary, output)
    if source_count != EXPECTED_H2_PATHS:
        raise ValueError("prepared Episode source baseline drift")
    if source_count != train_only_count + sum(exclusion_counts.values()) + eligible_count:
        raise ValueError("prepared Episode counts do not reconcile")
    payload: dict[str, Any] = {
        "schema_name": "stage2-s2t15-prepared-episode-report",
        "schema_version": "1.0",
        "status": "PASS",
        "source_h2_path_count": source_count,
        "train_only_not_evaluated_count": train_only_count,
        "excluded_episode_count": sum(exclusion_counts.values()),
        "eligible_episode_count": eligible_count,
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
        "parquet_sha256": _sha256_file(output),
        "parquet_row_count": pq.ParquetFile(output).metadata.num_rows,
        "control_outcome_fields_read": [],
        "historical_evidence_only": True,
    }
    payload["report_hash"] = canonical_hash(payload)
    with report_path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    return payload, output
