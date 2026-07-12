from pathlib import Path

import pytest
from pydantic import ValidationError

from era100x.foundation.audit import AppendOnlyAuditStore, AuditRecord, ExperimentManifest


HASH = "a" * 64


def test_manifest_is_deterministic() -> None:
    manifest = ExperimentManifest(
        experiment_id="exp-1",
        git_commit="1234567",
        config_hash=HASH,
        data_hashes={},
        rule_ids=("RULE-ONE",),
        evidence_level="H1",
        created_at_ns=1,
    )
    assert manifest.sha256() == manifest.sha256()


def test_audit_store_is_append_only(tmp_path: Path) -> None:
    record = AuditRecord(
        record_id="r1",
        event_type="TEST",
        rule_id=None,
        config_hash=HASH,
        evidence_level="H1",
        wall_clock_ns=1,
        monotonic_ns=2,
        payload={},
    )
    store = AppendOnlyAuditStore(tmp_path)
    store.append(record)
    with pytest.raises(FileExistsError):
        store.append(record)


def test_unknown_manifest_field_rejected() -> None:
    with pytest.raises(ValidationError):
        ExperimentManifest.model_validate({"experiment_id": "x", "unexpected": True})
