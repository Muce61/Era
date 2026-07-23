from __future__ import annotations

import hashlib
import random
from decimal import Decimal

import pytest
from pydantic import ValidationError

from era100x.research.stage_2.labels.ambiguity import (
    HistoricalAmbiguityBounds,
    derive_ambiguity_bounds,
    summarize_ambiguity_bounds,
)
from era100x.research.stage_2.labels.first_passage.models import HistoricalFirstPassageLabel

S = 1_000_000_000
START = 10 * S
END = START + 60 * S


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _first_passage(
    label: str,
    *,
    evidence_level: str = "H1",
    reason: str | None = None,
    salt: int = 1,
    instrument: str = "BTCUSDT",
) -> HistoricalFirstPassageLabel:
    reasons = {
        "TARGET_FIRST": "TARGET_OBSERVED_FIRST",
        "STOP_FIRST": "STOP_OBSERVED_FIRST",
        "EXPIRED": "HORIZON_EXPIRED_WITHOUT_TOUCH",
        "AMBIGUOUS": "H1_SAME_EVENT_TARGET_AND_STOP",
    }
    selected_reason = reason or reasons[label]
    target_ts = None
    stop_ts = None
    decision_ts = None
    conservative = None
    observation_count = 60
    window_complete = True
    if label == "TARGET_FIRST":
        target_ts = 20 * S
        decision_ts = target_ts
        conservative = "TARGET_FIRST"
    elif label == "STOP_FIRST":
        stop_ts = 20 * S
        decision_ts = stop_ts
        conservative = "STOP_FIRST"
    elif label == "EXPIRED":
        conservative = "EXPIRED"
    elif selected_reason == "H1_SAME_EVENT_TARGET_AND_STOP":
        target_ts = stop_ts = decision_ts = 20 * S
        conservative = "STOP_FIRST"
    elif selected_reason == "NO_OBSERVATIONS":
        observation_count = 0
    elif selected_reason == "WINDOW_TRUNCATED_BEFORE_DECISION":
        window_complete = False
    source_gap_codes = (
        ("H1_MISSING_SECONDS",) if selected_reason == "SOURCE_GAP_BEFORE_DECISION" else ()
    )
    return HistoricalFirstPassageLabel.seal(
        {
            "instrument": instrument,
            "market_episode_id": f"{salt:064x}",
            "canonical_candidate_id": f"{salt + 100:064x}",
            "candidate_version_id": f"{salt + 200:064x}",
            "canonical_payload_hash": f"{salt + 300:064x}",
            "parameter_set_id": "G1-PRIMARY-V1",
            "evidence_level": evidence_level,
            "reference_price_type": "CONTRACT" if evidence_level == "H1" else "TRADE",
            "reference_price": Decimal("100"),
            "target_bps": Decimal("20"),
            "stop_bps": Decimal("15"),
            "target_price": Decimal("100.20"),
            "stop_price": Decimal("99.85"),
            "timing_id": "T1",
            "horizon_seconds": 60,
            "window_start_ns": START,
            "requested_window_end_ns": END,
            "source_window_end_ns": END if window_complete else END - S,
            "window_complete": window_complete,
            "observation_count": observation_count,
            "label": label,
            "label_reason": selected_reason,
            "conservative_main_label": conservative,
            "target_touch_ts_event_ns": target_ts,
            "stop_touch_ts_event_ns": stop_ts,
            "decision_ts_event_ns": decision_ts,
            "time_to_decision_ns": None if decision_ts is None else decision_ts - START,
            "strict_target_first": label == "TARGET_FIRST",
            "stable_order": (
                ("ts_event_ns", "source_row_hash")
                if evidence_level == "H1"
                else ("ts_event_ns", "venue_trade_id", "canonical_trade_id")
            ),
            "source_quality_status": "COMPLETE",
            "source_gap_codes": source_gap_codes,
            "source_ambiguity_codes": (),
            "historical_evidence_only": True,
            "source_path_hash": _sha(f"path-{salt}"),
        }
    )


def test_h1_same_event_keeps_raw_ambiguous_and_reports_both_bounds() -> None:
    source = _first_passage("AMBIGUOUS")

    result = derive_ambiguity_bounds(source)

    assert result.raw_label == "AMBIGUOUS"
    assert result.raw_ambiguous_preserved is True
    assert result.primary_ambiguous_policy == "FAILURE"
    assert result.primary_target_first == 0
    assert result.conditional_target_first is None
    assert result.theoretical_lower_target_first == 0
    assert result.theoretical_upper_target_first == 1
    assert result.pessimistic_path_label == "STOP_FIRST"
    assert result.optimistic_path_label == "TARGET_FIRST"
    assert result.source_first_passage_hash == source.output_hash


@pytest.mark.parametrize(
    "reason",
    ("NO_OBSERVATIONS", "SOURCE_GAP_BEFORE_DECISION", "WINDOW_TRUNCATED_BEFORE_DECISION"),
)
def test_unresolved_source_ambiguity_gets_indicator_bounds_without_invented_path_labels(
    reason: str,
) -> None:
    result = derive_ambiguity_bounds(_first_passage("AMBIGUOUS", reason=reason))

    assert result.raw_label == "AMBIGUOUS"
    assert result.primary_target_first == 0
    assert result.theoretical_upper_target_first == 1
    assert result.pessimistic_path_label is None
    assert result.optimistic_path_label is None


@pytest.mark.parametrize(
    ("label", "expected"),
    (("TARGET_FIRST", 1), ("STOP_FIRST", 0), ("EXPIRED", 0)),
)
def test_determinate_labels_collapse_to_one_bound(label: str, expected: int) -> None:
    result = derive_ambiguity_bounds(_first_passage(label))

    assert result.raw_label == label
    assert result.primary_target_first == expected
    assert result.conditional_target_first == expected
    assert result.theoretical_lower_target_first == expected
    assert result.theoretical_upper_target_first == expected
    assert result.pessimistic_path_label == label
    assert result.optimistic_path_label == label
    assert result.excluded_from_conditional is False


def test_h2_determinate_order_passes_through_without_ambiguity_invention() -> None:
    result = derive_ambiguity_bounds(_first_passage("TARGET_FIRST", evidence_level="H2"))

    assert result.evidence_level == "H2"
    assert result.raw_label == "TARGET_FIRST"
    assert result.theoretical_lower_target_first == result.theoretical_upper_target_first == 1


def test_distribution_reports_failure_conditional_and_theoretical_upper_rates() -> None:
    labels = (
        _first_passage("TARGET_FIRST", salt=1),
        _first_passage("STOP_FIRST", salt=2),
        _first_passage("EXPIRED", salt=3),
        _first_passage("AMBIGUOUS", salt=4),
    )
    records = tuple(derive_ambiguity_bounds(label) for label in labels)

    result = summarize_ambiguity_bounds(records)

    assert result.total_count == 4
    assert result.target_first_count == 1
    assert result.stop_first_count == 1
    assert result.expired_count == 1
    assert result.ambiguous_count == 1
    assert result.primary_target_first_rate == Decimal("0.25")
    assert result.conditional_target_first_rate == Decimal(1) / Decimal(3)
    assert result.theoretical_lower_target_first_rate == Decimal("0.25")
    assert result.theoretical_upper_target_first_rate == Decimal("0.5")


def test_all_ambiguous_distribution_has_no_conditional_rate() -> None:
    records = tuple(
        derive_ambiguity_bounds(_first_passage("AMBIGUOUS", salt=salt)) for salt in (1, 2)
    )

    result = summarize_ambiguity_bounds(records)

    assert result.conditional_denominator == 0
    assert result.conditional_target_first_rate is None
    assert result.primary_target_first_rate == 0
    assert result.theoretical_upper_target_first_rate == 1


def test_distribution_rejects_mixed_instruments_and_duplicate_evidence() -> None:
    btc = derive_ambiguity_bounds(_first_passage("TARGET_FIRST", salt=1))
    eth = derive_ambiguity_bounds(_first_passage("TARGET_FIRST", salt=2, instrument="ETHUSDT"))
    with pytest.raises(ValueError, match="must remain separate"):
        summarize_ambiguity_bounds((btc, eth))
    with pytest.raises(ValueError, match="duplicate"):
        summarize_ambiguity_bounds((btc, btc))


def test_input_shuffle_does_not_change_distribution_hash() -> None:
    records = [
        derive_ambiguity_bounds(_first_passage(label, salt=index))
        for index, label in enumerate(
            ("TARGET_FIRST", "STOP_FIRST", "EXPIRED", "AMBIGUOUS"), start=1
        )
    ]
    expected = summarize_ambiguity_bounds(tuple(records))
    random.Random(20260721).shuffle(records)

    actual = summarize_ambiguity_bounds(tuple(records))

    assert actual.output_hash == expected.output_hash
    assert actual.source_bounds_hashes == expected.source_bounds_hashes


def test_hash_tampering_and_invalid_ambiguous_reclassification_fail_closed() -> None:
    source = _first_passage("AMBIGUOUS")
    tampered_source = source.model_copy(update={"market_episode_id": "f" * 64})
    with pytest.raises(ValueError, match="source first-passage hash"):
        derive_ambiguity_bounds(tampered_source)

    result = derive_ambiguity_bounds(source)
    tampered_payload = result.model_dump(mode="python")
    tampered_payload["optimistic_path_label"] = "EXPIRED"
    with pytest.raises(ValidationError, match="adverse/optimistic bounds"):
        HistoricalAmbiguityBounds.model_validate(tampered_payload)


def test_raw_label_reason_mismatch_cannot_be_hidden_behind_a_source_hash() -> None:
    result = derive_ambiguity_bounds(_first_passage("TARGET_FIRST"))
    payload = result.model_dump(mode="python")
    payload["raw_label_reason"] = "STOP_OBSERVED_FIRST"

    with pytest.raises(ValidationError, match="label and reason disagree"):
        HistoricalAmbiguityBounds.model_validate(payload)


def test_historical_boundary_forbids_pnl_round_success_and_ambiguity_deletion() -> None:
    result = derive_ambiguity_bounds(_first_passage("AMBIGUOUS"))

    assert result.historical_evidence_only is True
    assert {
        "PNL",
        "RETURN",
        "ROUND_SUCCESS",
        "LIVE_EXECUTION",
        "RAW_LABEL_RECLASSIFICATION",
        "AMBIGUITY_DELETION",
    }.issubset(result.prohibited_interpretations)
    assert "round_success" not in HistoricalAmbiguityBounds.model_fields
