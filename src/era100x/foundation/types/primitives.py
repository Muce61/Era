"""Value objects that prevent precision, time-source, and identifier ambiguity."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Self


@dataclass(frozen=True, slots=True)
class PositiveDecimal:
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise TypeError("binary float and non-Decimal values are forbidden")
        if not self.value.is_finite() or self.value < 0:
            raise ValueError("value must be finite and non-negative")

    @classmethod
    def parse(cls, raw: str) -> Self:
        try:
            return cls(Decimal(raw))
        except InvalidOperation as exc:
            raise ValueError("invalid decimal string") from exc

    def serialize(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class _Nanoseconds:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError("nanoseconds must be an integer")
        if self.value < 0:
            raise ValueError("nanoseconds cannot be negative")


@dataclass(frozen=True, slots=True)
class UtcWallClockNs(_Nanoseconds):
    """Local UTC wall-clock timestamp."""


@dataclass(frozen=True, slots=True)
class ExchangeEventNs(_Nanoseconds):
    """Exchange event timestamp."""


@dataclass(frozen=True, slots=True)
class ExchangeTransactionNs(_Nanoseconds):
    """Exchange transaction timestamp."""


@dataclass(frozen=True, slots=True)
class MonotonicReceiveNs(_Nanoseconds):
    """Local monotonic receive timestamp for durations/freshness only."""


@dataclass(frozen=True, slots=True)
class StableId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("identifier must be a string")
        if not self.value or not self.value.strip() or self.value == "0":
            raise ValueError("identifier cannot be empty or a zero sentinel")
        if self.value != self.value.strip():
            raise ValueError("identifier cannot contain surrounding whitespace")

