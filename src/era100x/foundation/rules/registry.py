from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuleStatus(StrEnum):
    FROZEN = "FROZEN"
    BASELINE = "BASELINE"
    RESEARCH = "RESEARCH"
    DEPRECATED = "DEPRECATED"
    BLOCKED_BY_FORWARD_VALIDATION = "BLOCKED_BY_FORWARD_VALIDATION"


class RuleMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]+$")
    status: RuleStatus
    source: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    tests: list[str] = Field(min_length=1)
    effective_version: str = Field(min_length=1)
    live_override: bool
    inputs: list[str] = Field(min_length=1)
    check_timing: list[str] = Field(min_length=1)
    failure_action: str = Field(min_length=1)

    @model_validator(mode="after")
    def frozen_rules_cannot_allow_live_override(self) -> RuleMetadata:
        if self.status is RuleStatus.FROZEN and self.live_override:
            raise ValueError("FROZEN rules require live_override=false")
        return self


class RuleRegistry:
    def __init__(self, rules: tuple[RuleMetadata, ...]) -> None:
        ids = [rule.rule_id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule_id")
        self.rules = rules

    @classmethod
    def load(cls, path: Path) -> RuleRegistry:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(tuple(RuleMetadata.model_validate(item) for item in raw["rules"]))

    def by_id(self, rule_id: str) -> RuleMetadata:
        return next(rule for rule in self.rules if rule.rule_id == rule_id)
