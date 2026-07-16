"""Freeze one append-only S2-T10 dual-build execution Manifest at the current HEAD."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from era100x.research.stage_2.manifests.models import Stage2ExecutionManifest
from era100x.research.stage_2.manifests.repository import AppendOnlyManifestRepository

PREREGISTRATION_HASH = "6b0f66e4007b86e08b58a9b366170eeee952199baa203d7f174b2ca69478c1f9"
CONFIG_HASH = "adb6295e210de66d1e69aa008e6161e8fef1e1fd72001ff812b68597f8c72e3f"
FAILED_RUN_ID = "stage2-g1-full-a-20260716-4c15e46"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quality-evidence", type=Path, required=True)
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path(
            "/Volumes/FuckingLife/era100x_stage2/runs/stage2-g1-preregistration-v1.0/manifests"
        ),
    )
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
        raise ValueError("execution Manifest requires a clean worktree")
    raw = args.quality_evidence.read_bytes()
    evidence_hash = hashlib.sha256(raw).hexdigest()
    evidence = json.loads(raw)
    if evidence.get("status") != "PASS" or evidence.get("code_commit") != head:
        raise ValueError("quality evidence does not bind the current passing HEAD")
    manifest = Stage2ExecutionManifest.seal(
        {
            "schema_name": "stage2-group1-execution",
            "manifest_version": "1.2-dual-full-build",
            "preregistration_manifest_hash": PREREGISTRATION_HASH,
            "code_commit": head,
            "fixture_logical_hash": (
                "2fcb1602c86207e7e81c419178acfa9249482231ba26de2e6e80b7603bc7dcf6"
            ),
            "small_sample_validation_hash": (
                "73287e72e480d5946db013377c5dafa11810c720968a957a3b2d73c1032abae8"
            ),
            "config_hash": CONFIG_HASH,
            "stage1_data_run_id": ("stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"),
            "stage1_logical_hashes": {
                "BTCUSDT": ("03d437ed9a6c19d92162e5c9dd115df4988e8accce3c8180b749f15cfdcc36a8"),
                "ETHUSDT": ("6db4d5e411edae3838b352944b83c38ba68915841a1f9c9de8f16ef44c3b8332"),
            },
            "full_run_cli": (
                "uv run python scripts/run_stage2_group1_candidates.py "
                "{preflight,run,resume,verify}"
            ),
            "invalidation_conditions": (
                "code/config/data hash drift",
                "quality or small-sample validation invalidated",
                "CLI, candidate identity, role or publication contract changed",
            ),
            "quality_gate_evidence_hash": evidence_hash,
            "tool_versions": evidence["tool_versions"],
            "recovery": {
                "recovery_of_run_id": FAILED_RUN_ID,
                "supersedes_failed_run_id": FAILED_RUN_ID,
                "failure_reason": (
                    "CR-2026-003 archive path omission and CR-2026-004 legacy candidate identity"
                ),
                "change_request": "CR-2026-003",
                "identity_change_request": "CR-2026-004",
                "fix_code_commit": head,
                "reused_price_staging": False,
            },
        }
    )
    path = AppendOnlyManifestRepository(args.repository).publish(manifest)
    print(json.dumps({"manifest_hash": manifest.manifest_hash, "path": str(path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
