"""Deterministic paired lifecycle evaluation without real execution claims."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from .models import (
    ACTIVATION_NET_ROE,
    BPS,
    MAX_HORIZON_SECONDS,
    MONEY_QUANTUM,
    PRIMARY_LANDMARK_SECONDS,
    PRIMARY_NEAR_ZERO_ROE,
    RESERVE_EQUITY,
    TICKET_EQUITY,
    USABLE_MARGIN,
    CensorReason,
    CostScenario,
    ExitReason,
    FundingTrack,
    LifecycleObservation,
    LifecyclePairResult,
    LifecyclePolicyResult,
    SourceCoverage,
)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def funding_for_track(actual_signed_funding: Decimal, track: FundingTrack) -> Decimal:
    """Apply a preregistered adverse transform without inventing Primary funding."""

    if track is FundingTrack.PRIMARY_HISTORICAL_ACTUAL:
        return actual_signed_funding
    if track is FundingTrack.STRESS_NO_FUNDING_CREDIT:
        return max(actual_signed_funding, Decimal(0))
    if actual_signed_funding <= 0:
        return actual_signed_funding
    multiplier = Decimal("1.5") if track is FundingTrack.STRESS_ADVERSE_1_5X else Decimal("2")
    return actual_signed_funding * multiplier


def _net_pnl(
    *,
    entry_price: Decimal,
    current_price: Decimal,
    notional: Decimal,
    funding: Decimal,
    scenario: CostScenario,
) -> Decimal:
    gross = notional * (current_price / entry_price - Decimal(1))
    cost = notional * scenario.total_cost_bps / BPS
    return _quantize(gross - cost - funding)


def _close(
    *,
    policy_id: str,
    reason: ExitReason,
    ts_ns: int,
    net_pnl: Decimal,
    scenario: CostScenario,
) -> LifecyclePolicyResult:
    quantity = Decimal(1)
    first_fill = quantity * scenario.initial_fill_ratio
    remaining = quantity - first_fill
    fallback_fill = remaining
    remaining -= fallback_fill
    terminal_equity = _quantize(TICKET_EQUITY + net_pnl)
    return LifecyclePolicyResult(
        policy_id=policy_id,
        terminal_state="THEORETICAL_FULLY_FLAT",
        exit_reason=reason,
        censor_reason=None,
        decision_ts_ns=ts_ns,
        scenario_net_pnl=net_pnl,
        terminal_ticket_equity=terminal_equity,
        ticket_doubled=terminal_equity >= TICKET_EQUITY * 2,
        reserve_breached=terminal_equity < RESERVE_EQUITY,
        remaining_proxy_quantity=remaining,
    )


def _censored(*, policy_id: str, reason: CensorReason, ts_ns: int | None) -> LifecyclePolicyResult:
    return LifecyclePolicyResult(
        policy_id=policy_id,
        terminal_state="RIGHT_CENSORED",
        exit_reason=None,
        censor_reason=reason,
        decision_ts_ns=ts_ns,
        scenario_net_pnl=None,
        terminal_ticket_equity=None,
        ticket_doubled=None,
        reserve_breached=None,
        remaining_proxy_quantity=Decimal(1),
    )


def _source_censor_reason(coverage: SourceCoverage) -> CensorReason | None:
    if coverage is SourceCoverage.DECLARED_GAP:
        return CensorReason.SOURCE_GAP_CENSORED
    if coverage is SourceCoverage.DATA_END:
        return CensorReason.DATA_END_CENSORED
    return None


def evaluate_lifecycle_pair(
    *,
    market_episode_id: str,
    instrument: str,
    entry_ts_ns: int,
    entry_price: Decimal,
    observations: tuple[LifecycleObservation, ...],
    source_coverage: SourceCoverage,
    scenario: CostScenario,
    funding_track: FundingTrack,
    historical_funding_source_bound: bool,
    stop_bps: Decimal,
) -> LifecyclePairResult:
    """Evaluate immediate-exit and continuation policies on the same observed path."""

    if not market_episode_id or instrument not in {"BTCUSDT", "ETHUSDT"}:
        raise ValueError("lifecycle requires one supported instrument and episode identity")
    if entry_price <= 0 or entry_ts_ns < 0:
        raise ValueError("entry reference must be positive and timestamped")
    if stop_bps <= 0:
        raise ValueError("lifecycle stop must be an explicit positive value")
    if not historical_funding_source_bound:
        raise ValueError("historical funding source must be bound before any funding track")
    if source_coverage in {SourceCoverage.UNBOUND, SourceCoverage.HASH_DRIFT}:
        raise ValueError(f"run-level source integrity failure: {source_coverage.value}")
    keys = tuple(
        (item.ts_event_ns, item.venue_trade_id, item.canonical_trade_id) for item in observations
    )
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("lifecycle observations must use unique frozen H2 stable order")
    incomplete_reason = _source_censor_reason(source_coverage)
    if incomplete_reason is not None:
        incomplete = LifecyclePairResult(
            market_episode_id=market_episode_id,
            instrument=instrument,
            eligible_at_primary_landmark=False,
            activated_before_landmark=False,
            landmark_net_exitable_pnl=None,
            immediate_exit=_censored(
                policy_id="EXIT_AT_PRIMARY_LANDMARK",
                reason=incomplete_reason,
                ts_ns=None,
            ),
            continue_holding=_censored(
                policy_id="CONTINUE_TO_THEORETICAL_CLOSE",
                reason=incomplete_reason,
                ts_ns=None,
            ),
            source_coverage=source_coverage,
            funding_track=funding_track,
            price_proxy_source="CONTRACT_PRICE_H3_PROXY",
            historical_mark_price_claim=False,
            output_hash="",
        )
        return replace(incomplete, output_hash=incomplete.computed_hash())
    max_end_ns = entry_ts_ns + MAX_HORIZON_SECONDS * 1_000_000_000
    landmark_ns = entry_ts_ns + PRIMARY_LANDMARK_SECONDS * 1_000_000_000
    notional = USABLE_MARGIN * Decimal("100")
    stop_price = entry_price * (Decimal(1) - stop_bps / BPS)
    before_landmark = tuple(item for item in observations if item.ts_event_ns <= landmark_ns)
    with localcontext() as context:
        context.prec = 50
        net_values = tuple(
            _net_pnl(
                entry_price=entry_price,
                current_price=item.price,
                notional=notional,
                funding=funding_for_track(item.cumulative_funding, funding_track),
                scenario=scenario,
            )
            for item in before_landmark
        )
        activated = bool(net_values) and max(net_values) >= USABLE_MARGIN * ACTIVATION_NET_ROE
        landmark_observation = before_landmark[-1] if before_landmark else None
        landmark_net = (
            None
            if landmark_observation is None
            else _net_pnl(
                entry_price=entry_price,
                current_price=landmark_observation.price,
                notional=notional,
                funding=funding_for_track(landmark_observation.cumulative_funding, funding_track),
                scenario=scenario,
            )
        )
        eligible = (
            landmark_net is not None
            and not activated
            and abs(landmark_net) <= USABLE_MARGIN * PRIMARY_NEAR_ZERO_ROE
        )
        if eligible and landmark_observation is not None and landmark_net is not None:
            immediate = _close(
                policy_id="EXIT_AT_PRIMARY_LANDMARK",
                reason=ExitReason.IMMEDIATE_LANDMARK_EXIT,
                ts_ns=landmark_ns,
                net_pnl=landmark_net,
                scenario=scenario,
            )
        else:
            immediate = _censored(
                policy_id="EXIT_AT_PRIMARY_LANDMARK",
                reason=CensorReason.DATA_END_CENSORED,
                ts_ns=landmark_ns,
            )

        continued: LifecyclePolicyResult | None = None
        for item in observations:
            if item.ts_event_ns < landmark_ns or item.ts_event_ns >= max_end_ns:
                continue
            net = _net_pnl(
                entry_price=entry_price,
                current_price=item.price,
                notional=notional,
                funding=funding_for_track(item.cumulative_funding, funding_track),
                scenario=scenario,
            )
            reason: ExitReason | None = None
            if net <= -USABLE_MARGIN:
                reason = ExitReason.SCENARIO_LIQUIDATION_BOUNDARY_CROSSED
            elif item.price <= stop_price:
                reason = ExitReason.STOP
            elif item.protection_exit:
                reason = ExitReason.PROTECTION
            elif item.structure_exit:
                reason = ExitReason.STRUCTURE
            elif net >= TICKET_EQUITY:
                reason = ExitReason.TICKET_DOUBLE_TARGET
            if reason is not None:
                continued = _close(
                    policy_id="CONTINUE_TO_THEORETICAL_CLOSE",
                    reason=reason,
                    ts_ns=item.ts_event_ns,
                    net_pnl=net,
                    scenario=scenario,
                )
                break
        if continued is None:
            source_reason = _source_censor_reason(source_coverage)
            continued = _censored(
                policy_id="CONTINUE_TO_THEORETICAL_CLOSE",
                reason=source_reason or CensorReason.MAX_HORIZON_CENSORED,
                ts_ns=max_end_ns,
            )
    result = LifecyclePairResult(
        market_episode_id=market_episode_id,
        instrument=instrument,
        eligible_at_primary_landmark=eligible,
        activated_before_landmark=activated,
        landmark_net_exitable_pnl=landmark_net,
        immediate_exit=immediate,
        continue_holding=continued,
        source_coverage=source_coverage,
        funding_track=funding_track,
        price_proxy_source="CONTRACT_PRICE_H3_PROXY",
        historical_mark_price_claim=False,
        output_hash="",
    )
    return replace(result, output_hash=result.computed_hash())
