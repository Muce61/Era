from __future__ import annotations

from pathlib import Path

import pytest

from era100x.research.stage_2.lifecycle.governance import load_policy


ROOT = Path(__file__).resolve().parents[4]


def test_repository_plan_v18_policy_binds_passed_source_audit() -> None:
    policy = load_policy(
        ROOT / "configs/governance/stage2_active_policy_v7.json",
        repository_root=ROOT,
    )
    assert policy.payload["stage_plan_version"] == "1.8"
    assert policy.payload["formal_run_authorization"] == (
        "SEPARATE_COMMIT_BOUND_APPROVAL_REQUIRED"
    )
    assert policy.source_audit_hash == (
        "48d7f421d16172322a0628a927865bc69599a35b212b9e0d4ac7085bc9e03319"
    )


def test_policy_rejects_source_audit_hash_drift(tmp_path: Path) -> None:
    source = ROOT / "configs/governance/stage2_active_policy_v7.json"
    payload = source.read_text(encoding="utf-8").replace(
        "48d7f421d16172322a0628a927865bc69599a35b212b9e0d4ac7085bc9e03319",
        "0" * 64,
    )
    path = tmp_path / "policy.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="source audit"):
        load_policy(path, repository_root=ROOT)
