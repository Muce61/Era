"""Bounded Stage 2 conditional H3 lifecycle research."""

from .engine import evaluate_lifecycle_pair
from .models import (
    CostScenario,
    FundingTrack,
    LifecycleObservation,
    LifecyclePairResult,
    LifecyclePolicyResult,
    OptionalExitModelStatus,
    PriceObservationSource,
    SourceCoverage,
)
from .producer import (
    AdmissionDecision,
    CanonicalTradePoint,
    ContractPricePoint,
    FundingSettlement,
    assemble_lifecycle_observations,
    replay_single_position_admission,
)

__all__ = [
    "CostScenario",
    "FundingTrack",
    "LifecycleObservation",
    "LifecyclePairResult",
    "LifecyclePolicyResult",
    "OptionalExitModelStatus",
    "PriceObservationSource",
    "SourceCoverage",
    "evaluate_lifecycle_pair",
    "AdmissionDecision",
    "CanonicalTradePoint",
    "ContractPricePoint",
    "FundingSettlement",
    "assemble_lifecycle_observations",
    "replay_single_position_admission",
]
