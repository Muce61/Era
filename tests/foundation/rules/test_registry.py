from pathlib import Path

import pytest
from pydantic import ValidationError

from era100x.foundation.rules import RuleMetadata, RuleRegistry


REGISTRY = Path("configs/rules/v1.3.4.yaml")


def test_registry_contains_32_unique_formal_rules() -> None:
    registry = RuleRegistry.load(REGISTRY)
    assert len(registry.rules) == 32
    assert len({rule.rule_id for rule in registry.rules}) == 32
    assert all(rule.live_override is False for rule in registry.rules)


def test_required_v134_rules_exist() -> None:
    registry = RuleRegistry.load(REGISTRY)
    assert registry.by_id("EXIT-BOOTSTRAP-MODE").effective_version == "V1.3.4"
    assert registry.by_id("INVARIANT-ID-GLOBAL-UNIQUE").status.value == "FROZEN"


def test_frozen_live_override_rejected() -> None:
    with pytest.raises(ValidationError, match="live_override"):
        RuleMetadata.model_validate(
            {
                "rule_id": "TEST-RULE",
                "status": "FROZEN",
                "source": "test",
                "owner": "test",
                "tests": ["T-1"],
                "effective_version": "V1.3.4",
                "live_override": True,
                "inputs": ["test"],
                "check_timing": ["test"],
                "failure_action": "BLOCKED",
            }
        )


def test_deprecated_rule_is_not_implemented() -> None:
    registry = RuleRegistry.load(REGISTRY)
    assert not [rule for rule in registry.rules if rule.status.value == "DEPRECATED"]
