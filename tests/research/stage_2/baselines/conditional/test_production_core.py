from __future__ import annotations

from decimal import Decimal

import pytest

from era100x.research.stage_2.baselines.conditional.production_core import ActiveLevelIndex


def test_active_level_index_selects_nearest_then_priority_then_id() -> None:
    index = ActiveLevelIndex()
    index.add(
        parameter_set_id="P",
        level_price=Decimal(99),
        priority=2,
        key_level_id="z",
        available_at_ns=0,
        expires_at_ns=200,
    )
    index.add(
        parameter_set_id="P",
        level_price=Decimal(99),
        priority=1,
        key_level_id="a",
        available_at_ns=0,
        expires_at_ns=200,
    )
    index.add(
        parameter_set_id="P",
        level_price=Decimal(101),
        priority=0,
        key_level_id="above",
        available_at_ns=0,
        expires_at_ns=200,
    )
    key_level_id, distance = index.nearest(parameter_set_id="P", reference_price=Decimal(100))
    assert key_level_id == "above"
    assert distance == Decimal("99.009900990099009901")


def test_active_level_index_expires_at_left_closed_end() -> None:
    index = ActiveLevelIndex()
    index.add(
        parameter_set_id="P",
        level_price=Decimal(100),
        priority=0,
        key_level_id="level",
        available_at_ns=0,
        expires_at_ns=10,
    )
    index.expire(10)
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        index.nearest(parameter_set_id="P", reference_price=Decimal(100))
