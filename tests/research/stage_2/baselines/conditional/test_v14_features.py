from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from era100x.data.schema.models import ContractBar
from era100x.research.stage_2.baselines.conditional.features import (
    MINUTE_NS,
    NS,
    ActiveCanonicalLevel,
    ActivitySecond,
    PriceBar1m,
    daily_control_anchors,
    daily_grid_offset_seconds,
    evaluation_membership,
    freeze_tie_preserving_quintiles,
    frozen_context_state,
    information_span_is_eligible,
    nearest_active_key_level,
    rolling_fold_contracts,
    trades_activity_count_60s,
    volatility_1m_60bar_rms_bps,
)

HASH = "a" * 64


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * NS)


def _bars(count: int = 61) -> list[PriceBar1m]:
    return [
        PriceBar1m(
            instrument="BTCUSDT",
            event_ts_ns=index * MINUTE_NS,
            available_at_ns=(index + 1) * MINUTE_NS,
            close=Decimal(100 + index),
            source_file_sha256=f"{index:064x}",
        )
        for index in range(count)
    ]


def test_volatility_is_causal_decimal_deterministic_and_shuffle_safe() -> None:
    bars = _bars()
    expected = volatility_1m_60bar_rms_bps(bars, instrument="BTCUSDT", anchor_ns=61 * MINUTE_NS)
    random.Random(20260716).shuffle(bars)
    actual = volatility_1m_60bar_rms_bps(bars, instrument="BTCUSDT", anchor_ns=61 * MINUTE_NS)
    assert actual == expected
    assert actual.as_tuple().exponent == -18


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda rows: rows[:-1], "61_BARS"),
        (
            lambda rows: [
                *rows[:30],
                replace(rows[30], event_ts_ns=rows[30].event_ts_ns + MINUTE_NS),
                *rows[31:],
            ],
            "DUPLICATE_BAR",
        ),
        (
            lambda rows: [replace(rows[0], close=Decimal(0)), *rows[1:]],
            "NONPOSITIVE_CLOSE",
        ),
    ],
)
def test_volatility_fails_closed(
    mutator: Callable[[list[PriceBar1m]], list[PriceBar1m]], reason: str
) -> None:
    changed = mutator(_bars())
    with pytest.raises(ValueError, match=reason):
        volatility_1m_60bar_rms_bps(changed, instrument="BTCUSDT", anchor_ns=61 * MINUTE_NS)


def test_activity_zero_requires_complete_coverage_and_uses_left_closed_window() -> None:
    anchor = 100 * NS
    assert (
        trades_activity_count_60s(
            [], instrument="BTCUSDT", anchor_ns=anchor, source_coverage_complete=True
        )
        == 0
    )
    rows = [
        ActivitySecond("BTCUSDT", 40 * NS, 40 * NS, 99),
        ActivitySecond("BTCUSDT", 41 * NS, 41 * NS, 2),
        ActivitySecond("BTCUSDT", 100 * NS, 100 * NS, 3),
    ]
    assert (
        trades_activity_count_60s(
            rows, instrument="BTCUSDT", anchor_ns=anchor, source_coverage_complete=True
        )
        == 5
    )
    with pytest.raises(ValueError, match="SOURCE_COVERAGE"):
        trades_activity_count_60s(
            [], instrument="BTCUSDT", anchor_ns=anchor, source_coverage_complete=False
        )


def test_rolling_folds_are_unique_and_apply_full_purge_embargo() -> None:
    assert len(rolling_fold_contracts()) == 12
    assert evaluation_membership(_timestamp("2020-01-10T00:00:00Z")) is None
    assert evaluation_membership(_timestamp("2020-05-26T00:00:00Z")) == ("P1", "F0")
    assert evaluation_membership(_timestamp("2026-01-02T00:00:00Z")) == ("P3", "F3")
    contract = next(
        item for item in rolling_fold_contracts() if item.period == "P1" and item.fold == "F0"
    )
    assert not information_span_is_eligible(contract.evaluation_start_ns, contract)
    assert information_span_is_eligible(contract.evaluation_start_ns + 3600 * NS, contract)
    assert not information_span_is_eligible(contract.evaluation_end_ns - 600 * NS + 1, contract)


def test_daily_grid_is_deterministic_one_anchor_per_minute_and_namespaced() -> None:
    day = date(2024, 1, 1)
    btc = daily_control_anchors("BTCUSDT", day)
    eth = daily_control_anchors("ETHUSDT", day)
    assert len(btc) == 1440
    assert all(right - left == MINUTE_NS for left, right in zip(btc, btc[1:], strict=False))
    assert btc == daily_control_anchors("BTCUSDT", day)
    assert daily_grid_offset_seconds("BTCUSDT", day) != daily_grid_offset_seconds("ETHUSDT", day)
    assert btc != eth


def test_context_delegates_to_accepted_causal_ema20_and_ignores_open_hour() -> None:
    hour_ns = 3600 * NS
    bars = [
        ContractBar(
            instrument="BTCUSDT",
            source_type="CONTRACT",
            interval_seconds=3600,
            bucket_start_ns=index * hour_ns,
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            volume=Decimal(1),
        )
        for index in range(20)
    ]
    future = bars[-1].model_copy(update={"bucket_start_ns": 20 * hour_ns, "close": Decimal(1)})
    assert frozen_context_state(bars, 20 * hour_ns) == "UP"
    assert frozen_context_state([*bars, future], 20 * hour_ns) == "UP"


def test_nearest_key_level_is_causal_parameter_isolated_and_tie_stable() -> None:
    levels = [
        ActiveCanonicalLevel("BTCUSDT", "PSET", "z", Decimal(99), 2, 0, 200 * NS),
        ActiveCanonicalLevel("BTCUSDT", "PSET", "a", Decimal(99), 1, 0, 200 * NS),
        ActiveCanonicalLevel("BTCUSDT", "OTHER", "closer", Decimal("99.9"), 0, 0, 200 * NS),
        ActiveCanonicalLevel("BTCUSDT", "PSET", "future", Decimal(100), 0, 101 * NS, 200 * NS),
    ]
    selected, distance = nearest_active_key_level(
        levels,
        instrument="BTCUSDT",
        parameter_set_id="PSET",
        anchor_ns=100 * NS,
        reference_price=Decimal(100),
    )
    assert selected.key_level_id == "a"
    assert distance == Decimal(100) / Decimal(99) * Decimal(10_000) - Decimal(10_000)


def test_tie_preserving_quintiles_are_train_only_hash_bound_and_nonempty() -> None:
    values = tuple(Decimal(value) for value in (1, 1, 2, 2, 3, 4, 5, 6, 7, 8))
    boundary = freeze_tie_preserving_quintiles(
        values,
        instrument="BTCUSDT",
        period="P1",
        fold="F0",
        feature_kind="VOLATILITY",
        feature_source_hash=HASH,
        split_contract_hash="b" * 64,
    )
    assert sum(boundary.bin_counts) == len(values)
    assert all(count > 0 for count in boundary.bin_counts)
    assert tuple(sorted(boundary.cut_points)) == boundary.cut_points
    shuffled = list(values)
    random.Random(7).shuffle(shuffled)
    assert (
        freeze_tie_preserving_quintiles(
            shuffled,
            instrument="BTCUSDT",
            period="P1",
            fold="F0",
            feature_kind="VOLATILITY",
            feature_source_hash=HASH,
            split_contract_hash="b" * 64,
        ).boundary_hash
        == boundary.boundary_hash
    )
    with pytest.raises(ValueError, match="FEWER_THAN_FIVE"):
        freeze_tie_preserving_quintiles(
            tuple(Decimal(value) for value in (1, 1, 2, 2, 3, 4)),
            instrument="BTCUSDT",
            period="P1",
            fold="F0",
            feature_kind="VOLATILITY",
            feature_source_hash=HASH,
            split_contract_hash="b" * 64,
        )
