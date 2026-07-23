from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from era100x.foundation.rules import RuleRegistry
from era100x.research.stage_2.manifests.special_research import (
    DeclaredResearchExemption,
    ExemptionKind,
    build_special_research_manifest,
    canonical_hash,
)


REGISTRY = Path("configs/rules/v1.3.5.yaml")


def _rule_exemption(rule_id: str) -> DeclaredResearchExemption:
    rule = RuleRegistry.load(REGISTRY).by_id(rule_id)
    return DeclaredResearchExemption(
        kind=ExemptionKind.RULE,
        identifier=rule_id,
        source_hash=canonical_hash(rule.model_dump(mode="json")),
        scope="SRP-S2-TEST isolated fixture",
        reason="test one bounded research question",
        risk="selection bias",
        replacement_control="append-only exploratory output",
        approval_reference="TEST-APPROVAL",
        expiry="fixture completion",
    )


def test_empty_exemptions_keep_every_rule_effective() -> None:
    manifest = build_special_research_manifest(
        point_id="SRP-S2-TEST", registry_path=REGISTRY, exemptions=()
    )
    assert manifest.effective_rule_ids == manifest.all_rule_ids
    assert manifest.evidence_class == "EXPLORATORY_NONCOMPLIANT"
    with pytest.raises(ValueError, match="formal pipeline rejects"):
        manifest.assert_formal_consumer_rejected()


def test_one_declared_rule_is_the_only_removed_rule() -> None:
    exemption = _rule_exemption("RESEARCH-LOCKED-REPLAY-ONCE")
    manifest = build_special_research_manifest(
        point_id="SRP-S2-TEST", registry_path=REGISTRY, exemptions=(exemption,)
    )
    assert exemption.identifier not in manifest.effective_rule_ids
    assert len(manifest.all_rule_ids) == len(manifest.effective_rule_ids) + 1


@pytest.mark.parametrize(
    ("item", "message"),
    [
        (replace(_rule_exemption("RESEARCH-LOCKED-REPLAY-ONCE"), identifier="*"), "wildcard"),
        (
            replace(_rule_exemption("RESEARCH-LOCKED-REPLAY-ONCE"), identifier="NOT-A-RULE"),
            "unknown",
        ),
        (
            replace(_rule_exemption("RESEARCH-LOCKED-REPLAY-ONCE"), source_hash="0" * 64),
            "hash drift",
        ),
    ],
)
def test_invalid_exemption_fails_closed(item: DeclaredResearchExemption, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_special_research_manifest(
            point_id="SRP-S2-TEST", registry_path=REGISTRY, exemptions=(item,)
        )


def test_duplicate_and_nonwaivable_rules_fail_closed() -> None:
    item = _rule_exemption("RESEARCH-LOCKED-REPLAY-ONCE")
    with pytest.raises(ValueError, match="duplicate"):
        build_special_research_manifest(
            point_id="SRP-S2-TEST", registry_path=REGISTRY, exemptions=(item, item)
        )

    data_rule = RuleRegistry.load(REGISTRY).by_id("DATA-HISTORICAL-NO-FAKE-EXECUTION")
    nonwaivable = replace(
        item,
        identifier=data_rule.rule_id,
        source_hash=canonical_hash(data_rule.model_dump(mode="json")),
    )
    with pytest.raises(ValueError, match="non-waivable"):
        build_special_research_manifest(
            point_id="SRP-S2-TEST", registry_path=REGISTRY, exemptions=(nonwaivable,)
        )


def test_manifest_hash_is_deterministic() -> None:
    item = _rule_exemption("RESEARCH-LOCKED-REPLAY-ONCE")
    first = build_special_research_manifest(
        point_id="SRP-S2-TEST", registry_path=REGISTRY, exemptions=(item,)
    )
    second = build_special_research_manifest(
        point_id="SRP-S2-TEST", registry_path=REGISTRY, exemptions=(item,)
    )
    assert first.manifest_hash == second.manifest_hash
