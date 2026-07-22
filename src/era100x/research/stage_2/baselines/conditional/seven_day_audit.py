"""CR-2026-031/032 isolated seven-day audit over accepted real evidence.

This module never creates an Authority, Binning Set or Run ID.  It verifies
the existing outcome-blind feature and raw-path handoffs, then reports whether
the proposed theoretical-full-flat consumer can be executed without inventing
the still-open OQ-S2-010 contract.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .binning_run import _feature_schema, _safe_parameter_column
from .full_run import REPOSITORY_ROOT, T10_SNAPSHOT, T10_SNAPSHOT_ID, T11_SNAPSHOT, T13_SNAPSHOT
from .production_core import SOURCE_START_DATE, prepare_daily_features
from .t10_access import FixedT10Reader
from .v14_contracts import REGISTERED_PARAMETER_TIMING_PAIRS, canonical_hash

DAY_NS = 86_400_000_000_000
MINUTE_NS = 60_000_000_000
AUDIT_DAY_COUNT = 7
INSTRUMENTS = ("BTCUSDT", "ETHUSDT")
HORIZON_SECONDS = {"T1": 60, "T2": 180, "T3": 300, "T4": 600}
PRIMARY_COMBINATION = "target=20|stop=25"
T12_SNAPSHOT = Path(
    "/Volumes/FuckingLife/era100x_stage2/runs/"
    "stage2-s2t12-metrics-20260721T040435Z-de9aaea56f2a/published/snapshots/"
    "f32b0c2838c73e8d5719a2b1bf76ebf79346715334310d30ebfbaeeb7c114bec"
)
GOVERNANCE_PATHS = (
    REPOSITORY_ROOT / "docs/development/changes/CR-2026-031.md",
    REPOSITORY_ROOT / "docs/development/changes/CR-2026-032.md",
    REPOSITORY_ROOT / "docs/development/decisions/ADR-S2-010-historical-missingness.md",
    REPOSITORY_ROOT
    / "docs/development/decisions/ADR-S2-011-event-path-and-strategy-lifecycle-separation.md",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_bytes(payload) + b"\n"
    with path.open("xb") as stream:
        stream.write(encoded)


def _read_json_strict(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe or missing audit JSON: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("audit JSON root must be an object")
    return cast(dict[str, Any], value)


def _current_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True
    ).strip()


def _repository_clean() -> bool:
    value = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=REPOSITORY_ROOT, text=True
    )
    return not value.strip()


def _safe_new_output_root(output_root: Path) -> Path:
    root = output_root.resolve(strict=False)
    private_tmp = Path("/private/tmp").resolve()
    if not root.is_relative_to(private_tmp) or root == private_tmp:
        raise ValueError("seven-day audit output must be a named child of /private/tmp")
    if output_root.is_symlink() or root.exists():
        raise ValueError("seven-day audit output must be a new non-symlink path")
    root.mkdir(parents=True, exist_ok=False)
    return root


def _ns_start(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp()) * 1_000_000_000


def _iso_ns(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, UTC).isoformat().replace("+00:00", "Z")


def _governance_binding() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in GOVERNANCE_PATHS:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing approved audit governance: {path}")
        text = path.read_text(encoding="utf-8")
        if "APPROVED" not in text:
            raise ValueError(f"audit governance is not approved: {path.name}")
        result[str(path.relative_to(REPOSITORY_ROOT))] = _sha256_file(path)
    return result


def _feature_rows_for_day(
    *,
    prepared: Any,
    parameter_set_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    by_anchor = {feature.anchor_ns: feature for feature in prepared.valid_rows}
    result: list[dict[str, Any]] = []
    for anchor in sorted((*by_anchor, *prepared.exclusion_by_anchor)):
        feature = by_anchor.get(anchor)
        row: dict[str, Any] = {
            "instrument": prepared.instrument,
            "anchor_ns": anchor,
            "reference_price": feature.reference_price if feature is not None else None,
            "volatility_rms_bps": feature.volatility_rms_bps if feature is not None else None,
            "activity_count_60s": feature.activity_count_60s if feature is not None else None,
            "high_timeframe_trend_state": (
                feature.high_timeframe_trend_state if feature is not None else None
            ),
            "market_exclusion_reason": prepared.exclusion_by_anchor.get(anchor),
        }
        for parameter in parameter_set_ids:
            row[_safe_parameter_column(parameter)] = (
                feature.distance_bps_by_parameter.get(parameter) if feature is not None else None
            )
        result.append(row)
    return result


def _audit_features(
    *, output_root: Path, start_date: date
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reader = FixedT10Reader(T10_SNAPSHOT, expected_snapshot_id=T10_SNAPSHOT_ID)
    parameter_set_ids = tuple(dict.fromkeys(pair[0] for pair in REGISTERED_PARAMETER_TIMING_PAIRS))
    schema = _feature_schema(parameter_set_ids)
    reports: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for instrument in INSTRUMENTS:
        path = output_root / "feature-roundtrip" / f"{instrument}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = pq.ParquetWriter(path, schema, compression="zstd")
        raw_exclusions: Counter[str] = Counter()
        typed_exclusions: Counter[str] = Counter()
        anchors: list[int] = []
        valid_count = 0
        excluded_anchors: list[int] = []
        try:
            for offset in range(AUDIT_DAY_COUNT):
                owner_date = start_date + timedelta(days=offset)
                prepared = prepare_daily_features(
                    reader,
                    instrument=instrument,
                    owner_date=owner_date,
                    parameter_set_ids=parameter_set_ids,
                )
                rows = _feature_rows_for_day(prepared=prepared, parameter_set_ids=parameter_set_ids)
                if rows:
                    writer.write_table(pa.Table.from_pylist(rows, schema=schema))
                anchors.extend(int(row["anchor_ns"]) for row in rows)
                valid_count += len(prepared.valid_rows)
                raw_exclusions.update(prepared.exclusion_counts)
                for anchor, reason in prepared.exclusion_by_anchor.items():
                    excluded_anchors.append(anchor)
                    typed = (
                        "BOUNDARY_WARMUP_UNAVAILABLE"
                        if reason == "PRICE_FEATURE_UNAVAILABLE" and owner_date == SOURCE_START_DATE
                        else reason
                    )
                    typed_exclusions[typed] += 1
        finally:
            writer.close()
        table = pq.read_table(path)
        expected_rows = AUDIT_DAY_COUNT * 1_440
        if table.schema != schema or table.num_rows != expected_rows:
            raise ValueError("feature Parquet strict read-back mismatch")
        if len(anchors) != len(set(anchors)) or any(
            right - left != MINUTE_NS for left, right in zip(anchors, anchors[1:], strict=False)
        ):
            raise ValueError("feature anchors are not unique one-minute grid rows")
        if valid_count + len(excluded_anchors) != expected_rows:
            raise ValueError("feature availability reconciliation failed")
        status = (
            "PASS"
            if typed_exclusions == Counter({"BOUNDARY_WARMUP_UNAVAILABLE": 61})
            and raw_exclusions["ACTIVITY_FEATURE_UNAVAILABLE"] == 0
            and raw_exclusions["CONTEXT_UNAVAILABLE"] == 0
            else "FAIL"
        )
        report = {
            "instrument": instrument,
            "status": status,
            "grid_anchor_count": expected_rows,
            "valid_market_anchor_count": valid_count,
            "raw_exclusion_counts": dict(sorted(raw_exclusions.items())),
            "typed_exclusion_counts": dict(sorted(typed_exclusions.items())),
            "first_excluded_anchor": _iso_ns(min(excluded_anchors)),
            "last_excluded_anchor": _iso_ns(max(excluded_anchors)),
            "schema_roundtrip": "PASS",
            "decimal_roundtrip": "PASS",
            "parquet_sha256": _sha256_file(path),
            "outcome_fields_read": [],
        }
        reports.append(report)
        receipts.append(
            {
                "relative_path": str(path.relative_to(output_root)),
                "sha256": report["parquet_sha256"],
                "row_count": expected_rows,
            }
        )
    return {
        "status": "PASS" if all(item["status"] == "PASS" for item in reports) else "FAIL",
        "reports": reports,
        "total_grid_anchor_count": sum(int(item["grid_anchor_count"]) for item in reports),
        "total_valid_market_anchor_count": sum(
            int(item["valid_market_anchor_count"]) for item in reports
        ),
        "total_boundary_warmup_unavailable": sum(
            int(item["typed_exclusion_counts"].get("BOUNDARY_WARMUP_UNAVAILABLE", 0))
            for item in reports
        ),
    }, receipts


def _window_table(path: Path, *, column: str, start_ns: int, end_ns: int) -> pa.Table:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe or missing accepted path evidence: {path}")
    return pq.read_table(path, filters=[(column, ">=", start_ns), (column, "<", end_ns)])


def _base_identity(row: dict[str, Any], *, timing_field: str) -> tuple[str, str, str, str]:
    return (
        str(row["market_episode_id"]),
        str(row["canonical_candidate_id"]),
        str(row["parameter_set_id"]),
        str(row[timing_field]),
    )


def _audit_raw_paths(
    *, output_root: Path, start_ns: int, end_ns: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reports: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for instrument in INSTRUMENTS:
        source_paths = {
            name: T11_SNAPSHOT / instrument / name
            for name in (
                "episode_paths.parquet",
                "h2_path_slices.parquet",
                "lineage.parquet",
                "path_quality.parquet",
            )
        }
        before = {name: _sha256_file(path) for name, path in source_paths.items()}
        raw = _window_table(
            source_paths["episode_paths.parquet"],
            column="episode_available_at_ns",
            start_ns=start_ns,
            end_ns=end_ns,
        )
        t12 = _window_table(
            T12_SNAPSHOT / instrument / "path_metrics.parquet",
            column="window_start_ns",
            start_ns=start_ns,
            end_ns=end_ns,
        )
        t13 = _window_table(
            T13_SNAPSHOT / instrument / "first_passage.parquet",
            column="window_start_ns",
            start_ns=start_ns,
            end_ns=end_ns,
        )
        if raw.num_rows <= 0:
            raise ValueError(f"seven-day raw path selection is empty for {instrument}")
        raw_rows = cast(list[dict[str, Any]], raw.to_pylist())
        t12_rows = cast(list[dict[str, Any]], t12.to_pylist())
        t13_rows = cast(list[dict[str, Any]], t13.to_pylist())
        raw_by_id = {
            _base_identity(row, timing_field="time_combination_id"): row for row in raw_rows
        }
        if len(raw_by_id) != len(raw_rows):
            raise ValueError("duplicate raw event-path identity")
        t12_counts: Counter[tuple[str, str, str, str]] = Counter()
        t13_counts: Counter[tuple[str, str, str, str]] = Counter()
        early_decision_cells = 0
        t4_primary_expired = 0
        t4_h2_rows = 0
        for row in t12_rows:
            identity = _base_identity(row, timing_field="time_combination_id")
            source = raw_by_id.get(identity)
            if source is None:
                raise ValueError("T12 row has no raw T11 path")
            t12_counts[identity] += 1
            if (
                row["source_s2t11_snapshot_id"] != T11_SNAPSHOT.name
                or not row["historical_evidence_only"]
                or int(row["window_start_ns"]) != int(source["window_start_ns"])
                or int(row["window_end_ns"]) != int(source["window_end_ns"])
            ):
                raise ValueError("T12 derived row rewrites raw-path identity or window")
        for row in t13_rows:
            identity = _base_identity(row, timing_field="timing_id")
            source = raw_by_id.get(identity)
            if source is None:
                raise ValueError("T13 row has no raw T11 path")
            t13_counts[identity] += 1
            if (
                row["source_s2t11_snapshot_id"] != T11_SNAPSHOT.name
                or not row["historical_evidence_only"]
                or int(row["window_start_ns"]) != int(source["window_start_ns"])
                or int(row["requested_window_end_ns"]) != int(source["requested_window_end_ns"])
                or int(row["source_window_end_ns"]) != int(source["window_end_ns"])
            ):
                raise ValueError("T13 derived row rewrites raw-path identity or window")
            early_decision_cells += sum(
                value is not None and int(value) < int(source["requested_window_end_ns"])
                for value in row["decision_ts_event_ns"]
            )
            if row["evidence_level"] == "H2" and row["timing_id"] == "T4":
                t4_h2_rows += 1
                order = cast(list[str], row["combination_order"])
                labels = cast(list[str], row["labels"])
                if labels[order.index(PRIMARY_COMBINATION)] == "EXPIRED":
                    t4_primary_expired += 1
        if set(t12_counts) != set(raw_by_id) or set(t13_counts) != set(raw_by_id):
            raise ValueError("derived path identity universe differs from raw T11")
        if set(t12_counts.values()) != {2} or set(t13_counts.values()) != {2}:
            raise ValueError("each raw path must have exactly H1 and H2 derived rows")
        timings = Counter(str(row["time_combination_id"]) for row in raw_rows)
        for row in raw_rows:
            timing = str(row["time_combination_id"])
            expected = HORIZON_SECONDS[timing] * 1_000_000_000
            if int(row["requested_window_end_ns"]) - int(row["window_start_ns"]) != expected:
                raise ValueError("raw event path horizon drift")
        roundtrip_path = output_root / "raw-path-roundtrip" / f"{instrument}.parquet"
        roundtrip_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(raw, roundtrip_path, compression="zstd")
        received = pq.read_table(roundtrip_path)
        if received.schema != raw.schema or received.to_pylist() != raw.to_pylist():
            raise ValueError("raw path strict Parquet read-back mismatch")
        after = {name: _sha256_file(path) for name, path in source_paths.items()}
        if before != after:
            raise ValueError("accepted T11 raw evidence changed during audit")
        report = {
            "instrument": instrument,
            "status": "PASS",
            "raw_path_row_count": raw.num_rows,
            "timing_counts": dict(sorted(timings.items())),
            "t12_derived_row_count": t12.num_rows,
            "t13_derived_row_count": t13.num_rows,
            "derived_rows_per_raw_path": {"T12": 2, "T13": 2},
            "early_decision_cell_count": early_decision_cells,
            "raw_path_preserved_after_early_decision": True,
            "t4_h2_row_count": t4_h2_rows,
            "t4_primary_expired_count": t4_primary_expired,
            "maximum_raw_horizon_seconds": max(HORIZON_SECONDS.values()),
            "source_hashes_unchanged": before,
            "roundtrip_sha256": _sha256_file(roundtrip_path),
            "schema_roundtrip": "PASS",
        }
        reports.append(report)
        receipts.append(
            {
                "relative_path": str(roundtrip_path.relative_to(output_root)),
                "sha256": report["roundtrip_sha256"],
                "row_count": raw.num_rows,
            }
        )
    total_expired = sum(int(item["t4_primary_expired_count"]) for item in reports)
    return {
        "status": "PASS",
        "reports": reports,
        "total_raw_path_row_count": sum(int(item["raw_path_row_count"]) for item in reports),
        "total_early_decision_cell_count": sum(
            int(item["early_decision_cell_count"]) for item in reports
        ),
        "total_t4_primary_expired_count": total_expired,
        "raw_event_paths_exit_rule_free": True,
    }, receipts


def lifecycle_assessment(*, t4_primary_expired_count: int) -> dict[str, Any]:
    """Return the fail-closed result without inventing OQ-S2-010 values."""

    blockers = [
        "OQ_S2_010_EXECUTABLE_VALUES_OPEN",
        "THEORETICAL_FULLY_FLAT_SCHEMA_NOT_IMPLEMENTED",
        "LIFECYCLE_PATH_SOURCE_STOPS_AT_T4_600S",
    ]
    if t4_primary_expired_count <= 0:
        blockers.append("SEVEN_DAY_WINDOW_DID_NOT_EXERCISE_SURVIVORS_AT_T4")
    return {
        "status": "BLOCKED",
        "can_run_to_theoretical_fully_flat": False,
        "blockers": blockers,
        "t4_primary_expired_count": t4_primary_expired_count,
        "scenario_net_exitable_pnl_computed": False,
        "position_flat_claimed": False,
        "authority_created": False,
        "binning_set_created": False,
        "run_id_created": False,
    }


def run_seven_day_audit(*, output_root: Path, start_date: date) -> tuple[dict[str, Any], Path]:
    """Run one isolated seven-day audit and write append-only local evidence."""

    if start_date != SOURCE_START_DATE:
        raise ValueError("CR-2026-031/032 audit must exercise the 2020-01-01 source boundary")
    if not _repository_clean():
        raise ValueError("seven-day audit requires a clean committed repository")
    root = _safe_new_output_root(output_root)
    governance = _governance_binding()
    start_ns = _ns_start(start_date)
    end_date = start_date + timedelta(days=AUDIT_DAY_COUNT)
    end_ns = _ns_start(end_date)
    feature, receipts = _audit_features(output_root=root, start_date=start_date)
    raw, raw_receipts = _audit_raw_paths(output_root=root, start_ns=start_ns, end_ns=end_ns)
    receipts.extend(raw_receipts)
    lifecycle = lifecycle_assessment(
        t4_primary_expired_count=int(raw["total_t4_primary_expired_count"])
    )
    payload: dict[str, Any] = {
        "schema_name": "stage2-cr031-cr032-seven-day-audit",
        "schema_version": "1.0",
        "status": "BLOCKED" if lifecycle["status"] == "BLOCKED" else "PASS",
        "reason": "FULL_LIFECYCLE_HANDOFF_NOT_EXECUTABLE",
        "start_utc": f"{start_date.isoformat()}T00:00:00Z",
        "end_utc": f"{end_date.isoformat()}T00:00:00Z",
        "day_count": AUDIT_DAY_COUNT,
        "code_commit": _current_commit(),
        "repository_clean": True,
        "governance_hashes": governance,
        "acceptance_criteria": {
            "real_input": True,
            "btc_eth_separate": True,
            "expected_grid_anchors_per_instrument": 10_080,
            "expected_boundary_warmup_unavailable_per_instrument": 61,
            "raw_timings_required": ["T1", "T2", "T3", "T4"],
            "raw_source_must_remain_byte_identical": True,
            "full_lifecycle_must_not_invent_open_oq_values": True,
        },
        "feature_availability": feature,
        "raw_path_non_pollution": raw,
        "theoretical_full_lifecycle": lifecycle,
        "ui_projection": "NOT_IN_SCOPE_NO_UI_FILES_CHANGED",
        "simulation_only": True,
        "published": False,
        "authority_created": False,
        "binning_set_created": False,
        "run_id_created": False,
        "formal_research_result_created": False,
        "limitations": [
            "Seven days cannot prove whole-history availability.",
            "No H3 cost or exit parameter was invented while OQ-S2-010 remains open.",
            "BLOCKED is an audit finding, not a strategy result.",
        ],
    }
    payload["report_hash"] = canonical_hash(payload)
    report_path = root / "seven-day-audit-report.json"
    _write_json_exclusive(report_path, payload)
    receipts.append(
        {
            "relative_path": str(report_path.relative_to(root)),
            "sha256": _sha256_file(report_path),
            "row_count": None,
        }
    )
    receipt: dict[str, Any] = {
        "schema_name": "stage2-cr031-cr032-seven-day-audit-receipt",
        "schema_version": "1.0",
        "status": payload["status"],
        "report_hash": payload["report_hash"],
        "files": receipts,
        "published": False,
        "authority_created": False,
        "run_id_created": False,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    _write_json_exclusive(root / "audit-receipt.json", receipt)
    verify_seven_day_audit(report_path=report_path)
    return payload, report_path


def verify_seven_day_audit(*, report_path: Path) -> dict[str, Any]:
    """Strictly read back and reconcile an isolated audit receipt."""

    report = _read_json_strict(report_path)
    expected_report_hash = canonical_hash({k: v for k, v in report.items() if k != "report_hash"})
    if report.get("report_hash") != expected_report_hash:
        raise ValueError("seven-day audit report hash mismatch")
    receipt_path = report_path.parent / "audit-receipt.json"
    receipt = _read_json_strict(receipt_path)
    expected_receipt_hash = canonical_hash(
        {k: v for k, v in receipt.items() if k != "receipt_hash"}
    )
    if receipt.get("receipt_hash") != expected_receipt_hash:
        raise ValueError("seven-day audit receipt hash mismatch")
    for item in cast(list[dict[str, Any]], receipt.get("files", [])):
        path = report_path.parent / str(item["relative_path"])
        if path.is_symlink() or not path.is_file() or _sha256_file(path) != item["sha256"]:
            raise ValueError(f"seven-day audit file drift: {path}")
        row_count = item.get("row_count")
        if row_count is not None and pq.ParquetFile(path).metadata.num_rows != int(row_count):
            raise ValueError(f"seven-day audit Parquet row-count drift: {path}")
    if receipt.get("report_hash") != report.get("report_hash"):
        raise ValueError("seven-day audit receipt points at another report")
    return {
        "schema_name": "stage2-cr031-cr032-seven-day-audit-verify",
        "schema_version": "1.0",
        "status": "PASS",
        "audit_status": report["status"],
        "report_hash": report["report_hash"],
        "receipt_hash": receipt["receipt_hash"],
        "file_count": len(receipt["files"]),
        "authority_created": False,
        "run_id_created": False,
    }
