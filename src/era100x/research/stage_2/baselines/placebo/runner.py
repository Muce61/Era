"""Append-only S2P14-T17 producer, reconciliation and independent verification."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import sqlite3
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.baselines.conditional.outcome_blind_producer import (
    BinningIndex,
)
from era100x.research.stage_2.baselines.conditional.v14_contracts import (
    BACKWARD_PURGE_SECONDS,
    COMBINATION_ORDER,
    FORWARD_EMBARGO_SECONDS,
    OutcomeCell,
)

from .contracts import (
    BlindPlaceboSelection,
    PlaceboCandidate,
    PlaceboEventReference,
    PlaceboMatchMatrix,
    PlaceboSummary,
    S2P14T17Authority,
    canonical_hash,
    parse_outcome_cells,
)
from .governance import (
    PlaceboPolicy,
    T16Binding,
    audit_t16_source,
    freeze_authority,
    read_json,
    repository_clean,
    repository_commit,
    sha256_file,
    validate_approval,
    write_exclusive,
)
from .matching import select_placebo

NS = 1_000_000_000
EXPECTED_GROUPS = 456
EXPECTED_SUMMARIES = 13_680
SELECTION_COLUMNS = (
    "instrument",
    "pre_registered_period",
    "evaluation_fold",
    "parameter_set_id",
    "time_combination_id",
    "market_episode_id",
    "classification_row_hash",
    "status",
    "match_level",
    "control_candidate_ids",
    "selected_candidates_json",
    "selection_hash",
)
SELECTION_SCHEMA = pa.schema(
    [
        pa.field("source_episode_id", pa.string(), nullable=False),
        pa.field("source_h2_path_hash", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("placebo_event_candidate_id", pa.string()),
        pa.field("placebo_event_match_level", pa.string(), nullable=False),
        pa.field("placebo_control_match_level", pa.string(), nullable=False),
        pa.field("placebo_control_candidate_ids", pa.list_(pa.string()), nullable=False),
        pa.field("selection_hash", pa.string(), nullable=False),
        pa.field("selection_json", pa.string(), nullable=False),
    ]
)
MATCH_SCHEMA = pa.schema(
    [
        pa.field("source_episode_id", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("placebo_event_candidate_id", pa.string()),
        pa.field("placebo_control_candidate_ids", pa.list_(pa.string()), nullable=False),
        pa.field("output_hash", pa.string(), nullable=False),
        pa.field("matrix_json", pa.string(), nullable=False),
    ]
)
SUMMARY_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("pre_registered_period", pa.string(), nullable=False),
        pa.field("evaluation_fold", pa.string(), nullable=False),
        pa.field("parameter_set_id", pa.string(), nullable=False),
        pa.field("time_combination_id", pa.string(), nullable=False),
        pa.field("combination_id", pa.string(), nullable=False),
        pa.field("slot_count", pa.int64(), nullable=False),
        pa.field("matched_count", pa.int64(), nullable=False),
        pa.field("unmatched_count", pa.int64(), nullable=False),
        pa.field("placebo_event_rate", pa.string()),
        pa.field("placebo_baseline_rate", pa.string()),
        pa.field("placebo_delta", pa.string()),
        pa.field("real_event_delta", pa.string()),
        pa.field("placebo_minus_real_delta", pa.string()),
        pa.field("research_status", pa.string(), nullable=False),
    ]
)

ProgressCallback = Callable[[dict[str, Any]], None]


def _candidate(payload: dict[str, Any]) -> PlaceboCandidate:
    fields = PlaceboCandidate.model_fields
    normalized = {key: value for key, value in payload.items() if key in fields}
    return PlaceboCandidate.model_validate(normalized)


def _utc_parts(timestamp_ns: int) -> tuple[int, int, int]:
    instant = datetime.fromtimestamp(timestamp_ns / NS, UTC)
    return instant.year, (instant.month - 1) // 3 + 1, instant.hour // 4


def _group_relative(selection_path: Path, selections_root: Path) -> Path:
    relative = selection_path.relative_to(selections_root)
    return relative.with_suffix("")


def _selection_files(root: Path) -> tuple[Path, ...]:
    files = tuple(
        path
        for path in root.rglob("*.parquet")
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )
    if len(files) != EXPECTED_GROUPS:
        raise ValueError(f"T16 selection group count drift: {len(files)}")
    return tuple(sorted(files))


def _prepared_episode_index(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    columns = [
        "market_episode_id",
        "classification_row_hash",
        "parameter_set_id",
        "time_combination_id",
        "anchor_ns",
        "episode_status",
        "high_timeframe_trend_state",
        "volatility_rms_bps",
        "activity_count_60s",
        "key_level_distance_bps",
    ]
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=32_768, columns=columns):
        for row in batch.to_pylist():
            if row["episode_status"] != "ELIGIBLE":
                continue
            key = (
                str(row["market_episode_id"]),
                str(row["parameter_set_id"]),
                str(row["time_combination_id"]),
            )
            if key in result:
                raise ValueError("duplicate eligible T16 prepared episode identity")
            result[key] = cast(dict[str, Any], row)
    return result


def _candidate_pool(rows: list[dict[str, Any]]) -> tuple[PlaceboCandidate, ...]:
    by_id: dict[str, PlaceboCandidate] = {}
    for row in rows:
        payload = json.loads(str(row["selected_candidates_json"]))
        if not isinstance(payload, list):
            raise ValueError("T16 selected_candidates_json must be a list")
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("T16 selected candidate payload must be an object")
            candidate = _candidate(cast(dict[str, Any], item))
            previous = by_id.setdefault(candidate.control_candidate_id, candidate)
            if previous != candidate:
                raise ValueError("candidate ID maps to conflicting payloads")
    return tuple(by_id[key] for key in sorted(by_id))


def _event_reference(
    *,
    selection_row: dict[str, Any],
    prepared: dict[str, Any],
    original_controls: tuple[str, ...],
    candidates: tuple[PlaceboCandidate, ...],
    bins: BinningIndex,
) -> PlaceboEventReference:
    if not candidates:
        raise ValueError("matched T16 group has no candidate metadata")
    if prepared["classification_row_hash"] != selection_row["classification_row_hash"]:
        raise ValueError("prepared Episode and T16 selection Hash binding disagree")
    exemplar = candidates[0]
    anchor = int(prepared["anchor_ns"])
    year, quarter, bucket = _utc_parts(anchor)
    instrument = str(selection_row["instrument"])
    period = str(selection_row["pre_registered_period"])
    fold = str(selection_row["evaluation_fold"])
    parameter = str(selection_row["parameter_set_id"])
    volatility = bins.boundary(
        instrument=instrument,
        period=period,
        fold=fold,
        feature_kind="VOLATILITY",
    )
    activity = bins.boundary(
        instrument=instrument,
        period=period,
        fold=fold,
        feature_kind="TRADES_ACTIVITY",
    )
    distance = bins.boundary(
        instrument=instrument,
        period=period,
        fold=fold,
        feature_kind="KEY_LEVEL_DISTANCE",
        parameter_set_id=parameter,
    )
    return PlaceboEventReference(
        source_episode_id=str(selection_row["market_episode_id"]),
        source_h2_path_hash=str(selection_row["classification_row_hash"]),
        instrument=cast(Any, instrument),
        anchor_ns=anchor,
        direction=exemplar.direction,
        setup_id=exemplar.setup_id,
        context_model_id=exemplar.context_model_id,
        high_timeframe_trend_state=str(prepared["high_timeframe_trend_state"]),
        pre_registered_period=cast(Any, period),
        evaluation_fold=cast(Any, fold),
        parameter_set_id=parameter,
        time_combination_id=cast(Any, selection_row["time_combination_id"]),
        label_contract_hash=exemplar.label_contract_hash,
        volatility_quintile=volatility.assign(Decimal(prepared["volatility_rms_bps"])),
        activity_quintile=activity.assign(Decimal(prepared["activity_count_60s"])),
        key_level_distance_quintile=distance.assign(Decimal(prepared["key_level_distance_bps"])),
        utc_four_hour_bucket=bucket,
        utc_calendar_quarter=quarter,
        utc_calendar_year=year,
        binning_snapshot_hash=bins.combined_hash(instrument, period, fold, parameter),
        information_span_start_ns=anchor - BACKWARD_PURGE_SECONDS * NS,
        information_span_end_ns=anchor + FORWARD_EMBARGO_SECONDS * NS,
        original_control_candidate_ids=original_controls,
    )


def produce_blind_selections(
    *,
    binding: T16Binding,
    output_root: Path,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Produce and seal all 456 outcome-blind group files."""

    existing_seal_path = output_root / "selection-seal.json"
    if existing_seal_path.is_file() and not existing_seal_path.is_symlink():
        existing_seal = read_json(existing_seal_path)
        claimed = existing_seal.get("seal_hash")
        if (
            isinstance(claimed, str)
            and canonical_hash(
                {key: value for key, value in existing_seal.items() if key != "seal_hash"}
            )
            == claimed
            and existing_seal.get("status") == "SEALED"
            and existing_seal.get("outcome_fields_read") == []
        ):
            return existing_seal
        raise ValueError("existing blind-selection seal is invalid")
    selection_files = _selection_files(binding.selections_root)
    prepared = _prepared_episode_index(binding.prepared_episodes_path)
    binning_manifest = next(
        path
        for path in binding.binning_root.glob("binning-set-*.json")
        if path.is_file() and not path.name.startswith("._")
    )
    bins = BinningIndex(binning_manifest, authority_hash=binding.authority_hash)
    output_root.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    total_slots = 0
    total_source_unmatched = 0
    for index, source_path in enumerate(selection_files, start=1):
        table = pq.read_table(source_path, columns=list(SELECTION_COLUMNS))
        rows = cast(list[dict[str, Any]], table.to_pylist())
        matched_rows = [row for row in rows if row["status"] == "MATCHED"]
        source_unmatched = len(rows) - len(matched_rows)
        candidates = _candidate_pool(matched_rows)
        used_placebo_event_ids: set[str] = set()
        selections: list[BlindPlaceboSelection] = []
        for row in sorted(matched_rows, key=lambda item: str(item["market_episode_id"])):
            key = (
                str(row["market_episode_id"]),
                str(row["parameter_set_id"]),
                str(row["time_combination_id"]),
            )
            source_prepared = prepared.get(key)
            if source_prepared is None:
                raise ValueError(f"missing eligible prepared episode: {key}")
            original_controls = tuple(str(value) for value in row["control_candidate_ids"])
            source = _event_reference(
                selection_row=row,
                prepared=source_prepared,
                original_controls=original_controls,
                candidates=candidates,
                bins=bins,
            )
            selections.append(
                select_placebo(
                    source,
                    candidates,
                    used_placebo_event_ids=used_placebo_event_ids,
                )
            )
        relative = _group_relative(source_path, binding.selections_root)
        target = output_root / relative.with_suffix(".parquet")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload_rows = [
            {
                "source_episode_id": item.source_episode_id,
                "source_h2_path_hash": item.source_h2_path_hash,
                "status": item.status,
                "placebo_event_candidate_id": item.placebo_event_candidate_id,
                "placebo_event_match_level": item.placebo_event_match_level,
                "placebo_control_match_level": item.placebo_control_match_level,
                "placebo_control_candidate_ids": list(item.placebo_control_candidate_ids),
                "selection_hash": item.selection_hash,
                "selection_json": item.model_dump_json(),
            }
            for item in selections
        ]
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise ValueError("unsafe blind-selection checkpoint")
            existing_rows = pq.read_table(target, columns=["selection_json"]).to_pylist()
            if [row["selection_json"] for row in existing_rows] != [
                row["selection_json"] for row in payload_rows
            ]:
                raise ValueError("blind-selection checkpoint input or output drift")
        else:
            pq.write_table(pa.Table.from_pylist(payload_rows, schema=SELECTION_SCHEMA), target)
        counts = Counter(item.status for item in selections)
        report = {
            "group": str(relative),
            "slot_count": len(selections),
            "source_unmatched_not_sampled": source_unmatched,
            "matched": counts["MATCHED"],
            "unmatched_no_placebo_event": counts["UNMATCHED_NO_PLACEBO_EVENT"],
            "unmatched_controls": counts["UNMATCHED_CONTROLS"],
            "unique_placebo_events": len(used_placebo_event_ids),
            "output_hash": sha256_file(target),
        }
        reports.append(report)
        total_slots += len(selections)
        total_source_unmatched += source_unmatched
        if progress is not None:
            progress(
                {
                    "phase": "BLIND_SELECTION",
                    "processed_units": index,
                    "total_units": len(selection_files),
                    "percent": index * 100 / len(selection_files),
                    "heartbeat_at": datetime.now(UTC).isoformat(),
                }
            )
    if (
        total_slots != binding.counts["matched"]
        or total_source_unmatched != binding.counts["unmatched"]
    ):
        raise ValueError("placebo slot/source-unmatched reconciliation failed")
    selection_set_hash = canonical_hash(
        [{"group": item["group"], "output_hash": item["output_hash"]} for item in reports]
    )
    seal = {
        "schema_name": "s2p14-t17-blind-selection-seal",
        "schema_version": "1.0",
        "source_t16_verify_hash": binding.verify_hash,
        "group_count": len(reports),
        "placebo_slot_count": total_slots,
        "source_unmatched_not_sampled": total_source_unmatched,
        "selection_set_hash": selection_set_hash,
        "outcome_fields_read": [],
        "status": "SEALED",
    }
    seal["seal_hash"] = canonical_hash(seal)
    write_exclusive(output_root / "selection-seal.json", seal)
    return seal


def _create_outcome_index(
    binding: T16Binding,
    database_path: Path,
    *,
    progress: ProgressCallback | None,
) -> sqlite3.Connection:
    database = sqlite3.connect(database_path)
    database.execute("PRAGMA journal_mode=WAL")
    database.execute("PRAGMA synchronous=FULL")
    database.execute(
        "CREATE TABLE outcomes(candidate_id TEXT PRIMARY KEY, matrix_id TEXT NOT NULL, "
        "outcomes_json TEXT NOT NULL)"
    )
    parquet = pq.ParquetFile(binding.outcome_path)
    processed = 0
    for batch in parquet.iter_batches(
        batch_size=8192,
        columns=["control_candidate_id", "control_outcome_matrix_id", "outcomes_json"],
    ):
        rows = [
            (
                str(row["control_candidate_id"]),
                str(row["control_outcome_matrix_id"]),
                str(row["outcomes_json"]),
            )
            for row in batch.to_pylist()
        ]
        database.executemany("INSERT INTO outcomes VALUES(?,?,?)", rows)
        processed += len(rows)
        if processed % 65_536 == 0:
            database.commit()
            if progress is not None:
                progress(
                    {
                        "phase": "OUTCOME_ATTACH",
                        "subphase": "INDEX_T16_OUTCOMES",
                        "processed_units": processed,
                        "total_units": binding.counts["controls"],
                        "percent": processed * 100 / binding.counts["controls"],
                        "heartbeat_at": datetime.now(UTC).isoformat(),
                    }
                )
    database.commit()
    if (
        database.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
        != binding.counts["controls"]
    ):
        raise ValueError("T16 outcome index count drift")
    database.execute(
        "CREATE TABLE real_matches(episode_id TEXT PRIMARY KEY, output_hash TEXT NOT NULL, "
        "matrix_json TEXT NOT NULL)"
    )
    parquet = pq.ParquetFile(binding.match_path)
    for batch in parquet.iter_batches(
        batch_size=4096,
        columns=["market_episode_id", "output_hash", "matrix_json"],
    ):
        database.executemany(
            "INSERT INTO real_matches VALUES(?,?,?)",
            [
                (
                    str(row["market_episode_id"]),
                    str(row["output_hash"]),
                    str(row["matrix_json"]),
                )
                for row in batch.to_pylist()
            ],
        )
    database.commit()
    return database


def _outcome(
    database: sqlite3.Connection, candidate_id: str
) -> tuple[str, tuple[OutcomeCell, ...]]:
    row = database.execute(
        "SELECT matrix_id,outcomes_json FROM outcomes WHERE candidate_id=?", (candidate_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"outcome binding missing for candidate {candidate_id}")
    return str(row[0]), parse_outcome_cells(str(row[1]))


def _real_matrix(
    database: sqlite3.Connection, episode_id: str
) -> tuple[str, tuple[OutcomeCell, ...], tuple[str, ...]]:
    row = database.execute(
        "SELECT output_hash,matrix_json FROM real_matches WHERE episode_id=?", (episode_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"real T16 matrix missing for episode {episode_id}")
    payload = json.loads(str(row[1]))
    if not isinstance(payload, dict) or payload.get("market_episode_id") != episode_id:
        raise ValueError("real T16 outcome binding mismatch")
    event = tuple(OutcomeCell.model_validate(item) for item in payload["event_outcomes"])
    controls = tuple(str(value) for value in payload["control_candidate_ids"])
    return str(row[0]), event, controls


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return Decimal(numerator) / Decimal(denominator)


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def attach_outcomes_and_summarize(
    *,
    binding: T16Binding,
    blind_root: Path,
    output_root: Path,
    local_database_path: Path,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Attach outcomes only after a valid all-group blind-selection seal exists."""

    existing_reconciliation = output_root / "reconciliation.json"
    if existing_reconciliation.is_file() and not existing_reconciliation.is_symlink():
        payload = read_json(existing_reconciliation)
        claimed = payload.get("reconciliation_hash")
        if (
            isinstance(claimed, str)
            and canonical_hash(
                {key: value for key, value in payload.items() if key != "reconciliation_hash"}
            )
            == claimed
            and payload.get("status") == "PASS"
        ):
            return payload
        raise ValueError("existing placebo reconciliation is invalid")
    seal = read_json(blind_root / "selection-seal.json")
    if (
        seal.get("status") != "SEALED"
        or seal.get("outcome_fields_read") != []
        or seal.get("group_count") != EXPECTED_GROUPS
        or not isinstance(seal.get("seal_hash"), str)
        or canonical_hash({k: v for k, v in seal.items() if k != "seal_hash"}) != seal["seal_hash"]
    ):
        raise ValueError("blind selections are not completely sealed")
    output_root.mkdir(parents=True, exist_ok=True)
    database = _create_outcome_index(binding, local_database_path, progress=progress)
    reports: list[dict[str, Any]] = []
    all_summaries: list[dict[str, Any]] = []
    reuse: Counter[str] = Counter()
    total_matched = 0
    total_unmatched = 0
    total_assignments = 0
    try:
        files = tuple(
            sorted(
                path
                for path in blind_root.rglob("*.parquet")
                if not path.name.startswith("._") and not path.is_symlink()
            )
        )
        if len(files) != EXPECTED_GROUPS:
            raise ValueError("blind selection group count drift before outcome attach")
        for group_index, source_path in enumerate(files, start=1):
            relative = source_path.relative_to(blind_root)
            selections = [
                BlindPlaceboSelection.model_validate_json(row["selection_json"])
                for row in pq.read_table(source_path).to_pylist()
            ]
            matches: list[PlaceboMatchMatrix] = []
            for selection in selections:
                real_hash, real_event, real_control_ids = _real_matrix(
                    database, selection.source_episode_id
                )
                real_controls = tuple(_outcome(database, item)[1] for item in real_control_ids)
                if selection.status == "MATCHED":
                    assert selection.placebo_event_candidate_id is not None
                    event_matrix_id, placebo_event = _outcome(
                        database, selection.placebo_event_candidate_id
                    )
                    controls = tuple(
                        _outcome(database, item) for item in selection.placebo_control_candidate_ids
                    )
                    for candidate_id in selection.placebo_control_candidate_ids:
                        reuse[candidate_id] += 1
                    match = PlaceboMatchMatrix.seal(
                        {
                            "source_episode_id": selection.source_episode_id,
                            "source_real_matrix_hash": real_hash,
                            "selection_hash": selection.selection_hash,
                            "status": selection.status,
                            "placebo_event_candidate_id": (selection.placebo_event_candidate_id),
                            "placebo_event_outcome_matrix_id": event_matrix_id,
                            "placebo_event_outcomes": placebo_event,
                            "placebo_control_candidate_ids": (
                                selection.placebo_control_candidate_ids
                            ),
                            "placebo_control_outcome_matrix_ids": tuple(
                                item[0] for item in controls
                            ),
                            "placebo_control_outcomes": tuple(item[1] for item in controls),
                            "real_event_outcomes": real_event,
                            "real_control_outcomes": real_controls,
                        }
                    )
                    total_matched += 1
                    total_assignments += 5
                else:
                    match = PlaceboMatchMatrix.seal(
                        {
                            "source_episode_id": selection.source_episode_id,
                            "source_real_matrix_hash": real_hash,
                            "selection_hash": selection.selection_hash,
                            "status": selection.status,
                            "placebo_event_candidate_id": (selection.placebo_event_candidate_id),
                            "placebo_event_outcome_matrix_id": None,
                            "real_event_outcomes": real_event,
                            "real_control_outcomes": real_controls,
                        }
                    )
                    total_unmatched += 1
                matches.append(match)
            target = output_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            match_rows = [
                {
                    "source_episode_id": item.source_episode_id,
                    "status": item.status,
                    "placebo_event_candidate_id": item.placebo_event_candidate_id,
                    "placebo_control_candidate_ids": list(item.placebo_control_candidate_ids),
                    "output_hash": item.output_hash,
                    "matrix_json": item.model_dump_json(),
                }
                for item in matches
            ]
            if target.exists():
                if target.is_symlink() or not target.is_file():
                    raise ValueError("unsafe placebo match checkpoint")
                existing = pq.read_table(target, columns=["matrix_json"]).to_pylist()
                if [row["matrix_json"] for row in existing] != [
                    row["matrix_json"] for row in match_rows
                ]:
                    raise ValueError("placebo match checkpoint input or output drift")
            else:
                pq.write_table(
                    pa.Table.from_pylist(match_rows, schema=MATCH_SCHEMA),
                    target,
                )
            parts = relative.parts
            instrument, period, fold = parts[0], parts[1], parts[2]
            parameter, timing = relative.stem.rsplit("__", 1)
            for cell_index, combination in enumerate(COMBINATION_ORDER):
                matched = [item for item in matches if item.status == "MATCHED"]
                placebo_event_success = sum(
                    item.placebo_event_outcomes[cell_index].strict_target_first for item in matched
                )
                placebo_baseline_success = sum(
                    sum(
                        controls[cell_index].strict_target_first
                        for controls in item.placebo_control_outcomes
                    )
                    for item in matched
                )
                real_event_success = sum(
                    item.real_event_outcomes[cell_index].strict_target_first for item in matches
                )
                real_baseline_success = sum(
                    sum(
                        controls[cell_index].strict_target_first
                        for controls in item.real_control_outcomes
                    )
                    for item in matches
                )
                placebo_event_rate = _rate(placebo_event_success, len(matched))
                placebo_baseline_rate = _rate(placebo_baseline_success, len(matched) * 5)
                real_event_rate = _rate(real_event_success, len(matches))
                real_baseline_rate = _rate(real_baseline_success, len(matches) * 5)
                placebo_delta = (
                    None
                    if placebo_event_rate is None or placebo_baseline_rate is None
                    else placebo_event_rate - placebo_baseline_rate
                )
                real_delta = (
                    None
                    if real_event_rate is None or real_baseline_rate is None
                    else real_event_rate - real_baseline_rate
                )
                difference = (
                    None
                    if placebo_delta is None or real_delta is None
                    else placebo_delta - real_delta
                )
                summary = PlaceboSummary(
                    instrument=cast(Any, instrument),
                    pre_registered_period=cast(Any, period),
                    evaluation_fold=cast(Any, fold),
                    parameter_set_id=parameter,
                    time_combination_id=cast(Any, timing),
                    combination_id=combination,
                    slot_count=len(matches),
                    matched_count=len(matched),
                    unmatched_count=len(matches) - len(matched),
                    placebo_event_rate=_text(placebo_event_rate),
                    placebo_baseline_rate=_text(placebo_baseline_rate),
                    placebo_delta=_text(placebo_delta),
                    real_event_delta=_text(real_delta),
                    placebo_minus_real_delta=_text(difference),
                )
                all_summaries.append(summary.model_dump(mode="python"))
            reports.append(
                {
                    "group": str(relative.with_suffix("")),
                    "slot_count": len(matches),
                    "matched": sum(item.status == "MATCHED" for item in matches),
                    "unmatched": sum(item.status != "MATCHED" for item in matches),
                    "output_hash": sha256_file(target),
                }
            )
            if progress is not None:
                progress(
                    {
                        "phase": "OUTCOME_ATTACH",
                        "subphase": "GROUPS",
                        "processed_units": group_index,
                        "total_units": len(files),
                        "percent": group_index * 100 / len(files),
                        "heartbeat_at": datetime.now(UTC).isoformat(),
                    }
                )
    finally:
        database.close()
    if len(all_summaries) != EXPECTED_SUMMARIES:
        raise ValueError("placebo summary row count drift")
    summary_path = output_root / "descriptive_summaries.parquet"
    if summary_path.exists():
        if summary_path.is_symlink() or pq.read_table(summary_path).to_pylist() != all_summaries:
            raise ValueError("placebo summary checkpoint drift")
    else:
        pq.write_table(
            pa.Table.from_pylist(all_summaries, schema=SUMMARY_SCHEMA),
            summary_path,
        )
    if total_matched + total_unmatched != binding.counts["matched"]:
        raise ValueError("placebo slot reconciliation failed")
    if total_assignments != total_matched * 5:
        raise ValueError("placebo assignment reconciliation failed")
    unique_used = len(reuse)
    report = {
        "schema_name": "s2p14-t17-reconciliation",
        "schema_version": "1.0",
        "source_eligible": binding.counts["eligible"],
        "source_matched_slots": binding.counts["matched"],
        "source_unmatched_not_sampled": binding.counts["unmatched"],
        "placebo_matched": total_matched,
        "placebo_unmatched": total_unmatched,
        "assignments": total_assignments,
        "unique_assigned_controls": unique_used,
        "reused_assignment_count": total_assignments - unique_used,
        "group_count": len(reports),
        "summary_row_count": len(all_summaries),
        "duplicate_placebo_event_within_group": 0,
        "orphan_assignment_count": 0,
        "duplicate_assignment_within_matrix": 0,
        "status": "PASS",
        "research_status": "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING",
    }
    report["reconciliation_hash"] = canonical_hash(report)
    write_exclusive(output_root / "reconciliation.json", report)
    return report


def _catalog(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not path.name.startswith("._")
        and path.name not in {"catalog.json", "manifest.json", "verify.json"}
    ):
        relative = path.relative_to(root)
        entry: dict[str, Any] = {
            "relative_path": str(relative),
            "byte_size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if path.suffix == ".parquet":
            entry["row_count"] = pq.ParquetFile(path).metadata.num_rows
        files.append(entry)
    catalog: dict[str, Any] = {
        "schema_name": "s2p14-t17-catalog",
        "schema_version": "1.0",
        "files": files,
    }
    catalog["catalog_hash"] = canonical_hash(catalog)
    return catalog


def publish_run(
    *,
    run_root: Path,
    authority: S2P14T17Authority,
    binding: T16Binding,
    reconciliation: dict[str, Any],
) -> dict[str, Any]:
    snapshot_source = run_root / "work"
    catalog = _catalog(snapshot_source)
    snapshot_id = str(catalog["catalog_hash"])
    snapshot = run_root / "published/snapshots" / snapshot_id
    if snapshot.exists():
        raise FileExistsError("placebo snapshot already exists")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        snapshot_source,
        snapshot,
        ignore=shutil.ignore_patterns("._*", ".DS_Store", "*.sqlite", "*.sqlite-*"),
    )
    write_exclusive(snapshot / "catalog.json", catalog)
    manifest: dict[str, Any] = {
        "schema_name": "s2p14-t17-manifest",
        "schema_version": "1.0",
        "run_id": run_root.name,
        "snapshot_id": snapshot_id,
        "catalog_hash": catalog["catalog_hash"],
        "authority_hash": authority.authority_hash,
        "source_t16_verify_hash": binding.verify_hash,
        "source_t16_snapshot_id": binding.snapshot_id,
        "reconciliation_hash": reconciliation["reconciliation_hash"],
        "historical_evidence_only": True,
        "research_status": "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING",
        "stage3_locked": True,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    write_exclusive(snapshot / "manifest.json", manifest)
    return manifest


def verify_run(run_root: Path, *, binding: T16Binding | None = None) -> dict[str, Any]:
    snapshots = tuple(
        path
        for path in (run_root / "published/snapshots").glob("*")
        if path.is_dir() and not path.is_symlink()
    )
    if len(snapshots) != 1:
        raise ValueError("placebo Run must publish exactly one snapshot")
    snapshot = snapshots[0]
    catalog = read_json(snapshot / "catalog.json")
    manifest = read_json(snapshot / "manifest.json")
    if (
        not isinstance(catalog.get("catalog_hash"), str)
        or canonical_hash({k: v for k, v in catalog.items() if k != "catalog_hash"})
        != catalog["catalog_hash"]
        or not isinstance(manifest.get("manifest_hash"), str)
        or canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
        != manifest["manifest_hash"]
        or manifest.get("catalog_hash") != catalog.get("catalog_hash")
        or snapshot.name != catalog.get("catalog_hash")
        or manifest.get("stage3_locked") is not True
    ):
        raise ValueError("placebo Manifest/Catalog self-hash drift")
    total_match_rows = 0
    summary_rows = 0
    for entry in cast(list[dict[str, Any]], catalog["files"]):
        relative = Path(str(entry["relative_path"]))
        target = snapshot / relative
        if sha256_file(target) != entry["sha256"]:
            raise ValueError(f"placebo evidence Hash drift: {relative}")
        if relative.parts[:2] == ("results", "matches") and target.suffix == ".parquet":
            total_match_rows += pq.ParquetFile(target).metadata.num_rows
        if relative.name == "descriptive_summaries.parquet":
            summary_rows = pq.ParquetFile(target).metadata.num_rows
    reconciliation = read_json(snapshot / "results/reconciliation.json")
    if (
        not isinstance(reconciliation.get("reconciliation_hash"), str)
        or canonical_hash({k: v for k, v in reconciliation.items() if k != "reconciliation_hash"})
        != reconciliation["reconciliation_hash"]
        or reconciliation.get("status") != "PASS"
        or reconciliation.get("group_count") != EXPECTED_GROUPS
        or reconciliation.get("summary_row_count") != EXPECTED_SUMMARIES
        or total_match_rows != reconciliation.get("source_matched_slots")
        or summary_rows != EXPECTED_SUMMARIES
    ):
        raise ValueError("placebo full reconciliation failed")
    if binding is not None and manifest.get("source_t16_verify_hash") != binding.verify_hash:
        raise ValueError("placebo source T16 binding drift")
    verify: dict[str, Any] = {
        "schema_name": "s2p14-t17-verify-record",
        "schema_version": "1.0",
        "run_id": run_root.name,
        "snapshot_id": snapshot.name,
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "reconciliation_hash": reconciliation["reconciliation_hash"],
        "placebo_slot_count": total_match_rows,
        "placebo_matched": reconciliation["placebo_matched"],
        "placebo_unmatched": reconciliation["placebo_unmatched"],
        "summary_row_count": summary_rows,
        "status": "PASS",
        "research_status": "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING",
        "stage3_locked": True,
    }
    verify["verify_hash"] = canonical_hash(verify)
    return verify


def _progress_writer(path: Path, run_id: str) -> ProgressCallback:
    started = time.monotonic()

    def update(payload: dict[str, Any]) -> None:
        value = {
            "schema_name": "s2p14-t17-progress",
            "schema_version": "1.0",
            "run_id": run_id,
            "status": "IN_PROGRESS",
            "elapsed_seconds": int(time.monotonic() - started),
            **payload,
        }
        value["progress_hash"] = canonical_hash(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        )
        os.replace(temporary, path)

    return update


def _promote_result_metadata(results_root: Path) -> None:
    for name in ("descriptive_summaries.parquet", "reconciliation.json"):
        source = results_root / "matches" / name
        destination = results_root / name
        if destination.exists():
            if not source.exists() or sha256_file(source) != sha256_file(destination):
                raise ValueError(f"resumed placebo {name} changed")
            source.unlink()
        else:
            shutil.move(str(source), str(destination))


def run_formal(
    *,
    policy: PlaceboPolicy,
    approval_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    if not repository_clean(repository_root):
        raise ValueError("formal T17 Run requires a clean repository")
    binding = audit_t16_source(policy, full_hash_scan=True)
    approval = validate_approval(
        approval_path,
        policy=policy,
        repository_root=repository_root,
        binding=binding,
    )
    lock_path = policy.operations_root / "run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another formal T17 Run holds the unique lock") from exc
        authorities = policy.evidence_root / "authorities"
        existing_authorities = tuple(authorities.glob("authority-*.json"))
        existing_runs = tuple((policy.evidence_root / "runs").glob("stage2-s2p14-t17-*"))
        if existing_authorities or existing_runs:
            raise ValueError("formal T17 successor already exists")
        authority = freeze_authority(
            policy=policy,
            approval=approval,
            binding=binding,
            repository_root=repository_root,
        )
        authority_path = authorities / f"authority-{authority.authority_hash}.json"
        write_exclusive(
            authority_path,
            json.loads(authority.model_dump_json()),
        )
        reread = S2P14T17Authority.model_validate_json(authority_path.read_text())
        if reread.authority_hash != authority.authority_hash:
            raise ValueError("placebo Authority read-back failed")
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"stage2-s2p14-t17-{timestamp}-{authority.authority_hash[:12]}"
        run_root = policy.evidence_root / "runs" / run_id
        run_root.mkdir(parents=True, exist_ok=False)
        run_contract: dict[str, Any] = {
            "schema_name": "s2p14-t17-run-contract",
            "schema_version": "1.0",
            "run_id": run_id,
            "authority_hash": authority.authority_hash,
            "approval_hash": approval["approval_hash"],
            "code_commit": authority.code_commit,
            "policy_hash": policy.policy_hash,
            "source_t16_verify_hash": binding.verify_hash,
            "status": "UNPUBLISHED",
        }
        run_contract["run_contract_hash"] = canonical_hash(run_contract)
        write_exclusive(run_root / "run-contract.json", run_contract)
        progress = _progress_writer(run_root / "checkpoint.json", run_id)
        progress(
            {
                "phase": "AUDIT",
                "processed_units": 1,
                "total_units": 1,
                "percent": 100.0,
                "heartbeat_at": datetime.now(UTC).isoformat(),
            }
        )
        blind_root = run_root / "work/blind-selections"
        produce_blind_selections(binding=binding, output_root=blind_root, progress=progress)
        local_root = Path(tempfile.mkdtemp(prefix="s2p14-t17-"))
        try:
            results_root = run_root / "work/results"
            reconciliation = attach_outcomes_and_summarize(
                binding=binding,
                blind_root=blind_root,
                output_root=results_root / "matches",
                local_database_path=local_root / "outcomes.sqlite",
                progress=progress,
            )
            _promote_result_metadata(results_root)
            manifest = publish_run(
                run_root=run_root,
                authority=authority,
                binding=binding,
                reconciliation=reconciliation,
            )
            verify = verify_run(run_root, binding=binding)
            verify_path = run_root / "verify" / f"{verify['verify_hash']}.json"
            write_exclusive(verify_path, verify)
        finally:
            shutil.rmtree(local_root, ignore_errors=True)
        progress(
            {
                "phase": "VERIFY",
                "processed_units": 1,
                "total_units": 1,
                "percent": 100.0,
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "status": "PASS",
            }
        )
        return {
            "status": "PASS",
            "run_id": run_id,
            "authority_hash": authority.authority_hash,
            "manifest_hash": manifest["manifest_hash"],
            "verify_hash": verify["verify_hash"],
            "research_status": "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING",
            "stage3_locked": True,
        }


def resume_formal(
    *,
    policy: PlaceboPolicy,
    approval_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    """Resume the sole unpublished Run from hash-verified group checkpoints."""

    if not repository_clean(repository_root):
        raise ValueError("formal T17 resume requires a clean repository")
    binding = audit_t16_source(policy, full_hash_scan=True)
    approval = validate_approval(
        approval_path,
        policy=policy,
        repository_root=repository_root,
        binding=binding,
    )
    runs = tuple(
        path
        for path in (policy.evidence_root / "runs").glob("stage2-s2p14-t17-*")
        if path.is_dir() and not path.is_symlink()
    )
    authorities = tuple(
        path
        for path in (policy.evidence_root / "authorities").glob("authority-*.json")
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )
    if len(runs) != 1 or len(authorities) != 1:
        raise ValueError("resume requires exactly one Authority and one Run")
    run_root = runs[0]
    authority = S2P14T17Authority.model_validate_json(authorities[0].read_text())
    contract = read_json(run_root / "run-contract.json")
    if (
        canonical_hash(
            {key: value for key, value in contract.items() if key != "run_contract_hash"}
        )
        != contract.get("run_contract_hash")
        or contract.get("authority_hash") != authority.authority_hash
        or contract.get("approval_hash") != approval["approval_hash"]
        or contract.get("code_commit") != repository_commit(repository_root)
        or contract.get("source_t16_verify_hash") != binding.verify_hash
    ):
        raise ValueError("T17 resume contract drift")
    published = run_root / "published/snapshots"
    if published.is_dir() and any(published.iterdir()):
        verify = verify_run(run_root, binding=binding)
        return {
            "status": "PASS",
            "run_id": run_root.name,
            "authority_hash": authority.authority_hash,
            "verify_hash": verify["verify_hash"],
            "research_status": verify["research_status"],
            "stage3_locked": True,
        }
    progress = _progress_writer(run_root / "checkpoint.json", run_root.name)
    blind_root = run_root / "work/blind-selections"
    produce_blind_selections(binding=binding, output_root=blind_root, progress=progress)
    local_root = Path(tempfile.mkdtemp(prefix="s2p14-t17-resume-"))
    try:
        results_root = run_root / "work/results"
        reconciliation = attach_outcomes_and_summarize(
            binding=binding,
            blind_root=blind_root,
            output_root=results_root / "matches",
            local_database_path=local_root / "outcomes.sqlite",
            progress=progress,
        )
        _promote_result_metadata(results_root)
        manifest = publish_run(
            run_root=run_root,
            authority=authority,
            binding=binding,
            reconciliation=reconciliation,
        )
        verify = verify_run(run_root, binding=binding)
        verify_path = run_root / "verify" / f"{verify['verify_hash']}.json"
        write_exclusive(verify_path, verify)
    finally:
        shutil.rmtree(local_root, ignore_errors=True)
    progress(
        {
            "phase": "VERIFY",
            "processed_units": 1,
            "total_units": 1,
            "percent": 100.0,
            "heartbeat_at": datetime.now(UTC).isoformat(),
            "status": "PASS",
        }
    )
    return {
        "status": "PASS",
        "run_id": run_root.name,
        "authority_hash": authority.authority_hash,
        "manifest_hash": manifest["manifest_hash"],
        "verify_hash": verify["verify_hash"],
        "research_status": "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING",
        "stage3_locked": True,
    }
