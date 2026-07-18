"""Freeze the fixed S2-T10 v1.8 Runtime V2 authority chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.pipelines.candidates.stage1_catalog import Stage1CatalogAuthority
from era100x.research.stage_2.runtime_v2.manifest_factory import build_runtime_v2_manifest
from era100x.research.stage_2.runtime_v2.models import DigestBinding
from era100x.research.stage_2.runtime_v2.orchestrator import (
    CONFIG_SHA256,
    PREREGISTRATION_SHA256,
    RUN_A_ID,
    STAGE1_DATA_RUN_ID,
    STAGE1_MANIFEST_SHA256,
    compute_v2_code_tree_sha256,
)
from era100x.research.stage_2.runtime_v2.production_backend import (
    CONTRACT_PRICE_INVENTORY_SHA256,
    CONTRACT_PRICE_ROOT,
    STAGE1_CATALOG_ROOT,
    STAGE1_CATALOG_SHA256S,
    STAGE1_LOGICAL_HASHES,
    STAGE1_PHYSICAL_MANIFEST_SHA256,
    STAGE1_PUBLISHED_ROOT,
)
from era100x.research.stage_2.runtime_v2.source_authority import (
    CONTRACT_PRICE_MANIFEST_AUTHORITY,
    TRADES_RESOLVED_INDEX_AUTHORITY,
    freeze_contract_price_inventory_manifest,
    freeze_stage1_resolved_source_index_from_catalog,
)
from era100x.research.stage_2.runtime_v2.transition import (
    freeze_run_a_protection,
    freeze_v2_migration_manifest,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[1]
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
RUNS_ROOT = STAGE2_ROOT / "runs"
RUN_A_ROOT = RUNS_ROOT / RUN_A_ID
APPROVED_BRANCH = "stage/2-multi-event-runtime-v2"
RUN_A_EXECUTION_MANIFEST = (
    RUN_A_ROOT
    / "manifests"
    / ("71385c11e38b0e76b198e3a2ba510665a3301d052f770a8407797795e5312a4b.json")
)
RUN_A_RELEASE_SUPPLEMENT = (
    RUN_A_ROOT
    / "manifests"
    / ("5ef20632761acd77ca9836ede3c12f1e48f58e814f96cad56d86646fcc259007.json")
)
FAILED_AUTHORITY_COMMIT = "18d6660bd75a0ba6750d55c29ba45df0cfa1de51"
FAILED_RESERVED_RUN_B_ID = "stage2-g1-v2-b-20260717T160947Z-18d6660bd75a"
EXPECTED_RESOLVED_PARTITION_COUNT = 4752
EXPECTED_ARCHIVE_COUNTS = {
    "BTCUSDT": {"monthly_archive_count": 78, "daily_archive_count": 3},
    "ETHUSDT": {"monthly_archive_count": 78, "daily_archive_count": 3},
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Freeze Runtime V2 authorities")
    result.add_argument(
        "action",
        nargs="?",
        choices=("freeze", "record-failure"),
        default="freeze",
    )
    result.add_argument("--transition-run-id", required=True)
    result.add_argument("--destination-run-id")
    result.add_argument("--quality-evidence", type=Path)
    result.add_argument("--memory-evidence", type=Path)
    result.add_argument("--finalization-memory-evidence", type=Path)
    result.add_argument("--failure-log", type=Path)
    result.add_argument("--failed-code-commit")
    result.add_argument("--error-type", choices=("ValidationError",), default="ValidationError")
    result.add_argument(
        "--failure-field", choices=("archive_partition",), default="archive_partition"
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.action == "record-failure":
        return _record_failure(args)
    if (
        args.destination_run_id is None
        or args.quality_evidence is None
        or args.memory_evidence is None
        or args.finalization_memory_evidence is None
    ):
        raise ValueError(
            "freeze requires --destination-run-id, --quality-evidence, --memory-evidence "
            "and --finalization-memory-evidence"
        )
    transition_root = _bounded_run_root(args.transition_run_id, "stage2-g1-v2-authority-")
    destination_root = _new_destination_root(args.destination_run_id)
    head = _git("rev-parse", "HEAD")
    if _git("branch", "--show-current") != APPROVED_BRANCH:
        raise ValueError(f"authority freeze requires {APPROVED_BRANCH}")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("authority freeze requires a clean worktree")
    quality_path = args.quality_evidence.resolve()
    if not quality_path.is_relative_to((transition_root / "reports").resolve()):
        raise ValueError("quality evidence must belong to this transition run")
    quality = _read_object(quality_path)
    if quality.get("status") != "PASS" or quality.get("code_commit") != head:
        raise ValueError("quality evidence is not PASS for current HEAD")
    code_tree_hash = compute_v2_code_tree_sha256(ROOT)
    if quality.get("runtime_v2_code_tree_sha256") != code_tree_hash:
        raise ValueError("quality evidence Runtime V2 code-tree authority differs")
    recorded_at = quality.get("created_at")
    if not isinstance(recorded_at, str) or not recorded_at:
        raise ValueError("quality evidence created_at is missing")
    memory_path = args.memory_evidence.resolve()
    if (
        not memory_path.is_file()
        or memory_path.is_symlink()
        or not memory_path.is_relative_to(RUNS_ROOT.resolve())
        or not memory_path.parent.parent.name.startswith(
            "stage2-g1-v2-memory-diagnostic-cr-2026-011-"
        )
    ):
        raise ValueError("memory evidence is outside the approved diagnostic authority")
    memory = _read_object(memory_path)
    if (
        memory.get("status") != "PASS"
        or memory.get("change_request") != "CR-2026-011"
        or memory.get("deterministic_replay") != "PASS"
        or memory.get("semantic_regression") != "PASS"
    ):
        raise ValueError("CR-2026-011 memory evidence is not PASS")
    finalization_memory_path = args.finalization_memory_evidence.resolve()
    if (
        not finalization_memory_path.is_file()
        or finalization_memory_path.is_symlink()
        or not finalization_memory_path.is_relative_to(RUNS_ROOT.resolve())
        or not finalization_memory_path.parent.parent.name.startswith(
            "stage2-g1-v2-finalization-diagnostic-cr-2026-012-"
        )
    ):
        raise ValueError(
            "finalization memory evidence is outside the approved diagnostic authority"
        )
    finalization_memory = _read_object(finalization_memory_path)
    limits = finalization_memory.get("limits")
    if (
        finalization_memory.get("result") != "PASS"
        or finalization_memory.get("change_request") != "CR-2026-012"
        or not isinstance(limits, dict)
        or finalization_memory.get("read_only_source") is not True
        or finalization_memory.get("packed_row_group_count") != 9504
        or finalization_memory.get("receipt_count") != 9504
        or not isinstance(finalization_memory.get("max_arrow_bytes"), int)
        or not isinstance(finalization_memory.get("max_current_rss_bytes"), int)
        or not isinstance(finalization_memory.get("max_phase_current_rss_delta_bytes"), int)
        or limits.get("arrow_inflight_bytes") != 1_073_741_824
        or limits.get("current_rss_bytes") != 3_221_225_472
        or limits.get("phase_current_rss_delta_bytes") != 1_073_741_824
        or limits.get("lifetime_peak_policy") != "AUDIT_ONLY"
    ):
        raise ValueError("CR-2026-012 finalization memory evidence is not PASS")

    manifests = transition_root / "manifests"
    price_path = manifests / "contract-price-inventory-v2.json"
    trades_path = manifests / "stage1-trades-resolved-index-v2.json"
    price = freeze_contract_price_inventory_manifest(
        root=CONTRACT_PRICE_ROOT,
        output_path=price_path,
        expected_inventory_hash=CONTRACT_PRICE_INVENTORY_SHA256,
    )
    catalog_authority = Stage1CatalogAuthority(
        data_run_id=STAGE1_DATA_RUN_ID,
        dataset_version="stage1-trades-v2",
        canonical_manifest_sha256=STAGE1_MANIFEST_SHA256,
        physical_manifest_sha256=STAGE1_PHYSICAL_MANIFEST_SHA256,
        catalog_sha256s=STAGE1_CATALOG_SHA256S,
        logical_hashes=STAGE1_LOGICAL_HASHES,
    )
    trades = freeze_stage1_resolved_source_index_from_catalog(
        catalog_run_root=STAGE1_CATALOG_ROOT,
        published_root=STAGE1_PUBLISHED_ROOT,
        authority=catalog_authority,
        output_path=trades_path,
    )
    _supersession, protection = freeze_run_a_protection(
        run_a_root=RUN_A_ROOT,
        transition_run_root=transition_root,
        execution_manifest_path=RUN_A_EXECUTION_MANIFEST,
        release_supplement_path=RUN_A_RELEASE_SUPPLEMENT,
        approved_at=recorded_at,
    )
    migration = freeze_v2_migration_manifest(
        protection=protection,
        transition_run_root=transition_root,
        destination_run_id=args.destination_run_id,
        destination_root=destination_root,
        v2_code_commit=head,
        v2_code_tree_hash=code_tree_hash,
        contract_price_inventory_manifest_path=price_path,
        stage1_resolved_source_index_path=trades_path,
        recorded_at=recorded_at,
    )
    authorities = tuple(
        DigestBinding(name=name, sha256=digest)
        for name, digest in sorted(
            {
                "contract_price_inventory": CONTRACT_PRICE_INVENTORY_SHA256,
                CONTRACT_PRICE_MANIFEST_AUTHORITY: price.manifest_hash,
                "runtime_v2_quality_evidence": sha256_file(quality_path),
                "runtime_v2_memory_evidence": sha256_file(memory_path),
                "runtime_v2_finalization_memory_evidence": sha256_file(finalization_memory_path),
                "stage1_btc_catalog": STAGE1_CATALOG_SHA256S["BTCUSDT"],
                "stage1_eth_catalog": STAGE1_CATALOG_SHA256S["ETHUSDT"],
                "stage1_manifest": STAGE1_MANIFEST_SHA256,
                "stage1_physical_manifest": STAGE1_PHYSICAL_MANIFEST_SHA256,
                TRADES_RESOLVED_INDEX_AUTHORITY: trades.manifest_hash,
                "trades_btc_logical": STAGE1_LOGICAL_HASHES["BTCUSDT"],
                "trades_eth_logical": STAGE1_LOGICAL_HASHES["ETHUSDT"],
            }.items()
        )
    )
    runtime = build_runtime_v2_manifest(
        stage1_data_run_id=STAGE1_DATA_RUN_ID,
        stage1_authorities=authorities,
        preregistration_manifest_sha256=PREREGISTRATION_SHA256,
        config_sha256=CONFIG_SHA256,
        code_tree_sha256=code_tree_hash,
    )
    runtime_path = manifests / f"{runtime.manifest_hash}.json"
    _write_once(runtime_path, runtime.model_dump(mode="json"))
    components = {
        "contract_price_inventory": _component_binding(
            transition_root, price_path, price.manifest_hash
        ),
        "runtime_manifest": _component_binding(
            transition_root, runtime_path, runtime.manifest_hash
        ),
        "run_a_protection": _component_binding(
            transition_root,
            manifests / f"{protection.manifest_hash}.json",
            protection.manifest_hash,
        ),
        "orchestration_supersession": _component_binding(
            transition_root,
            transition_root / "reports" / "orchestration-supersession.json",
            sha256_file(transition_root / "reports" / "orchestration-supersession.json"),
        ),
        "stage1_trades_resolved_index": _component_binding(
            transition_root, trades_path, trades.manifest_hash
        ),
        "v2_migration_manifest": _component_binding(
            transition_root,
            manifests / f"{migration.manifest_hash}.json",
            migration.manifest_hash,
        ),
    }
    archive_counts = _archive_partition_counts(trades)
    if trades.resolved_partition_count != EXPECTED_RESOLVED_PARTITION_COUNT:
        raise ValueError("resolved Stage 1 Trades partition count is not 4,752")
    if archive_counts != EXPECTED_ARCHIVE_COUNTS:
        raise ValueError("resolved Stage 1 Trades archive layout changed")
    bundle_basis = {
        "schema_name": "stage2-v2-authority-bundle-validation-v1",
        "validation_version": "1.1",
        "status": "PASS",
        "change_request": "CR-2026-013",
        "superseded_authority_change_requests": [
            "CR-2026-009",
            "CR-2026-010",
            "CR-2026-011",
            "CR-2026-012",
        ],
        "transition_run_id": args.transition_run_id,
        "reserved_destination_run_id": args.destination_run_id,
        "destination_status": "RESERVED_NOT_CREATED",
        "destination_created": False,
        "code_commit": head,
        "repository_tree_sha1": _git("rev-parse", "HEAD^{tree}"),
        "runtime_v2_code_tree_sha256": code_tree_hash,
        "quality_evidence": _component_binding(
            transition_root, quality_path, sha256_file(quality_path)
        ),
        "memory_evidence": {
            "source_path": str(memory_path),
            "physical_sha256": sha256_file(memory_path),
            "diagnostic_run_id": memory["diagnostic_run_id"],
        },
        "finalization_memory_evidence": {
            "source_path": str(finalization_memory_path),
            "physical_sha256": sha256_file(finalization_memory_path),
            "diagnostic_run_id": finalization_memory_path.parent.parent.name,
            "packed_row_group_count": finalization_memory["packed_row_group_count"],
            "receipt_count": finalization_memory["receipt_count"],
            "max_arrow_bytes": finalization_memory["max_arrow_bytes"],
            "max_current_rss_bytes": finalization_memory["max_current_rss_bytes"],
            "max_phase_current_rss_delta_bytes": finalization_memory[
                "max_phase_current_rss_delta_bytes"
            ],
            "lifetime_peak_policy": limits["lifetime_peak_policy"],
            "threshold_policy": "AUDIT_ANOMALY_ONLY",
        },
        "stage1_data_run_id": STAGE1_DATA_RUN_ID,
        "stage1_manifest_sha256": STAGE1_MANIFEST_SHA256,
        "stage1_physical_manifest_sha256": STAGE1_PHYSICAL_MANIFEST_SHA256,
        "stage1_catalog_sha256s": STAGE1_CATALOG_SHA256S,
        "stage1_logical_hashes": STAGE1_LOGICAL_HASHES,
        "preregistration_sha256": PREREGISTRATION_SHA256,
        "config_sha256": CONFIG_SHA256,
        "run_a_id": protection.source_run_id,
        "run_a_catalog_logical_hash": protection.catalog_logical_hash,
        "run_a_catalog_physical_hash": protection.catalog_physical_hash,
        "resolved_partition_count": trades.resolved_partition_count,
        "archive_partition_counts": archive_counts,
        "components": components,
    }
    if destination_root.exists():
        raise ValueError("authority freeze must not create the reserved Run B directory")
    basis_hash = hashlib.sha256(canonical_json(bundle_basis).encode()).hexdigest()
    bundle_id = f"stage2-v2-authority-bundle-{basis_hash[:24]}"
    receipt = {
        **bundle_basis,
        "authority_bundle_id": bundle_id,
        "authority_bundle_hash": basis_hash,
    }
    receipt_path = transition_root / "reports" / "authority-bundle-validation.json"
    _write_once(receipt_path, receipt)
    _validate_bundle_receipt(receipt_path, expected_basis=bundle_basis)
    output = {
        "transition_run_id": args.transition_run_id,
        "destination_run_id": args.destination_run_id,
        "code_commit": head,
        "code_tree_sha256": code_tree_hash,
        "quality_evidence_sha256": sha256_file(quality_path),
        "contract_price_manifest": str(price_path),
        "contract_price_manifest_hash": price.manifest_hash,
        "trades_source_index": str(trades_path),
        "trades_source_index_hash": trades.manifest_hash,
        "run_a_protection": str(manifests / f"{protection.manifest_hash}.json"),
        "run_a_protection_hash": protection.manifest_hash,
        "migration_manifest": str(manifests / f"{migration.manifest_hash}.json"),
        "migration_manifest_hash": migration.manifest_hash,
        "runtime_manifest": str(runtime_path),
        "runtime_manifest_hash": runtime.manifest_hash,
        "snapshot_id": runtime.snapshot_id,
        "authority_bundle_id": bundle_id,
        "authority_bundle_hash": basis_hash,
        "authority_bundle_validation": str(receipt_path),
        "authority_bundle_validation_physical_sha256": sha256_file(receipt_path),
    }
    print(canonical_json(output))
    return 0


def _record_failure(args: argparse.Namespace) -> int:
    if args.failure_log is None or args.failed_code_commit is None:
        raise ValueError("record-failure requires --failure-log and --failed-code-commit")
    if (
        args.destination_run_id is not None
        or args.quality_evidence is not None
        or args.memory_evidence is not None
        or args.finalization_memory_evidence is not None
    ):
        raise ValueError("record-failure does not accept freeze inputs")
    if args.failed_code_commit != FAILED_AUTHORITY_COMMIT:
        raise ValueError("failed code commit differs from the frozen failed authority")
    transition_root = _existing_bounded_run_root(args.transition_run_id, "stage2-g1-v2-authority-")
    raw_failure_log = args.failure_log
    if not raw_failure_log.is_file() or raw_failure_log.is_symlink():
        raise FileNotFoundError(raw_failure_log)
    failure_log = raw_failure_log.resolve()
    if not failure_log.is_relative_to((transition_root / "logs").resolve()):
        raise ValueError("failure log must belong to the failed transition run")
    existing_manifests = {
        path.relative_to(transition_root).as_posix(): sha256_file(path)
        for path in sorted((transition_root / "manifests").glob("*.json"))
        if path.is_file() and not path.name.startswith("._")
    }
    reserved_run_b = RUNS_ROOT / FAILED_RESERVED_RUN_B_ID
    if reserved_run_b.exists():
        raise ValueError("failed authority reserved Run B unexpectedly exists")
    payload = {
        "schema_name": "stage2-v2-authority-freeze-failure-v1",
        "failure_version": "1.0",
        "status": "FAILED_AUTHORITY_FREEZE",
        "change_request": "CR-2026-009",
        "transition_run_id": args.transition_run_id,
        "failed_code_commit": args.failed_code_commit,
        "error_type": args.error_type,
        "failure_field": args.failure_field,
        "failure_reason": "CATALOG_AUTHORIZED_DAILY_ARCHIVE_REJECTED_BY_V2_SCHEMA",
        "failure_log_relative_path": failure_log.relative_to(transition_root).as_posix(),
        "failure_log_sha256": sha256_file(failure_log),
        "existing_manifest_physical_sha256s": existing_manifests,
        "source_mutation_allowed": False,
        "reserved_destination_run_id": FAILED_RESERVED_RUN_B_ID,
        "run_b_created": False,
    }
    receipt_path = transition_root / "reports" / "authority-freeze-failure.json"
    _write_once(receipt_path, payload)
    print(
        canonical_json(
            {
                "status": payload["status"],
                "path": str(receipt_path),
                "physical_sha256": sha256_file(receipt_path),
            }
        )
    )
    return 0


def _component_binding(root: Path, path: Path, semantic_sha256: str) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"authority component is missing or unsafe: {path}")
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"authority component is outside the transition run: {path}")
    return {
        "relative_path": resolved.relative_to(root.resolve()).as_posix(),
        "semantic_sha256": semantic_sha256,
        "physical_sha256": sha256_file(resolved),
    }


def _archive_partition_counts(manifest: Any) -> dict[str, dict[str, int]]:
    partitions: dict[str, dict[str, set[str]]] = {
        "BTCUSDT": {"monthly": set(), "daily": set()},
        "ETHUSDT": {"monthly": set(), "daily": set()},
    }
    for entry in manifest.entries:
        key = "monthly" if len(entry.archive_partition) == 7 else "daily"
        partitions[entry.instrument][key].add(entry.archive_partition)
    return {
        instrument: {
            "monthly_archive_count": len(values["monthly"]),
            "daily_archive_count": len(values["daily"]),
        }
        for instrument, values in sorted(partitions.items())
    }


def _validate_bundle_receipt(path: Path, *, expected_basis: dict[str, Any]) -> None:
    receipt = _read_object(path)
    actual_hash = receipt.pop("authority_bundle_hash", None)
    bundle_id = receipt.pop("authority_bundle_id", None)
    if receipt != expected_basis:
        raise ValueError("Authority Bundle validation receipt payload differs")
    expected_hash = hashlib.sha256(canonical_json(expected_basis).encode()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("Authority Bundle validation receipt hash differs")
    if bundle_id != f"stage2-v2-authority-bundle-{expected_hash[:24]}":
        raise ValueError("Authority Bundle validation receipt ID differs")


def _bounded_run_root(run_id: str, prefix: str) -> Path:
    if not run_id.startswith(prefix) or "/" in run_id or ".." in run_id:
        raise ValueError(f"invalid run_id for {prefix}")
    if not Path("/Volumes/FuckingLife").is_mount() or not RUNS_ROOT.is_dir():
        raise FileNotFoundError("approved Stage 2 volume is unavailable")
    root = RUNS_ROOT / run_id
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.resolve().is_relative_to(RUNS_ROOT.resolve()):
        raise ValueError("unsafe Stage 2 run root")
    for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
        (root / name).mkdir(exist_ok=True)
    return root


def _existing_bounded_run_root(run_id: str, prefix: str) -> Path:
    if not run_id.startswith(prefix) or "/" in run_id or ".." in run_id:
        raise ValueError(f"invalid run_id for {prefix}")
    if not Path("/Volumes/FuckingLife").is_mount() or not RUNS_ROOT.is_dir():
        raise FileNotFoundError("approved Stage 2 volume is unavailable")
    root = RUNS_ROOT / run_id
    if not root.is_dir() or root.is_symlink():
        raise FileNotFoundError("failed transition run does not exist")
    if not root.resolve().is_relative_to(RUNS_ROOT.resolve()):
        raise ValueError("unsafe Stage 2 run root")
    return root


def _new_destination_root(run_id: str) -> Path:
    if not run_id.startswith("stage2-g1-v2-b-") or "/" in run_id or ".." in run_id:
        raise ValueError("invalid V2 Run B run_id")
    root = RUNS_ROOT / run_id
    if root.exists():
        raise FileExistsError("destination Run B must not exist before authority freeze")
    if not root.parent.resolve().is_relative_to(RUNS_ROOT.resolve()):
        raise ValueError("unsafe V2 Run B root")
    return root


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return cast(dict[str, Any], value)


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    encoded = (canonical_json(payload) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != encoded:
            raise FileExistsError(f"append-only authority differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


if __name__ == "__main__":
    raise SystemExit(main())
