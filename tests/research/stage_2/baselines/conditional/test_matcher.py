from __future__ import annotations

import hashlib
import random
from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from era100x.research.stage_2.baselines.conditional import (
    ConditionalBaselineManifest,
    ControlCandidate,
    FrozenQuintileBoundaries,
    PrimaryEpisode,
    match_conditional_controls,
    summarize_conditional_matches,
)

S = 1_000_000_000
MANIFEST_HASH = "a" * 64
CONFIG_HASH = "b" * 64
BIN_HASH = "c" * 64


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ns(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * S)


def _manifest(**updates: object) -> ConditionalBaselineManifest:
    payload: dict[str, object] = {
        "source_preregistration_manifest_hash": MANIFEST_HASH,
        "source_config_hash": CONFIG_HASH,
    }
    payload.update(updates)
    return ConditionalBaselineManifest.model_validate(payload)


def _episode(
    *,
    salt: str = "episode-1",
    available: str = "2020-01-02T10:00:00Z",
    instrument: str = "BTCUSDT",
    split: str = "TRAIN-1",
    trend: str = "UP",
    bucket: str = "B2",
    volatility: int = 3,
    activity: int = 3,
    quarter: int = 1,
    label: str = "TARGET_FIRST",
) -> PrimaryEpisode:
    available_ns = _ns(available)
    return PrimaryEpisode.model_validate(
        {
            "instrument": instrument,
            "setup_id": "KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
            "context_model_id": "G1_CONTEXT_V1",
            "high_timeframe_trend_state": trend,
            "pre_registered_period": "P1",
            "research_split_or_fold": split,
            "available_at_ns": available_ns,
            "utc_four_hour_bucket": bucket,
            "volatility_quintile": volatility,
            "activity_quintile": activity,
            "utc_calendar_quarter": quarter,
            "binning_snapshot_hash": BIN_HASH,
            "market_episode_id": _sha(salt),
            "event_window_start_ns": available_ns,
            "event_window_end_ns": available_ns + 180 * S,
            "purge_embargo_start_ns": available_ns - 3_600 * S,
            "purge_embargo_end_ns": available_ns + 3_600 * S,
            "raw_label": label,
        }
    )


def _control(
    index: int,
    *,
    timestamp: str = "2020-01-03T10:00:00Z",
    instrument: str = "BTCUSDT",
    split: str = "TRAIN-1",
    trend: str = "UP",
    bucket: str = "B2",
    volatility: int = 3,
    activity: int = 3,
    quarter: int = 1,
    setup: str = "KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
    context: str = "G1_CONTEXT_V1",
    same_family: bool = False,
    target: int = 0,
    bin_hash: str = BIN_HASH,
) -> ControlCandidate:
    timestamp_ns = _ns(timestamp) + index * S
    return ControlCandidate.model_validate(
        {
            "instrument": instrument,
            "setup_id": setup,
            "context_model_id": context,
            "high_timeframe_trend_state": trend,
            "pre_registered_period": "P1",
            "research_split_or_fold": split,
            "available_at_ns": timestamp_ns,
            "utc_four_hour_bucket": bucket,
            "volatility_quintile": volatility,
            "activity_quintile": activity,
            "utc_calendar_quarter": quarter,
            "binning_snapshot_hash": bin_hash,
            "control_id": _sha(f"control-{index}-{timestamp}"),
            "candidate_timestamp_ns": timestamp_ns,
            "window_start_ns": timestamp_ns,
            "window_end_ns": timestamp_ns + 60 * S,
            "is_registered_same_family_event": same_family,
            "target_first_strict": target,
        }
    )


def test_l0_selects_five_unique_controls_in_preregistered_hash_order() -> None:
    episode = _episode()
    controls = tuple(_control(index, target=index % 2) for index in range(8))

    result = match_conditional_controls(episode, controls, _manifest())

    assert result.status == "MATCHED"
    assert result.event_match_level == "L0"
    assert len(result.control_ids) == len(set(result.control_ids)) == 5
    assert result.episode_control_mean == Decimal(sum(result.control_target_first_values)) / 5
    assert result.primary_target_first == 1


@pytest.mark.parametrize(
    ("expected_level", "attributes", "timestamp"),
    (
        ("L1", {"activity": 4}, "2020-01-03T10:00:00Z"),
        ("L2", {"activity": 4, "volatility": 4}, "2020-01-03T10:00:00Z"),
        ("L3", {"activity": 4, "volatility": 4, "bucket": "B3"}, "2020-01-03T14:00:00Z"),
        (
            "L4",
            {"activity": 4, "volatility": 4, "bucket": "B3", "quarter": 2},
            "2020-04-03T14:00:00Z",
        ),
    ),
)
def test_relaxation_is_cumulative_and_stops_at_first_level_with_five_controls(
    expected_level: str, attributes: dict[str, object], timestamp: str
) -> None:
    controls = tuple(_control(index, timestamp=timestamp, **attributes) for index in range(5))

    result = match_conditional_controls(_episode(), controls, _manifest())

    assert result.status == "MATCHED"
    assert result.event_match_level == expected_level


def test_l3_uses_circular_adjacent_four_hour_buckets() -> None:
    episode = _episode(available="2020-01-02T00:00:00Z", bucket="B0")
    controls = tuple(
        _control(index, timestamp="2020-01-03T22:00:00Z", bucket="B5") for index in range(5)
    )

    result = match_conditional_controls(episode, controls, _manifest())

    assert result.event_match_level == "L3"


def test_l5_unmatched_never_backfills_across_exact_boundaries() -> None:
    episode = _episode()
    controls = (
        *(_control(index, instrument="ETHUSDT") for index in range(5)),
        *(_control(index + 10, split="VALIDATION") for index in range(5)),
        *(_control(index + 20, trend="DOWN") for index in range(5)),
        *(_control(index + 30, same_family=True) for index in range(5)),
        *(_control(index + 40, setup="OTHER_SETUP") for index in range(5)),
        *(_control(index + 50, context="OTHER_CONTEXT") for index in range(5)),
    )

    result = match_conditional_controls(episode, controls, _manifest())

    assert result.status == "UNMATCHED"
    assert result.event_match_level == "L5"
    assert result.control_ids == ()
    assert result.episode_control_mean is None


def test_purge_embargo_and_event_overlap_are_excluded_at_left_closed_boundaries() -> None:
    episode = _episode()
    before = _control(1, timestamp="2020-01-02T08:58:59Z")
    inside_purge = tuple(
        _control(index + 10, timestamp="2020-01-02T09:30:00Z") for index in range(5)
    )
    after = tuple(_control(index + 20, timestamp="2020-01-02T11:00:00Z") for index in range(4))

    result = match_conditional_controls(episode, (before, *inside_purge, *after), _manifest())

    assert result.status == "MATCHED"
    assert set(result.control_ids) == {
        before.control_id,
        *(control.control_id for control in after),
    }


def test_period_bucket_and_quarter_claims_fail_closed() -> None:
    with pytest.raises(ValueError, match="preregistered period"):
        match_conditional_controls(
            _episode(),
            tuple(_control(index, timestamp="2022-01-03T10:00:00Z") for index in range(5)),
            _manifest(),
        )
    with pytest.raises(ValueError, match="four-hour bucket"):
        match_conditional_controls(
            _episode(bucket="B1"),
            tuple(_control(index) for index in range(5)),
            _manifest(),
        )
    with pytest.raises(ValueError, match="calendar quarter"):
        match_conditional_controls(
            _episode(quarter=2),
            tuple(_control(index) for index in range(5)),
            _manifest(),
        )


def test_duplicate_controls_and_binning_snapshot_drift_fail_closed() -> None:
    control = _control(1)
    with pytest.raises(ValueError, match="duplicate control_id"):
        match_conditional_controls(_episode(), (control, control), _manifest())

    controls = tuple(_control(index, bin_hash="d" * 64) for index in range(5))
    result = match_conditional_controls(_episode(), controls, _manifest())
    assert result.status == "UNMATCHED"


def test_training_only_quintile_boundaries_require_five_valid_bins_and_are_hash_bound() -> None:
    boundaries = FrozenQuintileBoundaries.seal(
        {
            "boundary_kind": "VOLATILITY",
            "training_split_or_fold": "TRAIN-1",
            "cut_points": (Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")),
            "training_sample_count": 100,
            "source_manifest_hash": MANIFEST_HASH,
        }
    )

    assert [boundaries.assign(Decimal(value)) for value in ("0", "1", "2.5", "4", "5")] == [
        1,
        2,
        3,
        5,
        5,
    ]
    with pytest.raises(ValidationError, match="strictly increasing"):
        FrozenQuintileBoundaries.seal(
            {
                "boundary_kind": "TRADES_ACTIVITY",
                "training_split_or_fold": "TRAIN-1",
                "cut_points": (Decimal("1"), Decimal("2"), Decimal("2"), Decimal("4")),
                "training_sample_count": 100,
                "source_manifest_hash": MANIFEST_HASH,
            }
        )
    with pytest.raises(ValidationError, match="hash mismatch"):
        FrozenQuintileBoundaries.model_validate(
            boundaries.model_copy(update={"training_sample_count": 101}).model_dump()
        )


def test_manifest_snapshot_rejects_relaxation_period_or_exact_field_drift() -> None:
    with pytest.raises(ValidationError, match="relaxation order"):
        _manifest(relaxation_order=("L0", "L2", "L1", "L3", "L4", "L5"))
    with pytest.raises(ValidationError, match="period boundaries"):
        _manifest(periods=(("P1", 0, 1), ("P2", 1, 2), ("P3", 2, 3)))
    with pytest.raises(ValidationError, match="non-relaxable"):
        _manifest(exact_match_fields=("instrument",))


def test_input_shuffle_does_not_change_match_or_summary_hashes() -> None:
    controls = [_control(index, target=index % 2) for index in range(10)]
    expected_match = match_conditional_controls(_episode(), tuple(controls), _manifest())
    random.Random(20260721).shuffle(controls)
    actual_match = match_conditional_controls(_episode(), tuple(controls), _manifest())

    assert actual_match.output_hash == expected_match.output_hash
    assert actual_match.control_ids == expected_match.control_ids
    expected_summary = summarize_conditional_matches((expected_match,))
    actual_summary = summarize_conditional_matches((actual_match,))
    assert actual_summary.output_hash == expected_summary.output_hash


def test_summary_is_episode_equal_weighted_reports_reuse_and_keeps_ambiguous_failure() -> None:
    controls = tuple(_control(index, target=1 if index < 3 else 0) for index in range(5))
    target = match_conditional_controls(_episode(salt="target"), controls, _manifest())
    ambiguous = match_conditional_controls(
        _episode(salt="ambiguous", label="AMBIGUOUS"), controls, _manifest()
    )

    summary = summarize_conditional_matches((target, ambiguous))

    assert summary.matched_episode_count == 2
    assert summary.matching_coverage == 1
    assert summary.event_target_first_rate == Decimal("0.5")
    assert summary.matched_baseline_target_first_rate == Decimal("0.6")
    assert summary.delta_target_first == Decimal("-0.1")
    assert summary.control_reuse_rate == Decimal("0.5")
    assert ambiguous.primary_target_first == 0


def test_summary_rejects_mixed_groups_duplicate_episodes_and_tampered_hashes() -> None:
    controls = tuple(_control(index) for index in range(5))
    btc = match_conditional_controls(_episode(), controls, _manifest())
    eth_controls = tuple(_control(index + 10, instrument="ETHUSDT") for index in range(5))
    eth = match_conditional_controls(
        _episode(salt="eth", instrument="ETHUSDT"), eth_controls, _manifest()
    )
    with pytest.raises(ValueError, match="must remain separate"):
        summarize_conditional_matches((btc, eth))
    with pytest.raises(ValueError, match="duplicate market_episode_id"):
        summarize_conditional_matches((btc, btc))
    tampered = btc.model_copy(update={"primary_target_first": 0})
    with pytest.raises(ValueError, match="source conditional match hash"):
        summarize_conditional_matches((tampered,))


def test_fixture_remains_historical_and_has_no_pnl_or_round_success_fields() -> None:
    result = match_conditional_controls(
        _episode(label="AMBIGUOUS"), tuple(_control(index) for index in range(5)), _manifest()
    )

    assert result.historical_evidence_only is True
    assert {"PNL", "RETURN", "ROUND_SUCCESS", "LIVE_EXECUTION"}.issubset(
        result.prohibited_interpretations
    )
    assert "pnl" not in type(result).model_fields
    assert "round_success" not in type(result).model_fields
