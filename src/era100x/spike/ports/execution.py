"""Offline protocols only. This module contains no network or exchange client."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class CapabilityStatus(StrEnum):
    OBSERVED_OFFLINE = "OBSERVED_OFFLINE"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class CapabilityObservation:
    capability: str
    scenario: str
    status: CapabilityStatus
    evidence: str


@dataclass(frozen=True, slots=True)
class SpikeManifest:
    network_disabled: bool
    credential_fields_present: bool
    observations: tuple[CapabilityObservation, ...]

    def __post_init__(self) -> None:
        if not self.network_disabled:
            raise ValueError("Stage 0 spike must keep network disabled")
        if self.credential_fields_present:
            raise ValueError("Stage 0 spike cannot contain credentials")


class BinanceExecutionPort(Protocol):
    """Future capability boundary; Stage 0 permits only offline implementations."""

    def observe(self, scenario: str) -> CapabilityObservation: ...


class OfflineExecutionMock:
    ALLOWED_SCENARIOS = frozenset(
        {"IOC", "ALGO_CREATE", "ALGO_UPDATE", "UNKNOWN", "RESTART", "EXIT_RACE"}
    )

    def observe(self, scenario: str) -> CapabilityObservation:
        if scenario not in self.ALLOWED_SCENARIOS:
            raise ValueError("scenario is outside the approved offline capability matrix")
        return CapabilityObservation(
            capability="offline_protocol_expression",
            scenario=scenario,
            status=CapabilityStatus.OBSERVED_OFFLINE,
            evidence="deterministic_mock",
        )


def deny_network_access(*_args: object, **_kwargs: object) -> None:
    raise PermissionError("Stage 0 execution spike network access is disabled")
