from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceLineage:
    data_run_id: str
    dataset_logical_hash: str
    config_hash: str
    code_version: str
    parameter_set_id: str
