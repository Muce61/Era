"""Namespaced Stage 2 task identities introduced by Plan v1.3."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Stage2TaskIdentity:
    stage_plan_version: str
    task_id: str

    def __post_init__(self) -> None:
        if self.stage_plan_version == "1.3":
            if not self.task_id.startswith("S2P13-T"):
                raise ValueError("Plan v1.3 task IDs must use the S2P13 namespace")
        elif self.stage_plan_version == "1.2":
            if not self.task_id.startswith("S2-T"):
                raise ValueError("Plan v1.2 task IDs must retain the legacy S2-T namespace")
        else:
            raise ValueError("unsupported Stage 2 plan version")

    @property
    def key(self) -> str:
        return f"stage_2_plan_v{self.stage_plan_version}:{self.task_id}"


PLAN_V13_TASKS = tuple(
    Stage2TaskIdentity("1.3", f"S2P13-T{number:02d}") for number in range(11, 22)
)
PLAN_V13_EXECUTION_LIMIT = Stage2TaskIdentity("1.3", "S2P13-T16")
