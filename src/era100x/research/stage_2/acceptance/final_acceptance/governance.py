"""Fail-closed policy, source bindings and approval gates for T20."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    read_canonical_json,
    sha256_file,
    verify_canonical_json_file,
    write_canonical_json_exclusive,
)
from era100x.research.stage_2.acceptance.evidence_gate.governance import (
    SourceBindings as T19Upstreams,
    audit_sources as audit_t19_upstreams,
    load_policy as load_t19_policy,
)
from era100x.research.stage_2.statistics.bootstrap.formatting import read_json

from .contracts import LIFECYCLE_DECISION, RESEARCH_DECISION, S2P17T20Authority

EXPECTED_T11_RECEIPT = "2414dacb4e9483aae6260b2aa2d5460d96670a2bad1cd754332caddba6af0760"
EXPECTED_T16_VERIFY = "b866905c18fd1cb1f3bbed1f74e5301c56a78e891b81ab3eea61bcff37ed2b86"
EXPECTED_T17_VERIFY = "bb6f7186f068a1dcd040f369c980bdcae4bb5fef9964c2b5ee61e2d30b6c2f1c"
EXPECTED_T18_VERIFY = "dc9ebcab3e4af3ff75e03e76ee9fa4f147e27cb2910a80b2b25874f8d5e514d1"
EXPECTED_T19_VERIFY = "a272924b834d7f687020ae3ec3bb30e7b639d1fb367b810de40807746dcdabef"
APPROVAL_SCHEMA = "s2p17-t20-formal-approval-v1"


def repository_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def repository_clean(root: Path) -> bool:
    return not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ).strip()


def _self_hash(payload: dict[str, Any], field: str) -> bool:
    claimed = payload.get(field)
    return isinstance(claimed, str) and claimed == canonical_content_hash(
        {key: value for key, value in payload.items() if key != field}
    )


@dataclass(frozen=True, slots=True)
class FinalAcceptancePolicy:
    path: Path
    payload: dict[str, Any]
    policy_hash: str
    preregistration_hash: str
    evidence_root: Path
    source_t19_run_root: Path
    contract_hashes: dict[str, str]

    @property
    def operations_root(self) -> Path:
        return self.evidence_root / "operations"


def load_policy(path: Path, *, repository_root: Path) -> FinalAcceptancePolicy:
    payload = read_json(path)
    required = {
        "schema_name",
        "schema_version",
        "stage",
        "stage_plan_version",
        "execution_limit",
        "stage3_locked",
        "code_commit_mode",
        "contract_paths",
        "preregistration_path",
        "evidence_root",
        "task_dag",
        "source_t19_run_root",
        "required_gates",
    }
    if set(payload) != required:
        raise ValueError("Plan v1.7 policy fields drift")
    if (
        payload["schema_name"] != "stage2-active-policy-v6"
        or payload["schema_version"] != "6.0"
        or payload["stage"] != "S2"
        or payload["stage_plan_version"] != "1.7"
        or payload["execution_limit"] != "S2P17-T20"
        or payload["stage3_locked"] is not True
        or payload["code_commit_mode"] != "CURRENT_CLEAN_HEAD"
        or payload["task_dag"]
        != {
            "S2P17-T20": [
                "S2P13-T11",
                "S2P13-T16",
                "S2P14-T17",
                "S2P15-T18",
                "S2P16-T19",
            ]
        }
    ):
        raise ValueError("Plan v1.7 policy contract drift")
    hashes: dict[str, str] = {}
    for raw in cast(list[object], payload["contract_paths"]):
        relative = Path(str(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe T20 contract path")
        hashes[str(relative)] = sha256_file(repository_root / relative)
    preregistration = repository_root / str(payload["preregistration_path"])
    evidence_root = Path(str(payload["evidence_root"]))
    source_t19 = Path(str(payload["source_t19_run_root"]))
    if any(not root.is_absolute() or root.is_symlink() for root in (evidence_root, source_t19)):
        raise ValueError("unsafe T20 evidence root")
    preregistration_hash = sha256_file(preregistration)
    return FinalAcceptancePolicy(
        path=path,
        payload=payload,
        policy_hash=canonical_content_hash(
            {
                "policy": payload,
                "contract_hashes": hashes,
                "preregistration_hash": preregistration_hash,
            }
        ),
        preregistration_hash=preregistration_hash,
        evidence_root=evidence_root,
        source_t19_run_root=source_t19,
        contract_hashes=hashes,
    )


@dataclass(frozen=True, slots=True)
class T19Binding:
    run_root: Path
    authority_hash: str
    manifest_hash: str
    catalog_hash: str
    verify_hash: str
    published_root: Path
    gate_path: Path
    landscape_path: Path
    frequency_path: Path
    cards_path: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class SourceBindings:
    upstreams: T19Upstreams
    t19: T19Binding


def audit_sources(
    policy: FinalAcceptancePolicy,
    *,
    repository_root: Path,
    full_hash_scan: bool,
) -> SourceBindings:
    t19_policy = load_t19_policy(
        repository_root / "configs/governance/stage2_active_policy_v5.json",
        repository_root=repository_root,
    )
    if t19_policy.evidence_root != policy.source_t19_run_root.parents[1]:
        raise ValueError("T20 and T19 evidence roots disagree")
    upstreams = audit_t19_upstreams(
        t19_policy,
        repository_root=repository_root,
        full_hash_scan=full_hash_scan,
    )
    if (
        upstreams.t11.receipt_hash != EXPECTED_T11_RECEIPT
        or upstreams.upstreams.t16.verify_hash != EXPECTED_T16_VERIFY
        or upstreams.upstreams.t17.verify_hash != EXPECTED_T17_VERIFY
        or upstreams.t18.verify_hash != EXPECTED_T18_VERIFY
    ):
        raise ValueError("T20 transitive source binding drift")

    verify_path = policy.source_t19_run_root / "verify" / f"{EXPECTED_T19_VERIFY}.json"
    verify = read_canonical_json(verify_path)
    published = policy.source_t19_run_root / "published"
    manifest = read_canonical_json(published / "manifest.json")
    catalog = read_canonical_json(published / "catalog.json")
    authority_hash = str(verify.get("authority_hash"))
    authority_path = (
        policy.source_t19_run_root.parents[1] / "authorities" / f"authority-{authority_hash}.json"
    )
    authority = read_canonical_json(authority_path)
    if (
        verify.get("status") != "PASS"
        or verify.get("verify_hash") != EXPECTED_T19_VERIFY
        or not _self_hash(verify, "verify_hash")
        or not _self_hash(manifest, "manifest_hash")
        or not _self_hash(catalog, "catalog_hash")
        or not _self_hash(authority, "authority_hash")
        or manifest.get("manifest_hash") != verify.get("manifest_hash")
        or catalog.get("catalog_hash") != verify.get("catalog_hash")
        or manifest.get("research_status") != "EVIDENCE_SYNTHESIS_COMPLETE_FINAL_HUMAN_GATE_PENDING"
        or manifest.get("stage3_locked") is not True
    ):
        raise ValueError("formal T19 evidence binding drift")
    if full_hash_scan:
        for entry in cast(list[dict[str, Any]], catalog["files"]):
            relative = Path(str(entry["relative_path"]))
            if relative.name.startswith("._") or ".." in relative.parts:
                raise ValueError("unsafe T19 Catalog path")
            if sha256_file(published / relative) != entry["sha256"]:
                raise ValueError("formal T19 published Hash drift")
    cards = read_canonical_json(published / "evidence-cards.json")
    lifecycle = cast(dict[str, dict[str, Any]], cards.get("lifecycle"))
    if (
        cards.get("overall_recommendation") != "NO_GO_CURRENT_EVIDENCE"
        or cards.get("btc_primary") != "PRIMARY_FAILED"
        or any(
            lifecycle[instrument].get("decision") != LIFECYCLE_DECISION
            for instrument in ("BTCUSDT", "ETHUSDT")
        )
    ):
        raise ValueError("formal T19 research decision drift")
    return SourceBindings(
        upstreams=upstreams,
        t19=T19Binding(
            run_root=policy.source_t19_run_root,
            authority_hash=authority_hash,
            manifest_hash=str(manifest["manifest_hash"]),
            catalog_hash=str(catalog["catalog_hash"]),
            verify_hash=EXPECTED_T19_VERIFY,
            published_root=published,
            gate_path=published / "gate-results.parquet",
            landscape_path=published / "parameter-landscape.parquet",
            frequency_path=published / "frequency-waiting.parquet",
            cards_path=published / "evidence-cards.json",
            report_path=published / "evidence-report.md",
        ),
    )


def record_approval(
    *,
    policy: FinalAcceptancePolicy,
    repository_root: Path,
    approved_by: str,
    approval_source: str,
    format_smoke_hash: str,
    approved_at: str | None,
) -> Path:
    if not repository_clean(repository_root):
        raise ValueError("formal T20 approval requires a clean repository")
    sources = audit_sources(policy, repository_root=repository_root, full_hash_scan=False)
    smoke = read_canonical_json(
        policy.operations_root / "format-smokes" / f"{format_smoke_hash}.json"
    )
    commit = repository_commit(repository_root)
    if (
        smoke.get("format_smoke_hash") != format_smoke_hash
        or not _self_hash(smoke, "format_smoke_hash")
        or smoke.get("status") != "PASS"
        or smoke.get("code_commit") != commit
        or smoke.get("policy_hash") != policy.policy_hash
        or smoke.get("source_t19_verify_hash") != sources.t19.verify_hash
    ):
        raise ValueError("format smoke does not authorize this T20 commit")
    payload: dict[str, object] = {
        "schema_name": APPROVAL_SCHEMA,
        "schema_version": "1.0",
        "task_id": "S2P17-T20",
        "code_commit": commit,
        "policy_hash": policy.policy_hash,
        "preregistration_hash": policy.preregistration_hash,
        "format_smoke_hash": format_smoke_hash,
        "source_t11_receipt_hash": sources.upstreams.t11.receipt_hash,
        "source_t16_verify_hash": sources.upstreams.upstreams.t16.verify_hash,
        "source_t17_verify_hash": sources.upstreams.upstreams.t17.verify_hash,
        "source_t18_verify_hash": sources.upstreams.t18.verify_hash,
        "source_t19_verify_hash": sources.t19.verify_hash,
        "approved_by": approved_by,
        "approved_at": approved_at or datetime.now(UTC).isoformat(),
        "approval_source": approval_source,
        "stage3_locked": True,
    }
    payload["approval_hash"] = canonical_content_hash(payload)
    path = policy.operations_root / "approvals" / f"approval-{payload['approval_hash']}.json"
    write_canonical_json_exclusive(path, payload)
    return path


def validate_approval(
    path: Path,
    *,
    policy: FinalAcceptancePolicy,
    repository_root: Path,
) -> dict[str, Any]:
    approval = read_canonical_json(path)
    sources = audit_sources(policy, repository_root=repository_root, full_hash_scan=False)
    if (
        approval.get("schema_name") != APPROVAL_SCHEMA
        or not _self_hash(approval, "approval_hash")
        or approval.get("code_commit") != repository_commit(repository_root)
        or approval.get("policy_hash") != policy.policy_hash
        or approval.get("preregistration_hash") != policy.preregistration_hash
        or approval.get("source_t11_receipt_hash") != sources.upstreams.t11.receipt_hash
        or approval.get("source_t16_verify_hash") != sources.upstreams.upstreams.t16.verify_hash
        or approval.get("source_t17_verify_hash") != sources.upstreams.upstreams.t17.verify_hash
        or approval.get("source_t18_verify_hash") != sources.upstreams.t18.verify_hash
        or approval.get("source_t19_verify_hash") != sources.t19.verify_hash
        or approval.get("stage3_locked") is not True
    ):
        raise ValueError("T20 approval binding drift")
    smoke_hash = str(approval["format_smoke_hash"])
    smoke_path = policy.operations_root / "format-smokes" / f"{smoke_hash}.json"
    verify_canonical_json_file(smoke_path, expected_hash=smoke_hash)
    smoke = read_canonical_json(smoke_path)
    if (
        smoke.get("code_commit") != approval["code_commit"]
        or smoke.get("policy_hash") != policy.policy_hash
        or smoke.get("source_t19_verify_hash") != sources.t19.verify_hash
    ):
        raise ValueError("T20 approval format-smoke binding drift")
    return approval


def freeze_authority(
    *,
    policy: FinalAcceptancePolicy,
    approval: dict[str, Any],
    sources: SourceBindings,
    repository_root: Path,
) -> S2P17T20Authority:
    authority = S2P17T20Authority.seal(
        {
            "code_commit": repository_commit(repository_root),
            "policy_hash": policy.policy_hash,
            "approval_hash": approval["approval_hash"],
            "preregistration_hash": policy.preregistration_hash,
            "format_smoke_hash": approval["format_smoke_hash"],
            "source_t11_receipt_hash": sources.upstreams.t11.receipt_hash,
            "source_t16_verify_hash": sources.upstreams.upstreams.t16.verify_hash,
            "source_t17_verify_hash": sources.upstreams.upstreams.t17.verify_hash,
            "source_t18_verify_hash": sources.upstreams.t18.verify_hash,
            "source_t19_verify_hash": sources.t19.verify_hash,
            "canonical_json_schema": "CANONICAL_JSON_CONTENT_V1",
            "research_decision": RESEARCH_DECISION,
            "lifecycle_decision": LIFECYCLE_DECISION,
            "historical_evidence_only": True,
            "stage3_locked": True,
        }
    )
    path = policy.evidence_root / "authorities" / f"authority-{authority.authority_hash}.json"
    write_canonical_json_exclusive(path, authority.model_dump(mode="python"))
    reread = S2P17T20Authority.model_validate_json(path.read_bytes(), strict=True)
    if reread != authority:
        raise ValueError("T20 Authority strict readback drift")
    return authority
