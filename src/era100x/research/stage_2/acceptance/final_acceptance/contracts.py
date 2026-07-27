"""Strict machine contracts for S2P17-T20."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.acceptance.canonical_json import canonical_content_hash
from era100x.research.stage_2.contracts.models import StrictEventModel

SHA256_PATTERN = r"^[0-9a-f]{64}$"
GIT_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
RESEARCH_DECISION = "STAGE2_NO_GO_CURRENT_EVIDENCE"
LIFECYCLE_DECISION = "INCONCLUSIVE_SOURCE_GAP_CENSORING"


class S2P17T20Authority(StrictEventModel):
    schema_name: Literal["s2p17-t20-authority"] = "s2p17-t20-authority"
    schema_version: Literal["1.0"] = "1.0"
    task_id: Literal["S2P17-T20"] = "S2P17-T20"
    stage_plan_version: Literal["1.7"] = "1.7"
    code_commit: str = Field(pattern=GIT_COMMIT_PATTERN)
    policy_hash: str = Field(pattern=SHA256_PATTERN)
    approval_hash: str = Field(pattern=SHA256_PATTERN)
    preregistration_hash: str = Field(pattern=SHA256_PATTERN)
    format_smoke_hash: str = Field(pattern=SHA256_PATTERN)
    source_t11_receipt_hash: str = Field(pattern=SHA256_PATTERN)
    source_t16_verify_hash: str = Field(pattern=SHA256_PATTERN)
    source_t17_verify_hash: str = Field(pattern=SHA256_PATTERN)
    source_t18_verify_hash: str = Field(pattern=SHA256_PATTERN)
    source_t19_verify_hash: str = Field(pattern=SHA256_PATTERN)
    canonical_json_schema: Literal["CANONICAL_JSON_CONTENT_V1"]
    research_decision: Literal["STAGE2_NO_GO_CURRENT_EVIDENCE"]
    lifecycle_decision: Literal["INCONCLUSIVE_SOURCE_GAP_CENSORING"]
    historical_evidence_only: Literal[True] = True
    stage3_locked: Literal[True] = True
    authority_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_content_hash(self.model_dump(mode="python", exclude={"authority_hash"}))

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.authority_hash != "0" * 64 and self.authority_hash != self.computed_hash():
            raise ValueError("T20 Authority Hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "authority_hash": "0" * 64})
        return provisional.model_copy(update={"authority_hash": provisional.computed_hash()})
