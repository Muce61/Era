"""T15-local H2 matrix outcomes using the accepted T13 crossing semantics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Sequence
from typing import cast

from era100x.research.stage_2.paths.extraction.models import PathGap

from .v14_contracts import (
    COMBINATION_ORDER,
    REGISTERED_STOP_BPS,
    REGISTERED_TARGET_BPS,
    ControlOutcomeMatrix,
    HistoricalLabel,
    OutcomeCell,
)

NS = 1_000_000_000
BPS = Decimal(10_000)
HORIZONS_SECONDS = {"T1": 60, "T2": 180, "T3": 300, "T4": 600}
H2_COVERAGE_CONTRACT_ID = "H2_WINDOW_INTERNAL_GAP_BEFORE_DECISION_V1"


@dataclass(frozen=True, slots=True)
class H2Trade:
    ts_event_ns: int
    venue_trade_id: int
    canonical_trade_id: str
    price: Decimal


def detect_h2_window_gaps(trades: Sequence[H2Trade]) -> tuple[PathGap, ...]:
    """Detect only gaps observable between adjacent facts in this exact H2 window."""

    gaps: list[PathGap] = []
    for left, right in zip(trades, trades[1:], strict=False):
        if right.venue_trade_id > left.venue_trade_id + 1:
            gaps.append(
                PathGap(
                    evidence_level="H2",
                    reason_code="H2_VENUE_TRADE_ID_GAP",
                    preceding_ts_event_ns=left.ts_event_ns,
                    following_ts_event_ns=right.ts_event_ns,
                    missing_count=right.venue_trade_id - left.venue_trade_id - 1,
                    preceding_venue_trade_id=left.venue_trade_id,
                    following_venue_trade_id=right.venue_trade_id,
                )
            )
        elif right.venue_trade_id < left.venue_trade_id:
            gaps.append(
                PathGap(
                    evidence_level="H2",
                    reason_code="H2_VENUE_TRADE_ID_REVERSAL",
                    preceding_ts_event_ns=left.ts_event_ns,
                    following_ts_event_ns=right.ts_event_ns,
                    missing_count=left.venue_trade_id - right.venue_trade_id,
                    preceding_venue_trade_id=left.venue_trade_id,
                    following_venue_trade_id=right.venue_trade_id,
                )
            )
    return tuple(gaps)


def _gap_precedes(
    gaps: Sequence[PathGap],
    *,
    anchor_ns: int,
    cutoff_ns: int,
) -> bool:
    return any(
        gap.evidence_level == "H2"
        and gap.preceding_ts_event_ns < cutoff_ns
        and gap.following_ts_event_ns > anchor_ns
        for gap in gaps
    )


def classify_h2_cells(
    trades: Sequence[H2Trade],
    *,
    anchor_ns: int,
    reference_price: Decimal,
    time_combination_id: str,
    source_partition_bound: bool,
    source_gaps: Sequence[PathGap] = (),
) -> tuple[OutcomeCell, ...]:
    """Classify 30 cells; an unbound partition is a hard run failure."""

    if not source_partition_bound:
        raise ValueError("UPSTREAM_SOURCE_PARTITION_UNBOUND")
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    try:
        horizon_seconds = HORIZONS_SECONDS[time_combination_id]
    except KeyError as exc:
        raise ValueError("unregistered time combination") from exc
    end_ns = anchor_ns + horizon_seconds * NS
    ordered = tuple(trades)
    previous_identity: tuple[int, int, str] | None = None
    for row in ordered:
        identity = (row.ts_event_ns, row.venue_trade_id, row.canonical_trade_id)
        if identity == previous_identity:
            raise ValueError("duplicate H2 stable-order identity")
        if previous_identity is not None and identity < previous_identity:
            raise ValueError("H2 input must already use the frozen stable order")
        previous_identity = identity
    window = tuple(row for row in ordered if anchor_ns <= row.ts_event_ns < end_ns)
    if any(row.price <= 0 for row in window):
        raise ValueError("invalid H2 Trade price")
    cells: list[OutcomeCell] = []
    for target in REGISTERED_TARGET_BPS:
        target_price = reference_price * (Decimal(1) + target / BPS)
        for stop in REGISTERED_STOP_BPS:
            combination_id = f"target={target:f}|stop={stop:f}"
            stop_price = reference_price * (Decimal(1) - stop / BPS)
            if not window:
                label = "AMBIGUOUS"
                reason = "NO_OBSERVATIONS"
            else:
                label = "EXPIRED"
                reason = "HORIZON_EXPIRED_WITHOUT_TOUCH"
                decision_ns: int | None = None
                for trade in window:
                    if trade.price >= target_price:
                        label = "TARGET_FIRST"
                        reason = "TARGET_OBSERVED_FIRST"
                        decision_ns = trade.ts_event_ns
                        break
                    if trade.price <= stop_price:
                        label = "STOP_FIRST"
                        reason = "STOP_OBSERVED_FIRST"
                        decision_ns = trade.ts_event_ns
                        break
                cutoff_ns = end_ns if decision_ns is None else decision_ns
                if _gap_precedes(source_gaps, anchor_ns=anchor_ns, cutoff_ns=cutoff_ns):
                    label = "AMBIGUOUS"
                    reason = "SOURCE_GAP_BEFORE_DECISION"
            cells.append(
                OutcomeCell.model_validate(
                    {
                        "combination_id": combination_id,
                        "label": cast(HistoricalLabel, label),
                        "label_reason": reason,
                        "strict_target_first": int(label == "TARGET_FIRST"),
                    }
                )
            )
    if tuple(cell.combination_id for cell in cells) != COMBINATION_ORDER:
        raise ValueError("internal 30-cell combination-order drift")
    return tuple(cells)


def classify_h2_cells_fast(
    trades: Sequence[H2Trade],
    *,
    anchor_ns: int,
    reference_price: Decimal,
    time_combination_id: str,
    source_partition_bound: bool,
    source_gaps: Sequence[PathGap] = (),
) -> tuple[OutcomeCell, ...]:
    """Equivalent 30-cell classifier with one shared pass over the Trade window."""

    if not source_partition_bound:
        raise ValueError("UPSTREAM_SOURCE_PARTITION_UNBOUND")
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    try:
        horizon_seconds = HORIZONS_SECONDS[time_combination_id]
    except KeyError as exc:
        raise ValueError("unregistered time combination") from exc
    end_ns = anchor_ns + horizon_seconds * NS
    ordered = tuple(trades)
    previous_identity: tuple[int, int, str] | None = None
    for row in ordered:
        identity = (row.ts_event_ns, row.venue_trade_id, row.canonical_trade_id)
        if identity == previous_identity:
            raise ValueError("duplicate H2 stable-order identity")
        if previous_identity is not None and identity < previous_identity:
            raise ValueError("H2 input must already use the frozen stable order")
        if row.price <= 0:
            raise ValueError("invalid H2 Trade price")
        previous_identity = identity
    window = tuple(row for row in ordered if anchor_ns <= row.ts_event_ns < end_ns)
    if not window:
        cells = tuple(
            OutcomeCell.model_validate(
                {
                    "combination_id": combination_id,
                    "label": "AMBIGUOUS",
                    "label_reason": "NO_OBSERVATIONS",
                    "strict_target_first": 0,
                }
            )
            for combination_id in COMBINATION_ORDER
        )
        return cells

    target_prices = tuple(
        reference_price * (Decimal(1) + target / BPS) for target in REGISTERED_TARGET_BPS
    )
    stop_prices = tuple(
        reference_price * (Decimal(1) - stop / BPS) for stop in REGISTERED_STOP_BPS
    )
    first_target: list[int | None] = [None] * len(target_prices)
    first_stop: list[int | None] = [None] * len(stop_prices)
    unresolved_targets = len(target_prices)
    unresolved_stops = len(stop_prices)
    for index, trade in enumerate(window):
        if unresolved_targets:
            for threshold_index, threshold in enumerate(target_prices):
                if first_target[threshold_index] is None and trade.price >= threshold:
                    first_target[threshold_index] = index
                    unresolved_targets -= 1
        if unresolved_stops:
            for threshold_index, threshold in enumerate(stop_prices):
                if first_stop[threshold_index] is None and trade.price <= threshold:
                    first_stop[threshold_index] = index
                    unresolved_stops -= 1
        if not unresolved_targets and not unresolved_stops:
            break

    cells_list: list[OutcomeCell] = []
    for target_index, target in enumerate(REGISTERED_TARGET_BPS):
        for stop_index, stop in enumerate(REGISTERED_STOP_BPS):
            combination_id = f"target={target:f}|stop={stop:f}"
            target_hit = first_target[target_index]
            stop_hit = first_stop[stop_index]
            if target_hit is None and stop_hit is None:
                label = "EXPIRED"
                reason = "HORIZON_EXPIRED_WITHOUT_TOUCH"
                cutoff_ns = end_ns
            elif stop_hit is None or (
                target_hit is not None and target_hit < stop_hit
            ):
                label = "TARGET_FIRST"
                reason = "TARGET_OBSERVED_FIRST"
                cutoff_ns = window[cast(int, target_hit)].ts_event_ns
            else:
                label = "STOP_FIRST"
                reason = "STOP_OBSERVED_FIRST"
                cutoff_ns = window[stop_hit].ts_event_ns
            if _gap_precedes(source_gaps, anchor_ns=anchor_ns, cutoff_ns=cutoff_ns):
                label = "AMBIGUOUS"
                reason = "SOURCE_GAP_BEFORE_DECISION"
            cells_list.append(
                OutcomeCell.model_validate(
                    {
                        "combination_id": combination_id,
                        "label": cast(HistoricalLabel, label),
                        "label_reason": reason,
                        "strict_target_first": int(label == "TARGET_FIRST"),
                    }
                )
            )
    cells = tuple(cells_list)
    if tuple(cell.combination_id for cell in cells) != COMBINATION_ORDER:
        raise ValueError("internal 30-cell combination-order drift")
    return cells


def build_control_outcome_matrix(
    *,
    control_candidate_id: str,
    time_combination_id: str,
    reference_price: Decimal,
    trades: Sequence[H2Trade],
    anchor_ns: int,
    source_path_hash: str,
    source_partition_bound: bool,
    source_gaps: Sequence[PathGap] = (),
) -> ControlOutcomeMatrix:
    outcomes = classify_h2_cells(
        trades,
        anchor_ns=anchor_ns,
        reference_price=reference_price,
        time_combination_id=time_combination_id,
        source_partition_bound=source_partition_bound,
        source_gaps=source_gaps,
    )
    return ControlOutcomeMatrix.seal(
        {
            "control_candidate_id": control_candidate_id,
            "time_combination_id": time_combination_id,
            "reference_price": reference_price,
            "outcomes": outcomes,
            "source_path_hash": source_path_hash,
        }
    )
