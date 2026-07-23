"""Fail-closed manifests for explicitly bounded special research points."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from era100x.foundation.rules import RuleRegistry


class ExemptionKind(StrEnum):
    RULE = "RULE"
    CONSTRAINT = "CONSTRAINT"


EXEMPTABLE_RESEARCH_RULES: Final[frozenset[str]] = frozenset(
    {
        "EVENT-CONSUME-MARKET-EPISODE",
        "RESEARCH-LOCKED-REPLAY-ONCE",
        "STRATEGY-V1-PRICE-ONLY-HISTORICAL",
        "RESEARCH-H3-CONDITIONAL-ROUND-PROB",
    }
)
NON_WAIVABLE_RULES: Final[frozenset[str]] = frozenset(
    {
        "DATA-HISTORICAL-NO-FAKE-EXECUTION",
        "EXEC-EXIT-COORDINATOR-ONLY",
        "PNL-NO-DOUBLE-SLIPPAGE",
        "RISK-LIQUIDATION-BUFFER",
        "RISK-RESIZING-FULL-REVALIDATION",
        "ROUND-ONE-NONZERO-FILL",
        "ROUND-SUCCESS-FLAT-EQUITY",
        "CLOSE-THREE-STAGE",
    }
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_identifier(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned or any(token in cleaned.upper() for token in ("*", "?", "ALL", "ANY")):
        raise ValueError(f"{field} must be one exact identifier without wildcard semantics")
    return cleaned


@dataclass(frozen=True)
class DeclaredResearchExemption:
    kind: ExemptionKind
    identifier: str
    source_hash: str
    scope: str
    reason: str
    risk: str
    replacement_control: str
    approval_reference: str
    expiry: str

    def validated(self) -> DeclaredResearchExemption:
        _safe_identifier(self.identifier, "exemption identifier")
        invalid_hash = len(self.source_hash) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.source_hash
        )
        if invalid_hash:
            raise ValueError("exemption source_hash must be lowercase SHA-256")
        for field, value in (
            ("scope", self.scope),
            ("reason", self.reason),
            ("risk", self.risk),
            ("replacement_control", self.replacement_control),
            ("approval_reference", self.approval_reference),
            ("expiry", self.expiry),
        ):
            if not value.strip():
                raise ValueError(f"exemption {field} must be non-empty")
        return self

    def to_payload(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "identifier": self.identifier,
            "source_hash": self.source_hash,
            "scope": self.scope,
            "reason": self.reason,
            "risk": self.risk,
            "replacement_control": self.replacement_control,
            "approval_reference": self.approval_reference,
            "expiry": self.expiry,
        }


@dataclass(frozen=True)
class SpecialResearchPointManifest:
    point_id: str
    registry_hash: str
    all_rule_ids: tuple[str, ...]
    exemptions: tuple[DeclaredResearchExemption, ...]
    effective_rule_ids: tuple[str, ...]
    evidence_class: str = "EXPLORATORY_NONCOMPLIANT"
    formal_stage_evidence: bool = False
    eligible_for_authority: bool = False
    eligible_for_task_pass: bool = False
    eligible_for_stage_gate: bool = False
    live_or_testnet_authorized: bool = False
    manifest_hash: str = ""

    def body(self) -> dict[str, object]:
        return {
            "schema_name": "stage2-special-research-point-v1",
            "point_id": self.point_id,
            "registry_hash": self.registry_hash,
            "all_rule_ids": list(self.all_rule_ids),
            "exemptions": [item.to_payload() for item in self.exemptions],
            "effective_rule_ids": list(self.effective_rule_ids),
            "evidence_class": self.evidence_class,
            "formal_stage_evidence": self.formal_stage_evidence,
            "eligible_for_authority": self.eligible_for_authority,
            "eligible_for_task_pass": self.eligible_for_task_pass,
            "eligible_for_stage_gate": self.eligible_for_stage_gate,
            "live_or_testnet_authorized": self.live_or_testnet_authorized,
        }

    def to_payload(self) -> dict[str, object]:
        return {**self.body(), "manifest_hash": self.manifest_hash}

    def assert_formal_consumer_rejected(self) -> None:
        if self.evidence_class == "EXPLORATORY_NONCOMPLIANT":
            raise ValueError("formal pipeline rejects EXPLORATORY_NONCOMPLIANT evidence")


def build_special_research_manifest(
    *,
    point_id: str,
    registry_path: Path,
    exemptions: tuple[DeclaredResearchExemption, ...],
) -> SpecialResearchPointManifest:
    safe_point_id = _safe_identifier(point_id, "point_id")
    if registry_path.is_symlink() or not registry_path.is_file():
        raise ValueError("rule registry path is missing or unsafe")
    registry = RuleRegistry.load(registry_path)
    all_ids = tuple(sorted(rule.rule_id for rule in registry.rules))
    by_id = {rule.rule_id: rule for rule in registry.rules}
    seen: set[tuple[ExemptionKind, str]] = set()
    exempt_rule_ids: set[str] = set()
    validated: list[DeclaredResearchExemption] = []
    for raw in exemptions:
        item = raw.validated()
        key = (item.kind, item.identifier)
        if key in seen:
            raise ValueError(f"duplicate declared exemption: {item.identifier}")
        seen.add(key)
        if item.kind is ExemptionKind.RULE:
            if item.identifier not in by_id:
                raise ValueError(f"unknown exempted rule_id: {item.identifier}")
            if item.identifier in NON_WAIVABLE_RULES:
                raise ValueError(f"non-waivable rule_id: {item.identifier}")
            rule = by_id[item.identifier]
            if rule.owner != "research" or item.identifier not in EXEMPTABLE_RESEARCH_RULES:
                raise ValueError(
                    f"rule is not an approved research-owner exemption: {item.identifier}"
                )
            source_hash = canonical_hash(rule.model_dump(mode="json"))
            if source_hash != item.source_hash:
                raise ValueError(f"exemption source hash drift: {item.identifier}")
            exempt_rule_ids.add(item.identifier)
        validated.append(item)
    manifest = SpecialResearchPointManifest(
        point_id=safe_point_id,
        registry_hash=sha256_file(registry_path),
        all_rule_ids=all_ids,
        exemptions=tuple(validated),
        effective_rule_ids=tuple(rule_id for rule_id in all_ids if rule_id not in exempt_rule_ids),
    )
    return SpecialResearchPointManifest(
        **{**manifest.__dict__, "manifest_hash": canonical_hash(manifest.body())}
    )
