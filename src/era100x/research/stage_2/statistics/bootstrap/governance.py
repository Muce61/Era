"""Fail-closed Plan v1.5 policy, source binding and approval gates."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from era100x.research.stage_2.baselines.placebo.governance import (
    T16Binding,
    audit_t16_source,
    load_policy as load_t17_policy,
)

from .contracts import S2P15T18Authority
from .formatting import canonical_hash, read_json, sha256_file, write_exclusive

POLICY_SCHEMA = "stage2-active-policy-v4"
APPROVAL_SCHEMA = "s2p15-t18-formal-approval-v1"
EXPECTED_T16_VERIFY = "b866905c18fd1cb1f3bbed1f74e5301c56a78e891b81ab3eea61bcff37ed2b86"
EXPECTED_T17_VERIFY = "bb6f7186f068a1dcd040f369c980bdcae4bb5fef9964c2b5ee61e2d30b6c2f1c"
EXPECTED_T17_SNAPSHOT = "2e5f00e4e375ad7e89e84a29bc6baaded7752cfa59e634f69a92e9dce1d91b00"
EXPECTED_T17_COUNTS = {
    "source_eligible": 413_837,
    "source_matched_slots": 413_827,
    "source_unmatched_not_sampled": 10,
    "placebo_matched": 412_021,
    "placebo_unmatched": 1_806,
    "groups": 456,
    "summaries": 13_680,
}


def repository_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def repository_clean(root: Path) -> bool:
    return not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ).strip()


def _self_hash_matches(payload: dict[str, Any], field: str) -> bool:
    expected = payload.get(field)
    return isinstance(expected, str) and expected == canonical_hash(
        {key: value for key, value in payload.items() if key != field}
    )


@dataclass(frozen=True, slots=True)
class BootstrapPolicy:
    path: Path
    payload: dict[str, Any]
    policy_hash: str
    preregistration_path: Path
    preregistration_hash: str
    evidence_root: Path
    source_t16_chain_root: Path
    source_t17_run_root: Path
    contract_hashes: dict[str, str]

    @property
    def operations_root(self) -> Path:
        return self.evidence_root / "operations"


def load_policy(path: Path, *, repository_root: Path) -> BootstrapPolicy:
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
        "source_t16_chain_root",
        "source_t17_run_root",
        "required_gates",
    }
    if set(payload) != required:
        raise ValueError("Plan v1.5 policy fields drift")
    if (
        payload["schema_name"] != POLICY_SCHEMA
        or payload["schema_version"] != "4.0"
        or payload["stage"] != "S2"
        or payload["stage_plan_version"] != "1.5"
        or payload["execution_limit"] != "S2P15-T18"
        or payload["stage3_locked"] is not True
        or payload["code_commit_mode"] != "CURRENT_CLEAN_HEAD"
        or payload["task_dag"] != {"S2P15-T18": ["S2P13-T16", "S2P14-T17"]}
        or payload["required_gates"]
        != [
            "FORMAT_SMOKE_PASS",
            "COMMIT_BOUND_HUMAN_APPROVAL",
            "AUTHORITY_BEFORE_RUN",
            "UNIQUE_RUN_LOCK",
            "FULL_RECONCILIATION",
            "FULL_VERIFY",
        ]
    ):
        raise ValueError("Plan v1.5 policy contract drift")
    contract_hashes: dict[str, str] = {}
    for raw in cast(list[object], payload["contract_paths"]):
        relative = Path(str(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe T18 policy contract path")
        contract_hashes[str(relative)] = sha256_file(repository_root / relative)
    preregistration_path = repository_root / str(payload["preregistration_path"])
    preregistration_hash = sha256_file(preregistration_path)
    evidence_root = Path(str(payload["evidence_root"]))
    t16_root = Path(str(payload["source_t16_chain_root"]))
    t17_root = Path(str(payload["source_t17_run_root"]))
    for root in (evidence_root, t16_root, t17_root):
        if not root.is_absolute() or root.is_symlink():
            raise ValueError("unsafe Plan v1.5 evidence root")
    resolved = {
        "policy": payload,
        "contract_hashes": contract_hashes,
        "preregistration_hash": preregistration_hash,
    }
    return BootstrapPolicy(
        path=path,
        payload=payload,
        policy_hash=canonical_hash(resolved),
        preregistration_path=preregistration_path,
        preregistration_hash=preregistration_hash,
        evidence_root=evidence_root,
        source_t16_chain_root=t16_root,
        source_t17_run_root=t17_root,
        contract_hashes=contract_hashes,
    )


@dataclass(frozen=True, slots=True)
class T17Binding:
    run_root: Path
    snapshot_root: Path
    snapshot_id: str
    verify_hash: str
    manifest_hash: str
    catalog_hash: str
    prepared_source_verify_hash: str
    match_root: Path
    match_files: tuple[Path, ...]
    summary_path: Path
    counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class SourceBindings:
    t16: T16Binding
    t17: T17Binding


def _audit_t17(policy: BootstrapPolicy, *, full_hash_scan: bool) -> T17Binding:
    verify_path = policy.source_t17_run_root / "verify" / f"{EXPECTED_T17_VERIFY}.json"
    verify = read_json(verify_path)
    if (
        verify.get("status") != "PASS"
        or verify.get("verify_hash") != EXPECTED_T17_VERIFY
        or not _self_hash_matches(verify, "verify_hash")
        or verify.get("stage3_locked") is not True
        or verify.get("research_status") != "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING"
    ):
        raise ValueError("formal T17 Verify drift")
    snapshot_id = str(verify.get("snapshot_id"))
    if snapshot_id != EXPECTED_T17_SNAPSHOT:
        raise ValueError("formal T17 snapshot drift")
    snapshot_root = policy.source_t17_run_root / "published" / "snapshots" / snapshot_id
    manifest_path = snapshot_root / "manifest.json"
    catalog_path = snapshot_root / "catalog.json"
    manifest = read_json(manifest_path)
    catalog = read_json(catalog_path)
    reconciliation = read_json(snapshot_root / "results" / "reconciliation.json")
    if (
        not _self_hash_matches(manifest, "manifest_hash")
        or not _self_hash_matches(catalog, "catalog_hash")
        or not _self_hash_matches(reconciliation, "reconciliation_hash")
        or manifest.get("manifest_hash") != verify.get("manifest_hash")
        or catalog.get("catalog_hash") != verify.get("catalog_hash")
        or reconciliation.get("reconciliation_hash") != verify.get("reconciliation_hash")
    ):
        raise ValueError("formal T17 Manifest/Catalog drift")
    files = cast(list[dict[str, Any]], catalog.get("files"))
    match_entries = sorted(
        (
            item
            for item in files
            if str(item.get("relative_path", "")).startswith("results/matches/")
            and str(item.get("relative_path", "")).endswith(".parquet")
            and not Path(str(item["relative_path"])).name.startswith("._")
        ),
        key=lambda item: str(item["relative_path"]),
    )
    if len(match_entries) != EXPECTED_T17_COUNTS["groups"]:
        raise ValueError("formal T17 match group count drift")
    match_files: list[Path] = []
    for item in match_entries:
        path = snapshot_root / str(item["relative_path"])
        if path.is_symlink() or not path.is_file():
            raise ValueError("formal T17 match file missing")
        if full_hash_scan and (
            sha256_file(path) != item.get("sha256") or path.stat().st_size != item.get("byte_size")
        ):
            raise ValueError("formal T17 match file Hash drift")
        match_files.append(path)
    summary_path = snapshot_root / "results" / "descriptive_summaries.parquet"
    if not summary_path.is_file() or summary_path.is_symlink():
        raise ValueError("formal T17 summary missing")
    counts = {
        "source_eligible": int(reconciliation["source_eligible"]),
        "source_matched_slots": int(reconciliation["source_matched_slots"]),
        "source_unmatched_not_sampled": int(reconciliation["source_unmatched_not_sampled"]),
        "placebo_matched": int(reconciliation["placebo_matched"]),
        "placebo_unmatched": int(reconciliation["placebo_unmatched"]),
        "groups": len(match_files),
        "summaries": int(verify["summary_row_count"]),
    }
    if counts != EXPECTED_T17_COUNTS:
        raise ValueError("formal T17 count drift")
    return T17Binding(
        run_root=policy.source_t17_run_root,
        snapshot_root=snapshot_root,
        snapshot_id=snapshot_id,
        verify_hash=EXPECTED_T17_VERIFY,
        manifest_hash=str(manifest["manifest_hash"]),
        catalog_hash=str(catalog["catalog_hash"]),
        prepared_source_verify_hash=str(manifest.get("source_t16_verify_hash")),
        match_root=snapshot_root / "results" / "matches",
        match_files=tuple(match_files),
        summary_path=summary_path,
        counts=counts,
    )


def audit_sources(
    policy: BootstrapPolicy, *, repository_root: Path, full_hash_scan: bool
) -> SourceBindings:
    old_policy = load_t17_policy(
        repository_root / "configs/governance/stage2_active_policy_v3.json",
        repository_root=repository_root,
    )
    if old_policy.source_chain_root != policy.source_t16_chain_root:
        raise ValueError("T18 and T17 T16 roots disagree")
    t16 = audit_t16_source(old_policy, full_hash_scan=full_hash_scan)
    if t16.verify_hash != EXPECTED_T16_VERIFY:
        raise ValueError("formal T16 Verify drift")
    t17 = _audit_t17(policy, full_hash_scan=full_hash_scan)
    if t17.prepared_source_verify_hash != t16.verify_hash:
        raise ValueError("T17 does not bind the approved T16 Verify")
    return SourceBindings(t16=t16, t17=t17)


def record_approval(
    *,
    policy: BootstrapPolicy,
    repository_root: Path,
    approved_by: str,
    approval_source: str,
    format_smoke_hash: str,
    approved_at: str | None,
) -> Path:
    if not repository_clean(repository_root):
        raise ValueError("formal T18 approval requires a clean repository")
    commit = repository_commit(repository_root)
    smoke_path = policy.operations_root / "format-smokes" / f"{format_smoke_hash}.json"
    smoke = read_json(smoke_path)
    if (
        smoke.get("format_smoke_hash") != format_smoke_hash
        or not _self_hash_matches(smoke, "format_smoke_hash")
        or smoke.get("status") != "PASS"
        or smoke.get("code_commit") != commit
        or smoke.get("policy_hash") != policy.policy_hash
        or smoke.get("source_t16_verify_hash") != EXPECTED_T16_VERIFY
        or smoke.get("source_t17_verify_hash") != EXPECTED_T17_VERIFY
    ):
        raise ValueError("format smoke does not authorize this T18 commit")
    payload: dict[str, object] = {
        "schema_name": APPROVAL_SCHEMA,
        "schema_version": "1.0",
        "task_id": "S2P15-T18",
        "code_commit": commit,
        "policy_hash": policy.policy_hash,
        "preregistration_hash": policy.preregistration_hash,
        "format_smoke_hash": format_smoke_hash,
        "source_t16_verify_hash": EXPECTED_T16_VERIFY,
        "source_t17_verify_hash": EXPECTED_T17_VERIFY,
        "approved_by": approved_by,
        "approved_at": approved_at or datetime.now(UTC).isoformat(),
        "approval_source": approval_source,
        "stage3_locked": True,
    }
    payload["approval_hash"] = canonical_hash(payload)
    return write_exclusive(
        policy.operations_root / "approvals" / f"approval-{payload['approval_hash']}.json",
        payload,
    )


def validate_approval(
    path: Path,
    *,
    policy: BootstrapPolicy,
    repository_root: Path,
) -> dict[str, Any]:
    approval = read_json(path)
    if (
        approval.get("schema_name") != APPROVAL_SCHEMA
        or not _self_hash_matches(approval, "approval_hash")
        or approval.get("code_commit") != repository_commit(repository_root)
        or approval.get("policy_hash") != policy.policy_hash
        or approval.get("preregistration_hash") != policy.preregistration_hash
        or approval.get("source_t16_verify_hash") != EXPECTED_T16_VERIFY
        or approval.get("source_t17_verify_hash") != EXPECTED_T17_VERIFY
        or approval.get("stage3_locked") is not True
    ):
        raise ValueError("T18 approval binding drift")
    smoke_hash = str(approval.get("format_smoke_hash"))
    smoke = read_json(policy.operations_root / "format-smokes" / f"{smoke_hash}.json")
    if (
        smoke.get("format_smoke_hash") != smoke_hash
        or not _self_hash_matches(smoke, "format_smoke_hash")
        or smoke.get("status") != "PASS"
        or smoke.get("code_commit") != approval.get("code_commit")
        or smoke.get("policy_hash") != policy.policy_hash
        or smoke.get("source_t16_verify_hash") != EXPECTED_T16_VERIFY
        or smoke.get("source_t17_verify_hash") != EXPECTED_T17_VERIFY
    ):
        raise ValueError("T18 approval format-smoke binding drift")
    return approval


def freeze_authority(
    *,
    policy: BootstrapPolicy,
    approval: dict[str, Any],
    sources: SourceBindings,
    repository_root: Path,
) -> S2P15T18Authority:
    authority = S2P15T18Authority.seal(
        {
            "code_commit": repository_commit(repository_root),
            "policy_hash": policy.policy_hash,
            "approval_hash": approval["approval_hash"],
            "preregistration_hash": policy.preregistration_hash,
            "format_smoke_hash": approval["format_smoke_hash"],
            "source_t16_verify_hash": sources.t16.verify_hash,
            "source_t17_verify_hash": sources.t17.verify_hash,
            "source_t16_snapshot_id": sources.t16.snapshot_id,
            "source_t17_snapshot_id": sources.t17.snapshot_id,
            "cluster_contract": "INSTRUMENT_UTC_MONDAY_WEEK_V1",
            "bootstrap_iterations": 5000,
            "bootstrap_seed": 20260716,
            "rng": "NUMPY_PCG64_DERIVED_GROUP_SEED_V1",
            "metric_families": (
                "REAL_EVENT_DELTA",
                "PLACEBO_DELTA",
                "PAIRED_REAL_MINUS_PLACEBO",
            ),
            "analysis_scopes": ("FOLD", "PERIOD", "OVERALL"),
            "historical_evidence_only": True,
            "stage3_locked": True,
        }
    )
    path = policy.evidence_root / "authorities" / f"authority-{authority.authority_hash}.json"
    if path.exists():
        existing = S2P15T18Authority.model_validate_json(path.read_text(), strict=True)
        if existing != authority:
            raise ValueError("T18 Authority path collision")
    else:
        write_exclusive(path, authority.model_dump(mode="python"))
    return authority
