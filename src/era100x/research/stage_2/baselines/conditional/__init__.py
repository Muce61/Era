"""S2-T15 preregistered conditional-random baseline fixture capability."""

from .matcher import match_conditional_controls, summarize_conditional_matches
from .models import (
    ConditionalBaselineManifest,
    ConditionalBaselineMatch,
    ConditionalBaselineSummary,
    ControlCandidate,
    FrozenQuintileBoundaries,
    PrimaryEpisode,
)

__all__ = [
    "ConditionalBaselineManifest",
    "ConditionalBaselineMatch",
    "ConditionalBaselineSummary",
    "ControlCandidate",
    "FrozenQuintileBoundaries",
    "PrimaryEpisode",
    "match_conditional_controls",
    "summarize_conditional_matches",
]
