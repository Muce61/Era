"""Fail-closed policy and immutable source bindings for T19."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from era100x.research.stage_2.statistics.bootstrap.governance import (
    SourceBindings as T18Upstreams,
    audit_sources as audit_t18_upstreams,
    load_policy as load_t18_policy,
)

from .contracts import S2P16T19Authority
from .formatting import canonical_hash, read_json, sha256_file, write_exclusive

EXPECTED_T11_RECEIPT = "2414dacb4e9483aae6260b2aa2d5460d96670a2bad1cd754332caddba6af0760"
EXPECTED_T11_OUTPUT = "12c33c5d47147e859bb5bab95d42abeafc46dfbeda085c46179a71acd058bf6c"
EXPECTED_T18_VERIFY = "dc9ebcab3e4af3ff75e03e76ee9fa4f147e27cb2910a80b2b25874f8d5e514d1"
APPROVAL_SCHEMA = "s2p16-t19-formal-approval-v1"


def repository_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def repository_clean(root: Path) -> bool:
    return not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ).strip()


def _self_hash(payload: dict[str, Any], field: str) -> bool:
    value = payload.get(field)
    return isinstance(value, str) and value == canonical_hash(
        {key: item for key, item in payload.items() if key != field}
    )


@dataclass(frozen=True, slots=True)
class EvidenceGatePolicy:
    path: Path
    payload: dict[str, Any]
    policy_hash: str
    preregistration_hash: str
    evidence_root: Path
    source_t11_chain_root: Path
    source_t18_run_root: Path
    contract_hashes: dict[str, str]

    @property
    def operations_root(self) -> Path:
        return self.evidence_root / "operations"


def load_policy(path: Path, *, repository_root: Path) -> EvidenceGatePolicy:
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
        "source_t11_chain_root",
        "source_t16_chain_root",
        "source_t17_run_root",
        "source_t18_run_root",
        "required_gates",
    }
    if set(payload) != required:
        raise ValueError("Plan v1.6 policy fields drift")
    if (
        payload["schema_name"] != "stage2-active-policy-v5"
        or payload["schema_version"] != "5.0"
        or payload["stage_plan_version"] != "1.6"
        or payload["execution_limit"] != "S2P16-T19"
        or payload["stage3_locked"] is not True
        or payload["task_dag"]
        != {"S2P16-T19": ["S2P13-T11", "S2P13-T16", "S2P14-T17", "S2P15-T18"]}
    ):
        raise ValueError("Plan v1.6 policy contract drift")
    hashes: dict[str, str] = {}
    for raw in cast(list[object], payload["contract_paths"]):
        relative = Path(str(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe T19 contract path")
        hashes[str(relative)] = sha256_file(repository_root / relative)
    prereg = repository_root / str(payload["preregistration_path"])
    roots = (
        Path(str(payload["evidence_root"])),
        Path(str(payload["source_t11_chain_root"])),
        Path(str(payload["source_t18_run_root"])),
    )
    if any(not root.is_absolute() or root.is_symlink() for root in roots):
        raise ValueError("unsafe T19 evidence root")
    return EvidenceGatePolicy(
        path=path,
        payload=payload,
        policy_hash=canonical_hash(
            {
                "policy": payload,
                "contract_hashes": hashes,
                "preregistration_hash": sha256_file(prereg),
            }
        ),
        preregistration_hash=sha256_file(prereg),
        evidence_root=roots[0],
        source_t11_chain_root=roots[1],
        source_t18_run_root=roots[2],
        contract_hashes=hashes,
    )


@dataclass(frozen=True, slots=True)
class T11Binding:
    receipt_hash: str
    manifest_hash: str
    catalog_hash: str
    output_hash: str
    output_path: Path
    row_count: int


@dataclass(frozen=True, slots=True)
class T18Binding:
    verify_hash: str
    manifest_hash: str
    catalog_hash: str
    summary_path: Path
    cluster_path: Path
    summary_rows: int


@dataclass(frozen=True, slots=True)
class SourceBindings:
    t11: T11Binding
    upstreams: T18Upstreams
    t18: T18Binding


def audit_sources(
    policy: EvidenceGatePolicy, *, repository_root: Path, full_hash_scan: bool
) -> SourceBindings:
    checkpoint = read_json(policy.source_t11_chain_root / "operations/checkpoint.json")
    handoff = cast(
        dict[str, Any], cast(dict[str, Any], checkpoint["tasks"])["S2P13-T11"]["handoff"]
    )
    receipt_path = policy.source_t11_chain_root / "tasks/S2P13-T11/receipt.json"
    receipt = read_json(receipt_path)
    if (
        checkpoint.get("status") != "COMPLETE"
        or handoff.get("verify_status") != "PASS"
        or receipt.get("receipt_hash") != EXPECTED_T11_RECEIPT
        or not _self_hash(receipt, "receipt_hash")
        or receipt.get("row_count") != 87_768
    ):
        raise ValueError("formal T11 binding drift")
    catalog = read_json(Path(str(receipt["catalog_path"])))
    manifest = read_json(Path(str(receipt["manifest_path"])))
    if (
        catalog.get("catalog_hash") != receipt.get("catalog_hash")
        or manifest.get("manifest_hash") != receipt.get("manifest_hash")
        or catalog.get("files")
        != [{"content_hash": EXPECTED_T11_OUTPUT, "relative_path": "output.json"}]
    ):
        raise ValueError("formal T11 Manifest/Catalog drift")
    output_path = Path(str(receipt["artifact_root"])) / "output.json"
    if full_hash_scan and sha256_file(output_path) != EXPECTED_T11_OUTPUT:
        raise ValueError("formal T11 output Hash drift")

    old_policy = load_t18_policy(
        repository_root / "configs/governance/stage2_active_policy_v4.json",
        repository_root=repository_root,
    )
    upstreams = audit_t18_upstreams(
        old_policy, repository_root=repository_root, full_hash_scan=full_hash_scan
    )
    verify = read_json(policy.source_t18_run_root / "verify" / f"{EXPECTED_T18_VERIFY}.json")
    published = policy.source_t18_run_root / "published"
    t18_manifest = read_json(published / "manifest.json")
    t18_catalog = read_json(published / "catalog.json")
    if (
        verify.get("status") != "PASS"
        or verify.get("verify_hash") != EXPECTED_T18_VERIFY
        or not _self_hash(verify, "verify_hash")
        or verify.get("manifest_hash") != t18_manifest.get("manifest_hash")
        or verify.get("catalog_hash") != t18_catalog.get("catalog_hash")
        or verify.get("summary_rows") != 54_720
    ):
        raise ValueError("formal T18 binding drift")
    if full_hash_scan:
        for entry in cast(list[dict[str, Any]], t18_catalog["files"]):
            target = published / str(entry["relative_path"])
            if sha256_file(target) != entry["sha256"]:
                raise ValueError("formal T18 published Hash drift")
    return SourceBindings(
        t11=T11Binding(
            receipt_hash=EXPECTED_T11_RECEIPT,
            manifest_hash=str(receipt["manifest_hash"]),
            catalog_hash=str(receipt["catalog_hash"]),
            output_hash=EXPECTED_T11_OUTPUT,
            output_path=output_path,
            row_count=87_768,
        ),
        upstreams=upstreams,
        t18=T18Binding(
            verify_hash=EXPECTED_T18_VERIFY,
            manifest_hash=str(verify["manifest_hash"]),
            catalog_hash=str(verify["catalog_hash"]),
            summary_path=published / "bootstrap-summaries.parquet",
            cluster_path=published / "cluster-statistics.parquet",
            summary_rows=54_720,
        ),
    )


def record_approval(
    *,
    policy: EvidenceGatePolicy,
    repository_root: Path,
    approved_by: str,
    approval_source: str,
    format_smoke_hash: str,
    approved_at: str | None = None,
) -> Path:
    if not repository_clean(repository_root):
        raise ValueError("formal approval requires a clean repository")
    sources = audit_sources(policy, repository_root=repository_root, full_hash_scan=False)
    payload: dict[str, object] = {
        "schema_name": APPROVAL_SCHEMA,
        "schema_version": "1.0",
        "approved_at": approved_at or datetime.now(UTC).isoformat(),
        "approved_by": approved_by,
        "approval_source": approval_source,
        "code_commit": repository_commit(repository_root),
        "policy_hash": policy.policy_hash,
        "format_smoke_hash": format_smoke_hash,
        "source_t11_receipt_hash": sources.t11.receipt_hash,
        "source_t16_verify_hash": sources.upstreams.t16.verify_hash,
        "source_t17_verify_hash": sources.upstreams.t17.verify_hash,
        "source_t18_verify_hash": sources.t18.verify_hash,
        "stage3_locked": True,
    }
    payload["approval_hash"] = canonical_hash(payload)
    return write_exclusive(
        policy.operations_root / "approvals" / f"approval-{payload['approval_hash']}.json", payload
    )


def validate_approval(
    path: Path, *, policy: EvidenceGatePolicy, repository_root: Path
) -> dict[str, Any]:
    payload = read_json(path)
    sources = audit_sources(policy, repository_root=repository_root, full_hash_scan=False)
    if (
        payload.get("schema_name") != APPROVAL_SCHEMA
        or not _self_hash(payload, "approval_hash")
        or payload.get("code_commit") != repository_commit(repository_root)
        or payload.get("policy_hash") != policy.policy_hash
        or payload.get("source_t11_receipt_hash") != sources.t11.receipt_hash
        or payload.get("source_t16_verify_hash") != sources.upstreams.t16.verify_hash
        or payload.get("source_t17_verify_hash") != sources.upstreams.t17.verify_hash
        or payload.get("source_t18_verify_hash") != sources.t18.verify_hash
        or payload.get("stage3_locked") is not True
    ):
        raise ValueError("T19 approval binding drift")
    return payload


def freeze_authority(
    *,
    policy: EvidenceGatePolicy,
    approval: dict[str, Any],
    sources: SourceBindings,
    repository_root: Path,
) -> S2P16T19Authority:
    authority = S2P16T19Authority.seal(
        {
            "code_commit": repository_commit(repository_root),
            "policy_hash": policy.policy_hash,
            "approval_hash": approval["approval_hash"],
            "preregistration_hash": policy.preregistration_hash,
            "format_smoke_hash": approval["format_smoke_hash"],
            "source_t11_receipt_hash": sources.t11.receipt_hash,
            "source_t16_verify_hash": sources.upstreams.t16.verify_hash,
            "source_t17_verify_hash": sources.upstreams.t17.verify_hash,
            "source_t18_verify_hash": sources.t18.verify_hash,
            "historical_evidence_only": True,
            "stage3_locked": True,
        }
    )
    path = policy.evidence_root / "authorities" / f"authority-{authority.authority_hash}.json"
    write_exclusive(path, authority.model_dump(mode="python"))
    reread = S2P16T19Authority.model_validate_json(path.read_bytes(), strict=True)
    if reread != authority:
        raise ValueError("T19 Authority readback drift")
    return authority
