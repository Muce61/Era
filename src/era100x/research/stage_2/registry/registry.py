from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ResearchSetupDefinition:
    setup_id: str
    setup_version: str
    required_data_capability: Literal["H1", "H2"]
    evidence_status: Literal["APPROVED", "TEST_ONLY"]


@dataclass(frozen=True, slots=True)
class ContextModelDefinition:
    context_model_id: str
    context_version: str
    required_data_capability: Literal["H1", "H2"]
    evidence_status: Literal["APPROVED", "TEST_ONLY"]


class ResearchRegistry:
    def __init__(self) -> None:
        self._setups: dict[tuple[str, str], ResearchSetupDefinition] = {}
        self._contexts: dict[tuple[str, str], ContextModelDefinition] = {}

    def register_setup(self, setup: ResearchSetupDefinition) -> None:
        key = (setup.setup_id, setup.setup_version)
        if key in self._setups:
            raise ValueError("setup already registered")
        self._setups[key] = setup

    def register_context(self, context: ContextModelDefinition) -> None:
        key = (context.context_model_id, context.context_version)
        if key in self._contexts:
            raise ValueError("context already registered")
        self._contexts[key] = context

    def require_setup(
        self, setup_id: str, version: str, capability: str
    ) -> ResearchSetupDefinition:
        try:
            setup = self._setups[(setup_id, version)]
        except KeyError as exc:
            raise ValueError("unknown setup") from exc
        rank = {"H1": 1, "H2": 2}
        if capability not in rank or rank[capability] < rank[setup.required_data_capability]:
            raise ValueError("insufficient data capability")
        if setup.evidence_status != "APPROVED":
            raise ValueError("setup is not approved")
        return setup


def approved_registry() -> ResearchRegistry:
    registry = ResearchRegistry()
    registry.register_setup(
        ResearchSetupDefinition("KEY_LOW_SWEEP_RECLAIM_HOLD_V1", "1.0", "H1", "APPROVED")
    )
    registry.register_context(ContextModelDefinition("CAUSAL_EMA20_1H", "1.0", "H1", "APPROVED"))
    return registry
