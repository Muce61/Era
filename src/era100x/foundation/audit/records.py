from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _FrozenRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


class ExperimentManifest(_FrozenRecord):
    experiment_id: str = Field(min_length=1)
    spec_version: str = "V1.3.4"
    git_commit: str = Field(min_length=7)
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_hashes: dict[str, str]
    rule_ids: tuple[str, ...]
    evidence_level: str
    created_at_ns: int = Field(ge=0)


class AuditRecord(_FrozenRecord):
    record_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    rule_id: str | None
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_level: str
    wall_clock_ns: int = Field(ge=0)
    monotonic_ns: int = Field(ge=0)
    payload: dict[str, Any]


class AppendOnlyAuditStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def append(self, record: AuditRecord) -> Path:
        path = self.directory / f"{record.record_id}.json"
        with path.open("x", encoding="utf-8") as handle:
            handle.write(record.canonical_json() + "\n")
        return path
