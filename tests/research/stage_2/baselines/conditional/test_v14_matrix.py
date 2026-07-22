from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from era100x.research.stage_2.baselines.conditional.matrix_matcher import (
    attach_outcome_matrices,
    select_outcome_blind_controls,
)
from era100x.research.stage_2.baselines.conditional.outcomes import (
    H2Trade,
    build_control_outcome_matrix,
    classify_h2_cells,
)
from era100x.research.stage_2.baselines.conditional.v14_contracts import (
    COMBINATION_ORDER,
    ControlAnchor,
    OutcomeCell,
    S2T15ContractAuthority,
    V14ControlCandidate,
    V14PrimaryEpisode,
)

NS = 1_000_000_000
HASH = "a" * 64


def _ts(day: int, hour: int = 12) -> int:
    return int(datetime(2020, 6, day, hour, tzinfo=UTC).timestamp() * NS)


def _episode(**changes: object) -> V14PrimaryEpisode:
    anchor = int(changes.pop("anchor_ns", _ts(1)))
    payload: dict[str, object] = {
        "market_episode_id": "1" * 64,
        "source_h2_path_hash": "2" * 64,
        "instrument": "BTCUSDT",
        "anchor_ns": anchor,
        "high_timeframe_trend_state": "UP",
        "pre_registered_period": "P1",
        "evaluation_fold": "F0",
        "parameter_set_id": "G1-PRIMARY-V1",
        "time_combination_id": "T2",
        "label_contract_hash": "3" * 64,
        "volatility_quintile": 2,
        "activity_quintile": 2,
        "key_level_distance_quintile": 2,
        "utc_four_hour_bucket": 3,
        "utc_calendar_quarter": 2,
        "utc_calendar_year": 2020,
        "binning_snapshot_hash": "4" * 64,
        "information_span_start_ns": anchor - 3600 * NS,
        "information_span_end_ns": anchor + 600 * NS,
    }
    payload.update(changes)
    return V14PrimaryEpisode.model_validate(payload)


def _candidate(index: int, **changes: object) -> V14ControlCandidate:
    anchor = int(changes.pop("candidate_timestamp_ns", _ts(index + 2)))
    payload: dict[str, object] = {
        "control_anchor_id": f"{index + 10:064x}",
        "instrument": "BTCUSDT",
        "candidate_timestamp_ns": anchor,
        "high_timeframe_trend_state": "UP",
        "pre_registered_period": "P1",
        "evaluation_fold": "F0",
        "parameter_set_id": "G1-PRIMARY-V1",
        "time_combination_id": "T2",
        "label_contract_hash": "3" * 64,
        "control_entry_price": Decimal(100),
        "entry_price_source_hash": "5" * 64,
        "outcome_contract_hash": "3" * 64,
        "volatility_quintile": 2,
        "activity_quintile": 2,
        "key_level_distance_quintile": 2,
        "utc_four_hour_bucket": 3,
        "utc_calendar_quarter": 2,
        "utc_calendar_year": 2020,
        "binning_snapshot_hash": "4" * 64,
        "information_span_start_ns": anchor - 3600 * NS,
        "information_span_end_ns": anchor + 600 * NS,
    }
    payload.update(changes)
    return V14ControlCandidate.seal(payload)


def _cells(label: str = "TARGET_FIRST") -> tuple[OutcomeCell, ...]:
    return tuple(
        OutcomeCell(
            combination_id=combination,
            label=label,
            label_reason=(
                "TARGET_OBSERVED_FIRST" if label == "TARGET_FIRST" else "NO_OBSERVATIONS"
            ),
            strict_target_first=int(label == "TARGET_FIRST"),
        )
        for combination in COMBINATION_ORDER
    )


def test_authority_is_hash_bound_and_contains_no_run_id() -> None:
    authority = S2T15ContractAuthority.seal(
        {
            "code_commit": "1" * 64,
            "upstream_binding_hash": "2" * 64,
            "source_s2t11_binding_hash": "5" * 64,
            "stage1_binding_hash": "6" * 64,
            "context_binding_hash": "3" * 64,
            "label_contract_hash": "7" * 64,
            "preregistration_addendum_hash": "4" * 64,
        }
    )
    assert authority.authority_hash == authority.computed_hash()
    assert "run_id" not in type(authority).model_fields
    with pytest.raises(ValidationError, match="Authority hash mismatch"):
        S2T15ContractAuthority.model_validate(
            authority.model_copy(update={"upstream_binding_hash": "9" * 64}).model_dump()
        )


def test_three_control_identity_layers_are_result_and_run_independent() -> None:
    anchor = ControlAnchor.seal(
        {
            "instrument": "BTCUSDT",
            "candidate_timestamp_ns": _ts(2),
            "stage1_data_run_id": "stage1-fixed",
            "t10_snapshot_hash": HASH,
        }
    )
    candidate = _candidate(0, control_anchor_id=anchor.control_anchor_id)
    assert "outcome" not in candidate.identity_payload()
    assert "run_id" not in candidate.identity_payload()
    assert candidate.control_candidate_id == candidate.computed_id()


def test_blind_selection_enforces_distance_parameter_timing_and_same_family() -> None:
    episode = _episode()
    valid = tuple(_candidate(index) for index in range(5))
    invalid = (
        _candidate(10, key_level_distance_quintile=3),
        _candidate(11, parameter_set_id="OTHER"),
        _candidate(12, time_combination_id="T3"),
        _candidate(13, is_registered_same_family_event=True),
    )
    selection = select_outcome_blind_controls(episode, (*valid, *invalid))
    assert selection.match_level == "L0"
    assert set(selection.control_candidate_ids) == {
        candidate.control_candidate_id for candidate in valid
    }


def test_l0_l4_relaxation_never_relaxes_distance() -> None:
    episode = _episode()
    l4 = tuple(
        _candidate(
            index,
            activity_quintile=3,
            volatility_quintile=3,
            utc_four_hour_bucket=2,
            utc_calendar_quarter=1,
        )
        for index in range(5)
    )
    assert select_outcome_blind_controls(episode, l4).match_level == "L4"
    wrong_distance = tuple(
        candidate.model_copy(update={"key_level_distance_quintile": 3}) for candidate in l4
    )
    assert select_outcome_blind_controls(episode, wrong_distance).match_level == "L5"


def test_complete_zero_trade_is_ambiguous_not_expired() -> None:
    cells = classify_h2_cells(
        (),
        anchor_ns=_ts(1),
        reference_price=Decimal(100),
        time_combination_id="T2",
        source_partition_bound=True,
    )
    assert {cell.label for cell in cells} == {"AMBIGUOUS"}
    assert {cell.label_reason for cell in cells} == {"NO_OBSERVATIONS"}
    assert {cell.strict_target_first for cell in cells} == {0}


def test_h2_stable_order_gap_and_unbound_partition_fail_closed() -> None:
    trades = (
        H2Trade(_ts(1) + NS, 2, "b", Decimal(101)),
        H2Trade(_ts(1) + NS, 1, "a", Decimal(99)),
    )
    with pytest.raises(ValueError, match="stable order"):
        classify_h2_cells(
            trades,
            anchor_ns=_ts(1),
            reference_price=Decimal(100),
            time_combination_id="T2",
            source_partition_bound=True,
        )
    with pytest.raises(ValueError, match="UNBOUND"):
        classify_h2_cells(
            (),
            anchor_ns=_ts(1),
            reference_price=Decimal(100),
            time_combination_id="T2",
            source_partition_bound=False,
        )
    gap_cells = classify_h2_cells(
        (H2Trade(_ts(1) + NS, 1, "a", Decimal(100)),),
        anchor_ns=_ts(1),
        reference_price=Decimal(100),
        time_combination_id="T2",
        source_partition_bound=True,
        declared_source_gap=True,
    )
    assert {cell.label for cell in gap_cells} == {"AMBIGUOUS"}


def test_all_30_combinations_share_same_five_controls_and_attach_only_after_selection() -> None:
    episode = _episode()
    candidates = tuple(_candidate(index) for index in range(5))
    selection = select_outcome_blind_controls(episode, candidates)
    matrices = tuple(
        build_control_outcome_matrix(
            control_candidate_id=candidate_id,
            time_combination_id="T2",
            reference_price=Decimal(100),
            trades=(),
            anchor_ns=_ts(index + 2),
            source_path_hash=f"{index + 20:064x}",
            source_partition_bound=True,
        )
        for index, candidate_id in enumerate(selection.control_candidate_ids)
    )
    result = attach_outcome_matrices(selection, event_outcomes=_cells(), control_matrices=matrices)
    assert result.control_candidate_ids == selection.control_candidate_ids
    assert len(result.event_outcomes) == 30
    assert len(result.control_outcome_matrix_ids) == 5
    with pytest.raises(ValueError, match="preselected controls"):
        attach_outcome_matrices(
            selection,
            event_outcomes=_cells(),
            control_matrices=tuple(reversed(matrices)),
        )
