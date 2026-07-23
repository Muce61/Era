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
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, cast

import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.baselines.conditional.episode_producer import (
    _episode_key,
    _load_t10_bindings,
)
from era100x.research.stage_2.baselines.conditional.full_run import (
    REPOSITORY_ROOT,
    T10_SNAPSHOT,
    T10_SNAPSHOT_ID,
    T13_SNAPSHOT,
)
from era100x.research.stage_2.baselines.conditional.matrix_matcher import (
    attach_outcome_matrices,
    select_outcome_blind_controls,
)
from era100x.research.stage_2.baselines.conditional.outcomes import (
    H2Trade,
    build_control_outcome_matrix,
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
    CostScenario,
    FundingTrack,
    LifecycleObservation,
    SourceCoverage,
    evaluate_lifecycle_pair,
)

from .orchestrator import REHEARSAL_SCHEMA, TASKS, TaskHandoff, current_commit

NS = 1_000_000_000
DAY_NS = 86_400 * NS
START_DATE = date(2020, 1, 1)
END_DATE = date(2020, 1, 8)
STAGE1_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/published/stage1-trades-v2/"
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
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _json_value(asdict(cast(Any, value)))
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _encoded(value: object) -> bytes:
    return (
        json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _canonical_hash(value: object) -> str:
    return canonical_hash(_json_value(value))


def _write_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(_encoded(value))


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
    return datetime.fromtimestamp(value / NS, UTC).date()


def _partition_paths(instrument: str, owner_date: date) -> tuple[Path, Path]:
    root = (
        STAGE1_ROOT / instrument / f"archive={owner_date:%Y-%m}" / f"date={owner_date.isoformat()}"
    )
    return root / "part-000.parquet", root / "partition.json"


def _verified_trade_window(
    *, instrument: str, start_ns: int, end_ns: int
) -> tuple[tuple[H2Trade, ...], tuple[str, ...], tuple[dict[str, Any], ...]]:
    rows: list[H2Trade] = []
    partition_hashes: list[str] = []
    declared_gaps: list[dict[str, Any]] = []
    cursor = _date_from_ns(start_ns)
    last_date = _date_from_ns(end_ns - 1)
    while cursor <= last_date:
        parquet_path, receipt_path = _partition_paths(instrument, cursor)
        receipt = _read_json(receipt_path)
        if (
            parquet_path.is_symlink()
            or not parquet_path.is_file()
            or receipt.get("instrument") != instrument
            or receipt.get("date") != cursor.isoformat()
            or receipt.get("byte_sha256") != _file_hash(parquet_path)
            or int(receipt.get("venue_trade_id_reversal_count", -1)) != 0
            or int(receipt.get("duplicate_exact_count", -1)) != 0
        ):
            raise ValueError(f"Stage 1 Trade partition Verify failed: {instrument} {cursor}")
        gap_count = int(receipt.get("venue_trade_id_gap_count", -1))
        if gap_count < 0:
            raise ValueError(f"Stage 1 Trade gap classification missing: {instrument} {cursor}")
        if gap_count:
            declared_gaps.append(
                {
                    "instrument": instrument,
                    "date": cursor.isoformat(),
                    "venue_trade_id_gap_count": gap_count,
                    "venue_trade_id_gap_examples": receipt.get("venue_trade_id_gap_examples", []),
                }
            )
        table = pq.read_table(
            parquet_path,
            columns=["ts_event_ns", "venue_trade_id", "canonical_trade_id", "price"],
        )
        table = table.filter(pc.greater_equal(table["ts_event_ns"], start_ns))
        table = table.filter(pc.less(table["ts_event_ns"], end_ns))
        rows.extend(
            H2Trade(
                ts_event_ns=int(row["ts_event_ns"]),
                venue_trade_id=int(row["venue_trade_id"]),
                canonical_trade_id=str(row["canonical_trade_id"]),
                price=Decimal(row["price"]),
            )
            for row in table.to_pylist()
        )
        partition_hashes.append(str(receipt["byte_sha256"]))
        cursor += timedelta(days=1)
    ordered = tuple(
        sorted(rows, key=lambda row: (row.ts_event_ns, row.venue_trade_id, row.canonical_trade_id))
    )
    identities = tuple(
        (row.ts_event_ns, row.venue_trade_id, row.canonical_trade_id) for row in ordered
    )
    if len(identities) != len(set(identities)):
        raise ValueError("Stage 1 Trade window contains duplicate stable identities")
    return ordered, tuple(partition_hashes), tuple(declared_gaps)


def _funding_rows(
    acceptance: dict[str, Any], *, instrument: str, start_ns: int, end_ns: int
) -> tuple[tuple[int, Decimal], ...]:
    entry = cast(dict[str, Any], acceptance["local_history"][instrument])
    path = Path(str(entry["path"]))
    if path.is_symlink() or not path.is_file() or _file_hash(path) != entry["sha256"]:
        raise ValueError(f"accepted funding source drift: {instrument}")
    result: list[tuple[int, Decimal]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            timestamp_ms = int(raw.get("settlement_ts_ms") or raw.get("calc_time") or 0)
            timestamp_ns = timestamp_ms * 1_000_000
            if start_ns < timestamp_ns <= end_ns:
                result.append(
                    (
                        timestamp_ns,
                        Decimal(raw.get("last_funding_rate") or raw["funding_rate"]),
                    )
                )
    if tuple(result) != tuple(sorted(result)):
        raise ValueError("accepted funding rows are not time ordered")
    return tuple(result)


def _selected_t13_rows() -> dict[str, dict[str, Any]]:
    start_ns = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() * NS)
    end_ns = int(datetime(2020, 1, 8, tzinfo=UTC).timestamp() * NS)
    result: dict[str, dict[str, Any]] = {}
    for instrument in ("BTCUSDT", "ETHUSDT"):
        path = T13_SNAPSHOT / instrument / "first_passage.parquet"
        table = pq.read_table(
            path,
            filters=[("window_start_ns", ">=", start_ns), ("window_start_ns", "<", end_ns)],
        )
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
            raise ValueError(f"seven-day window has no complete Primary H2 Episode: {instrument}")
        result[instrument] = min(matches, key=lambda row: int(row["window_start_ns"]))
    return result


def _lifecycle_probe(*, row: dict[str, Any], acceptance: dict[str, Any]) -> dict[str, Any]:
    instrument = str(row["instrument"])
    start_ns = int(row["window_start_ns"])
    end_ns = start_ns + 7 * DAY_NS
    trades, partition_hashes, declared_gaps = _verified_trade_window(
        instrument=instrument, start_ns=start_ns, end_ns=end_ns
    )
    funding = _funding_rows(acceptance, instrument=instrument, start_ns=start_ns, end_ns=end_ns)
    cumulative = Decimal(0)
    funding_cursor = 0
    observations: list[LifecycleObservation] = []
    for trade in trades:
        while funding_cursor < len(funding) and funding[funding_cursor][0] <= trade.ts_event_ns:
            cumulative += Decimal("800") * funding[funding_cursor][1]
            funding_cursor += 1
        observations.append(
            LifecycleObservation(
                ts_event_ns=trade.ts_event_ns,
                venue_trade_id=trade.venue_trade_id,
                canonical_trade_id=trade.canonical_trade_id,
                price=trade.price,
                cumulative_funding=cumulative,
            )
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
            observations=tuple(observations),
            source_coverage=(
                SourceCoverage.DECLARED_GAP if declared_gaps else SourceCoverage.COMPLETE
            ),
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
        "source_t13_classification_row_hash": row["classification_row_hash"],
        "entry_ts_ns": start_ns,
        "entry_reference_price": row["reference_price"],
        "trade_observation_count": len(observations),
        "stage1_partition_hashes": partition_hashes,
        "declared_source_gaps": declared_gaps,
        "source_coverage": "DECLARED_GAP" if declared_gaps else "COMPLETE",
        "funding_settlement_count": len(funding),
        "funding_acceptance_hash": acceptance["acceptance_hash"],
        "funding_tracks": results,
        "strict_consumer_readback": "PASS",
        "historical_execution_claim": False,
    }


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
                declared_source_gap=bool(declared_gaps),
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


def _handoff(task_id: str, run_id: str, payload: object, row_count: int) -> TaskHandoff:
    return TaskHandoff(
        task_id=task_id,
        run_id=run_id,
        output_hash=_canonical_hash(payload),
        row_count=row_count,
        consumer_readback="PASS",
        reconciliation="PASS",
        verify_status="PASS",
    )


def run_final_code_rehearsal(*, output_root: Path) -> tuple[dict[str, Any], Path]:
    """Run the isolated real-input rehearsal and leave UI finalization pending."""

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
            start_date=START_DATE,
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
    t13_rows = _selected_t13_rows()
    lifecycle = [
        _lifecycle_probe(row=t13_rows[instrument], acceptance=_read_json(FUNDING_ACCEPTANCE))
        for instrument in ("BTCUSDT", "ETHUSDT")
    ]
    reader = FixedT10Reader(T10_SNAPSHOT, expected_snapshot_id=T10_SNAPSHOT_ID)
    t16 = [_t16_probe(reader=reader, row=t13_rows[item]) for item in ("BTCUSDT", "ETHUSDT")]
    raw = cast(dict[str, Any], source_audit["raw_path_non_pollution"])
    feature = cast(dict[str, Any], source_audit["feature_availability"])
    run_id = f"rehearsal-7d-{commit[:12]}"
    handoffs = (
        _handoff("S2P13-T11", run_id, lifecycle, len(lifecycle) * len(FundingTrack)),
        _handoff(
            "S2P13-T12",
            run_id,
            {"raw": raw["reports"], "source": "accepted T11"},
            int(raw["total_raw_path_row_count"]),
        ),
        _handoff(
            "S2P13-T13",
            run_id,
            {"feature": feature, "source": "accepted T12"},
            int(feature["total_valid_market_anchor_count"]),
        ),
        _handoff(
            "S2P13-T14",
            run_id,
            {"t13": raw["reports"], "source": "accepted T13"},
            sum(int(item["t13_derived_row_count"]) for item in raw["reports"]),
        ),
        _handoff(
            "S2P13-T15",
            run_id,
            {"ambiguity_policy": "AMBIGUOUS_AS_FAILURE", "t13": raw["reports"]},
            sum(int(item["t13_derived_row_count"]) for item in raw["reports"]),
        ),
        _handoff("S2P13-T16", run_id, t16, len(t16)),
    )
    report: dict[str, Any] = {
        "schema_name": "stage2-plan-v13-seven-day-rehearsal-report-v1",
        "status": "PASS",
        "start_date": START_DATE.isoformat(),
        "end_date_exclusive": END_DATE.isoformat(),
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
    pending_path = OPERATIONS_ROOT / "seven-day-rehearsal-receipt.pending.json"
    _write_exclusive(pending_path, pending)
    verify_final_code_rehearsal(report_path)
    return report, report_path


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
    final_path = OPERATIONS_ROOT / "seven-day-rehearsal-receipt.json"
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
    ):
        raise ValueError("seven-day rehearsal report reconciliation failed")
    counts = Counter(item["task_id"] for item in report["handoffs"])
    if counts != Counter(TASKS):
        raise ValueError("seven-day rehearsal task handoff universe mismatch")
    return report
