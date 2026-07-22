"""S2-T15 preregistered historical conditional-random baseline capability."""

from .matcher import match_conditional_controls, summarize_conditional_matches
from .models import (
    ConditionalBaselineManifest,
    ConditionalBaselineMatch,
    ConditionalBaselineSummary,
    ControlCandidate,
    FrozenQuintileBoundaries,
    PrimaryEpisode,
)
from .v14_contracts import (
    ConditionalBaselineMatchMatrix,
    ControlAnchor,
    ControlOutcomeMatrix,
    S2T15ContractAuthority,
    V14ControlCandidate,
    V14PrimaryEpisode,
)

__all__ = [
    "ConditionalBaselineManifest",
    "ConditionalBaselineMatch",
    "ConditionalBaselineSummary",
    "ControlCandidate",
    "FrozenQuintileBoundaries",
    "PrimaryEpisode",
    "ConditionalBaselineMatchMatrix",
    "ControlAnchor",
    "ControlOutcomeMatrix",
    "S2T15ContractAuthority",
    "V14ControlCandidate",
    "V14PrimaryEpisode",
    "match_conditional_controls",
    "summarize_conditional_matches",
]
