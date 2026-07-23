"""Resumable read-only BTC/ETH feature-availability audit for OQ-S2-009."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from era100x.research.stage_2.baselines.conditional.full_run import (
    T10_SNAPSHOT,
    T10_SNAPSHOT_ID,
)
from era100x.research.stage_2.baselines.conditional.production_core import prepare_daily_features
from era100x.research.stage_2.baselines.conditional.t10_access import FixedT10Reader
from era100x.research.stage_2.baselines.conditional.v14_contracts import (
    REGISTERED_PARAMETER_TIMING_PAIRS,
)

INSTRUMENTS = ("BTCUSDT", "ETHUSDT")
SOURCE_START_DATE = date(2020, 1, 1)
SOURCE_END_EXCLUSIVE = date(2026, 7, 4)
DATASET_START_NS = 1_577_836_800_000_000_000
# The 61-bar feature needs the complete first 61 UTC minutes.  The deterministic
# daily grid may be offset by up to 59 seconds, so the exclusive boundary must
# cover the whole minute beginning at 01:00:00Z.
BOUNDARY_WARMUP_END_NS = DATASET_START_NS + 3_660 * 1_000_000_000
TYPED_REASONS = (
    "BOUNDARY_WARMUP_UNAVAILABLE",
    "DECLARED_SOURCE_GAP",
    "DATA_END_UNAVAILABLE",
    "UNBOUND_SOURCE_PARTITION",
    "FEATURE_VALUE_INVALID",
    "UNCLASSIFIED_UNAVAILABLE",
)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def audit_dates(start_date: date, end_date_exclusive: date) -> tuple[date, ...]:
    if start_date < SOURCE_START_DATE or end_date_exclusive > SOURCE_END_EXCLUSIVE:
        raise ValueError("availability audit range exceeds frozen source coverage")
    if end_date_exclusive <= start_date:
        raise ValueError("availability audit range must be non-empty")
    return tuple(
        start_date + timedelta(days=offset)
        for offset in range((end_date_exclusive - start_date).days)
    )


def classify_unavailable(*, owner_date: date, anchor_ns: int, raw_reason: str) -> str:
    if (
        owner_date == SOURCE_START_DATE
        and raw_reason == "PRICE_FEATURE_UNAVAILABLE"
        and anchor_ns < BOUNDARY_WARMUP_END_NS
    ):
        return "BOUNDARY_WARMUP_UNAVAILABLE"
    normalized = raw_reason.upper()
    if "DECLARED" in normalized and "GAP" in normalized:
        return "DECLARED_SOURCE_GAP"
    if "DATA_END" in normalized:
        return "DATA_END_UNAVAILABLE"
    if "UNBOUND" in normalized or "MISSING_PARTITION" in normalized:
        return "UNBOUND_SOURCE_PARTITION"
    if "INVALID" in normalized or "DUPLICATE" in normalized:
        return "FEATURE_VALUE_INVALID"
    return "UNCLASSIFIED_UNAVAILABLE"


def _empty_instrument() -> dict[str, Any]:
    return {
        "completed_dates": [],
        "grid_anchor_count": 0,
        "valid_market_anchor_count": 0,
        "available_zero_activity_count": 0,
        "typed_missingness_counts": {reason: 0 for reason in TYPED_REASONS},
        "raw_exclusion_counts": {},
        "by_month": {},
    }


def _new_checkpoint(
    *, start_date: date, end_date_exclusive: date, snapshot_id: str
) -> dict[str, Any]:
    return {
        "schema_name": "stage2-v13-availability-audit-checkpoint-v1",
        "status": "IN_PROGRESS",
        "reason_code": "S2_V13_AVAILABILITY_AUDIT_IN_PROGRESS",
        "stage_plan_version": "1.3",
        "source_t10_snapshot_id": snapshot_id,
        "date_start": start_date.isoformat(),
        "date_end_exclusive": end_date_exclusive.isoformat(),
        "instruments": {instrument: _empty_instrument() for instrument in INSTRUMENTS},
        "authority_created": False,
        "binning_set_created": False,
        "run_id_created": False,
        "historical_evidence_only": True,
        "stage3_locked": True,
    }


def _month(state: dict[str, Any], key: str) -> dict[str, Any]:
    months = cast(dict[str, dict[str, Any]], state["by_month"])
    return months.setdefault(
        key,
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
    root: Path,
    start_date: date,
    end_date_exclusive: date,
    t10_snapshot: Path = T10_SNAPSHOT,
    t10_snapshot_id: str = T10_SNAPSHOT_ID,
) -> tuple[dict[str, Any], Path]:
    """Run or resume an unpublished read-only availability audit."""

    dates = audit_dates(start_date, end_date_exclusive)
    if root.is_symlink():
        raise ValueError("availability audit root cannot be a symlink")
    checkpoint_path = root / "checkpoint.json"
    if checkpoint_path.exists():
        if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
            raise ValueError("unsafe availability audit checkpoint")
        checkpoint = cast(dict[str, Any], json.loads(checkpoint_path.read_bytes()))
    else:
        checkpoint = _new_checkpoint(
            start_date=start_date,
            end_date_exclusive=end_date_exclusive,
            snapshot_id=t10_snapshot_id,
        )
        _atomic_json(checkpoint_path, checkpoint)
    expected_contract = (
        checkpoint.get("schema_name") == "stage2-v13-availability-audit-checkpoint-v1"
        and checkpoint.get("source_t10_snapshot_id") == t10_snapshot_id
        and checkpoint.get("date_start") == start_date.isoformat()
        and checkpoint.get("date_end_exclusive") == end_date_exclusive.isoformat()
    )
    if not expected_contract:
        raise ValueError("availability audit checkpoint contract drift")
    reader = FixedT10Reader(t10_snapshot, expected_snapshot_id=t10_snapshot_id)
    parameter_ids = tuple(dict.fromkeys(pair[0] for pair in REGISTERED_PARAMETER_TIMING_PAIRS))
    for instrument in INSTRUMENTS:
        state = cast(dict[str, Any], checkpoint["instruments"][instrument])
        completed = set(cast(list[str], state["completed_dates"]))
        for owner_date in dates:
            if owner_date.isoformat() in completed:
                continue
            monthly = _month(state, owner_date.strftime("%Y-%m"))
            try:
                prepared = prepare_daily_features(
                    reader,
                    instrument=instrument,
                    owner_date=owner_date,
                    parameter_set_ids=parameter_ids,
                )
            except (OSError, ValueError) as exc:
                typed = Counter(cast(dict[str, int], state["typed_missingness_counts"]))
                typed["UNBOUND_SOURCE_PARTITION"] += 1
                state["typed_missingness_counts"] = dict(sorted(typed.items()))
                checkpoint.update(
                    {
                        "status": "BLOCKED",
                        "reason_code": "S2_V13_UNBOUND_SOURCE_PARTITION",
                        "failure": {
                            "instrument": instrument,
                            "date": owner_date.isoformat(),
                            "reason": str(exc),
                        },
                    }
                )
                _atomic_json(checkpoint_path, checkpoint)
                raise
            raw = Counter(cast(dict[str, int], state["raw_exclusion_counts"]))
            raw.update(prepared.exclusion_counts)
            state["raw_exclusion_counts"] = dict(sorted(raw.items()))
            month_raw = Counter(cast(dict[str, int], monthly["raw_exclusion_counts"]))
            month_raw.update(prepared.exclusion_counts)
            monthly["raw_exclusion_counts"] = dict(sorted(month_raw.items()))
            typed = Counter(cast(dict[str, int], state["typed_missingness_counts"]))
            month_typed = Counter(cast(dict[str, int], monthly["typed_missingness_counts"]))
            for anchor_ns, raw_reason in prepared.exclusion_by_anchor.items():
                reason = classify_unavailable(
                    owner_date=owner_date, anchor_ns=anchor_ns, raw_reason=raw_reason
                )
                typed[reason] += 1
                month_typed[reason] += 1
            zero_activity = sum(feature.activity_count_60s == 0 for feature in prepared.valid_rows)
            state["grid_anchor_count"] = (
                int(state["grid_anchor_count"]) + prepared.grid_anchor_count
            )
            state["valid_market_anchor_count"] = int(state["valid_market_anchor_count"]) + len(
                prepared.valid_rows
            )
            state["available_zero_activity_count"] = (
                int(state["available_zero_activity_count"]) + zero_activity
            )
            state["typed_missingness_counts"] = dict(sorted(typed.items()))
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
    blockers = {
        reason: sum(
            int(checkpoint["instruments"][instrument]["typed_missingness_counts"].get(reason, 0))
            for instrument in INSTRUMENTS
        )
        for reason in (
            "UNBOUND_SOURCE_PARTITION",
            "FEATURE_VALUE_INVALID",
            "UNCLASSIFIED_UNAVAILABLE",
        )
    }
    status = "PASS" if not any(blockers.values()) else "BLOCKED"
    payload: dict[str, Any] = {
        "schema_name": "stage2-v13-availability-audit-v1",
        "status": status,
        "reason_code": (
            "S2_V13_AVAILABILITY_AUDIT_PASS"
            if status == "PASS"
            else "S2_V13_AVAILABILITY_AUDIT_BLOCKED"
        ),
        "stage_plan_version": "1.3",
        "source_t10_snapshot_id": t10_snapshot_id,
        "date_start": start_date.isoformat(),
        "date_end_exclusive": end_date_exclusive.isoformat(),
        "day_count": len(dates),
        "instruments": checkpoint["instruments"],
        "blocking_missingness_counts": blockers,
        "authority_created": False,
        "binning_set_created": False,
        "run_id_created": False,
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    payload["audit_hash"] = _canonical_hash(payload)
    report = root / f"{payload['audit_hash']}.json"
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if report.exists():
        if report.is_symlink() or report.read_text(encoding="utf-8") != encoded:
            raise ValueError("availability audit append-only conflict")
    else:
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    checkpoint.update(
        {
            "status": status,
            "reason_code": payload["reason_code"],
            "audit_hash": payload["audit_hash"],
            "report_path": str(report),
        }
    )
    _atomic_json(checkpoint_path, checkpoint)
    verify_availability_audit(report)
    return payload, report


def verify_availability_audit(report_path: Path) -> dict[str, Any]:
    if report_path.is_symlink() or not report_path.is_file():
        raise ValueError("unsafe or missing availability report")
    payload = cast(dict[str, Any], json.loads(report_path.read_bytes()))
    claimed = payload.pop("audit_hash", None)
    computed = _canonical_hash(payload)
    if claimed != computed:
        raise ValueError("availability audit hash mismatch")
    for instrument in INSTRUMENTS:
        state = payload["instruments"][instrument]
        classified = sum(int(value) for value in state["typed_missingness_counts"].values())
        if int(state["grid_anchor_count"]) != int(state["valid_market_anchor_count"]) + classified:
            raise ValueError(f"availability reconciliation failed: {instrument}")
    return {
        "schema_name": "stage2-v13-availability-audit-verify-v1",
        "status": "PASS",
        "audit_status": payload["status"],
        "audit_hash": claimed,
        "stage_plan_version": "1.3",
    }
