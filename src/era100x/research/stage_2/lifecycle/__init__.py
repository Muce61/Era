"""Bounded Stage 2 conditional H3 lifecycle research."""

from .engine import evaluate_lifecycle_pair
from .models import (
    BoundaryClassification,
    CostScenario,
    FundingTrack,
    LifecycleObservation,
    LifecyclePairResult,
    LifecyclePolicyResult,
    LifecycleTrack,
    OptionalExitModelStatus,
    PriceObservationSource,
    SourceCoverage,
)
from .gap_recovery import (
    ContractPriceOhlcPoint,
    GapBoundaryDecision,
    classify_gap_bar,
    classify_gap_path,
    gap_identity,
    gap_second_bounds,
)
from .producer import (
    AdmissionDecision,
    CanonicalTradePoint,
    ContractPricePoint,
    FundingSettlement,
    assemble_lifecycle_observations,
    replay_single_position_admission,
)
from .dual_track import DualTrackLifecycleResult, evaluate_dual_track_lifecycle

__all__ = [
    "CostScenario",
    "BoundaryClassification",
    "FundingTrack",
    "LifecycleObservation",
    "LifecyclePairResult",
    "LifecyclePolicyResult",
    "LifecycleTrack",
    "OptionalExitModelStatus",
    "PriceObservationSource",
    "SourceCoverage",
    "ContractPriceOhlcPoint",
    "GapBoundaryDecision",
    "classify_gap_bar",
    "classify_gap_path",
    "gap_identity",
    "gap_second_bounds",
    "evaluate_lifecycle_pair",
    "AdmissionDecision",
    "CanonicalTradePoint",
    "ContractPricePoint",
    "FundingSettlement",
    "assemble_lifecycle_observations",
    "replay_single_position_admission",
    "DualTrackLifecycleResult",
    "evaluate_dual_track_lifecycle",
]
