"""Strict machine contracts for S2P16-T19."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.contracts.models import StrictEventModel

from .formatting import canonical_hash

SHA256_PATTERN = r"^[0-9a-f]{64}$"
GIT_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
RESEARCH_STATUS = "EVIDENCE_SYNTHESIS_COMPLETE_FINAL_HUMAN_GATE_PENDING"
GateStatus = Literal["PASS", "FAIL", "INCONCLUSIVE", "NOT_APPLICABLE"]


class GateResult(StrictEventModel):
    schema_name: Literal["s2p16-t19-gate-result"] = "s2p16-t19-gate-result"
    gate_id: str = Field(min_length=1)
    instrument: Literal["BTCUSDT", "ETHUSDT", "GLOBAL"]
    evidence_family: Literal["H2_PRIMARY", "H3_LIFECYCLE", "ETH_CLASSIFICATION", "OVERALL"]
    status: GateStatus
    observed_value: str | None
    threshold: str | None
    reason_code: str = Field(min_length=1)
    source_hash: str = Field(pattern=SHA256_PATTERN)
    result_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"result_hash"}))

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.result_hash != "0" * 64 and self.result_hash != self.computed_hash():
            raise ValueError("T19 gate-result Hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "result_hash": "0" * 64})
        return provisional.model_copy(update={"result_hash": provisional.computed_hash()})


class S2P16T19Authority(StrictEventModel):
    schema_name: Literal["s2p16-t19-authority"] = "s2p16-t19-authority"
    schema_version: Literal["1.0"] = "1.0"
    task_id: Literal["S2P16-T19"] = "S2P16-T19"
    stage_plan_version: Literal["1.6"] = "1.6"
    code_commit: str = Field(pattern=GIT_COMMIT_PATTERN)
    policy_hash: str = Field(pattern=SHA256_PATTERN)
    approval_hash: str = Field(pattern=SHA256_PATTERN)
    preregistration_hash: str = Field(pattern=SHA256_PATTERN)
    format_smoke_hash: str = Field(pattern=SHA256_PATTERN)
    source_t11_receipt_hash: str = Field(pattern=SHA256_PATTERN)
    source_t16_verify_hash: str = Field(pattern=SHA256_PATTERN)
    source_t17_verify_hash: str = Field(pattern=SHA256_PATTERN)
    source_t18_verify_hash: str = Field(pattern=SHA256_PATTERN)
    historical_evidence_only: Literal[True] = True
    stage3_locked: Literal[True] = True
    authority_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="python", exclude={"authority_hash"}))

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.authority_hash != "0" * 64 and self.authority_hash != self.computed_hash():
            raise ValueError("T19 Authority Hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, object]) -> Self:
        provisional = cls.model_validate({**payload, "authority_hash": "0" * 64})
        return provisional.model_copy(update={"authority_hash": provisional.computed_hash()})
