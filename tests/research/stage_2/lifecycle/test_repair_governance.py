from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.lifecycle.solo_governance import load_policy


ROOT = Path(__file__).resolve().parents[4]


def test_repository_plan_v110_policy_binds_solo_runtime_contract() -> None:
    policy = load_policy(
        ROOT / "configs/governance/stage2_active_policy_v9.json",
        repository_root=ROOT,
    )
    assert policy.payload["stage_plan_version"] == "1.10"
    assert policy.payload["formal_run_authorization"] == (
        "ONE_COMMIT_INPUTS_AND_ADOPTION_HASH_BOUND_HUMAN_APPROVAL"
    )
    assert policy.payload["operator_commands"] == ["status", "prepare", "run", "resume"]
    assert policy.payload["historical_plan_v19_status"] == "SUPERSEDED_UNEXECUTED"


def test_policy_rejects_solo_runtime_identity_drift(tmp_path: Path) -> None:
    source = ROOT / "configs/governance/stage2_active_policy_v9.json"
    payload = json.loads(source.read_bytes())
    payload["historical_plan_v19_status"] = "ACTIVE"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="policy contract drift"):
        load_policy(path, repository_root=ROOT)
