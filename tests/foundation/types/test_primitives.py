from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from era100x.foundation.types import (
    ExchangeEventNs,
    MonotonicReceiveNs,
    PositiveDecimal,
    StableId,
    UtcWallClockNs,
)


@given(st.decimals(allow_nan=False, allow_infinity=False, min_value=0))
def test_decimal_round_trip(value: Decimal) -> None:
    parsed = PositiveDecimal.parse(str(value))
    assert Decimal(parsed.serialize()) == value


@pytest.mark.parametrize("invalid", [0.1, 1, "1.0", None])
def test_non_decimal_constructor_rejected(invalid: object) -> None:
    with pytest.raises(TypeError):
        PositiveDecimal(invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", ["", " ", "0", " id "])
def test_invalid_identifiers_rejected(invalid: str) -> None:
    with pytest.raises(ValueError):
        StableId(invalid)


def test_timestamp_sources_are_distinct_types() -> None:
    wall = UtcWallClockNs(10)
    event = ExchangeEventNs(10)
    monotonic = MonotonicReceiveNs(10)
    assert type(wall) is not type(event)
    assert type(event) is not type(monotonic)


@pytest.mark.parametrize("invalid", [-1, 1.2, True])
def test_invalid_nanoseconds_rejected(invalid: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        UtcWallClockNs(invalid)  # type: ignore[arg-type]
