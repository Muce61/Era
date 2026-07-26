"""Post-selection H2 outcome production and descriptive T15 summaries."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast
from collections.abc import Iterator

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .h2_control_reader import H2ControlReader
from .outcomes import (
    H2_COVERAGE_CONTRACT_ID,
    HORIZONS_SECONDS,
    build_control_outcome_matrix,
)
from .v14_contracts import (
    COMBINATION_ORDER,
    ConditionalBaselineMatchMatrix,
    ControlOutcomeMatrix,
    OutcomeCell,
    V14ControlCandidate,
    canonical_hash,
)

CONTROL_OUTCOME_SCHEMA = pa.schema(
    [
        pa.field("control_candidate_id", pa.string(), nullable=False),
        pa.field("control_outcome_matrix_id", pa.string(), nullable=False),
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("candidate_timestamp_ns", pa.int64(), nullable=False),
        pa.field("time_combination_id", pa.string(), nullable=False),
        pa.field("reference_price", pa.decimal128(38, 18), nullable=False),
        pa.field("source_path_hash", pa.string(), nullable=False),
        pa.field("outcomes_json", pa.string(), nullable=False),
        pa.field("matrix_json", pa.string(), nullable=False),
    ]
)

MATCH_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("pre_registered_period", pa.string(), nullable=False),
        pa.field("evaluation_fold", pa.string(), nullable=False),
        pa.field("parameter_set_id", pa.string(), nullable=False),
        pa.field("time_combination_id", pa.string(), nullable=False),
        pa.field("market_episode_id", pa.string(), nullable=False),
        pa.field("source_h2_path_hash", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("match_level", pa.string(), nullable=False),
        pa.field("control_candidate_ids", pa.list_(pa.string()), nullable=False),
        pa.field("control_outcome_matrix_ids", pa.list_(pa.string()), nullable=False),
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
        pa.field("eligible_episode_count", pa.int64(), nullable=False),
        pa.field("matched_episode_count", pa.int64(), nullable=False),
        pa.field("unmatched_episode_count", pa.int64(), nullable=False),
        pa.field("event_target_first_rate", pa.string(), nullable=True),
        pa.field("baseline_target_first_rate", pa.string(), nullable=True),
        pa.field("delta_target_first", pa.string(), nullable=True),
        pa.field("event_gap_affected_rate", pa.string(), nullable=True),
        pa.field("baseline_gap_affected_rate", pa.string(), nullable=True),
        pa.field("gap_affected_rate_delta", pa.string(), nullable=True),
        pa.field("coverage_contract_id", pa.string(), nullable=False),
        pa.field("historical_evidence_only", pa.bool_(), nullable=False),
    ]
)


def _selection_files(root: Path) -> tuple[Path, ...]:
    files = tuple(sorted(path for path in root.rglob("*.parquet") if not path.name.startswith(".")))
    if not files:
        raise ValueError("no outcome-blind selection files exist")
    return files


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@contextmanager
def _local_sqlite_database() -> Iterator[Path]:
    """Create the mutable SQLite work database on a local ephemeral filesystem."""

    configured = os.environ.get("ERA_S2P13_LOCAL_SCRATCH_ROOT")
    scratch_root = Path(configured).expanduser() if configured else Path(tempfile.gettempdir())
    if not scratch_root.is_absolute() or scratch_root.is_symlink():
        raise ValueError("T16 local scratch root must be an absolute non-symlink path")
    scratch_root.mkdir(parents=True, exist_ok=True)
    resolved = scratch_root.resolve()
    if resolved == Path("/Volumes") or resolved.is_relative_to(Path("/Volumes")):
        raise ValueError("T16 SQLite scratch cannot use an external volume")
    with tempfile.TemporaryDirectory(prefix="era-s2p13-t16-", dir=resolved) as temporary:
        yield Path(temporary) / "control-outcomes.sqlite"


def _candidate_from_canonical_json(payload: dict[str, Any]) -> V14ControlCandidate:
    """Restore the one Decimal field without relaxing strict candidate validation."""

    raw_price = payload.get("control_entry_price")
    if not isinstance(raw_price, str):
        raise ValueError("control_entry_price must be a canonical JSON decimal string")
    try:
        price = Decimal(raw_price)
    except InvalidOperation as error:
        raise ValueError("control_entry_price is not a valid decimal string") from error
    if not price.is_finite() or price <= 0:
        raise ValueError("control_entry_price must be finite and positive")
    if format(price, "f") != raw_price:
        raise ValueError("control_entry_price is not canonically formatted")
    restored = {**payload, "control_entry_price": price}
    return V14ControlCandidate.model_validate(restored)


def _ingest_candidates(database: sqlite3.Connection, files: tuple[Path, ...]) -> int:
    database.execute(
        """
        CREATE TABLE candidates (
          control_candidate_id TEXT PRIMARY KEY,
          payload_json TEXT NOT NULL,
          instrument TEXT NOT NULL,
          anchor_ns INTEGER NOT NULL,
          timing_id TEXT NOT NULL,
          reference_price TEXT NOT NULL,
          matrix_id TEXT,
          matrix_json TEXT,
          outcomes_json TEXT,
          source_path_hash TEXT
        )
        """
    )
    for path in files:
        table = pq.read_table(path, columns=["selected_candidates_json"])
        for encoded in table["selected_candidates_json"].to_pylist():
            for payload in json.loads(str(encoded)):
                if not isinstance(payload, dict):
                    raise ValueError("selected candidate payload must be a JSON object")
                candidate = _candidate_from_canonical_json(payload)
                canonical = _json(payload)
                existing = database.execute(
                    "SELECT payload_json FROM candidates WHERE control_candidate_id = ?",
                    (candidate.control_candidate_id,),
                ).fetchone()
                if existing is not None:
                    if existing[0] != canonical:
                        raise ValueError("control candidate ID payload conflict")
                    continue
                database.execute(
                    """
                    INSERT INTO candidates
                    (control_candidate_id,payload_json,instrument,anchor_ns,timing_id,reference_price)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (
                        candidate.control_candidate_id,
                        canonical,
                        candidate.instrument,
                        candidate.candidate_timestamp_ns,
                        candidate.time_combination_id,
                        str(payload["control_entry_price"]),
                    ),
                )
        database.commit()
    return cast(int, database.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])


def _produce_control_outcomes(
    database: sqlite3.Connection,
    *,
    reader: H2ControlReader,
    output_path: Path,
) -> tuple[int, int, int]:
    writer = pq.ParquetWriter(output_path, CONTROL_OUTCOME_SCHEMA, compression="zstd")
    rows: list[dict[str, Any]] = []
    count = 0
    gap_matrix_count = 0
    gap_cell_count = 0
    try:
        cursor = database.execute(
            """
            SELECT control_candidate_id,instrument,anchor_ns,timing_id,reference_price
            FROM candidates ORDER BY instrument,anchor_ns,timing_id,control_candidate_id
            """
        )
        for candidate_id, instrument, anchor_ns, timing_id, reference_price in cursor:
            horizon = HORIZONS_SECONDS[str(timing_id)]
            trades, source_gaps, source_path_hash = reader.read_window(
                instrument=str(instrument),
                start_ns=int(anchor_ns),
                end_ns=int(anchor_ns) + horizon * 1_000_000_000,
            )
            matrix = build_control_outcome_matrix(
                control_candidate_id=str(candidate_id),
                time_combination_id=str(timing_id),
                reference_price=Decimal(str(reference_price)),
                trades=trades,
                anchor_ns=int(anchor_ns),
                source_path_hash=source_path_hash,
                source_partition_bound=True,
                source_gaps=source_gaps,
            )
            outcomes_json = _json([cell.model_dump(mode="json") for cell in matrix.outcomes])
            matrix_gap_cells = sum(
                cell.label_reason == "SOURCE_GAP_BEFORE_DECISION" for cell in matrix.outcomes
            )
            gap_matrix_count += matrix_gap_cells > 0
            gap_cell_count += matrix_gap_cells
            matrix_json = _json(matrix.model_dump(mode="json"))
            database.execute(
                """
                UPDATE candidates SET matrix_id=?,matrix_json=?,outcomes_json=?,source_path_hash=?
                WHERE control_candidate_id=?
                """,
                (
                    matrix.control_outcome_matrix_id,
                    matrix_json,
                    outcomes_json,
                    source_path_hash,
                    candidate_id,
                ),
            )
            rows.append(
                {
                    "control_candidate_id": candidate_id,
                    "control_outcome_matrix_id": matrix.control_outcome_matrix_id,
                    "instrument": instrument,
                    "candidate_timestamp_ns": anchor_ns,
                    "time_combination_id": timing_id,
                    "reference_price": Decimal(str(reference_price)),
                    "source_path_hash": source_path_hash,
                    "outcomes_json": outcomes_json,
                    "matrix_json": matrix_json,
                }
            )
            count += 1
            if len(rows) >= 2_000:
                writer.write_table(pa.Table.from_pylist(rows, schema=CONTROL_OUTCOME_SCHEMA))
                rows.clear()
                database.commit()
        if rows:
            writer.write_table(pa.Table.from_pylist(rows, schema=CONTROL_OUTCOME_SCHEMA))
        database.commit()
    finally:
        writer.close()
    return count, gap_matrix_count, gap_cell_count


def _outcome_lookup(
    database: sqlite3.Connection, candidate_ids: set[str]
) -> dict[str, ControlOutcomeMatrix]:
    result: dict[str, ControlOutcomeMatrix] = {}
    values = sorted(candidate_ids)
    for offset in range(0, len(values), 900):
        chunk = values[offset : offset + 900]
        placeholders = ",".join("?" for _ in chunk)
        rows = database.execute(
            f"SELECT control_candidate_id,matrix_id,matrix_json FROM candidates "
            f"WHERE control_candidate_id IN ({placeholders})",
            chunk,
        ).fetchall()
        for candidate_id, matrix_id, matrix_json in rows:
            if matrix_id is None or matrix_json is None:
                raise ValueError("selected control lacks an H2 outcome matrix")
            matrix = ControlOutcomeMatrix.model_validate_json(matrix_json)
            if matrix.control_outcome_matrix_id != str(matrix_id):
                raise ValueError("control matrix lookup identity drift")
            result[str(candidate_id)] = matrix
    if set(result) != candidate_ids:
        raise ValueError("control outcome lookup is incomplete")
    return result


def _attach_matches(
    database: sqlite3.Connection,
    *,
    files: tuple[Path, ...],
    match_path: Path,
    summary_path: Path,
) -> tuple[int, int, list[dict[str, Any]], dict[str, int]]:
    match_writer = pq.ParquetWriter(match_path, MATCH_SCHEMA, compression="zstd")
    summaries: list[dict[str, Any]] = []
    matched_total = 0
    eligible_total = 0
    event_gap_matrix_count = 0
    event_gap_cell_count = 0
    matched_event_gap_matrix_count = 0
    control_gap_assignment_count = 0
    try:
        for path in files:
            source_rows = cast(list[dict[str, Any]], pq.read_table(path).to_pylist())
            candidate_ids = {
                str(candidate_id)
                for row in source_rows
                for candidate_id in row["control_candidate_ids"]
            }
            lookup = _outcome_lookup(database, candidate_ids) if candidate_ids else {}
            output_rows: list[dict[str, Any]] = []
            per_cell_event = [0] * 30
            per_cell_baseline = [Decimal(0)] * 30
            per_cell_event_gap = [0] * 30
            per_cell_baseline_gap = [Decimal(0)] * 30
            matched = 0
            for row in source_rows:
                event_outcomes = tuple(
                    OutcomeCell.model_validate(item)
                    for item in json.loads(row["event_outcomes_json"])
                )
                controls = tuple(str(value) for value in row["control_candidate_ids"])
                event_gap_cells = tuple(
                    outcome.label_reason == "SOURCE_GAP_BEFORE_DECISION"
                    for outcome in event_outcomes
                )
                event_gap_matrix_count += any(event_gap_cells)
                event_gap_cell_count += sum(event_gap_cells)
                control_matrices: list[ControlOutcomeMatrix] = []
                for candidate_id in controls:
                    control_matrices.append(lookup[candidate_id])
                matrix = ConditionalBaselineMatchMatrix.seal(
                    {
                        "market_episode_id": row["market_episode_id"],
                        "source_h2_path_hash": row["classification_row_hash"],
                        "parameter_set_id": row["parameter_set_id"],
                        "time_combination_id": row["time_combination_id"],
                        "status": row["status"],
                        "match_level": row["match_level"],
                        "control_candidate_ids": controls,
                        "event_outcomes": event_outcomes,
                        "control_outcome_matrix_ids": tuple(
                            value.control_outcome_matrix_id for value in control_matrices
                        ),
                    }
                )
                if matrix.status == "MATCHED":
                    matched += 1
                    matched_event_gap_matrix_count += any(event_gap_cells)
                    control_gap_assignment_count += sum(
                        any(
                            outcome.label_reason == "SOURCE_GAP_BEFORE_DECISION"
                            for outcome in control.outcomes
                        )
                        for control in control_matrices
                    )
                    for index, event in enumerate(event_outcomes):
                        per_cell_event[index] += event.strict_target_first
                        per_cell_event_gap[index] += event_gap_cells[index]
                        per_cell_baseline[index] += Decimal(
                            sum(
                                control.outcomes[index].strict_target_first
                                for control in control_matrices
                            )
                        ) / Decimal(5)
                        per_cell_baseline_gap[index] += Decimal(
                            sum(
                                control.outcomes[index].label_reason == "SOURCE_GAP_BEFORE_DECISION"
                                for control in control_matrices
                            )
                        ) / Decimal(5)
                output_rows.append(
                    {
                        "instrument": row["instrument"],
                        "pre_registered_period": row["pre_registered_period"],
                        "evaluation_fold": row["evaluation_fold"],
                        "parameter_set_id": row["parameter_set_id"],
                        "time_combination_id": row["time_combination_id"],
                        "market_episode_id": matrix.market_episode_id,
                        "source_h2_path_hash": matrix.source_h2_path_hash,
                        "status": matrix.status,
                        "match_level": matrix.match_level,
                        "control_candidate_ids": list(matrix.control_candidate_ids),
                        "control_outcome_matrix_ids": list(matrix.control_outcome_matrix_ids),
                        "output_hash": matrix.output_hash,
                        "matrix_json": _json(matrix.model_dump(mode="json")),
                    }
                )
            match_writer.write_table(pa.Table.from_pylist(output_rows, schema=MATCH_SCHEMA))
            eligible = len(source_rows)
            eligible_total += eligible
            matched_total += matched
            first = source_rows[0] if source_rows else None
            if first is None:
                continue
            for index, combination in enumerate(COMBINATION_ORDER):
                event_rate: Decimal | None
                baseline_rate: Decimal | None
                delta: Decimal | None
                event_gap_rate: Decimal | None
                baseline_gap_rate: Decimal | None
                if matched:
                    event_rate = Decimal(per_cell_event[index]) / Decimal(matched)
                    baseline_rate = per_cell_baseline[index] / Decimal(matched)
                    delta = event_rate - baseline_rate
                    event_gap_rate = Decimal(per_cell_event_gap[index]) / Decimal(matched)
                    baseline_gap_rate = per_cell_baseline_gap[index] / Decimal(matched)
                else:
                    event_rate = None
                    baseline_rate = None
                    delta = None
                    event_gap_rate = None
                    baseline_gap_rate = None
                summaries.append(
                    {
                        "instrument": first["instrument"],
                        "pre_registered_period": first["pre_registered_period"],
                        "evaluation_fold": first["evaluation_fold"],
                        "parameter_set_id": first["parameter_set_id"],
                        "time_combination_id": first["time_combination_id"],
                        "combination_id": combination,
                        "eligible_episode_count": eligible,
                        "matched_episode_count": matched,
                        "unmatched_episode_count": eligible - matched,
                        "event_target_first_rate": (
                            format(event_rate, "f") if event_rate is not None else None
                        ),
                        "baseline_target_first_rate": (
                            format(baseline_rate, "f") if baseline_rate is not None else None
                        ),
                        "delta_target_first": format(delta, "f") if delta is not None else None,
                        "event_gap_affected_rate": (
                            format(event_gap_rate, "f") if event_gap_rate is not None else None
                        ),
                        "baseline_gap_affected_rate": (
                            format(baseline_gap_rate, "f")
                            if baseline_gap_rate is not None
                            else None
                        ),
                        "gap_affected_rate_delta": (
                            format(event_gap_rate - baseline_gap_rate, "f")
                            if event_gap_rate is not None and baseline_gap_rate is not None
                            else None
                        ),
                        "coverage_contract_id": H2_COVERAGE_CONTRACT_ID,
                        "historical_evidence_only": True,
                    }
                )
    finally:
        match_writer.close()
    pq.write_table(
        pa.Table.from_pylist(summaries, schema=SUMMARY_SCHEMA),
        summary_path,
        compression="zstd",
    )
    return (
        eligible_total,
        matched_total,
        summaries,
        {
            "event_gap_affected_matrix_count": event_gap_matrix_count,
            "event_gap_affected_cell_count": event_gap_cell_count,
            "matched_event_gap_affected_matrix_count": matched_event_gap_matrix_count,
            "control_gap_affected_assignment_count": control_gap_assignment_count,
        },
    )


def produce_post_selection_evidence(
    *,
    selection_root: Path,
    output_root: Path,
    h2_reader: H2ControlReader,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    files = _selection_files(selection_root)
    with _local_sqlite_database() as database_path:
        database = sqlite3.connect(database_path)
        try:
            unique_candidates = _ingest_candidates(database, files)
            control_path = output_root / "control_outcome_matrices.parquet"
            outcome_count, control_gap_matrices, control_gap_cells = _produce_control_outcomes(
                database, reader=h2_reader, output_path=control_path
            )
            if outcome_count != unique_candidates:
                raise ValueError("unique selected controls are not fully classified")
            match_path = output_root / "conditional_match_matrices.parquet"
            summary_path = output_root / "descriptive_summaries.parquet"
            eligible, matched, summaries, event_gap_counts = _attach_matches(
                database,
                files=files,
                match_path=match_path,
                summary_path=summary_path,
            )
        finally:
            database.close()
    assignments = sum(
        len(values)
        for path in files
        for values in pq.read_table(path, columns=["control_candidate_ids"])[
            "control_candidate_ids"
        ].to_pylist()
    )
    payload: dict[str, Any] = {
        "schema_name": "stage2-s2t15-post-selection-report",
        "schema_version": "1.0",
        "status": "PASS",
        "eligible_episode_count": eligible,
        "matched_episode_count": matched,
        "unmatched_episode_count": eligible - matched,
        "control_assignment_count": assignments,
        "unique_control_candidate_count": unique_candidates,
        "control_outcome_matrix_count": outcome_count,
        "control_outcome_cell_count": outcome_count * 30,
        "summary_row_count": len(summaries),
        "coverage_contract_id": H2_COVERAGE_CONTRACT_ID,
        "event_gap_affected_matrix_count": event_gap_counts["event_gap_affected_matrix_count"],
        "event_gap_affected_matrix_rate": format(
            Decimal(event_gap_counts["event_gap_affected_matrix_count"])
            / Decimal(max(eligible, 1)),
            "f",
        ),
        "event_gap_affected_cell_count": event_gap_counts["event_gap_affected_cell_count"],
        "matched_event_gap_affected_matrix_count": event_gap_counts[
            "matched_event_gap_affected_matrix_count"
        ],
        "matched_event_gap_affected_matrix_rate": format(
            Decimal(event_gap_counts["matched_event_gap_affected_matrix_count"])
            / Decimal(max(matched, 1)),
            "f",
        ),
        "control_gap_affected_matrix_count": control_gap_matrices,
        "control_gap_affected_matrix_rate": format(
            Decimal(control_gap_matrices) / Decimal(max(outcome_count, 1)),
            "f",
        ),
        "control_gap_affected_cell_count": control_gap_cells,
        "control_gap_affected_assignment_count": event_gap_counts[
            "control_gap_affected_assignment_count"
        ],
        "control_gap_affected_assignment_rate": format(
            Decimal(event_gap_counts["control_gap_affected_assignment_count"])
            / Decimal(max(matched * 5, 1)),
            "f",
        ),
        "coverage_comparability_status": "SHARED_CONTRACT_RATES_REPORTED",
        "control_outcomes_sha256": hashlib.sha256(control_path.read_bytes()).hexdigest(),
        "match_matrices_sha256": hashlib.sha256(match_path.read_bytes()).hexdigest(),
        "summaries_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "sqlite_scratch_policy": "LOCAL_EPHEMERAL_NOT_PUBLISHED",
        "research_result": "DESCRIPTIVE_ONLY_PRIMARY_PENDING_T18",
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    payload["report_hash"] = canonical_hash(payload)
    return payload
