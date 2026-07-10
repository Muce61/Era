from dataclasses import dataclass
from decimal import Decimal

from era100x.domain.models import ProtectionStep


@dataclass(frozen=True, slots=True)
class ProtectionDecision:
    previous_lock_net_roe_pct: Decimal | None
    new_lock_net_roe_pct: Decimal | None
    changed: bool


def next_protection_lock(*, mfe_net_roe_pct: Decimal, previous_lock_net_roe_pct: Decimal | None, ladder: tuple[ProtectionStep, ...]) -> ProtectionDecision:
    eligible = [step.lock_net_roe_pct for step in ladder if mfe_net_roe_pct >= step.mfe_net_roe_pct]
    proposed = max(eligible) if eligible else None
    if previous_lock_net_roe_pct is None:
        new_lock = proposed
    elif proposed is None:
        new_lock = previous_lock_net_roe_pct
    else:
        new_lock = max(previous_lock_net_roe_pct, proposed)
    return ProtectionDecision(previous_lock_net_roe_pct, new_lock, new_lock != previous_lock_net_roe_pct)
