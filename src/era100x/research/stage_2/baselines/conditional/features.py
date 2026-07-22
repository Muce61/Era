"""Causal, deterministic S2-T15 v1.4 feature and split primitives."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from collections.abc import Iterable, Sequence
from typing import cast

from era100x.data.schema.models import ContractBar
from era100x.research.stage_2.gates.price.gate import _context

from .v14_contracts import (
    ACTIVITY_FORMULA_ID,
    BACKWARD_PURGE_SECONDS,
    CONTROL_GRID_VERSION,
    DISTANCE_FORMULA_ID,
    FORWARD_EMBARGO_SECONDS,
    MATCHING_SEED,
    QUINTILE_ALGORITHM_ID,
    VOLATILITY_FORMULA_ID,
    FoldId,
    FrozenQuintileBoundaries,
    PeriodId,
    RollingFoldContract,
)

NS = 1_000_000_000
MINUTE_NS = 60 * NS
VOLATILITY_QUANTUM = Decimal("0.000000000000000001")


def _ns(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * NS)


PERIOD_BLOCK_BOUNDARIES: dict[PeriodId, tuple[int, int, int, int, int, int]] = {
    "P1": cast(
        tuple[int, int, int, int, int, int],
        tuple(
            _ns(value)
            for value in (
                "2020-01-01T00:00:00Z",
                "2020-05-26T00:00:00Z",
                "2020-10-19T00:00:00Z",
                "2021-03-14T00:00:00Z",
                "2021-08-07T00:00:00Z",
                "2022-01-01T00:00:00Z",
            )
        ),
    ),
    "P2": cast(
        tuple[int, int, int, int, int, int],
        tuple(
            _ns(value)
            for value in (
                "2022-01-01T00:00:00Z",
                "2022-05-27T00:00:00Z",
                "2022-10-20T00:00:00Z",
                "2023-03-15T00:00:00Z",
                "2023-08-08T00:00:00Z",
                "2024-01-01T00:00:00Z",
            )
        ),
    ),
    "P3": cast(
        tuple[int, int, int, int, int, int],
        tuple(
            _ns(value)
            for value in (
                "2024-01-01T00:00:00Z",
                "2024-07-02T00:00:00Z",
                "2025-01-01T00:00:00Z",
                "2025-07-03T00:00:00Z",
                "2026-01-02T00:00:00Z",
                "2026-07-04T00:00:00Z",
            )
        ),
    ),
}


def rolling_fold_contracts() -> tuple[RollingFoldContract, ...]:
    contracts: list[RollingFoldContract] = []
    for period, boundaries in PERIOD_BLOCK_BOUNDARIES.items():
        folds: tuple[FoldId, FoldId, FoldId, FoldId] = ("F0", "F1", "F2", "F3")
        for index, fold in enumerate(folds):
            contracts.append(
                RollingFoldContract(
                    period=period,
                    fold=fold,
                    train_start_ns=boundaries[0],
                    train_end_ns=boundaries[index + 1],
                    evaluation_start_ns=boundaries[index + 1],
                    evaluation_end_ns=boundaries[index + 2],
                    evaluation_role="HOLDOUT" if fold == "F3" else "VALIDATION",
                )
            )
    return tuple(contracts)


ROLLING_FOLDS = rolling_fold_contracts()


def evaluation_membership(anchor_ns: int) -> tuple[PeriodId, FoldId] | None:
    """Return the unique evaluation fold; B0 intentionally has no event delta."""

    matches = tuple(
        (contract.period, contract.fold)
        for contract in ROLLING_FOLDS
        if contract.evaluation_start_ns <= anchor_ns < contract.evaluation_end_ns
    )
    if len(matches) > 1:
        raise ValueError("evaluation folds overlap")
    return matches[0] if matches else None


def train_only_membership(anchor_ns: int) -> PeriodId | None:
    for period, boundaries in PERIOD_BLOCK_BOUNDARIES.items():
        if boundaries[0] <= anchor_ns < boundaries[1]:
            return period
    return None


def information_span_is_eligible(anchor_ns: int, contract: RollingFoldContract) -> bool:
    start = anchor_ns - BACKWARD_PURGE_SECONDS * NS
    end = anchor_ns + FORWARD_EMBARGO_SECONDS * NS
    return contract.evaluation_start_ns <= start and end <= contract.evaluation_end_ns


@dataclass(frozen=True, slots=True)
class PriceBar1m:
    instrument: str
    event_ts_ns: int
    available_at_ns: int
    close: Decimal
    interval_seconds: int = 60
    source_file_sha256: str = ""


@dataclass(frozen=True, slots=True)
class ActivitySecond:
    instrument: str
    second_end_ns: int
    available_at_ns: int
    trade_count: int
    source_logical_hash: str = ""


@dataclass(frozen=True, slots=True)
class ActiveCanonicalLevel:
    instrument: str
    parameter_set_id: str
    key_level_id: str
    level_price: Decimal
    priority: int
    available_at_ns: int
    expires_at_ns: int
    status: str = "ACTIVE"


def volatility_1m_60bar_rms_bps(
    bars: Sequence[PriceBar1m], *, instrument: str, anchor_ns: int
) -> Decimal:
    """Compute the frozen 61-bar/60-return causal RMS volatility."""

    eligible = sorted(
        (
            bar
            for bar in bars
            if bar.instrument == instrument
            and bar.interval_seconds == 60
            and bar.available_at_ns <= anchor_ns
        ),
        key=lambda bar: (bar.event_ts_ns, bar.available_at_ns, bar.source_file_sha256),
    )
    if len(eligible) < 61:
        raise ValueError("VOLATILITY_UNAVAILABLE_INSUFFICIENT_61_BARS")
    window = eligible[-61:]
    identities = [(bar.instrument, bar.event_ts_ns) for bar in window]
    if len(identities) != len(set(identities)):
        raise ValueError("VOLATILITY_UNAVAILABLE_DUPLICATE_BAR")
    if any(
        right.event_ts_ns - left.event_ts_ns != MINUTE_NS
        for left, right in zip(window, window[1:], strict=False)
    ):
        raise ValueError("VOLATILITY_UNAVAILABLE_BAR_GAP")
    if any(bar.close <= 0 for bar in window):
        raise ValueError("VOLATILITY_UNAVAILABLE_NONPOSITIVE_CLOSE")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        squared = sum(
            (
                (Decimal(10_000) * (right.close / left.close - Decimal(1))) ** 2
                for left, right in zip(window, window[1:], strict=False)
            ),
            start=Decimal(0),
        )
        return (squared / Decimal(60)).sqrt().quantize(VOLATILITY_QUANTUM, rounding=ROUND_HALF_EVEN)


def trades_activity_count_60s(
    rows: Sequence[ActivitySecond],
    *,
    instrument: str,
    anchor_ns: int,
    source_coverage_complete: bool,
) -> int:
    """Sum causal Trade-second primitives; missing coverage is never zero."""

    if not source_coverage_complete:
        raise ValueError("ACTIVITY_UNAVAILABLE_SOURCE_COVERAGE")
    cutoff_ns = anchor_ns // NS * NS
    selected = tuple(
        row
        for row in rows
        if row.instrument == instrument
        and cutoff_ns - 60 * NS < row.second_end_ns <= cutoff_ns
        and row.available_at_ns <= anchor_ns
    )
    if any(row.trade_count < 0 for row in selected):
        raise ValueError("ACTIVITY_UNAVAILABLE_NEGATIVE_TRADE_COUNT")
    identities = [(row.instrument, row.second_end_ns) for row in selected]
    if len(identities) != len(set(identities)):
        raise ValueError("ACTIVITY_UNAVAILABLE_DUPLICATE_SECOND")
    return sum(row.trade_count for row in selected)


def frozen_context_state(hourly_bars: list[ContractBar], anchor_ns: int) -> str:
    """Delegate to the already accepted S2-T07 causal EMA20 implementation."""

    state, _ = _context(hourly_bars, anchor_ns)
    return state


def nearest_active_key_level(
    levels: Iterable[ActiveCanonicalLevel],
    *,
    instrument: str,
    parameter_set_id: str,
    anchor_ns: int,
    reference_price: Decimal,
) -> tuple[ActiveCanonicalLevel, Decimal]:
    """Choose the registered nearest active level without future availability."""

    if reference_price <= 0:
        raise ValueError("reference price must be positive")
    eligible = tuple(
        level
        for level in levels
        if level.instrument == instrument
        and level.parameter_set_id == parameter_set_id
        and level.status == "ACTIVE"
        and level.available_at_ns <= anchor_ns < level.expires_at_ns
        and level.level_price > 0
    )
    if not eligible:
        raise ValueError("KEY_LEVEL_DISTANCE_UNAVAILABLE")
    ranked = sorted(
        (
            (
                (abs(reference_price / level.level_price - Decimal(1)) * Decimal(10_000)),
                level.priority,
                level.key_level_id,
                level,
            )
            for level in eligible
        ),
        key=lambda item: (item[0], item[1], item[2]),
    )
    distance, _, _, selected = ranked[0]
    return selected, distance


def daily_grid_offset_seconds(instrument: str, utc_date: date) -> int:
    payload = f"S2T15|{CONTROL_GRID_VERSION}|{instrument}|{utc_date.isoformat()}|{MATCHING_SEED}"
    return int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big") % 60


def daily_control_anchors(instrument: str, utc_date: date) -> tuple[int, ...]:
    day_start = int(datetime.combine(utc_date, datetime.min.time(), tzinfo=UTC).timestamp() * NS)
    offset = daily_grid_offset_seconds(instrument, utc_date) * NS
    return tuple(day_start + offset + index * MINUTE_NS for index in range(24 * 60))


def freeze_tie_preserving_quintiles(
    values: Sequence[Decimal],
    *,
    instrument: str,
    period: PeriodId,
    fold: FoldId,
    feature_kind: str,
    feature_source_hash: str,
    split_contract_hash: str,
    source_anchor_count: int | None = None,
    parameter_set_id: str | None = None,
) -> FrozenQuintileBoundaries:
    """Freeze the preregistered linear-scan tie-preserving quintile cuts."""

    if len(set(values)) < 5:
        raise ValueError("QUINTILE_BLOCKED_FEWER_THAN_FIVE_DISTINCT_VALUES")
    counts = Counter(values)
    distinct = sorted(counts)
    total = len(values)
    cumulative: list[int] = []
    running = 0
    for value in distinct:
        running += counts[value]
        cumulative.append(running)
    cut_indices: list[int] = []
    previous = 0
    for cut_number in range(1, 5):
        minimum = max(1, previous + 1)
        maximum = len(distinct) + cut_number - 5
        feasible = range(minimum, maximum + 1)
        target = Decimal(cut_number * total) / Decimal(5)
        chosen = min(
            feasible,
            key=lambda index: (abs(Decimal(cumulative[index - 1]) - target), index),
        )
        cut_indices.append(chosen)
        previous = chosen
    cut_points = tuple(distinct[index] for index in cut_indices)
    bin_counts = [0, 0, 0, 0, 0]
    for value in values:
        bin_counts[sum(value >= point for point in cut_points)] += 1
    formula = {
        "VOLATILITY": VOLATILITY_FORMULA_ID,
        "TRADES_ACTIVITY": ACTIVITY_FORMULA_ID,
        "KEY_LEVEL_DISTANCE": DISTANCE_FORMULA_ID,
    }.get(feature_kind)
    if formula is None:
        raise ValueError("unknown quintile feature kind")
    return FrozenQuintileBoundaries.seal(
        {
            "instrument": instrument,
            "pre_registered_period": period,
            "fold": fold,
            "parameter_set_id": parameter_set_id,
            "feature_kind": feature_kind,
            "feature_formula_id": formula,
            "algorithm_id": QUINTILE_ALGORITHM_ID,
            "source_train_split": f"{period}_{fold}_TRAIN",
            "source_anchor_count": source_anchor_count or total,
            "valid_feature_count": total,
            "distinct_value_count": len(distinct),
            "cut_points": cut_points,
            "bin_counts": tuple(bin_counts),
            "feature_source_hash": feature_source_hash,
            "split_contract_hash": split_contract_hash,
        }
    )


def utc_dates(start: date, end: date) -> tuple[date, ...]:
    """Small deterministic helper used by the streaming grid producer."""

    days = (end - start).days
    return tuple(start + timedelta(days=index) for index in range(days))
