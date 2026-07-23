"""Strict value objects for S2P13-T11 lifecycle research."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast


NANOSECONDS_PER_SECOND = 1_000_000_000
MAX_HORIZON_SECONDS = 7 * 24 * 60 * 60
LANDMARK_SECONDS = (300, 480, 900, 1500, 3600)
SURVIVAL_REPORT_SECONDS = (4 * 3600, 24 * 3600, 72 * 3600, MAX_HORIZON_SECONDS)
PRIMARY_LANDMARK_SECONDS = 480
TICKET_EQUITY = Decimal("10")
RESERVE_EQUITY = Decimal("2")
USABLE_MARGIN = Decimal("8")
MAX_LEVERAGE = Decimal("100")
ACTIVATION_NET_ROE = Decimal("0.20")
PRIMARY_NEAR_ZERO_ROE = Decimal("0.05")
SENSITIVITY_NEAR_ZERO_ROE = (Decimal("0.02"), Decimal("0.10"))
BPS = Decimal("10000")
MONEY_QUANTUM = Decimal("0.000000000000000001")


class SourceCoverage(StrEnum):
    COMPLETE = "COMPLETE"
    DECLARED_GAP = "DECLARED_GAP"
    DATA_END = "DATA_END"
    UNBOUND = "UNBOUND"
    HASH_DRIFT = "HASH_DRIFT"


class ExitReason(StrEnum):
    IMMEDIATE_LANDMARK_EXIT = "IMMEDIATE_LANDMARK_EXIT"
    TICKET_DOUBLE_TARGET = "TICKET_DOUBLE_TARGET"
    STOP = "STOP"
    PROTECTION = "PROTECTION"
    STRUCTURE = "STRUCTURE"
    SCENARIO_LIQUIDATION_BOUNDARY_CROSSED = "SCENARIO_LIQUIDATION_BOUNDARY_CROSSED"


class CensorReason(StrEnum):
    MAX_HORIZON_CENSORED = "MAX_HORIZON_CENSORED"
    SOURCE_GAP_CENSORED = "SOURCE_GAP_CENSORED"
    DATA_END_CENSORED = "DATA_END_CENSORED"


class FundingTrack(StrEnum):
    PRIMARY_HISTORICAL_ACTUAL = "PRIMARY_HISTORICAL_ACTUAL"
    STRESS_ADVERSE_1_5X = "STRESS_ADVERSE_1_5X"
    STRESS_ADVERSE_2X = "STRESS_ADVERSE_2X"
    STRESS_NO_FUNDING_CREDIT = "STRESS_NO_FUNDING_CREDIT"


def _convert(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _convert(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_convert(item) for item in value]
    return value


def canonical_hash(value: object) -> str:
    payload = _convert(
        asdict(cast(Any, value)) if hasattr(value, "__dataclass_fields__") else value
    )
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CostScenario:
    scenario_id: str
    round_trip_fee_bps: Decimal
    total_slippage_bps: Decimal
    latency_ms: int
    initial_fill_ratio: Decimal
    cost_multiplier: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id is required")
        if self.round_trip_fee_bps < 0 or self.total_slippage_bps < 0:
            raise ValueError("cost basis points cannot be negative")
        if self.latency_ms < 0:
            raise ValueError("latency cannot be negative")
        if self.initial_fill_ratio not in (Decimal("1"), Decimal("0.8"), Decimal("0.5")):
            raise ValueError("initial fill ratio must be a preregistered scenario")
        if self.cost_multiplier not in (Decimal("1"), Decimal("1.5"), Decimal("2")):
            raise ValueError("cost multiplier must be 1x, 1.5x or 2x")

    @property
    def total_cost_bps(self) -> Decimal:
        return (self.round_trip_fee_bps + self.total_slippage_bps) * self.cost_multiplier


@dataclass(frozen=True, order=True)
class LifecycleObservation:
    ts_event_ns: int
    venue_trade_id: int
    canonical_trade_id: str
    price: Decimal
    cumulative_funding: Decimal = Decimal("0")
    protection_exit: bool = False
    structure_exit: bool = False

    def __post_init__(self) -> None:
        if self.ts_event_ns < 0 or self.venue_trade_id < 0:
            raise ValueError("observation identity cannot be negative")
        if not self.canonical_trade_id or self.price <= 0:
            raise ValueError("observation requires identity and positive price")


@dataclass(frozen=True)
class LifecyclePolicyResult:
    policy_id: str
    terminal_state: str
    exit_reason: ExitReason | None
    censor_reason: CensorReason | None
    decision_ts_ns: int | None
    scenario_net_pnl: Decimal | None
    terminal_ticket_equity: Decimal | None
    ticket_doubled: bool | None
    reserve_breached: bool | None
    remaining_proxy_quantity: Decimal
    evidence_level: str = "H3_HISTORICAL_CONDITIONAL_LIFECYCLE"
    historical_execution_claim: bool = False


@dataclass(frozen=True)
class LifecyclePairResult:
    market_episode_id: str
    instrument: str
    eligible_at_primary_landmark: bool
    activated_before_landmark: bool
    landmark_net_exitable_pnl: Decimal | None
    immediate_exit: LifecyclePolicyResult
    continue_holding: LifecyclePolicyResult
    source_coverage: SourceCoverage
    funding_track: FundingTrack
    price_proxy_source: str
    historical_mark_price_claim: bool
    output_hash: str

    def computed_hash(self) -> str:
        payload = {key: value for key, value in asdict(self).items() if key != "output_hash"}
        return canonical_hash(payload)
