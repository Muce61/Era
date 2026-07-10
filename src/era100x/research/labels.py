from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Sequence


class BarrierOutcome(StrEnum):
    TARGET_FIRST = "target_first"
    STOP_FIRST = "stop_first"
    AMBIGUOUS = "ambiguous"
    CENSORED = "censored"


@dataclass(frozen=True, slots=True)
class BarrierLabel:
    outcome: BarrierOutcome
    touched_at_index: int | None


def label_competing_barriers(*, high_net_roe_pct: Sequence[Decimal], low_net_roe_pct: Sequence[Decimal], target_net_roe_pct: Decimal, stop_net_roe_pct: Decimal) -> BarrierLabel:
    if len(high_net_roe_pct) != len(low_net_roe_pct):
        raise ValueError("high and low paths must have equal length")
    if stop_net_roe_pct >= target_net_roe_pct:
        raise ValueError("stop barrier must be below target barrier")
    for index, (high_value, low_value) in enumerate(zip(high_net_roe_pct, low_net_roe_pct, strict=True)):
        target_hit = high_value >= target_net_roe_pct
        stop_hit = low_value <= stop_net_roe_pct
        if target_hit and stop_hit:
            return BarrierLabel(BarrierOutcome.AMBIGUOUS, index)
        if target_hit:
            return BarrierLabel(BarrierOutcome.TARGET_FIRST, index)
        if stop_hit:
            return BarrierLabel(BarrierOutcome.STOP_FIRST, index)
    return BarrierLabel(BarrierOutcome.CENSORED, None)
