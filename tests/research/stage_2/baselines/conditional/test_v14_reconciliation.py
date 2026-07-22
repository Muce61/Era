import pytest
from pydantic import ValidationError

from era100x.research.stage_2.baselines.conditional.reconciliation import (
    ControlReconciliation,
    EpisodeReconciliation,
)


def test_episode_reconciliation_accounts_every_path_and_cell() -> None:
    result = EpisodeReconciliation(
        source_h2_path_count=10,
        train_only_not_evaluated_count=2,
        excluded_episode_count=1,
        eligible_episode_count=7,
        matched_episode_count=5,
        unmatched_episode_count=2,
        source_h2_outcome_cell_count=300,
        event_outcome_cell_count=210,
    )
    assert result.eligible_episode_count == 7
    with pytest.raises(ValueError, match="sealed T13"):
        result.require_frozen_source_baseline()


def test_episode_reconciliation_fails_unpublished_on_any_count_gap() -> None:
    with pytest.raises(ValidationError, match="not fully reconciled"):
        EpisodeReconciliation(
            source_h2_path_count=10,
            train_only_not_evaluated_count=2,
            excluded_episode_count=1,
            eligible_episode_count=6,
            matched_episode_count=5,
            unmatched_episode_count=1,
            source_h2_outcome_cell_count=300,
            event_outcome_cell_count=180,
        )


def test_control_reconciliation_accounts_grid_assignments_and_matrix_cells() -> None:
    result = ControlReconciliation(
        grid_anchor_count=100,
        outside_period_or_split=10,
        incomplete_information_span=10,
        price_feature_unavailable=10,
        activity_feature_unavailable=10,
        context_unavailable=10,
        market_state_eligible_anchor_count=50,
        candidate_opportunity_count=50,
        key_level_unavailable=10,
        registered_same_family_event=10,
        outcome_source_unavailable=10,
        eligible_control_count=20,
        unique_control_candidate_count=20,
        matched_episode_count=2,
        control_assignment_count=10,
        orphan_assignment_count=0,
        duplicate_assignment_within_episode=0,
        control_outcome_matrix_count=8,
        control_outcome_cell_count=240,
    )
    assert result.grid_anchor_count == 100
    with pytest.raises(ValidationError, match="five assignments"):
        ControlReconciliation.model_validate(
            result.model_copy(update={"control_assignment_count": 9}).model_dump()
        )
