"""Freeze the fixed S2-T10 v1.8 Runtime V2 authority chain."""

from __future__ import annotations

import argparse
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


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Freeze Runtime V2 authorities")
    result.add_argument("--transition-run-id", required=True)
    result.add_argument("--destination-run-id", required=True)
    result.add_argument("--quality-evidence", required=True, type=Path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
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
    )
    authorities = tuple(
        DigestBinding(name=name, sha256=digest)
        for name, digest in sorted(
            {
                "contract_price_inventory": CONTRACT_PRICE_INVENTORY_SHA256,
                CONTRACT_PRICE_MANIFEST_AUTHORITY: price.manifest_hash,
                "runtime_v2_quality_evidence": sha256_file(quality_path),
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
    }
    print(canonical_json(output))
    return 0


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
