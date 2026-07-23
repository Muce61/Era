"""Streaming, outcome-blind feature preparation for S2-T15 v1.4.

This module intentionally has no H2 outcome reader.  It may construct market
state and key-level-distance features, but it cannot observe labels or control
outcomes.  The separation is enforced again by the full-run orchestration.
"""

from __future__ import annotations

import hashlib
import heapq
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]

from era100x.data.schema.models import ContractBar
from era100x.research.stage_2.contracts.models import Instrument

from .features import (
    MINUTE_NS,
    NS,
    VOLATILITY_QUANTUM,
    daily_control_anchors,
    frozen_context_state,
)
from .t10_access import FixedT10Reader

FOUNDATION_VERSION = "2.0"
FOUNDATION_VARIANT = "FOUNDATION"
KEY_LEVEL_VERSION = "group1-v1-price-v1"
KEY_LEVEL_VARIANT = "V1_PRICE"
DISTANCE_QUANTUM = Decimal("0.000000000000000001")
SOURCE_START_DATE = date(2020, 1, 1)


@dataclass(frozen=True, slots=True)
class PreparedMarketFeature:
    instrument: str
    anchor_ns: int
    reference_price: Decimal
    volatility_rms_bps: Decimal
    activity_count_60s: int
    high_timeframe_trend_state: str
    distance_bps_by_parameter: dict[str, Decimal]


@dataclass(frozen=True, slots=True)
class DailyPreparation:
    instrument: str
    owner_date: date
    grid_anchor_count: int
    valid_rows: tuple[PreparedMarketFeature, ...]
    exclusion_counts: dict[str, int]
    exclusion_by_anchor: dict[int, str]


@dataclass(frozen=True, slots=True)
class EpisodeFeatureRequest:
    episode_row_id: str
    anchor_ns: int
    parameter_set_id: str
    canonical_key_level_id: str
    reference_price: Decimal
    high_timeframe_trend_state: str


@dataclass(frozen=True, slots=True)
class PreparedEpisodeFeature:
    episode_row_id: str
    anchor_ns: int
    reference_price: Decimal
    volatility_rms_bps: Decimal
    activity_count_60s: int
    high_timeframe_trend_state: str
    key_level_distance_bps: Decimal


@dataclass(slots=True)
class _TreapNode:
    key: tuple[Decimal, int, str, int, int]
    priority: int
    expires_at_ns: int
    left: _TreapNode | None = None
    right: _TreapNode | None = None


def _priority(key: tuple[Decimal, int, str, int, int]) -> int:
    payload = f"{key[0]:f}|{key[1]}|{key[2]}|{key[3]}|{key[4]}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _rotate_left(root: _TreapNode) -> _TreapNode:
    child = root.right
    if child is None:
        raise AssertionError("left rotation requires a right child")
    root.right = child.left
    child.left = root
    return child


def _rotate_right(root: _TreapNode) -> _TreapNode:
    child = root.left
    if child is None:
        raise AssertionError("right rotation requires a left child")
    root.left = child.right
    child.right = root
    return child


def _insert(root: _TreapNode | None, node: _TreapNode) -> _TreapNode:
    if root is None:
        return node
    if node.key == root.key:
        if node.expires_at_ns != root.expires_at_ns:
            raise ValueError("canonical key-level identity has conflicting expiry")
        return root
    if node.key < root.key:
        root.left = _insert(root.left, node)
        if root.left.priority < root.priority:
            root = _rotate_right(root)
    else:
        root.right = _insert(root.right, node)
        if root.right.priority < root.priority:
            root = _rotate_left(root)
    return root


def _delete(root: _TreapNode | None, key: tuple[Decimal, int, str, int, int]) -> _TreapNode | None:
    if root is None:
        return None
    if key < root.key:
        root.left = _delete(root.left, key)
        return root
    if key > root.key:
        root.right = _delete(root.right, key)
        return root
    if root.left is None:
        return root.right
    if root.right is None:
        return root.left
    if root.left.priority < root.right.priority:
        root = _rotate_right(root)
        root.right = _delete(root.right, key)
    else:
        root = _rotate_left(root)
        root.left = _delete(root.left, key)
    return root


def _lower_bound(
    root: _TreapNode | None, key: tuple[Decimal, int, str, int, int]
) -> _TreapNode | None:
    result: _TreapNode | None = None
    while root is not None:
        if root.key >= key:
            result = root
            root = root.left
        else:
            root = root.right
    return result


def _predecessor(
    root: _TreapNode | None, key: tuple[Decimal, int, str, int, int]
) -> _TreapNode | None:
    result: _TreapNode | None = None
    while root is not None:
        if root.key < key:
            result = root
            root = root.right
        else:
            root = root.left
    return result


class ActiveLevelIndex:
    """Deterministic O(log n) active-level index isolated by parameter set."""

    def __init__(self) -> None:
        self._roots: dict[str, _TreapNode | None] = {}
        self._expiries: list[tuple[int, str, tuple[Decimal, int, str, int, int]]] = []

    def add(
        self,
        *,
        parameter_set_id: str,
        level_price: Decimal,
        priority: int,
        key_level_id: str,
        available_at_ns: int,
        expires_at_ns: int,
    ) -> None:
        key = (level_price, priority, key_level_id, available_at_ns, expires_at_ns)
        node = _TreapNode(key=key, priority=_priority(key), expires_at_ns=expires_at_ns)
        self._roots[parameter_set_id] = _insert(self._roots.get(parameter_set_id), node)
        heapq.heappush(self._expiries, (expires_at_ns, parameter_set_id, key))

    def expire(self, anchor_ns: int) -> None:
        while self._expiries and self._expiries[0][0] <= anchor_ns:
            _, parameter_set_id, key = heapq.heappop(self._expiries)
            self._roots[parameter_set_id] = _delete(self._roots.get(parameter_set_id), key)

    def nearest(self, *, parameter_set_id: str, reference_price: Decimal) -> tuple[str, Decimal]:
        root = self._roots.get(parameter_set_id)
        lower_key = (reference_price, -(2**63), "", -(2**63), -(2**63))
        upper = _lower_bound(root, lower_key)
        lower_any = _predecessor(root, lower_key)
        lower = (
            _lower_bound(
                root,
                (lower_any.key[0], -(2**63), "", -(2**63), -(2**63)),
            )
            if lower_any is not None
            else None
        )
        candidates = tuple(node for node in (lower, upper) if node is not None)
        if not candidates:
            raise ValueError("KEY_LEVEL_DISTANCE_UNAVAILABLE")
        ranked = sorted(
            (
                (
                    abs(reference_price / node.key[0] - Decimal(1)) * Decimal(10_000),
                    node.key[1],
                    node.key[2],
                )
                for node in candidates
            ),
            key=lambda item: (item[0], item[1], item[2]),
        )
        distance, _, key_level_id = ranked[0]
        return key_level_id, distance.quantize(DISTANCE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _rows(table: pa.Table) -> list[dict[str, Any]]:
    return table.to_pylist() if table.num_columns else []


def _read_days(
    reader: FixedT10Reader,
    *,
    dataset_name: str,
    dataset_version: str,
    instrument: str,
    variant: str,
    days: tuple[date, ...],
    columns: list[str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for owner_date in days:
        if owner_date < SOURCE_START_DATE:
            continue
        result.extend(
            _rows(
                reader.read(
                    dataset_name=dataset_name,
                    dataset_version=dataset_version,
                    instrument=instrument,
                    variant=variant,
                    owner_date=owner_date,
                    columns=columns,
                )
            )
        )
    return result


def _volatility_values(
    rows: list[dict[str, Any]], *, instrument: str, anchors: tuple[int, ...]
) -> dict[int, Decimal]:
    bars = sorted(
        (
            row
            for row in rows
            if row["instrument"] == instrument and int(row["interval_seconds"]) == 60
        ),
        key=lambda row: (int(row["event_ts_ns"]), int(row["available_at_ns"])),
    )
    available = [int(row["available_at_ns"]) for row in bars]
    event = [int(row["event_ts_ns"]) for row in bars]
    closes = [Decimal(row["close"]) for row in bars]
    if len(event) != len(set(event)):
        raise ValueError("VOLATILITY_UNAVAILABLE_DUPLICATE_BAR")
    squared: list[Decimal] = [Decimal(0)]
    gap_prefix: list[int] = [0]
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        for index in range(1, len(bars)):
            valid = event[index] - event[index - 1] == MINUTE_NS
            gap_prefix.append(gap_prefix[-1] + int(not valid))
            if closes[index - 1] <= 0 or closes[index] <= 0:
                squared.append(Decimal(0))
            else:
                change = Decimal(10_000) * (closes[index] / closes[index - 1] - Decimal(1))
                squared.append(change * change)
        cumulative: list[Decimal] = [Decimal(0)]
        for value in squared:
            cumulative.append(cumulative[-1] + value)
        result: dict[int, Decimal] = {}
        for anchor in anchors:
            last = bisect_right(available, anchor) - 1
            first = last - 60
            if first < 0:
                continue
            if any(value <= 0 for value in closes[first : last + 1]):
                continue
            if gap_prefix[last] - gap_prefix[first]:
                continue
            total = cumulative[last + 1] - cumulative[first + 1]
            result[anchor] = (
                (total / Decimal(60)).sqrt().quantize(VOLATILITY_QUANTUM, rounding=ROUND_HALF_EVEN)
            )
        return result


def _activity_values(rows: list[dict[str, Any]], anchors: tuple[int, ...]) -> dict[int, int]:
    ordered = sorted(rows, key=lambda row: int(row["second_end_ns"]))
    seconds = [int(row["second_end_ns"]) for row in ordered]
    if len(seconds) != len(set(seconds)):
        raise ValueError("ACTIVITY_UNAVAILABLE_DUPLICATE_SECOND")
    prefix = [0]
    for row in ordered:
        count = int(row["trade_count"])
        if count < 0:
            raise ValueError("ACTIVITY_UNAVAILABLE_NEGATIVE_TRADE_COUNT")
        prefix.append(prefix[-1] + count)
    result: dict[int, int] = {}
    for anchor in anchors:
        cutoff = anchor // NS * NS
        start = bisect_right(seconds, cutoff - 60 * NS)
        end = bisect_right(seconds, cutoff)
        result[anchor] = prefix[end] - prefix[start]
    return result


def _reference_prices(rows: list[dict[str, Any]], anchors: tuple[int, ...]) -> dict[int, Decimal]:
    values = {
        int(row["event_ts_ns"]): Decimal(row["close"])
        for row in rows
        if int(row["available_at_ns"]) <= int(row["event_ts_ns"]) + NS
    }
    return {
        anchor: values[anchor - NS]
        for anchor in anchors
        if anchor - NS in values and values[anchor - NS] > 0
    }


def _context_values(
    rows: list[dict[str, Any]], *, instrument: str, anchors: tuple[int, ...]
) -> dict[int, str]:
    hourly = [
        ContractBar(
            instrument=cast(Instrument, instrument),
            source_type="CONTRACT",
            interval_seconds=3600,
            bucket_start_ns=int(row["event_ts_ns"]),
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=Decimal(row["volume"]),
        )
        for row in rows
        if row["instrument"] == instrument and int(row["interval_seconds"]) == 3600
    ]
    result: dict[int, str] = {}
    cache: dict[int, str] = {}
    for anchor in anchors:
        hour = anchor // (3600 * NS)
        try:
            result[anchor] = cache.setdefault(hour, frozen_context_state(hourly, anchor))
        except ValueError:
            continue
    return result


def _distance_values(
    rows: list[dict[str, Any]],
    *,
    anchors: tuple[int, ...],
    references: dict[int, Decimal],
    parameter_set_ids: tuple[str, ...],
) -> dict[int, dict[str, Decimal]]:
    levels = sorted(
        (
            row
            for row in rows
            if row["status"] == "ACTIVE"
            and str(row["event_parameter_set_id"]) in parameter_set_ids
            and Decimal(row["level_price"]) > 0
        ),
        key=lambda row: (
            int(row["available_at_ts"]),
            str(row["event_parameter_set_id"]),
            str(row["key_level_id"]),
        ),
    )
    index = ActiveLevelIndex()
    cursor = 0
    result: dict[int, dict[str, Decimal]] = {}
    for anchor in anchors:
        while cursor < len(levels) and int(levels[cursor]["available_at_ts"]) <= anchor:
            row = levels[cursor]
            if anchor < int(row["expires_at_ns"]):
                index.add(
                    parameter_set_id=str(row["event_parameter_set_id"]),
                    level_price=Decimal(row["level_price"]),
                    priority=int(row["priority"]),
                    key_level_id=str(row["key_level_id"]),
                    available_at_ns=int(row["available_at_ts"]),
                    expires_at_ns=int(row["expires_at_ns"]),
                )
            cursor += 1
        index.expire(anchor)
        reference = references.get(anchor)
        if reference is None:
            continue
        distances: dict[str, Decimal] = {}
        for parameter_set_id in parameter_set_ids:
            try:
                _, distance = index.nearest(
                    parameter_set_id=parameter_set_id, reference_price=reference
                )
            except ValueError:
                continue
            distances[parameter_set_id] = distance
        result[anchor] = distances
    return result


def prepare_daily_features(
    reader: FixedT10Reader,
    *,
    instrument: str,
    owner_date: date,
    parameter_set_ids: tuple[str, ...],
) -> DailyPreparation:
    """Prepare one UTC day without observing an event or control outcome."""

    anchors = daily_control_anchors(instrument, owner_date)
    previous = owner_date - timedelta(days=1)
    days = (previous, owner_date)
    bar_rows = _read_days(
        reader,
        dataset_name="causal_price_bars",
        dataset_version=FOUNDATION_VERSION,
        instrument=instrument,
        variant=FOUNDATION_VARIANT,
        days=days,
        columns=[
            "instrument",
            "interval_seconds",
            "event_ts_ns",
            "available_at_ns",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
    )
    activity_rows = _read_days(
        reader,
        dataset_name="trade_second_primitives",
        dataset_version=FOUNDATION_VERSION,
        instrument=instrument,
        variant=FOUNDATION_VARIANT,
        days=days,
        columns=["instrument", "second_end_ns", "available_at_ns", "trade_count"],
    )
    price_rows = _read_days(
        reader,
        dataset_name="contract_price_1s",
        dataset_version=FOUNDATION_VERSION,
        instrument=instrument,
        variant=FOUNDATION_VARIANT,
        days=days,
        columns=["instrument", "event_ts_ns", "available_at_ns", "close"],
    )
    level_rows = _read_days(
        reader,
        dataset_name="canonical_key_levels",
        dataset_version=KEY_LEVEL_VERSION,
        instrument=instrument,
        variant=KEY_LEVEL_VARIANT,
        days=days,
        columns=[
            "instrument",
            "available_at_ts",
            "key_level_id",
            "level_price",
            "priority",
            "expires_at_ns",
            "status",
            "event_parameter_set_id",
        ],
    )
    volatility = _volatility_values(bar_rows, instrument=instrument, anchors=anchors)
    activity = _activity_values(activity_rows, anchors)
    references = _reference_prices(price_rows, anchors)
    contexts = _context_values(bar_rows, instrument=instrument, anchors=anchors)
    distances = _distance_values(
        level_rows,
        anchors=anchors,
        references=references,
        parameter_set_ids=parameter_set_ids,
    )
    exclusions = {
        "PRICE_FEATURE_UNAVAILABLE": 0,
        "ACTIVITY_FEATURE_UNAVAILABLE": 0,
        "CONTEXT_UNAVAILABLE": 0,
        "MARKET_STATE_ELIGIBLE": 0,
    }
    exclusion_by_anchor: dict[int, str] = {}
    prepared: list[PreparedMarketFeature] = []
    for anchor in anchors:
        if anchor not in references or anchor not in volatility:
            exclusions["PRICE_FEATURE_UNAVAILABLE"] += 1
            exclusion_by_anchor[anchor] = "PRICE_FEATURE_UNAVAILABLE"
        elif anchor not in activity:
            exclusions["ACTIVITY_FEATURE_UNAVAILABLE"] += 1
            exclusion_by_anchor[anchor] = "ACTIVITY_FEATURE_UNAVAILABLE"
        elif anchor not in contexts:
            exclusions["CONTEXT_UNAVAILABLE"] += 1
            exclusion_by_anchor[anchor] = "CONTEXT_UNAVAILABLE"
        else:
            exclusions["MARKET_STATE_ELIGIBLE"] += 1
            prepared.append(
                PreparedMarketFeature(
                    instrument=instrument,
                    anchor_ns=anchor,
                    reference_price=references[anchor],
                    volatility_rms_bps=volatility[anchor],
                    activity_count_60s=activity[anchor],
                    high_timeframe_trend_state=contexts[anchor],
                    distance_bps_by_parameter=distances[anchor],
                )
            )
    return DailyPreparation(
        instrument=instrument,
        owner_date=owner_date,
        grid_anchor_count=len(anchors),
        valid_rows=tuple(prepared),
        exclusion_counts=exclusions,
        exclusion_by_anchor=exclusion_by_anchor,
    )


def prepare_episode_features(
    reader: FixedT10Reader,
    *,
    instrument: str,
    owner_date: date,
    requests: tuple[EpisodeFeatureRequest, ...],
) -> tuple[dict[str, PreparedEpisodeFeature], dict[str, str]]:
    """Rebuild causal Episode features while preserving its bound key-level identity."""

    if len({request.episode_row_id for request in requests}) != len(requests):
        raise ValueError("duplicate episode feature request identity")
    previous = owner_date - timedelta(days=1)
    days = (previous, owner_date)
    anchors = tuple(sorted({request.anchor_ns for request in requests}))
    bar_rows = _read_days(
        reader,
        dataset_name="causal_price_bars",
        dataset_version=FOUNDATION_VERSION,
        instrument=instrument,
        variant=FOUNDATION_VARIANT,
        days=days,
        columns=[
            "instrument",
            "interval_seconds",
            "event_ts_ns",
            "available_at_ns",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
    )
    activity_rows = _read_days(
        reader,
        dataset_name="trade_second_primitives",
        dataset_version=FOUNDATION_VERSION,
        instrument=instrument,
        variant=FOUNDATION_VARIANT,
        days=days,
        columns=["instrument", "second_end_ns", "available_at_ns", "trade_count"],
    )
    level_rows = _read_days(
        reader,
        dataset_name="canonical_key_levels",
        dataset_version=KEY_LEVEL_VERSION,
        instrument=instrument,
        variant=KEY_LEVEL_VARIANT,
        days=days,
        columns=[
            "instrument",
            "available_at_ts",
            "key_level_id",
            "level_price",
            "priority",
            "expires_at_ns",
            "status",
            "event_parameter_set_id",
        ],
    )
    volatility = _volatility_values(bar_rows, instrument=instrument, anchors=anchors)
    activity = _activity_values(activity_rows, anchors)
    by_binding: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in level_rows:
        by_binding.setdefault(
            (str(row["event_parameter_set_id"]), str(row["key_level_id"])), []
        ).append(row)
    prepared: dict[str, PreparedEpisodeFeature] = {}
    excluded: dict[str, str] = {}
    for request in requests:
        if request.reference_price <= 0 or request.anchor_ns not in volatility:
            excluded[request.episode_row_id] = "FEATURE_UNAVAILABLE"
            continue
        if request.anchor_ns not in activity:
            excluded[request.episode_row_id] = "FEATURE_UNAVAILABLE"
            continue
        bound = tuple(
            row
            for row in by_binding.get(
                (request.parameter_set_id, request.canonical_key_level_id), []
            )
            if row["status"] == "ACTIVE"
            and int(row["available_at_ts"]) <= request.anchor_ns
            and request.anchor_ns < int(row["expires_at_ns"])
        )
        prices = {Decimal(row["level_price"]) for row in bound}
        if not prices:
            excluded[request.episode_row_id] = "FEATURE_UNAVAILABLE"
            continue
        if len(prices) != 1:
            excluded[request.episode_row_id] = "UPSTREAM_LABEL_BINDING_INVALID"
            continue
        level_price = next(iter(prices))
        distance = (
            abs(request.reference_price / level_price - Decimal(1)) * Decimal(10_000)
        ).quantize(DISTANCE_QUANTUM, rounding=ROUND_HALF_EVEN)
        prepared[request.episode_row_id] = PreparedEpisodeFeature(
            episode_row_id=request.episode_row_id,
            anchor_ns=request.anchor_ns,
            reference_price=request.reference_price,
            volatility_rms_bps=volatility[request.anchor_ns],
            activity_count_60s=activity[request.anchor_ns],
            high_timeframe_trend_state=request.high_timeframe_trend_state,
            key_level_distance_bps=distance,
        )
    return prepared, excluded
