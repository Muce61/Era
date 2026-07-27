from __future__ import annotations

from types import SimpleNamespace

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    write_canonical_json_exclusive,
)
from era100x.research.stage_2.acceptance.final_acceptance import governance


def test_validate_approval_treats_format_smoke_hash_as_self_hash(tmp_path, monkeypatch) -> None:
    commit = "1" * 40
    policy_hash = "2" * 64
    preregistration_hash = "3" * 64
    t11_hash = "4" * 64
    t16_hash = "5" * 64
    t17_hash = "6" * 64
    t18_hash = "7" * 64
    t19_hash = "8" * 64
    sources = SimpleNamespace(
        upstreams=SimpleNamespace(
            t11=SimpleNamespace(receipt_hash=t11_hash),
            upstreams=SimpleNamespace(
                t16=SimpleNamespace(verify_hash=t16_hash),
                t17=SimpleNamespace(verify_hash=t17_hash),
            ),
            t18=SimpleNamespace(verify_hash=t18_hash),
        ),
        t19=SimpleNamespace(verify_hash=t19_hash),
    )
    policy = SimpleNamespace(
        operations_root=tmp_path / "operations",
        policy_hash=policy_hash,
        preregistration_hash=preregistration_hash,
    )
    smoke = {
        "schema_name": "s2p17-t20-format-smoke",
        "status": "PASS",
        "code_commit": commit,
        "policy_hash": policy_hash,
        "source_t19_verify_hash": t19_hash,
    }
    smoke_hash = canonical_content_hash(smoke)
    smoke["format_smoke_hash"] = smoke_hash
    write_canonical_json_exclusive(
        policy.operations_root / "format-smokes" / f"{smoke_hash}.json",
        smoke,
    )
    approval = {
        "schema_name": governance.APPROVAL_SCHEMA,
        "code_commit": commit,
        "policy_hash": policy_hash,
        "preregistration_hash": preregistration_hash,
        "format_smoke_hash": smoke_hash,
        "source_t11_receipt_hash": t11_hash,
        "source_t16_verify_hash": t16_hash,
        "source_t17_verify_hash": t17_hash,
        "source_t18_verify_hash": t18_hash,
        "source_t19_verify_hash": t19_hash,
        "stage3_locked": True,
    }
    approval["approval_hash"] = canonical_content_hash(approval)
    approval_path = tmp_path / "approval.json"
    write_canonical_json_exclusive(approval_path, approval)
    monkeypatch.setattr(governance, "audit_sources", lambda *_args, **_kwargs: sources)
    monkeypatch.setattr(governance, "repository_commit", lambda _root: commit)

    validated = governance.validate_approval(
        approval_path,
        policy=policy,
        repository_root=tmp_path,
    )

    assert validated["approval_hash"] == approval["approval_hash"]
