from __future__ import annotations

from types import SimpleNamespace

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    write_canonical_json_exclusive,
)
from era100x.research.stage_2.acceptance.final_acceptance.cli import (
    _sealed_run_authorization,
)


def test_sealed_run_authorization_survives_later_repository_commit(tmp_path) -> None:
    authority = {
        "schema_name": "s2p17-t20-authority",
        "approval_hash": "1" * 64,
        "format_smoke_hash": "2" * 64,
        "code_commit": "3" * 40,
    }
    authority["authority_hash"] = canonical_content_hash(authority)
    evidence_root = tmp_path / "evidence"
    write_canonical_json_exclusive(
        evidence_root / "authorities" / f"authority-{authority['authority_hash']}.json",
        authority,
    )
    policy = SimpleNamespace(evidence_root=evidence_root)
    contract = {
        "authority_hash": authority["authority_hash"],
        "code_commit": authority["code_commit"],
    }

    projected = _sealed_run_authorization(policy, contract)

    assert projected["approval_hash"] == authority["approval_hash"]
    assert projected["format_smoke_hash"] == authority["format_smoke_hash"]
