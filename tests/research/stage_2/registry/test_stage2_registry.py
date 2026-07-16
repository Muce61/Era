import pytest

from era100x.research.stage_2.registry.registry import (
    ResearchSetupDefinition,
    approved_registry,
)


def test_approved_setup_and_capability_guard() -> None:
    registry = approved_registry()
    setup = registry.require_setup("KEY_LOW_SWEEP_RECLAIM_HOLD_V1", "1.0", "H1")
    assert setup.evidence_status == "APPROVED"
    with pytest.raises(ValueError, match="unknown setup"):
        registry.require_setup("UNKNOWN", "1.0", "H2")


def test_dummy_setup_registration_does_not_change_registry_code() -> None:
    registry = approved_registry()
    registry.register_setup(ResearchSetupDefinition("DUMMY", "1.0", "H1", "TEST_ONLY"))
    with pytest.raises(ValueError, match="not approved"):
        registry.require_setup("DUMMY", "1.0", "H1")
