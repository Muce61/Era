from __future__ import annotations

import random
from typing import Any

import pytest

from era100x.research.stage_2.baselines.placebo.contracts import (
    PlaceboCandidate,
    PlaceboEventReference,
)
from era100x.research.stage_2.baselines.placebo.matching import select_placebo


def _hash(value: int) -> str:
    return f"{value:064x}"


def _candidate(
    value: int,
    *,
    anchor_ns: int | None = None,
    activity: int = 3,
    volatility: int = 3,
    bucket: int = 2,
    quarter: int = 2,
    year: int = 2022,
    same_family: bool = False,
) -> PlaceboCandidate:
    anchor = anchor_ns if anchor_ns is not None else (value + 100) * 10_000_000_000_000
    return PlaceboCandidate(
        control_candidate_id=_hash(value),
        control_anchor_id=_hash(value + 10_000),
        instrument="BTCUSDT",
        candidate_timestamp_ns=anchor,
        setup_id="KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0",
        context_model_id="CAUSAL_EMA20_1H@1.0",
        high_timeframe_trend_state="UP",
        pre_registered_period="P2",
        evaluation_fold="F1",
        parameter_set_id="G1-PRIMARY-V1",
        time_combination_id="T2",
        label_contract_hash=_hash(90_001),
        volatility_quintile=volatility,
        activity_quintile=activity,
        key_level_distance_quintile=2,
        utc_four_hour_bucket=bucket,
        utc_calendar_quarter=quarter,
        utc_calendar_year=year,
        binning_snapshot_hash=_hash(90_002),
        information_span_start_ns=anchor - 3_600_000_000_000,
        information_span_end_ns=anchor + 600_000_000_000,
        is_registered_same_family_event=same_family,
    )


def _source(value: int = 50_000) -> PlaceboEventReference:
    anchor = 1_650_000_000_000_000_000 + value
    return PlaceboEventReference(
        source_episode_id=_hash(value),
        source_h2_path_hash=_hash(value + 1),
        instrument="BTCUSDT",
        anchor_ns=anchor,
        setup_id="KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0",
        context_model_id="CAUSAL_EMA20_1H@1.0",
        high_timeframe_trend_state="UP",
        pre_registered_period="P2",
        evaluation_fold="F1",
        parameter_set_id="G1-PRIMARY-V1",
        time_combination_id="T2",
        label_contract_hash=_hash(90_001),
        volatility_quintile=3,
        activity_quintile=3,
        key_level_distance_quintile=2,
        utc_four_hour_bucket=2,
        utc_calendar_quarter=2,
        utc_calendar_year=2022,
        binning_snapshot_hash=_hash(90_002),
        information_span_start_ns=anchor - 3_600_000_000_000,
        information_span_end_ns=anchor + 600_000_000_000,
        original_control_candidate_ids=tuple(_hash(index) for index in range(1, 6)),
    )


def test_input_shuffle_is_deterministic_and_original_controls_are_excluded() -> None:
    candidates = tuple(_candidate(index) for index in range(1, 20))
    first = select_placebo(_source(), candidates, used_placebo_event_ids=set())
    shuffled = list(candidates)
    random.Random(7).shuffle(shuffled)
    second = select_placebo(_source(), tuple(shuffled), used_placebo_event_ids=set())
    assert first == second
    assert first.status == "MATCHED"
    assert first.placebo_event_candidate_id not in _source().original_control_candidate_ids
    assert not set(first.placebo_control_candidate_ids) & set(
        _source().original_control_candidate_ids
    )
    assert first.placebo_event_candidate_id not in first.placebo_control_candidate_ids


def test_fake_event_is_unique_within_group() -> None:
    candidates = tuple(_candidate(index) for index in range(10, 30))
    used: set[str] = set()
    first = select_placebo(_source(50_000), candidates, used_placebo_event_ids=used)
    second = select_placebo(_source(50_100), candidates, used_placebo_event_ids=used)
    assert first.placebo_event_candidate_id != second.placebo_event_candidate_id
    assert len(used) == 2


def test_overlap_and_same_family_are_excluded() -> None:
    source = _source()
    overlap = _candidate(
        100,
        anchor_ns=source.information_span_end_ns + 1,
    ).model_copy(
        update={
            "information_span_start_ns": source.information_span_end_ns - 1,
            "information_span_end_ns": source.information_span_end_ns + 1,
        }
    )
    same_family = _candidate(101, same_family=True)
    clean = tuple(_candidate(index) for index in range(102, 115))
    result = select_placebo(
        source,
        (overlap, same_family, *clean),
        used_placebo_event_ids=set(),
    )
    assert result.status == "MATCHED"
    assert result.placebo_event_candidate_id not in {
        overlap.control_candidate_id,
        same_family.control_candidate_id,
    }


def test_exact_fields_never_relax_but_l1_to_l4_do() -> None:
    source = _source()
    relaxed = tuple(
        _candidate(index, activity=4, volatility=4, bucket=3, quarter=3, year=2022)
        for index in range(200, 220)
    )
    result = select_placebo(source, relaxed, used_placebo_event_ids=set())
    assert result.status == "MATCHED"
    assert result.placebo_event_match_level == "L4"
    wrong_distance = tuple(
        item.model_copy(update={"key_level_distance_quintile": 5}) for item in relaxed
    )
    blocked = select_placebo(source, wrong_distance, used_placebo_event_ids=set())
    assert blocked.status == "UNMATCHED_NO_PLACEBO_EVENT"


def test_chosen_fake_event_is_not_replaced_when_controls_are_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    fake = _candidate(300, activity=3)
    four_controls = tuple(_candidate(index, activity=3) for index in range(301, 305))
    rescue_family = tuple(_candidate(index, activity=4) for index in range(310, 320))

    def ordered(
        namespace: str,
        source_id: str,
        candidates: Any,
    ) -> list[PlaceboCandidate]:
        del namespace, source_id
        values = list(candidates)
        return sorted(
            values,
            key=lambda item: (
                item.control_candidate_id != fake.control_candidate_id,
                item.control_candidate_id,
            ),
        )

    monkeypatch.setattr(
        "era100x.research.stage_2.baselines.placebo.matching._ordered",
        ordered,
    )
    from era100x.research.stage_2.baselines.placebo import matching

    original_eligible = matching._eligible_at_level

    def eligible(*args: Any, **kwargs: Any) -> list[PlaceboCandidate]:
        values = original_eligible(*args, **kwargs)
        if (
            args
            and isinstance(args[0], PlaceboCandidate)
            and args[0].control_candidate_id == fake.control_candidate_id
        ):
            return values[:4]
        return values

    monkeypatch.setattr(
        "era100x.research.stage_2.baselines.placebo.matching._eligible_at_level",
        eligible,
    )
    result = select_placebo(
        source,
        (fake, *four_controls, *rescue_family),
        used_placebo_event_ids=set(),
    )
    assert result.placebo_event_candidate_id == fake.control_candidate_id
    assert result.status == "UNMATCHED_CONTROLS"
    assert result.placebo_control_candidate_ids == ()


def test_duplicate_candidate_id_with_conflicting_payload_fails() -> None:
    first = _candidate(400)
    conflicting = first.model_copy(update={"activity_quintile": 5})
    with pytest.raises(ValueError, match="conflicting payloads"):
        select_placebo(
            _source(),
            (first, conflicting),
            used_placebo_event_ids=set(),
        )
