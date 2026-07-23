import pytest

from era100x.research.stage_2.task_identity import (
    PLAN_V13_EXECUTION_LIMIT,
    PLAN_V13_TASKS,
    Stage2TaskIdentity,
)


def test_legacy_and_v13_identity_never_alias() -> None:
    legacy = Stage2TaskIdentity("1.2", "S2-T11")
    current = Stage2TaskIdentity("1.3", "S2P13-T11")
    assert legacy.key != current.key
    assert len(PLAN_V13_TASKS) == 11
    assert PLAN_V13_EXECUTION_LIMIT.task_id == "S2P13-T16"


@pytest.mark.parametrize(
    ("version", "task_id"),
    [("1.3", "S2-T11"), ("1.2", "S2P13-T11"), ("1.4", "S2P14-T11")],
)
def test_invalid_namespace_fails_closed(version: str, task_id: str) -> None:
    with pytest.raises(ValueError):
        Stage2TaskIdentity(version, task_id)
