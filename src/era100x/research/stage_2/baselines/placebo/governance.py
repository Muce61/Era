"""Small fail-closed governance and T16 source binding for S2P14-T17."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .contracts import S2P14T17Authority, canonical_hash

POLICY_SCHEMA = "stage2-active-policy-v3"
APPROVAL_SCHEMA = "s2p14-t17-formal-approval-v1"
EXPECTED_CHAIN = "fa92072063be8455fab814c1e9f302f2b06392a999820a53bd430e7282f57579"
EXPECTED_RUN = "stage2-s2p13-t16-20260726T091411Z-5f56fc680bc9"
EXPECTED_VERIFY = "b866905c18fd1cb1f3bbed1f74e5301c56a78e891b81ab3eea61bcff37ed2b86"
EXPECTED_SNAPSHOT = "ac45672c61977e855a90ca0d572efad0059ee8404eff57f19c28962ae98387e1"
EXPECTED_AUTHORITY = "5f56fc680bc970596afff672da0f301bdad428ca37174a60324f9543c3c71477"
EXPECTED_BINNING = "3b0de1c9b4a0632c53451418d0d063f932ca852b106e02bf82e99b0c4306e786"
EXPECTED_COUNTS = {
    "eligible": 413_837,
    "matched": 413_827,
    "unmatched": 10,
    "controls": 1_278_527,
    "summaries": 13_680,
    "groups": 456,
}


def sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.name.startswith("._"):
        raise ValueError(f"unsafe or missing evidence file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.name.startswith("._"):
        raise ValueError(f"unsafe or missing JSON evidence: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("evidence JSON root must be an object")
    return cast(dict[str, Any], value)


def self_hash_matches(payload: dict[str, Any], field: str) -> bool:
    expected = payload.get(field)
    body = {key: value for key, value in payload.items() if key != field}
    return isinstance(expected, str) and expected == canonical_hash(body)


def write_exclusive(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def repository_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def repository_clean(root: Path) -> bool:
    return not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ).strip()


@dataclass(frozen=True, slots=True)
class PlaceboPolicy:
    path: Path
    payload: dict[str, Any]
    policy_hash: str
    preregistration_path: Path
    preregistration_hash: str
    evidence_root: Path
    source_chain_root: Path
    contract_hashes: dict[str, str]

    @property
    def operations_root(self) -> Path:
        return self.evidence_root / "operations"


def load_policy(path: Path, *, repository_root: Path) -> PlaceboPolicy:
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
        "required_gates",
    }
    if set(payload) != required:
        raise ValueError("Plan v1.4 policy fields drift")
    if (
        payload["schema_name"] != POLICY_SCHEMA
        or payload["schema_version"] != "3.0"
        or payload["stage"] != "S2"
        or payload["stage_plan_version"] != "1.4"
        or payload["execution_limit"] != "S2P14-T17"
        or payload["stage3_locked"] is not True
        or payload["code_commit_mode"] != "CURRENT_CLEAN_HEAD"
        or payload["task_dag"] != {"S2P14-T17": ["S2P13-T16"]}
        or payload["required_gates"]
        != [
            "COMMIT_BOUND_HUMAN_APPROVAL",
            "AUTHORITY_BEFORE_RUN",
            "UNIQUE_RUN_LOCK",
            "FULL_RECONCILIATION",
            "FULL_VERIFY",
        ]
    ):
        raise ValueError("Plan v1.4 policy contract drift")
    contract_hashes: dict[str, str] = {}
    for relative_value in cast(list[object], payload["contract_paths"]):
        relative = Path(str(relative_value))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe policy contract path")
        target = repository_root / relative
        contract_hashes[str(relative)] = sha256_file(target)
    preregistration_path = repository_root / str(payload["preregistration_path"])
    preregistration_hash = sha256_file(preregistration_path)
    evidence_root = Path(str(payload["evidence_root"]))
    source_chain_root = Path(str(payload["source_t16_chain_root"]))
    if (
        not evidence_root.is_absolute()
        or evidence_root.is_symlink()
        or not source_chain_root.is_absolute()
        or source_chain_root.is_symlink()
        or source_chain_root.name != EXPECTED_CHAIN
    ):
        raise ValueError("unsafe or unexpected Plan v1.4 evidence roots")
    resolved = {
        "policy": payload,
        "contract_hashes": contract_hashes,
        "preregistration_hash": preregistration_hash,
    }
    return PlaceboPolicy(
        path=path,
        payload=payload,
        policy_hash=canonical_hash(resolved),
        preregistration_path=preregistration_path,
        preregistration_hash=preregistration_hash,
        evidence_root=evidence_root,
        source_chain_root=source_chain_root,
        contract_hashes=contract_hashes,
    )


@dataclass(frozen=True, slots=True)
class T16Binding:
    receipt_path: Path
    receipt_hash: str
    artifact_manifest_hash: str
    artifact_catalog_hash: str
    authority_hash: str
    binning_hash: str
    snapshot_id: str
    verify_hash: str
    snapshot_root: Path
    binning_root: Path
    prepared_episodes_path: Path
    selections_root: Path
    outcome_path: Path
    match_path: Path
    summary_path: Path
    counts: dict[str, int]

    @property
    def counts_hash(self) -> str:
        return canonical_hash(self.counts)


def _locate_unique(root: Path, pattern: str) -> Path:
    matches = tuple(
        path
        for path in root.rglob(pattern)
        if path.is_file()
        and not path.is_symlink()
        and not path.name.startswith("._")
        and not any(part.startswith("._") for part in path.parts)
    )
    if len(matches) != 1:
        raise ValueError(f"expected one {pattern}, found {len(matches)}")
    return matches[0]


def audit_t16_source(policy: PlaceboPolicy, *, full_hash_scan: bool) -> T16Binding:
    receipt_path = policy.source_chain_root / "tasks/S2P13-T16/receipt.json"
    receipt = read_json(receipt_path)
    if (
        not self_hash_matches(receipt, "receipt_hash")
        or receipt.get("status") != "PASS"
        or receipt.get("verify_status") != "PASS"
        or receipt.get("reconciliation") != "PASS"
        or receipt.get("consumer_readback") != "PASS"
        or receipt.get("stage_plan_version") != "1.3"
        or receipt.get("task_id") != "S2P13-T16"
        or receipt.get("run_id") != "stage2-s2p13-t16-d1d182f50a29"
        or receipt.get("row_count") != 532_708
    ):
        raise ValueError("formal T16 receipt is invalid")
    artifact_root = Path(str(receipt["artifact_root"]))
    if artifact_root.is_symlink() or not artifact_root.is_dir():
        raise ValueError("formal T16 artifact root is invalid")
    artifact_manifest = read_json(Path(str(receipt["manifest_path"])))
    artifact_catalog = read_json(Path(str(receipt["catalog_path"])))
    if (
        not self_hash_matches(artifact_manifest, "manifest_hash")
        or not self_hash_matches(artifact_catalog, "catalog_hash")
        or artifact_manifest["manifest_hash"] != receipt["manifest_hash"]
        or artifact_catalog["catalog_hash"] != receipt["catalog_hash"]
    ):
        raise ValueError("formal T16 handoff Manifest/Catalog drift")
    verify_path = _locate_unique(artifact_root, f"{EXPECTED_VERIFY}.json")
    verify = read_json(verify_path)
    if (
        not self_hash_matches(verify, "verify_hash")
        or verify.get("verify_hash") != EXPECTED_VERIFY
        or verify.get("run_id") != EXPECTED_RUN
        or verify.get("snapshot_id") != EXPECTED_SNAPSHOT
        or verify.get("authority_hash") not in {None, EXPECTED_AUTHORITY}
        or verify.get("status") != "PASS"
        or verify.get("stage3_locked") is not True
    ):
        raise ValueError("formal T16 Verify drift")
    run_root = verify_path.parents[1]
    snapshot_root = run_root / "published/snapshots" / EXPECTED_SNAPSHOT
    snapshot_catalog = read_json(snapshot_root / "catalog.json")
    snapshot_manifest = read_json(snapshot_root / "manifest.json")
    if (
        canonical_hash(
            {
                key: value
                for key, value in snapshot_catalog.items()
                if key not in {"catalog_hash", "snapshot_id", "manifest_hash"}
            }
        )
        != snapshot_catalog.get("catalog_hash")
        or not self_hash_matches(snapshot_manifest, "manifest_hash")
        or snapshot_catalog.get("catalog_hash") != EXPECTED_SNAPSHOT
        or snapshot_catalog.get("authority_hash") != EXPECTED_AUTHORITY
        or snapshot_catalog.get("binning_set_hash") != EXPECTED_BINNING
        or snapshot_manifest.get("catalog_hash") != EXPECTED_SNAPSHOT
        or snapshot_manifest.get("stage3_locked") is not True
    ):
        raise ValueError("formal T16 published Manifest/Catalog drift")
    if full_hash_scan:
        for entry in cast(list[dict[str, Any]], snapshot_catalog["files"]):
            relative = Path(str(entry["relative_path"]))
            if relative.is_absolute() or ".." in relative.parts or relative.name.startswith("._"):
                raise ValueError("unsafe T16 catalog entry")
            target = snapshot_root / relative
            if sha256_file(target) != entry["sha256"]:
                raise ValueError(f"T16 published file Hash drift: {relative}")
    match_path = snapshot_root / "results/conditional_match_matrices.parquet"
    outcome_path = snapshot_root / "results/control_outcome_matrices.parquet"
    summary_path = snapshot_root / "results/descriptive_summaries.parquet"
    counts = {
        "eligible": pq.ParquetFile(match_path).metadata.num_rows,
        "matched": int(verify["matched_episode_count"]),
        "unmatched": int(verify["unmatched_episode_count"]),
        "controls": pq.ParquetFile(outcome_path).metadata.num_rows,
        "summaries": pq.ParquetFile(summary_path).metadata.num_rows,
        "groups": len(
            tuple(
                path
                for path in (snapshot_root / "selections").rglob("*.parquet")
                if not path.name.startswith("._") and not path.is_symlink()
            )
        ),
    }
    if counts != EXPECTED_COUNTS or counts["matched"] + counts["unmatched"] != counts["eligible"]:
        raise ValueError(f"formal T16 count drift: {counts}")
    binning_root = run_root.parents[1] / "train-bins" / EXPECTED_AUTHORITY
    if not binning_root.is_dir() or binning_root.is_symlink():
        raise ValueError("formal T16 binning root is missing")
    return T16Binding(
        receipt_path=receipt_path,
        receipt_hash=str(receipt["receipt_hash"]),
        artifact_manifest_hash=str(receipt["manifest_hash"]),
        artifact_catalog_hash=str(receipt["catalog_hash"]),
        authority_hash=EXPECTED_AUTHORITY,
        binning_hash=EXPECTED_BINNING,
        snapshot_id=EXPECTED_SNAPSHOT,
        verify_hash=EXPECTED_VERIFY,
        snapshot_root=snapshot_root,
        binning_root=binning_root,
        prepared_episodes_path=snapshot_root / "episodes/prepared-episodes.parquet",
        selections_root=snapshot_root / "selections",
        outcome_path=outcome_path,
        match_path=match_path,
        summary_path=summary_path,
        counts=counts,
    )


def record_approval(
    *,
    policy: PlaceboPolicy,
    repository_root: Path,
    approved_by: str,
    approval_source: str,
    approved_at: str | None = None,
    supersedes_authority_hash: str | None = None,
) -> Path:
    if not repository_clean(repository_root):
        raise ValueError("formal T17 approval requires a clean repository")
    binding = audit_t16_source(policy, full_hash_scan=True)
    commit = repository_commit(repository_root)
    timestamp = approved_at or datetime.now(UTC).isoformat()
    payload: dict[str, Any] = {
        "schema_name": APPROVAL_SCHEMA,
        "schema_version": "1.0",
        "stage_plan_version": "1.4",
        "task_id": "S2P14-T17",
        "code_commit": commit,
        "policy_hash": policy.policy_hash,
        "preregistration_hash": policy.preregistration_hash,
        "source_t16_verify_hash": binding.verify_hash,
        "source_t16_receipt_hash": binding.receipt_hash,
        "approved_by": approved_by,
        "approved_at": timestamp,
        "approval_source": approval_source,
        "authority_count": 1,
        "run_count": 1,
        "stage3_locked": True,
    }
    if supersedes_authority_hash is not None:
        if len(supersedes_authority_hash) != 64 or any(
            character not in "0123456789abcdef" for character in supersedes_authority_hash
        ):
            raise ValueError("superseded T17 Authority Hash is invalid")
        payload.update(
            {
                "supersedes_authority_hash": supersedes_authority_hash,
                "superseded_authority_run_count": 0,
                "successor_authority_count": 1,
            }
        )
    payload["approval_hash"] = canonical_hash(payload)
    path = policy.operations_root / "approvals" / f"approval-{payload['approval_hash']}.json"
    return write_exclusive(path, payload)


def validate_approval(
    path: Path,
    *,
    policy: PlaceboPolicy,
    repository_root: Path,
    binding: T16Binding,
) -> dict[str, Any]:
    approval = read_json(path)
    supersedes = approval.get("supersedes_authority_hash")
    successor_fields_valid = supersedes is None or (
        isinstance(supersedes, str)
        and len(supersedes) == 64
        and all(character in "0123456789abcdef" for character in supersedes)
        and approval.get("superseded_authority_run_count") == 0
        and approval.get("successor_authority_count") == 1
    )
    if (
        not self_hash_matches(approval, "approval_hash")
        or approval.get("schema_name") != APPROVAL_SCHEMA
        or approval.get("code_commit") != repository_commit(repository_root)
        or approval.get("policy_hash") != policy.policy_hash
        or approval.get("preregistration_hash") != policy.preregistration_hash
        or approval.get("source_t16_verify_hash") != binding.verify_hash
        or approval.get("source_t16_receipt_hash") != binding.receipt_hash
        or approval.get("authority_count") != 1
        or approval.get("run_count") != 1
        or approval.get("stage3_locked") is not True
        or not successor_fields_valid
    ):
        raise ValueError("formal T17 approval is invalid or stale")
    return approval


def freeze_authority(
    *,
    policy: PlaceboPolicy,
    approval: dict[str, Any],
    binding: T16Binding,
    repository_root: Path,
) -> S2P14T17Authority:
    preregistration = read_json(policy.preregistration_path)
    return S2P14T17Authority.seal(
        {
            "code_commit": repository_commit(repository_root),
            "policy_hash": policy.policy_hash,
            "approval_hash": approval["approval_hash"],
            "preregistration_hash": policy.preregistration_hash,
            "source_t16_receipt_hash": binding.receipt_hash,
            "source_t16_authority_hash": binding.authority_hash,
            "source_t16_binning_hash": binding.binning_hash,
            "source_t16_manifest_hash": binding.artifact_manifest_hash,
            "source_t16_catalog_hash": binding.artifact_catalog_hash,
            "source_t16_snapshot_id": binding.snapshot_id,
            "source_t16_verify_hash": binding.verify_hash,
            "source_counts_hash": binding.counts_hash,
            "exact_fields": tuple(preregistration["exact_fields"]),
            "relaxation_order": tuple(preregistration["relaxation_order"]),
        }
    )
