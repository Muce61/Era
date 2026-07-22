"""Frozen S2-T15 v1.4 historical conditional-baseline contracts.

The types in this module deliberately separate outcome-blind control identity
from H2 outcome evidence.  Nothing here represents an executable price, PnL,
or a live-return claim.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.contracts.models import Direction, Instrument, StrictEventModel
from era100x.research.stage_2.paths.extraction.models import _canonical_json

SHA256_PATTERN = r"^[0-9a-f]{64}$"
TASK_VERSION = "1.4"
SETUP_ID = "KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0"
CONTEXT_MODEL_ID = "CAUSAL_EMA20_1H@1.0"
MATCHING_SEED = 20260716
CONTROL_GRID_VERSION = "CONTROL_GRID_1M_DAILY_OFFSET_V1"
VOLATILITY_FORMULA_ID = "VOLATILITY_1M_60BAR_RMS_BPS_V1"
ACTIVITY_FORMULA_ID = "TRADES_ACTIVITY_COUNT_60S_V1"
DISTANCE_FORMULA_ID = "DISTANCE_TO_ACTIVE_CANONICAL_KEY_LEVEL_BPS_V1"
QUINTILE_ALGORITHM_ID = "TIE_PRESERVING_NEAREST_CUMULATIVE_V1"
REFERENCE_PRICE_SOURCE = "CONTRACT_PRICE_1S_CLOSE"
PATH_EVIDENCE_LEVEL = "H2"
BACKWARD_PURGE_SECONDS = 3600
FORWARD_EMBARGO_SECONDS = 600
CONTROLS_PER_EPISODE = 5
EXPECTED_H2_PATHS = 532_708
EXPECTED_H2_OUTCOME_CELLS = 15_981_240
REGISTERED_PARAMETER_TIMING_PAIRS: tuple[tuple[str, str], ...] = (
    ("G1-GAP_60-V1", "T2"),
    ("G1-GAP_900-V1", "T2"),
    ("G1-HOLD_0-V1", "T2"),
    ("G1-HOLD_2-V1", "T2"),
    ("G1-HOLD_3-V1", "T2"),
    ("G1-MERGE_15-V1", "T2"),
    ("G1-MERGE_5-V1", "T2"),
    ("G1-PRIMARY-V1", "T2"),
    ("G1-REARM_1800-V1", "T2"),
    ("G1-REARM_300-V1", "T2"),
    ("G1-RECLAIM_0-V1", "T2"),
    ("G1-RECLAIM_2-V1", "T2"),
    ("G1-RECLAIM_3-V1", "T2"),
    ("G1-SWEEP_10-V1", "T2"),
    ("G1-SWEEP_15-V1", "T2"),
    ("G1-SWEEP_5-V1", "T2"),
    ("G1-TIMING_T1-V1", "T1"),
    ("G1-TIMING_T3-V1", "T3"),
    ("G1-TIMING_T4-V1", "T4"),
)

PeriodId = Literal["P1", "P2", "P3"]
FoldId = Literal["F0", "F1", "F2", "F3"]
EvaluationRole = Literal["VALIDATION", "HOLDOUT"]
MatchLevel = Literal["L0", "L1", "L2", "L3", "L4", "L5"]
HistoricalLabel = Literal["TARGET_FIRST", "STOP_FIRST", "EXPIRED", "AMBIGUOUS"]
FeatureKind = Literal["VOLATILITY", "TRADES_ACTIVITY", "KEY_LEVEL_DISTANCE"]

REGISTERED_TARGET_BPS: tuple[Decimal, ...] = tuple(
    Decimal(value) for value in ("20", "30", "40", "50", "70", "100")
)
REGISTERED_STOP_BPS: tuple[Decimal, ...] = tuple(
    Decimal(value) for value in ("15", "20", "25", "30", "35")
)
COMBINATION_ORDER: tuple[str, ...] = tuple(
    f"target={target:f}|stop={stop:f}"
    for target in REGISTERED_TARGET_BPS
    for stop in REGISTERED_STOP_BPS
)
EXACT_MATCH_FIELDS: tuple[str, ...] = (
    "instrument",
    "direction",
    "setup_id",
    "context_model_id",
    "high_timeframe_trend_state",
    "pre_registered_period",
    "evaluation_fold",
    "parameter_set_id",
    "time_combination_id",
    "label_contract_hash",
    "key_level_distance_quintile",
    "binning_snapshot_hash",
)
RELAXATION_ORDER: tuple[MatchLevel, ...] = ("L0", "L1", "L2", "L3", "L4", "L5")
PROHIBITED_INTERPRETATIONS: tuple[str, ...] = (
    "PNL",
    "RETURN",
    "REAL_RETURN",
    "ROUND_SUCCESS",
    "LIVE_EXECUTION",
    "STAGE2_PRIMARY_PASS",
    "POST_RESULT_RELAXATION",
)


def canonical_hash(payload: object) -> str:
    """Hash canonical JSON using the repository-wide Stage 2 convention."""

    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class RollingFoldContract(StrictEventModel):
    period: PeriodId
    fold: FoldId
    train_start_ns: int = Field(ge=0)
    train_end_ns: int = Field(gt=0)
    evaluation_start_ns: int = Field(gt=0)
    evaluation_end_ns: int = Field(gt=0)
    evaluation_role: EvaluationRole

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.train_start_ns < self.train_end_ns == self.evaluation_start_ns:
            raise ValueError("rolling fold TRAIN must end exactly where evaluation begins")
        if self.evaluation_end_ns <= self.evaluation_start_ns:
            raise ValueError("rolling fold evaluation window must be non-empty")
        if (self.fold == "F3") != (self.evaluation_role == "HOLDOUT"):
            raise ValueError("only F3 is HOLDOUT")
        return self


class S2T15ContractAuthority(StrictEventModel):
    """Append-only contract frozen before any T15 Run ID exists."""

    schema_name: Literal["stage2-s2t15-contract-authority"] = "stage2-s2t15-contract-authority"
    schema_version: Literal["1.0"] = "1.0"
    task_id: Literal["S2-T15"] = "S2-T15"
    task_version: Literal["1.4"] = "1.4"
    manual_version: Literal["V1.3.4"] = "V1.3.4"
    change_request: Literal["CR-2026-026"] = "CR-2026-026"
    decision_record: Literal["ADR-S2-009"] = "ADR-S2-009"
    code_commit: str = Field(pattern=SHA256_PATTERN)
    upstream_binding_hash: str = Field(pattern=SHA256_PATTERN)
    source_s2t11_binding_hash: str = Field(pattern=SHA256_PATTERN)
    stage1_binding_hash: str = Field(pattern=SHA256_PATTERN)
    context_binding_hash: str = Field(pattern=SHA256_PATTERN)
    label_contract_hash: str = Field(pattern=SHA256_PATTERN)
    preregistration_addendum_hash: str = Field(pattern=SHA256_PATTERN)
    setup_id: Literal["KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0"] = "KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0"
    context_model_id: Literal["CAUSAL_EMA20_1H@1.0"] = "CAUSAL_EMA20_1H@1.0"
    feature_formula_ids: tuple[str, str, str] = (
        VOLATILITY_FORMULA_ID,
        ACTIVITY_FORMULA_ID,
        DISTANCE_FORMULA_ID,
    )
    quintile_algorithm_id: Literal["TIE_PRESERVING_NEAREST_CUMULATIVE_V1"] = (
        "TIE_PRESERVING_NEAREST_CUMULATIVE_V1"
    )
    distance_to_key_level_matching_enabled: Literal[True] = True
    backward_feature_purge_seconds: Literal[3600] = 3600
    forward_outcome_embargo_seconds: Literal[600] = 600
    control_grid_version: Literal["CONTROL_GRID_1M_DAILY_OFFSET_V1"] = (
        "CONTROL_GRID_1M_DAILY_OFFSET_V1"
    )
    matching_seed: Literal[20260716] = 20260716
    controls_per_episode: Literal[5] = 5
    exact_match_fields: tuple[str, ...] = EXACT_MATCH_FIELDS
    relaxation_order: tuple[MatchLevel, ...] = RELAXATION_ORDER
    combination_order: tuple[str, ...] = COMBINATION_ORDER
    reference_price_source: Literal["CONTRACT_PRICE_1S_CLOSE"] = "CONTRACT_PRICE_1S_CLOSE"
    path_evidence_level: Literal["H2"] = "H2"
    expected_h2_path_count: Literal[532708] = 532708
    expected_h2_outcome_cell_count: Literal[15981240] = 15981240
    registered_parameter_timing_pairs: tuple[tuple[str, str], ...] = (
        REGISTERED_PARAMETER_TIMING_PAIRS
    )
    historical_evidence_only: Literal[True] = True
    prohibited_interpretations: tuple[str, ...] = PROHIBITED_INTERPRETATIONS
    authority_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"authority_hash"}))

    @model_validator(mode="after")
    def validate_frozen_contract(self) -> Self:
        if self.exact_match_fields != EXACT_MATCH_FIELDS:
            raise ValueError("S2-T15 exact-match fields changed")
        if self.relaxation_order != RELAXATION_ORDER:
            raise ValueError("S2-T15 L0-L5 relaxation order changed")
        if self.combination_order != COMBINATION_ORDER:
            raise ValueError("S2-T15 30-cell combination order changed")
        if self.registered_parameter_timing_pairs != REGISTERED_PARAMETER_TIMING_PAIRS:
            raise ValueError("S2-T15 registered parameter/timing universe changed")
        if self.authority_hash != "0" * 64 and self.authority_hash != self.computed_hash():
            raise ValueError("S2-T15 Authority hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "authority_hash": "0" * 64})
        return provisional.model_copy(update={"authority_hash": provisional.computed_hash()})


class FrozenQuintileBoundaries(StrictEventModel):
    schema_name: Literal["stage2-s2t15-frozen-quintile-boundaries"] = (
        "stage2-s2t15-frozen-quintile-boundaries"
    )
    schema_version: Literal["1.0"] = "1.0"
    instrument: Instrument
    pre_registered_period: PeriodId
    fold: FoldId
    parameter_set_id: str | None = None
    feature_kind: FeatureKind
    feature_formula_id: str = Field(min_length=1)
    algorithm_id: Literal["TIE_PRESERVING_NEAREST_CUMULATIVE_V1"] = (
        "TIE_PRESERVING_NEAREST_CUMULATIVE_V1"
    )
    source_train_split: str = Field(min_length=1)
    source_anchor_count: int = Field(ge=5)
    valid_feature_count: int = Field(ge=5)
    distinct_value_count: int = Field(ge=5)
    cut_points: tuple[Decimal, Decimal, Decimal, Decimal]
    bin_counts: tuple[int, int, int, int, int]
    feature_source_hash: str = Field(pattern=SHA256_PATTERN)
    split_contract_hash: str = Field(pattern=SHA256_PATTERN)
    boundary_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"boundary_hash"}))

    def assign(self, value: Decimal) -> int:
        return 1 + sum(value >= point for point in self.cut_points)

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        if self.feature_kind == "KEY_LEVEL_DISTANCE" and not self.parameter_set_id:
            raise ValueError("distance boundaries require parameter_set_id isolation")
        if self.feature_kind != "KEY_LEVEL_DISTANCE" and self.parameter_set_id is not None:
            raise ValueError("market-state boundaries may not split by parameter_set_id")
        if self.source_anchor_count < self.valid_feature_count:
            raise ValueError("valid feature count exceeds source TRAIN anchors")
        if sum(self.bin_counts) != self.valid_feature_count or any(
            count <= 0 for count in self.bin_counts
        ):
            raise ValueError("five non-empty bins must account for every valid TRAIN feature")
        if any(
            right <= left for left, right in zip(self.cut_points, self.cut_points[1:], strict=False)
        ):
            raise ValueError("quintile cut points must be strictly increasing")
        if self.boundary_hash != "0" * 64 and self.boundary_hash != self.computed_hash():
            raise ValueError("quintile boundary hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "boundary_hash": "0" * 64})
        return provisional.model_copy(update={"boundary_hash": provisional.computed_hash()})


class ControlAnchor(StrictEventModel):
    instrument: Instrument
    candidate_timestamp_ns: int = Field(ge=0)
    control_grid_version: Literal["CONTROL_GRID_1M_DAILY_OFFSET_V1"] = (
        "CONTROL_GRID_1M_DAILY_OFFSET_V1"
    )
    stage1_data_run_id: str = Field(min_length=1)
    t10_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    control_anchor_id: str = Field(pattern=SHA256_PATTERN)

    def computed_id(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"control_anchor_id"}))

    @model_validator(mode="after")
    def validate_id(self) -> Self:
        if self.control_anchor_id != "0" * 64 and self.control_anchor_id != self.computed_id():
            raise ValueError("control_anchor_id payload conflict")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "control_anchor_id": "0" * 64})
        return provisional.model_copy(update={"control_anchor_id": provisional.computed_id()})


class V14ControlCandidate(StrictEventModel):
    control_anchor_id: str = Field(pattern=SHA256_PATTERN)
    instrument: Instrument
    candidate_timestamp_ns: int = Field(ge=0)
    direction: Direction = "LONG"
    setup_id: Literal["KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0"] = "KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0"
    context_model_id: Literal["CAUSAL_EMA20_1H@1.0"] = "CAUSAL_EMA20_1H@1.0"
    high_timeframe_trend_state: str = Field(min_length=1)
    pre_registered_period: PeriodId
    evaluation_fold: FoldId
    parameter_set_id: str = Field(min_length=1)
    time_combination_id: Literal["T1", "T2", "T3", "T4"]
    label_contract_hash: str = Field(pattern=SHA256_PATTERN)
    control_entry_price: Decimal = Field(gt=0)
    entry_price_source_hash: str = Field(pattern=SHA256_PATTERN)
    outcome_contract_hash: str = Field(pattern=SHA256_PATTERN)
    volatility_quintile: int = Field(ge=1, le=5)
    activity_quintile: int = Field(ge=1, le=5)
    key_level_distance_quintile: int = Field(ge=1, le=5)
    utc_four_hour_bucket: int = Field(ge=0, le=5)
    utc_calendar_quarter: int = Field(ge=1, le=4)
    utc_calendar_year: int = Field(ge=2020, le=2026)
    binning_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    information_span_start_ns: int = Field(ge=0)
    information_span_end_ns: int = Field(gt=0)
    is_registered_same_family_event: bool = False
    control_candidate_id: str = Field(pattern=SHA256_PATTERN)

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": "S2T15_CONTROL_CANDIDATE_V1",
            "control_anchor_id": self.control_anchor_id,
            "instrument": self.instrument,
            "candidate_timestamp_ns": self.candidate_timestamp_ns,
            "direction": self.direction,
            "setup_id": self.setup_id,
            "context_model_id": self.context_model_id,
            "high_timeframe_trend_state": self.high_timeframe_trend_state,
            "pre_registered_period": self.pre_registered_period,
            "evaluation_fold": self.evaluation_fold,
            "parameter_set_id": self.parameter_set_id,
            "time_combination_id": self.time_combination_id,
            "label_contract_hash": self.label_contract_hash,
            "volatility_quintile": self.volatility_quintile,
            "activity_quintile": self.activity_quintile,
            "key_level_distance_quintile": self.key_level_distance_quintile,
            "binning_snapshot_hash": self.binning_snapshot_hash,
        }

    def computed_id(self) -> str:
        return canonical_hash(self.identity_payload())

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        expected_start = self.candidate_timestamp_ns - BACKWARD_PURGE_SECONDS * 1_000_000_000
        expected_end = self.candidate_timestamp_ns + FORWARD_EMBARGO_SECONDS * 1_000_000_000
        if (self.information_span_start_ns, self.information_span_end_ns) != (
            expected_start,
            expected_end,
        ):
            raise ValueError("control information span must be exactly [-3600s,+600s)")
        if (
            self.control_candidate_id != "0" * 64
            and self.control_candidate_id != self.computed_id()
        ):
            raise ValueError("control_candidate_id payload conflict")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "control_candidate_id": "0" * 64})
        return provisional.model_copy(update={"control_candidate_id": provisional.computed_id()})


class V14PrimaryEpisode(StrictEventModel):
    market_episode_id: str = Field(pattern=SHA256_PATTERN)
    source_h2_path_hash: str = Field(pattern=SHA256_PATTERN)
    instrument: Instrument
    anchor_ns: int = Field(ge=0)
    direction: Direction = "LONG"
    setup_id: Literal["KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0"] = "KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0"
    context_model_id: Literal["CAUSAL_EMA20_1H@1.0"] = "CAUSAL_EMA20_1H@1.0"
    high_timeframe_trend_state: str = Field(min_length=1)
    pre_registered_period: PeriodId
    evaluation_fold: FoldId
    parameter_set_id: str = Field(min_length=1)
    time_combination_id: Literal["T1", "T2", "T3", "T4"]
    label_contract_hash: str = Field(pattern=SHA256_PATTERN)
    volatility_quintile: int = Field(ge=1, le=5)
    activity_quintile: int = Field(ge=1, le=5)
    key_level_distance_quintile: int = Field(ge=1, le=5)
    utc_four_hour_bucket: int = Field(ge=0, le=5)
    utc_calendar_quarter: int = Field(ge=1, le=4)
    utc_calendar_year: int = Field(ge=2020, le=2026)
    binning_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    information_span_start_ns: int = Field(ge=0)
    information_span_end_ns: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_episode(self) -> Self:
        expected_start = self.anchor_ns - BACKWARD_PURGE_SECONDS * 1_000_000_000
        expected_end = self.anchor_ns + FORWARD_EMBARGO_SECONDS * 1_000_000_000
        if (self.information_span_start_ns, self.information_span_end_ns) != (
            expected_start,
            expected_end,
        ):
            raise ValueError("episode information span must be exactly [-3600s,+600s)")
        return self


class OutcomeCell(StrictEventModel):
    combination_id: str = Field(min_length=1)
    label: HistoricalLabel
    label_reason: str = Field(min_length=1)
    strict_target_first: Literal[0, 1]

    @model_validator(mode="after")
    def validate_strict(self) -> Self:
        if self.strict_target_first != int(self.label == "TARGET_FIRST"):
            raise ValueError("strict outcome must treat AMBIGUOUS as failure")
        if self.label_reason == "NO_OBSERVATIONS" and self.label != "AMBIGUOUS":
            raise ValueError("complete zero-Trade H2 path must be AMBIGUOUS")
        return self


class ControlOutcomeMatrix(StrictEventModel):
    control_candidate_id: str = Field(pattern=SHA256_PATTERN)
    time_combination_id: Literal["T1", "T2", "T3", "T4"]
    reference_price_source: Literal["CONTRACT_PRICE_1S_CLOSE"] = "CONTRACT_PRICE_1S_CLOSE"
    path_evidence_level: Literal["H2"] = "H2"
    reference_price: Decimal = Field(gt=0)
    combination_order: tuple[str, ...] = COMBINATION_ORDER
    outcomes: tuple[OutcomeCell, ...]
    source_path_hash: str = Field(pattern=SHA256_PATTERN)
    control_outcome_matrix_id: str = Field(pattern=SHA256_PATTERN)

    def computed_id(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"control_outcome_matrix_id"}))

    @model_validator(mode="after")
    def validate_matrix(self) -> Self:
        if self.combination_order != COMBINATION_ORDER or len(self.outcomes) != 30:
            raise ValueError("control outcome matrix must contain the frozen 30 combinations")
        if tuple(cell.combination_id for cell in self.outcomes) != self.combination_order:
            raise ValueError("control outcomes disagree with frozen combination order")
        if (
            self.control_outcome_matrix_id != "0" * 64
            and self.control_outcome_matrix_id != self.computed_id()
        ):
            raise ValueError("control_outcome_matrix_id mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "control_outcome_matrix_id": "0" * 64})
        return provisional.model_copy(
            update={"control_outcome_matrix_id": provisional.computed_id()}
        )


class ConditionalBaselineMatchMatrix(StrictEventModel):
    schema_name: Literal["stage2-s2t15-conditional-baseline-match-matrix"] = (
        "stage2-s2t15-conditional-baseline-match-matrix"
    )
    task_version: Literal["1.4"] = "1.4"
    market_episode_id: str = Field(pattern=SHA256_PATTERN)
    source_h2_path_hash: str = Field(pattern=SHA256_PATTERN)
    parameter_set_id: str = Field(min_length=1)
    time_combination_id: Literal["T1", "T2", "T3", "T4"]
    status: Literal["MATCHED", "UNMATCHED"]
    match_level: MatchLevel
    control_candidate_ids: tuple[str, ...]
    event_outcomes: tuple[OutcomeCell, ...]
    control_outcome_matrix_ids: tuple[str, ...]
    historical_evidence_only: Literal[True] = True
    prohibited_interpretations: tuple[str, ...] = PROHIBITED_INTERPRETATIONS
    output_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"output_hash"}))

    @model_validator(mode="after")
    def validate_match_matrix(self) -> Self:
        if (
            len(self.event_outcomes) != 30
            or tuple(cell.combination_id for cell in self.event_outcomes) != COMBINATION_ORDER
        ):
            raise ValueError("event matrix must contain the frozen 30 combinations")
        if self.status == "MATCHED":
            if self.match_level == "L5":
                raise ValueError("MATCHED matrix cannot use L5")
            if len(self.control_candidate_ids) != 5 or len(set(self.control_candidate_ids)) != 5:
                raise ValueError("MATCHED matrix requires five unique outcome-blind controls")
            if len(self.control_outcome_matrix_ids) != 5:
                raise ValueError("MATCHED matrix requires five control outcome matrices")
        elif (
            self.match_level != "L5"
            or self.control_candidate_ids
            or self.control_outcome_matrix_ids
        ):
            raise ValueError("UNMATCHED matrix must be empty L5")
        if self.output_hash != "0" * 64 and self.output_hash != self.computed_hash():
            raise ValueError("conditional match matrix output hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "output_hash": "0" * 64})
        return provisional.model_copy(update={"output_hash": provisional.computed_hash()})
