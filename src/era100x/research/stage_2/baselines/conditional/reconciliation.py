"""Fail-closed quantity reconciliation for S2-T15 v1.4."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from era100x.research.stage_2.contracts.models import StrictEventModel

from .v14_contracts import EXPECTED_H2_OUTCOME_CELLS, EXPECTED_H2_PATHS


class EpisodeReconciliation(StrictEventModel):
    source_h2_path_count: int = Field(ge=0)
    train_only_not_evaluated_count: int = Field(ge=0)
    excluded_episode_count: int = Field(ge=0)
    eligible_episode_count: int = Field(ge=0)
    matched_episode_count: int = Field(ge=0)
    unmatched_episode_count: int = Field(ge=0)
    source_h2_outcome_cell_count: int = Field(ge=0)
    event_outcome_cell_count: int = Field(ge=0)

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        if self.source_h2_path_count != (
            self.train_only_not_evaluated_count
            + self.excluded_episode_count
            + self.eligible_episode_count
        ):
            raise ValueError("H2 paths are not fully reconciled")
        if self.matched_episode_count + self.unmatched_episode_count != self.eligible_episode_count:
            raise ValueError("eligible Episodes are not MATCHED/UNMATCHED exactly once")
        if self.source_h2_outcome_cell_count != self.source_h2_path_count * 30:
            raise ValueError("source H2 path/cell count mismatch")
        if self.event_outcome_cell_count != self.eligible_episode_count * 30:
            raise ValueError("eligible event matrix cell count mismatch")
        return self

    def require_frozen_source_baseline(self) -> None:
        if self.source_h2_path_count != EXPECTED_H2_PATHS:
            raise ValueError("sealed T13 H2 path count drift")
        if self.source_h2_outcome_cell_count != EXPECTED_H2_OUTCOME_CELLS:
            raise ValueError("sealed T13 H2 outcome-cell count drift")


class ControlReconciliation(StrictEventModel):
    grid_anchor_count: int = Field(ge=0)
    outside_period_or_split: int = Field(ge=0)
    incomplete_information_span: int = Field(ge=0)
    price_feature_unavailable: int = Field(ge=0)
    activity_feature_unavailable: int = Field(ge=0)
    context_unavailable: int = Field(ge=0)
    market_state_eligible_anchor_count: int = Field(ge=0)
    candidate_opportunity_count: int = Field(ge=0)
    key_level_unavailable: int = Field(ge=0)
    registered_same_family_event: int = Field(ge=0)
    outcome_source_unavailable: int = Field(ge=0)
    eligible_control_count: int = Field(ge=0)
    unique_control_candidate_count: int = Field(ge=0)
    matched_episode_count: int = Field(ge=0)
    control_assignment_count: int = Field(ge=0)
    orphan_assignment_count: int = Field(ge=0)
    duplicate_assignment_within_episode: int = Field(ge=0)
    control_outcome_matrix_count: int = Field(ge=0)
    control_outcome_cell_count: int = Field(ge=0)

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        classified = (
            self.outside_period_or_split
            + self.incomplete_information_span
            + self.price_feature_unavailable
            + self.activity_feature_unavailable
            + self.context_unavailable
            + self.market_state_eligible_anchor_count
        )
        if classified != self.grid_anchor_count:
            raise ValueError("control grid anchors are not classified exactly once")
        candidate_classified = (
            self.key_level_unavailable
            + self.registered_same_family_event
            + self.outcome_source_unavailable
            + self.eligible_control_count
        )
        if candidate_classified != self.candidate_opportunity_count:
            raise ValueError(
                "parameter-isolated control candidates are not classified exactly once"
            )
        if self.eligible_control_count != self.unique_control_candidate_count:
            raise ValueError("eligible controls do not have unique identities")
        if self.control_assignment_count != self.matched_episode_count * 5:
            raise ValueError("each MATCHED Episode must have five assignments")
        if self.orphan_assignment_count or self.duplicate_assignment_within_episode:
            raise ValueError("control assignments contain an orphan or within-Episode duplicate")
        if self.control_outcome_cell_count != self.control_outcome_matrix_count * 30:
            raise ValueError("control outcome matrices must each contain 30 cells")
        return self
