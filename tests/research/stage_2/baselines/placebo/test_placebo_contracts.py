from __future__ import annotations

import pytest
from pydantic import ValidationError

from era100x.research.stage_2.baselines.conditional.v14_contracts import (
    COMBINATION_ORDER,
    OutcomeCell,
)
from era100x.research.stage_2.baselines.placebo.contracts import (
    BlindPlaceboSelection,
    PlaceboMatchMatrix,
    RELAXATION_LEVELS,
    S2P14T17Authority,
)


def _hash(value: int) -> str:
    return f"{value:064x}"


def _cells(label: str = "EXPIRED") -> tuple[OutcomeCell, ...]:
    return tuple(
        OutcomeCell(
            combination_id=combination,
            label=label,  # type: ignore[arg-type]
            label_reason=(
                "TARGET_OBSERVED_FIRST"
                if label == "TARGET_FIRST"
                else "HORIZON_EXPIRED_WITHOUT_TOUCH"
            ),
            strict_target_first=1 if label == "TARGET_FIRST" else 0,
        )
        for combination in COMBINATION_ORDER
    )


def test_blind_selection_hash_and_five_controls_are_enforced() -> None:
    selection = BlindPlaceboSelection.seal(
        {
            "source_episode_id": _hash(1),
            "source_h2_path_hash": _hash(2),
            "instrument": "BTCUSDT",
            "pre_registered_period": "P1",
            "evaluation_fold": "F0",
            "parameter_set_id": "G1-PRIMARY-V1",
            "time_combination_id": "T2",
            "status": "MATCHED",
            "placebo_event_candidate_id": _hash(3),
            "placebo_event_match_level": "L0",
            "placebo_control_match_level": "L1",
            "placebo_control_candidate_ids": tuple(_hash(index) for index in range(4, 9)),
        }
    )
    assert selection.selection_hash == selection.computed_hash()
    with pytest.raises(ValidationError, match="five unique controls"):
        BlindPlaceboSelection.seal(
            {
                **selection.model_dump(mode="python"),
                "placebo_control_candidate_ids": (_hash(4),) * 5,
            }
        )


def test_thirty_combinations_share_one_fake_event_and_control_set() -> None:
    real = _cells()
    placebo = _cells("TARGET_FIRST")
    matrix = PlaceboMatchMatrix.seal(
        {
            "source_episode_id": _hash(10),
            "source_h2_path_hash": _hash(15),
            "source_real_matrix_hash": _hash(11),
            "selection_hash": _hash(12),
            "status": "MATCHED",
            "placebo_event_candidate_id": _hash(13),
            "placebo_event_outcome_matrix_id": _hash(14),
            "placebo_event_outcomes": placebo,
            "placebo_control_candidate_ids": tuple(_hash(index) for index in range(20, 25)),
            "placebo_control_outcome_matrix_ids": tuple(_hash(index) for index in range(30, 35)),
            "placebo_control_outcomes": (real,) * 5,
            "real_event_outcomes": real,
            "real_control_outcomes": (real,) * 5,
        }
    )
    assert len(matrix.placebo_event_outcomes) == 30
    assert len(matrix.placebo_control_outcomes) == 5
    assert all(len(cells) == 30 for cells in matrix.placebo_control_outcomes)
    assert matrix.prohibited_interpretations


def test_ambiguous_is_always_strict_failure() -> None:
    with pytest.raises(ValidationError, match="strict outcome"):
        OutcomeCell(
            combination_id=COMBINATION_ORDER[0],
            label="AMBIGUOUS",
            label_reason="SOURCE_GAP_BEFORE_DECISION",
            strict_target_first=1,
        )


def test_outcome_field_cannot_be_smuggled_into_blind_selection() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        BlindPlaceboSelection.seal(
            {
                "source_episode_id": _hash(40),
                "source_h2_path_hash": _hash(41),
                "instrument": "ETHUSDT",
                "pre_registered_period": "P3",
                "evaluation_fold": "F3",
                "parameter_set_id": "G1-PRIMARY-V1",
                "time_combination_id": "T2",
                "status": "UNMATCHED_NO_PLACEBO_EVENT",
                "placebo_event_candidate_id": None,
                "placebo_event_match_level": "L5",
                "placebo_control_match_level": "L5",
                "placebo_control_candidate_ids": (),
                "outcomes_json": "forbidden",
            }
        )


def test_authority_strictly_reads_back_its_json_array_fields() -> None:
    authority = S2P14T17Authority.seal(
        {
            "code_commit": "1" * 40,
            "policy_hash": _hash(1),
            "approval_hash": _hash(2),
            "preregistration_hash": _hash(3),
            "source_t16_receipt_hash": _hash(4),
            "source_t16_authority_hash": _hash(5),
            "source_t16_binning_hash": _hash(6),
            "source_t16_manifest_hash": _hash(7),
            "source_t16_catalog_hash": _hash(8),
            "source_t16_snapshot_id": _hash(9),
            "source_t16_verify_hash": _hash(10),
            "source_counts_hash": _hash(11),
            "exact_fields": ("instrument", "evaluation_fold"),
            "relaxation_order": RELAXATION_LEVELS,
        }
    )

    reread = S2P14T17Authority.model_validate_json(authority.model_dump_json())

    assert reread == authority
    assert isinstance(reread.exact_fields, tuple)
    assert isinstance(reread.relaxation_order, tuple)
