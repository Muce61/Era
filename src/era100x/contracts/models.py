"""Strict V1.3.4 Appendix C-E data-contract skeletons; no behavior."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvidenceFields(Contract):
    reference_price: Decimal
    reference_ask: Decimal | None
    spread_bps: Decimal | None
    receive_latency_ms: Decimal | None
    actual_fill_price: Decimal | None
    scenario_slippage_bps: Decimal | None
    data_quality: str
    evidence_level: str
    cost_scenario_id: str | None


class CanonicalKeyLevel(Contract):
    key_level_id: str
    instrument_id: str
    source_type: str
    source_timeframe: str
    level_price: Decimal
    formed_at_ns: int
    valid_from_ns: int
    expires_at_ns: int
    normalization_rule: str
    priority_rank: int
    member_key_level_ids: list[str]
    config_hash: str


class MarketEpisode(Contract):
    market_episode_id: str
    canonical_key_level_id: str
    sweep_start_ns: int
    sweep_end_ns: int | None
    max_sweep_depth_bps: Decimal
    reclaim_ts_ns: int | None
    hold_completed_ts_ns: int | None
    episode_status: str
    consumed: bool
    consumed_by_intent_id: str | None
    rearm_eligible_at_ns: int | None


class EntryIntent(Contract):
    intent_id: str
    intent_revision: int
    market_episode_id: str
    instrument_id: str
    side: Literal["BUY"]
    signal_ts_event_ns: int
    expires_at_ns: int
    reference_price: Decimal
    reference_price_type: str
    reference_ask: Decimal | None
    live_quote_snapshot_id: str | None
    expected_cost_scenario_id: str | None
    invalidation_price: Decimal
    max_entry_price: Decimal | None
    requested_quantity: Decimal
    sizing_snapshot_id: str
    effective_config_snapshot_hash: str
    max_target_bps_allowed_for_event: Decimal
    data_evidence_level: str
    gate_snapshot: dict[str, Any]
    config_hash: str
    strategy_version: str


class PositionState(Contract):
    position_instance_id: str
    position_revision: int
    active_exit_epoch: int | None
    exit_owner: str | None
    reconcile_phase: str
    position_qty_zero_confirmed_at_ns: int | None
    cleanup_complete: bool
    updated_at_ns: int


class PositionSnapshot(Contract):
    position_instance_id: str
    position_revision: int
    instrument_id: str
    venue_position_qty: Decimal
    avg_entry_price: Decimal
    accumulated_entry_fee: Decimal
    protected_state: str
    liquidation_price: Decimal | None
    snapshot_id: str
    source_ts_ns: int
    received_monotonic_ns: int


class AlgoProtectionState(Contract):
    client_algo_id: str
    algo_id: int | None
    instrument_id: str
    position_side: Literal["BOTH"]
    side: Literal["SELL"]
    algo_status: str
    working_type: str
    trigger_price: Decimal
    close_position: bool
    quantity: Decimal | None
    price_protect: bool
    created_at_ns: int
    last_update_ns: int
    linked_position_instance_id: str
    protection_checked_revision: int
    source: Literal["QUERY", "ALGO_UPDATE"]


class ExitIntent(Contract):
    exit_intent_id: str
    position_instance_id: str
    expected_position_revision: int
    requested_exit_owner: str
    requested_exit_reason: str
    requested_at_ns: int
    status: str


class ExitEpoch(Contract):
    exit_epoch: int
    position_instance_id: str
    created_against_position_revision: int
    exit_epoch_revision: int
    bootstrap_mode: str
    exit_owner: str
    previous_exit_owner: str | None
    owner_transition_reason: str | None
    initial_venue_qty: Decimal
    current_remaining_qty: Decimal
    realized_exit_qty: Decimal
    realized_exit_value: Decimal
    realized_exit_fee: Decimal
    status: str
    created_at_ns: int
    updated_at_ns: int


class ExitOrderLeg(Contract):
    exit_order_leg_id: str
    position_instance_id: str
    exit_epoch: int
    leg_sequence: int
    leg_type: str
    exit_owner: str
    bootstrap_mode: str
    order_origin: str
    requires_local_submission: bool
    client_order_id_source: str
    client_order_id: str | None
    venue_order_id: str | None
    algo_id: int | None
    requested_qty: Decimal | None
    submitted_qty: Decimal
    filled_qty: Decimal
    remaining_qty: Decimal
    order_type: str
    limit_price: Decimal | None
    reduce_only: bool
    status: str
    created_at_ns: int
    submitted_at_ns: int | None
    last_update_ns: int
    terminal_at_ns: int | None
    venue_event_ts_ns: int | None
    venue_transaction_ts_ns: int | None
    received_monotonic_ns: int | None
    replacement_of_leg_id: str | None
    fallback_reason: str | None


class ActiveLocalExitLeg(Contract):
    exit_epoch: int
    exit_order_leg_id: str
    created_at_ns: int


class StateTransition(Contract):
    transition_id: str
    position_instance_id: str | None
    position_revision_before: int | None
    position_revision_after: int | None
    exit_epoch: int | None
    exit_epoch_revision: int | None
    exit_order_leg_id: str | None
    reconcile_phase_before: str | None
    reconcile_phase_after: str | None
    from_state: str
    to_state: str
    reason_code: str
    event_ts_ns: int


class IncidentBundle(Contract):
    incident_id: str
    position_instance_id: str | None
    latest_position_revision: int | None
    active_exit_epoch: int | None
    exit_owner: str | None
    position_snapshots: list[PositionSnapshot]
    exit_epochs: list[ExitEpoch]
    exit_order_legs: list[ExitOrderLeg]
    active_local_exit_leg: ActiveLocalExitLeg | None
    algo_states: list[AlgoProtectionState]
    closure_protocol_state: dict[str, Any] | None
    config_hash: str


class RoundState(Contract):
    round_id: str
    starting_ticket_equity: Decimal
    current_realized_equity: Decimal
    estimated_ticket_equity_if_flat: Decimal | None
    final_realized_ticket_equity: Decimal | None
    entry_intent_count: int
    has_nonzero_fill: bool
    round_status: str
    round_started_at: int
    round_ended_at: int | None
    round_result_reason: str | None


class CircuitBreakerState(Contract):
    breaker_type: str
    effective_from: int
    trading_date: str
    round_id: str | None
    reason_code: str
    config_hash: str
    manual_release_required: bool
    released_by: str | None
    released_at: int | None


CONTRACT_TYPES = (
    EvidenceFields,
    CanonicalKeyLevel,
    MarketEpisode,
    EntryIntent,
    PositionState,
    PositionSnapshot,
    AlgoProtectionState,
    ExitIntent,
    ExitEpoch,
    ExitOrderLeg,
    ActiveLocalExitLeg,
    StateTransition,
    IncidentBundle,
    RoundState,
    CircuitBreakerState,
)
