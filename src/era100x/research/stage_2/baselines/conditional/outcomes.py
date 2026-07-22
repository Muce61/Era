"""T15-local H2 matrix outcomes using the accepted T13 crossing semantics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Sequence
from typing import cast

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


@dataclass(frozen=True, slots=True)
class H2Trade:
    ts_event_ns: int
    venue_trade_id: int
    canonical_trade_id: str
    price: Decimal


def classify_h2_cells(
    trades: Sequence[H2Trade],
    *,
    anchor_ns: int,
    reference_price: Decimal,
    time_combination_id: str,
    source_partition_bound: bool,
    declared_source_gap: bool = False,
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
    ordered = tuple(
        sorted(
            trades,
            key=lambda row: (row.ts_event_ns, row.venue_trade_id, row.canonical_trade_id),
        )
    )
    identities = tuple(
        (row.ts_event_ns, row.venue_trade_id, row.canonical_trade_id) for row in ordered
    )
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate H2 stable-order identity")
    if tuple(trades) != ordered:
        raise ValueError("H2 input must already use the frozen stable order")
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
            elif declared_source_gap:
                label = "AMBIGUOUS"
                reason = "SOURCE_GAP_BEFORE_DECISION"
            else:
                label = "EXPIRED"
                reason = "HORIZON_EXPIRED_WITHOUT_TOUCH"
                for trade in window:
                    if trade.price >= target_price:
                        label = "TARGET_FIRST"
                        reason = "TARGET_OBSERVED_FIRST"
                        break
                    if trade.price <= stop_price:
                        label = "STOP_FIRST"
                        reason = "STOP_OBSERVED_FIRST"
                        break
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


def build_control_outcome_matrix(
    *,
    control_candidate_id: str,
    time_combination_id: str,
    reference_price: Decimal,
    trades: Sequence[H2Trade],
    anchor_ns: int,
    source_path_hash: str,
    source_partition_bound: bool,
    declared_source_gap: bool = False,
) -> ControlOutcomeMatrix:
    outcomes = classify_h2_cells(
        trades,
        anchor_ns=anchor_ns,
        reference_price=reference_price,
        time_combination_id=time_combination_id,
        source_partition_bound=source_partition_bound,
        declared_source_gap=declared_source_gap,
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
