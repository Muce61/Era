"""Pure S2-T14 transformations over immutable S2-T13 labels."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from era100x.research.stage_2.labels.first_passage.models import HistoricalFirstPassageLabel

from .models import (
    PROHIBITED_INTERPRETATIONS,
    HistoricalAmbiguityBounds,
    HistoricalAmbiguityDistribution,
)


def derive_ambiguity_bounds(
    label: HistoricalFirstPassageLabel,
) -> HistoricalAmbiguityBounds:
    """Preserve a raw label while deriving the preregistered success bounds."""

    if label.output_hash != label.computed_hash():
        raise ValueError("source first-passage hash is not valid")
    if label.label == "AMBIGUOUS":
        pessimistic = (
            "STOP_FIRST" if label.label_reason == "H1_SAME_EVENT_TARGET_AND_STOP" else None
        )
        optimistic = (
            "TARGET_FIRST" if label.label_reason == "H1_SAME_EVENT_TARGET_AND_STOP" else None
        )
        primary = 0
        conditional = None
        lower = 0
        upper = 1
        preserved = True
        excluded = True
    else:
        pessimistic = label.label
        optimistic = label.label
        primary = 1 if label.label == "TARGET_FIRST" else 0
        conditional = primary
        lower = primary
        upper = primary
        preserved = False
        excluded = False
    return HistoricalAmbiguityBounds.seal(
        {
            "instrument": label.instrument,
            "market_episode_id": label.market_episode_id,
            "canonical_candidate_id": label.canonical_candidate_id,
            "candidate_version_id": label.candidate_version_id,
            "canonical_payload_hash": label.canonical_payload_hash,
            "parameter_set_id": label.parameter_set_id,
            "evidence_level": label.evidence_level,
            "target_bps": label.target_bps,
            "stop_bps": label.stop_bps,
            "timing_id": label.timing_id,
            "raw_label": label.label,
            "raw_label_reason": label.label_reason,
            "raw_ambiguous_preserved": preserved,
            "primary_ambiguous_policy": "FAILURE",
            "primary_target_first": primary,
            "conditional_target_first": conditional,
            "theoretical_lower_target_first": lower,
            "theoretical_upper_target_first": upper,
            "pessimistic_path_label": pessimistic,
            "optimistic_path_label": optimistic,
            "excluded_from_conditional": excluded,
            "historical_evidence_only": True,
            "prohibited_interpretations": PROHIBITED_INTERPRETATIONS,
            "source_first_passage_hash": label.output_hash,
        }
    )


def summarize_ambiguity_bounds(
    records: tuple[HistoricalAmbiguityBounds, ...],
) -> HistoricalAmbiguityDistribution:
    """Summarize one isolated instrument/evidence/parameter slice deterministically."""

    if not records:
        raise ValueError("at least one ambiguity-bound record is required")
    for record in records:
        if record.output_hash != record.computed_hash():
            raise ValueError("source ambiguity-bound hash is not valid")
    group_keys = {
        (
            record.instrument,
            record.evidence_level,
            record.parameter_set_id,
            record.target_bps,
            record.stop_bps,
            record.timing_id,
        )
        for record in records
    }
    if len(group_keys) != 1:
        raise ValueError("BTC/ETH, H1/H2 and parameter slices must remain separate")
    source_hashes = tuple(sorted(record.output_hash for record in records))
    if len(set(source_hashes)) != len(source_hashes):
        raise ValueError("duplicate ambiguity-bound evidence is not allowed")
    instrument, evidence_level, parameter_set_id, target_bps, stop_bps, timing_id = next(
        iter(group_keys)
    )
    counts = Counter(record.raw_label for record in records)
    total = len(records)
    ambiguous = counts["AMBIGUOUS"]
    target = counts["TARGET_FIRST"]
    conditional_denominator = total - ambiguous
    return HistoricalAmbiguityDistribution.seal(
        {
            "instrument": instrument,
            "evidence_level": evidence_level,
            "parameter_set_id": parameter_set_id,
            "target_bps": target_bps,
            "stop_bps": stop_bps,
            "timing_id": timing_id,
            "total_count": total,
            "target_first_count": target,
            "stop_first_count": counts["STOP_FIRST"],
            "expired_count": counts["EXPIRED"],
            "ambiguous_count": ambiguous,
            "conditional_denominator": conditional_denominator,
            "primary_target_first_rate": Decimal(target) / Decimal(total),
            "conditional_target_first_rate": (
                None
                if conditional_denominator == 0
                else Decimal(target) / Decimal(conditional_denominator)
            ),
            "theoretical_lower_target_first_rate": Decimal(target) / Decimal(total),
            "theoretical_upper_target_first_rate": Decimal(target + ambiguous) / Decimal(total),
            "source_bounds_hashes": source_hashes,
            "historical_evidence_only": True,
            "prohibited_interpretations": PROHIBITED_INTERPRETATIONS,
        }
    )
