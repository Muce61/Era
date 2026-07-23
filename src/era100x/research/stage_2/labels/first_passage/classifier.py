"""Pure S2-T13 historical first-passage classification."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Literal, cast

from era100x.research.stage_2.paths.extraction.models import ExtractedHistoricalPath

from .models import (
    PROHIBITED_INTERPRETATIONS,
    REGISTERED_HORIZONS_SECONDS,
    REGISTERED_STOP_BPS,
    REGISTERED_TARGET_BPS,
    HistoricalFirstPassageLabel,
)

BPS = Decimal("10000")
NANOSECONDS_PER_SECOND = 1_000_000_000
EvidenceLevel = Literal["H1", "H2"]
TimingId = Literal["T1", "T2", "T3", "T4"]


def _registered_inputs(*, target_bps: Decimal, stop_bps: Decimal, timing_id: TimingId) -> int:
    if target_bps not in REGISTERED_TARGET_BPS:
        raise ValueError("target_bps is outside the frozen Stage 2 preregistration")
    if stop_bps not in REGISTERED_STOP_BPS:
        raise ValueError("stop_bps is outside the frozen Stage 2 preregistration")
    return REGISTERED_HORIZONS_SECONDS[timing_id]


def _source_gap_codes(
    path: ExtractedHistoricalPath, evidence_level: EvidenceLevel
) -> tuple[str, ...]:
    return tuple(
        sorted({gap.reason_code for gap in path.gaps if gap.evidence_level == evidence_level})
    )


def _gap_precedes(
    path: ExtractedHistoricalPath,
    evidence_level: EvidenceLevel,
    cutoff_ns: int,
) -> bool:
    return any(
        gap.evidence_level == evidence_level
        and gap.preceding_ts_event_ns < cutoff_ns
        and gap.following_ts_event_ns > path.window_start_ns
        for gap in path.gaps
    )


def _base_payload(
    path: ExtractedHistoricalPath,
    *,
    evidence_level: EvidenceLevel,
    reference_price: Decimal,
    target_bps: Decimal,
    stop_bps: Decimal,
    timing_id: TimingId,
    horizon_seconds: int,
    observation_count: int,
) -> dict[str, object]:
    source = path.h1_source if evidence_level == "H1" else path.h2_source
    target_price = reference_price * (Decimal(1) + target_bps / BPS)
    stop_price = reference_price * (Decimal(1) - stop_bps / BPS)
    requested_end = path.window_start_ns + horizon_seconds * NANOSECONDS_PER_SECOND
    return {
        "instrument": path.instrument,
        "market_episode_id": path.market_episode_id,
        "canonical_candidate_id": path.canonical_candidate_id,
        "candidate_version_id": path.candidate_version_id,
        "canonical_payload_hash": path.canonical_payload_hash,
        "parameter_set_id": path.parameter_set_id,
        "evidence_level": evidence_level,
        "reference_price_type": source.reference_price_type,
        "reference_price": reference_price,
        "target_bps": target_bps,
        "stop_bps": stop_bps,
        "target_price": target_price,
        "stop_price": stop_price,
        "timing_id": timing_id,
        "horizon_seconds": horizon_seconds,
        "window_start_ns": path.window_start_ns,
        "requested_window_end_ns": requested_end,
        "source_window_end_ns": path.window_end_ns,
        "window_complete": path.window_end_ns >= requested_end,
        "observation_count": observation_count,
        "time_semantics": path.time_semantics,
        "stable_order": (
            ("ts_event_ns", "source_row_hash")
            if evidence_level == "H1"
            else ("ts_event_ns", "venue_trade_id", "canonical_trade_id")
        ),
        "source_quality_status": path.quality_status,
        "source_gap_codes": _source_gap_codes(path, evidence_level),
        "source_ambiguity_codes": path.ambiguity_codes,
        "historical_evidence_only": True,
        "prohibited_interpretations": PROHIBITED_INTERPRETATIONS,
        "source_path_hash": path.output_hash,
    }


def _seal_result(
    base: dict[str, object],
    *,
    label: str,
    label_reason: str,
    conservative_main_label: str | None,
    target_ts: int | None,
    stop_ts: int | None,
    decision_ts: int | None,
) -> HistoricalFirstPassageLabel:
    window_start = cast(int, base["window_start_ns"])
    return HistoricalFirstPassageLabel.seal(
        {
            **base,
            "label": label,
            "label_reason": label_reason,
            "conservative_main_label": conservative_main_label,
            "target_touch_ts_event_ns": target_ts,
            "stop_touch_ts_event_ns": stop_ts,
            "decision_ts_event_ns": decision_ts,
            "time_to_decision_ns": None if decision_ts is None else decision_ts - window_start,
            "strict_target_first": label == "TARGET_FIRST",
        }
    )


def _validate_path(path: ExtractedHistoricalPath, reference_price: Decimal) -> None:
    if path.output_hash != path.computed_hash():
        raise ValueError("source path hash is not valid")
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")


def _finish_classification(
    path: ExtractedHistoricalPath,
    *,
    evidence_level: EvidenceLevel,
    base: dict[str, object],
    target_ts: int | None,
    stop_ts: int | None,
    same_event_both: bool,
) -> HistoricalFirstPassageLabel:
    observed_decisions = tuple(ts for ts in (target_ts, stop_ts) if ts is not None)
    first_observed = min(observed_decisions) if observed_decisions else None
    requested_end = cast(int, base["requested_window_end_ns"])
    if first_observed is not None and _gap_precedes(path, evidence_level, first_observed):
        return _seal_result(
            base,
            label="AMBIGUOUS",
            label_reason="SOURCE_GAP_BEFORE_DECISION",
            conservative_main_label=None,
            target_ts=target_ts,
            stop_ts=stop_ts,
            decision_ts=None,
        )
    if same_event_both:
        assert first_observed is not None
        return _seal_result(
            base,
            label="AMBIGUOUS",
            label_reason="H1_SAME_EVENT_TARGET_AND_STOP",
            conservative_main_label="STOP_FIRST",
            target_ts=target_ts,
            stop_ts=stop_ts,
            decision_ts=first_observed,
        )
    if target_ts is not None and (stop_ts is None or target_ts < stop_ts):
        return _seal_result(
            base,
            label="TARGET_FIRST",
            label_reason="TARGET_OBSERVED_FIRST",
            conservative_main_label="TARGET_FIRST",
            target_ts=target_ts,
            stop_ts=stop_ts,
            decision_ts=target_ts,
        )
    if stop_ts is not None:
        return _seal_result(
            base,
            label="STOP_FIRST",
            label_reason="STOP_OBSERVED_FIRST",
            conservative_main_label="STOP_FIRST",
            target_ts=target_ts,
            stop_ts=stop_ts,
            decision_ts=stop_ts,
        )
    if cast(int, base["observation_count"]) == 0:
        return _seal_result(
            base,
            label="AMBIGUOUS",
            label_reason="NO_OBSERVATIONS",
            conservative_main_label=None,
            target_ts=None,
            stop_ts=None,
            decision_ts=None,
        )
    if _gap_precedes(path, evidence_level, requested_end):
        reason = "SOURCE_GAP_BEFORE_DECISION"
    elif not bool(base["window_complete"]):
        reason = "WINDOW_TRUNCATED_BEFORE_DECISION"
    else:
        return _seal_result(
            base,
            label="EXPIRED",
            label_reason="HORIZON_EXPIRED_WITHOUT_TOUCH",
            conservative_main_label="EXPIRED",
            target_ts=None,
            stop_ts=None,
            decision_ts=None,
        )
    return _seal_result(
        base,
        label="AMBIGUOUS",
        label_reason=reason,
        conservative_main_label=None,
        target_ts=None,
        stop_ts=None,
        decision_ts=None,
    )


def classify_h1_first_passage(
    path: ExtractedHistoricalPath,
    *,
    reference_price: Decimal,
    target_bps: Decimal,
    stop_bps: Decimal,
    timing_id: TimingId,
) -> HistoricalFirstPassageLabel:
    """Classify Contract-bar first passage without inventing intrasecond order."""

    _validate_path(path, reference_price)
    horizon_seconds = _registered_inputs(
        target_bps=target_bps, stop_bps=stop_bps, timing_id=timing_id
    )
    requested_end = path.window_start_ns + horizon_seconds * NANOSECONDS_PER_SECOND
    points = tuple(point for point in path.h1_points if point.ts_event_ns < requested_end)
    base = _base_payload(
        path,
        evidence_level="H1",
        reference_price=reference_price,
        target_bps=target_bps,
        stop_bps=stop_bps,
        timing_id=timing_id,
        horizon_seconds=horizon_seconds,
        observation_count=len(points),
    )
    target_price = cast(Decimal, base["target_price"])
    stop_price = cast(Decimal, base["stop_price"])
    grouped: dict[int, list[tuple[Decimal, Decimal]]] = defaultdict(list)
    for point in points:
        grouped[point.ts_event_ns].append((point.high, point.low))
    target_ts: int | None = None
    stop_ts: int | None = None
    same_event_both = False
    for ts in sorted(grouped):
        target_here = any(high >= target_price for high, _ in grouped[ts])
        stop_here = any(low <= stop_price for _, low in grouped[ts])
        if target_here and target_ts is None:
            target_ts = ts
        if stop_here and stop_ts is None:
            stop_ts = ts
        if target_here or stop_here:
            same_event_both = target_here and stop_here
            break
    return _finish_classification(
        path,
        evidence_level="H1",
        base=base,
        target_ts=target_ts,
        stop_ts=stop_ts,
        same_event_both=same_event_both,
    )


def classify_h2_first_passage(
    path: ExtractedHistoricalPath,
    *,
    reference_price: Decimal,
    target_bps: Decimal,
    stop_bps: Decimal,
    timing_id: TimingId,
) -> HistoricalFirstPassageLabel:
    """Classify Trade first passage in frozen V2 stable event order."""

    _validate_path(path, reference_price)
    horizon_seconds = _registered_inputs(
        target_bps=target_bps, stop_bps=stop_bps, timing_id=timing_id
    )
    requested_end = path.window_start_ns + horizon_seconds * NANOSECONDS_PER_SECOND
    points = tuple(point for point in path.h2_points if point.ts_event_ns < requested_end)
    base = _base_payload(
        path,
        evidence_level="H2",
        reference_price=reference_price,
        target_bps=target_bps,
        stop_bps=stop_bps,
        timing_id=timing_id,
        horizon_seconds=horizon_seconds,
        observation_count=len(points),
    )
    target_price = cast(Decimal, base["target_price"])
    stop_price = cast(Decimal, base["stop_price"])
    target_ts: int | None = None
    stop_ts: int | None = None
    for point in points:
        if point.price >= target_price:
            target_ts = point.ts_event_ns
            break
        if point.price <= stop_price:
            stop_ts = point.ts_event_ns
            break
    return _finish_classification(
        path,
        evidence_level="H2",
        base=base,
        target_ts=target_ts,
        stop_ts=stop_ts,
        same_event_both=False,
    )
