"""Causal input assembly and single-position admission for lifecycle research."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal

from .models import (
    MAX_HORIZON_SECONDS,
    NANOSECONDS_PER_SECOND,
    USABLE_MARGIN,
    LifecycleObservation,
    LifecyclePairResult,
    PriceObservationSource,
)


@dataclass(frozen=True, slots=True)
class ContractPricePoint:
    event_ts_ns: int
    available_at_ns: int
    close: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: Decimal | None = None
    source_file_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.event_ts_ns < 0 or self.available_at_ns < 0 or self.close <= 0:
            raise ValueError("invalid Contract Price point")
        if self.available_at_ns > self.event_ts_ns + NANOSECONDS_PER_SECOND:
            raise ValueError("Contract Price is not causally available")
        values = (self.open, self.high, self.low)
        if any(value is not None and value <= 0 for value in values):
            raise ValueError("Contract Price OHLC must be positive")
        if any(value is not None for value in values) and any(value is None for value in values):
            raise ValueError("Contract Price OHLC must be all present or all absent")
        if self.high is not None and self.low is not None and self.open is not None:
            if self.high < max(self.open, self.low, self.close):
                raise ValueError("Contract Price high violates OHLC bounds")
            if self.low > min(self.open, self.high, self.close):
                raise ValueError("Contract Price low violates OHLC bounds")
        if self.source_file_sha256 is not None and len(self.source_file_sha256) != 64:
            raise ValueError("Contract Price source file hash is invalid")
        if self.volume is not None and self.volume < 0:
            raise ValueError("Contract Price volume cannot be negative")


@dataclass(frozen=True, slots=True)
class CanonicalTradePoint:
    ts_event_ns: int
    venue_trade_id: int
    canonical_trade_id: str
    price: Decimal

    def __post_init__(self) -> None:
        if (
            self.ts_event_ns < 0
            or self.venue_trade_id < 0
            or not self.canonical_trade_id
            or self.price <= 0
        ):
            raise ValueError("invalid canonical Trade point")


@dataclass(frozen=True, slots=True)
class FundingSettlement:
    settlement_ts_ns: int
    signed_rate: Decimal

    def __post_init__(self) -> None:
        if self.settlement_ts_ns < 0:
            raise ValueError("invalid funding settlement timestamp")


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    market_episode_id: str
    policy_id: str
    entry_ts_ns: int
    admitted: bool
    reason: str
    occupied_until_ns: int | None


def assemble_lifecycle_observations(
    *,
    entry_price: Decimal,
    contract_prices: tuple[ContractPricePoint, ...],
    trades: tuple[CanonicalTradePoint, ...],
    funding: tuple[FundingSettlement, ...],
) -> tuple[LifecycleObservation, ...]:
    """Merge prices, Trades and actual funding without future leakage."""

    if entry_price <= 0:
        raise ValueError("entry price must be positive")
    contract_prices = tuple(sorted(contract_prices, key=lambda item: item.event_ts_ns))
    trades = tuple(
        sorted(
            trades,
            key=lambda item: (
                item.ts_event_ns,
                item.venue_trade_id,
                item.canonical_trade_id,
            ),
        )
    )
    funding = tuple(sorted(funding, key=lambda item: item.settlement_ts_ns))
    contract_times = tuple(item.event_ts_ns for item in contract_prices)
    if len(set(contract_times)) != len(contract_times):
        raise ValueError("duplicate Contract Price timestamp")
    trade_ids = tuple(
        (item.ts_event_ns, item.venue_trade_id, item.canonical_trade_id) for item in trades
    )
    if len(set(trade_ids)) != len(trade_ids):
        raise ValueError("duplicate canonical Trade identity")
    funding_times = tuple(item.settlement_ts_ns for item in funding)
    if len(set(funding_times)) != len(funding_times):
        raise ValueError("duplicate funding settlement timestamp")

    quantity = USABLE_MARGIN * Decimal("100") / entry_price
    cumulative_by_settlement: list[Decimal] = []
    cumulative = Decimal(0)
    for settlement in funding:
        contract_index = bisect_right(contract_times, settlement.settlement_ts_ns) - 1
        if contract_index < 0:
            raise ValueError("funding settlement has no causal Contract Price")
        valuation_price = contract_prices[contract_index].close
        cumulative += quantity * valuation_price * settlement.signed_rate
        cumulative_by_settlement.append(cumulative)

    def cumulative_at(timestamp_ns: int) -> Decimal:
        index = bisect_right(funding_times, timestamp_ns) - 1
        return Decimal(0) if index < 0 else cumulative_by_settlement[index]

    observations = [
        LifecycleObservation(
            ts_event_ns=point.event_ts_ns,
            available_at_ns=point.available_at_ns,
            price_source=PriceObservationSource.CONTRACT_PRICE_1S,
            venue_trade_id=ordinal,
            canonical_trade_id=f"contract-price-{point.event_ts_ns}",
            price=point.close,
            cumulative_funding=cumulative_at(point.event_ts_ns),
        )
        for ordinal, point in enumerate(contract_prices)
    ]
    observations.extend(
        LifecycleObservation(
            ts_event_ns=trade.ts_event_ns,
            price_source=PriceObservationSource.CANONICAL_TRADE,
            venue_trade_id=trade.venue_trade_id,
            canonical_trade_id=trade.canonical_trade_id,
            price=trade.price,
            cumulative_funding=cumulative_at(trade.ts_event_ns),
        )
        for trade in trades
    )
    return tuple(sorted(observations, key=lambda item: item.stable_order_key))


def replay_single_position_admission(
    results: tuple[LifecyclePairResult, ...],
    *,
    entry_ts_ns_by_episode: dict[str, int],
) -> tuple[AdmissionDecision, ...]:
    """Apply one-position occupancy separately to each paired policy."""

    if set(entry_ts_ns_by_episode) != {item.market_episode_id for item in results}:
        raise ValueError("entry timestamp universe does not match lifecycle results")
    ordered = tuple(
        sorted(
            results,
            key=lambda item: (
                entry_ts_ns_by_episode[item.market_episode_id],
                item.market_episode_id,
            ),
        )
    )
    decisions: list[AdmissionDecision] = []
    for policy_field in ("immediate_exit", "continue_holding"):
        occupied_until_ns: int | None = None
        right_censored = False
        for result in ordered:
            entry_ts_ns = entry_ts_ns_by_episode[result.market_episode_id]
            policy = getattr(result, policy_field)
            if right_censored or (
                occupied_until_ns is not None and entry_ts_ns < occupied_until_ns
            ):
                decisions.append(
                    AdmissionDecision(
                        market_episode_id=result.market_episode_id,
                        policy_id=policy.policy_id,
                        entry_ts_ns=entry_ts_ns,
                        admitted=False,
                        reason="SKIPPED_SINGLE_POSITION_OCCUPIED",
                        occupied_until_ns=occupied_until_ns,
                    )
                )
                continue
            if policy.terminal_state == "RIGHT_CENSORED":
                occupied_until_ns = entry_ts_ns + MAX_HORIZON_SECONDS * NANOSECONDS_PER_SECOND
                right_censored = True
            elif policy.decision_ts_ns is None:
                raise ValueError("flat lifecycle result lacks a decision timestamp")
            else:
                occupied_until_ns = policy.decision_ts_ns
            decisions.append(
                AdmissionDecision(
                    market_episode_id=result.market_episode_id,
                    policy_id=policy.policy_id,
                    entry_ts_ns=entry_ts_ns,
                    admitted=True,
                    reason="ADMITTED",
                    occupied_until_ns=occupied_until_ns,
                )
            )
    return tuple(decisions)
