from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.baselines.conditional import full_run


def test_governance_binding_includes_approved_seven_day_rehearsal_cr() -> None:
    binding = full_run._governance_binding()

    assert "docs/development/changes/CR-2026-030.md" in binding
    assert len(binding["docs/development/changes/CR-2026-030.md"]) == 64


def test_blocked_upstream_audit_cannot_freeze_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = tmp_path / "blocked-audit.json"
    audit.write_text(
        json.dumps(
            {
                "status": "BLOCKED",
                "reason_code": "S2_T15_UPSTREAM_T10_RECEIPT_DISTRIBUTIONS_MISSING",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(full_run, "repository_is_clean", lambda: True)

    with pytest.raises(ValueError, match="S2_T15_UPSTREAM_T10_RECEIPT_DISTRIBUTIONS_MISSING"):
        full_run.freeze_authority(audit_path=audit)


def test_symlinked_audit_is_rejected_before_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "audit.json"
    target.write_text('{"status":"PASS"}', encoding="utf-8")
    symlink = tmp_path / "audit-link.json"
    symlink.symlink_to(target)
    monkeypatch.setattr(full_run, "repository_is_clean", lambda: True)

    with pytest.raises(ValueError, match="unsafe, symlinked or missing evidence"):
        full_run.freeze_authority(audit_path=symlink)
