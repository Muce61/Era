#!/usr/bin/env python3
"""Audit CR-2026-015 and adopt sealed monthly results into one fresh run."""

from __future__ import annotations

import argparse
from pathlib import Path

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2.group1_packing_recovery import (
    Group1MonthlyAdoptionManifestV1,
    PackedArtifactAuditV1,
    adopt_completed_monthly_results,
    audit_failed_packing,
)

ROOT = Path("/Volumes/FuckingLife/era100x_stage2")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="CR-2026-015 Group-1 packing recovery")
    actions = result.add_subparsers(dest="action", required=True)
    audit = actions.add_parser("audit")
    audit.add_argument("--source-run-id", required=True)
    adopt = actions.add_parser("adopt")
    adopt.add_argument("--source-run-id", required=True)
    adopt.add_argument("--destination-run-id", required=True)
    adopt.add_argument("--destination-manifest", type=Path, required=True)
    return result


def _run(run_id: str) -> Path:
    if not run_id.startswith("stage2-g1-v2-b-") or "/" in run_id or ".." in run_id:
        raise ValueError("run ID is outside the approved V2 Run-B namespace")
    path = ROOT / "runs" / run_id
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to((ROOT / "runs").resolve(strict=True)) or path.is_symlink():
        raise ValueError("run path escapes the approved Stage 2 root")
    return path


def main() -> int:
    args = parser().parse_args()
    source = _run(args.source_run_id)
    result: PackedArtifactAuditV1 | Group1MonthlyAdoptionManifestV1
    if args.action == "audit":
        result = audit_failed_packing(source)
    else:
        result = adopt_completed_monthly_results(
            source_root=source,
            destination_root=_run(args.destination_run_id),
            destination_manifest_path=args.destination_manifest,
        )
    print(canonical_json(result.model_dump(mode="json")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
