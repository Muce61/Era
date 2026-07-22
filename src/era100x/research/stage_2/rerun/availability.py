"""Resumable whole-range CR-2026-031 availability audit.

This audit creates no research Authority, Binning Set, or Run ID.  It reads the fixed T10
Foundation and writes only an append-only audit report plus an operational checkpoint.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from era100x.research.stage_2.baselines.conditional.full_run import (
    AUDIT_ROOT,
    T10_SNAPSHOT,
    T10_SNAPSHOT_ID,
)
from era100x.research.stage_2.baselines.conditional.production_core import prepare_daily_features
from era100x.research.stage_2.baselines.conditional.t10_access import FixedT10Reader
from era100x.research.stage_2.baselines.conditional.v14_contracts import (
    REGISTERED_PARAMETER_TIMING_PAIRS,
)

from .orchestrator import canonical_hash

INSTRUMENTS = ("BTCUSDT", "ETHUSDT")
START_DATE = date(2020, 1, 1)
END_DATE_EXCLUSIVE = date(2026, 7, 4)
DATASET_START_NS = 1_577_836_800_000_000_000
BOUNDARY_WARMUP_END_NS = DATASET_START_NS + 3_601 * 1_000_000_000
AVAILABILITY_ROOT = AUDIT_ROOT / "availability"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _dates() -> tuple[date, ...]:
    count = (END_DATE_EXCLUSIVE - START_DATE).days
    return tuple(START_DATE + timedelta(days=index) for index in range(count))


def _empty_instrument() -> dict[str, Any]:
    return {
        "completed_dates": [],
        "grid_anchor_count": 0,
        "valid_market_anchor_count": 0,
        "available_zero_activity_count": 0,
        "typed_missingness_counts": {
            "BOUNDARY_WARMUP_UNAVAILABLE": 0,
            "DECLARED_SOURCE_GAP": 0,
            "UNBOUND_SOURCE_PARTITION": 0,
            "FEATURE_VALUE_INVALID": 0,
            "UNCLASSIFIED_UNAVAILABLE": 0,
        },
        "raw_exclusion_counts": {},
        "by_month": {},
    }


def _initial_checkpoint() -> dict[str, Any]:
    return {
        "schema_name": "stage2-s2t15-availability-audit-checkpoint-v1",
        "status": "IN_PROGRESS",
        "reason_code": "S2_T15_AVAILABILITY_AUDIT_IN_PROGRESS",
        "source_t10_snapshot_id": T10_SNAPSHOT_ID,
        "date_start": START_DATE.isoformat(),
        "date_end_exclusive": END_DATE_EXCLUSIVE.isoformat(),
        "instruments": {instrument: _empty_instrument() for instrument in INSTRUMENTS},
        "authority_created": False,
        "binning_set_created": False,
        "run_id_created": False,
        "seven_day_audit_executed": False,
        "historical_evidence_only": True,
        "stage3_locked": True,
    }


def _classify_unavailable(owner_date: date, anchor_ns: int, raw_reason: str) -> str:
    if (
        owner_date == START_DATE
        and raw_reason == "PRICE_FEATURE_UNAVAILABLE"
        and anchor_ns < BOUNDARY_WARMUP_END_NS
    ):
        return "BOUNDARY_WARMUP_UNAVAILABLE"
    return "UNCLASSIFIED_UNAVAILABLE"


def _month_payload(instrument_state: dict[str, Any], month: str) -> dict[str, Any]:
    months = cast(dict[str, dict[str, Any]], instrument_state["by_month"])
    return months.setdefault(
        month,
        {
            "days": 0,
            "grid_anchor_count": 0,
            "valid_market_anchor_count": 0,
            "available_zero_activity_count": 0,
            "typed_missingness_counts": {},
            "raw_exclusion_counts": {},
        },
    )


def run_availability_audit(
    *,
    root: Path = AVAILABILITY_ROOT,
    t10_snapshot: Path = T10_SNAPSHOT,
    t10_snapshot_id: str = T10_SNAPSHOT_ID,
) -> tuple[dict[str, Any], Path]:
    """Scan BTC/ETH full coverage and resume from the last completed UTC date."""

    checkpoint_path = root / "checkpoint.json"
    if checkpoint_path.exists():
        if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
            raise ValueError("unsafe availability audit checkpoint")
        checkpoint = cast(dict[str, Any], json.loads(checkpoint_path.read_bytes()))
    else:
        checkpoint = _initial_checkpoint()
        _atomic_json(checkpoint_path, checkpoint)
    if (
        checkpoint.get("schema_name") != "stage2-s2t15-availability-audit-checkpoint-v1"
        or checkpoint.get("source_t10_snapshot_id") != t10_snapshot_id
        or checkpoint.get("date_start") != START_DATE.isoformat()
        or checkpoint.get("date_end_exclusive") != END_DATE_EXCLUSIVE.isoformat()
    ):
        raise ValueError("availability audit checkpoint contract drift")
    reader = FixedT10Reader(t10_snapshot, expected_snapshot_id=t10_snapshot_id)
    parameters = tuple(pair[0] for pair in REGISTERED_PARAMETER_TIMING_PAIRS)
    for instrument in INSTRUMENTS:
        state = cast(dict[str, Any], checkpoint["instruments"][instrument])
        completed = set(cast(list[str], state["completed_dates"]))
        for owner_date in _dates():
            if owner_date.isoformat() in completed:
                continue
            month = owner_date.strftime("%Y-%m")
            monthly = _month_payload(state, month)
            try:
                prepared = prepare_daily_features(
                    reader,
                    instrument=instrument,
                    owner_date=owner_date,
                    parameter_set_ids=parameters,
                )
            except (OSError, ValueError) as exc:
                typed = cast(dict[str, int], state["typed_missingness_counts"])
                typed["UNBOUND_SOURCE_PARTITION"] += 1
                checkpoint["status"] = "BLOCKED"
                checkpoint["reason_code"] = "S2_T15_UNBOUND_SOURCE_PARTITION"
                checkpoint["failure"] = {
                    "instrument": instrument,
                    "date": owner_date.isoformat(),
                    "reason": str(exc),
                }
                _atomic_json(checkpoint_path, checkpoint)
                raise
            raw_counts = Counter(cast(dict[str, int], state["raw_exclusion_counts"]))
            raw_counts.update(prepared.exclusion_counts)
            state["raw_exclusion_counts"] = dict(sorted(raw_counts.items()))
            month_raw = Counter(cast(dict[str, int], monthly["raw_exclusion_counts"]))
            month_raw.update(prepared.exclusion_counts)
            monthly["raw_exclusion_counts"] = dict(sorted(month_raw.items()))
            typed_counts = Counter(cast(dict[str, int], state["typed_missingness_counts"]))
            month_typed = Counter(cast(dict[str, int], monthly["typed_missingness_counts"]))
            for anchor_ns, raw_reason in prepared.exclusion_by_anchor.items():
                reason = _classify_unavailable(owner_date, anchor_ns, raw_reason)
                typed_counts[reason] += 1
                month_typed[reason] += 1
            zero_activity = sum(
                1 for feature in prepared.valid_rows if feature.activity_count_60s == 0
            )
            state["grid_anchor_count"] = (
                int(state["grid_anchor_count"]) + prepared.grid_anchor_count
            )
            state["valid_market_anchor_count"] = int(state["valid_market_anchor_count"]) + len(
                prepared.valid_rows
            )
            state["available_zero_activity_count"] = (
                int(state["available_zero_activity_count"]) + zero_activity
            )
            state["typed_missingness_counts"] = dict(sorted(typed_counts.items()))
            monthly["days"] = int(monthly["days"]) + 1
            monthly["grid_anchor_count"] = (
                int(monthly["grid_anchor_count"]) + prepared.grid_anchor_count
            )
            monthly["valid_market_anchor_count"] = int(monthly["valid_market_anchor_count"]) + len(
                prepared.valid_rows
            )
            monthly["available_zero_activity_count"] = (
                int(monthly["available_zero_activity_count"]) + zero_activity
            )
            monthly["typed_missingness_counts"] = dict(sorted(month_typed.items()))
            completed.add(owner_date.isoformat())
            state["completed_dates"] = sorted(completed)
            checkpoint["updated_at"] = datetime.now(UTC).isoformat()
            _atomic_json(checkpoint_path, checkpoint)
    unclassified = sum(
        int(
            checkpoint["instruments"][instrument]["typed_missingness_counts"].get(
                "UNCLASSIFIED_UNAVAILABLE", 0
            )
        )
        for instrument in INSTRUMENTS
    )
    payload: dict[str, Any] = {
        "schema_name": "stage2-s2t15-availability-audit-v1",
        "status": "PASS" if unclassified == 0 else "BLOCKED",
        "reason_code": (
            "S2_T15_AVAILABILITY_AUDIT_PASS"
            if unclassified == 0
            else "S2_T15_UNCLASSIFIED_UNAVAILABLE"
        ),
        "source_t10_snapshot_id": t10_snapshot_id,
        "date_start": START_DATE.isoformat(),
        "date_end_exclusive": END_DATE_EXCLUSIVE.isoformat(),
        "instruments": checkpoint["instruments"],
        "unclassified_unavailable_count": unclassified,
        "authority_created": False,
        "binning_set_created": False,
        "run_id_created": False,
        "seven_day_audit_executed": False,
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    payload["audit_hash"] = canonical_hash(payload)
    report = root / f"{payload['audit_hash']}.json"
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if report.exists():
        if report.is_symlink() or report.read_text(encoding="utf-8") != encoded:
            raise ValueError("availability audit report append-only conflict")
    else:
        with report.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    checkpoint["status"] = payload["status"]
    checkpoint["reason_code"] = payload["reason_code"]
    checkpoint["audit_hash"] = payload["audit_hash"]
    checkpoint["report_path"] = str(report)
    _atomic_json(checkpoint_path, checkpoint)
    return payload, report
