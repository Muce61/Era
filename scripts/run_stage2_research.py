"""Fixed S2-T10 v1.8 Runtime V2 command surface.

There are deliberately no instrument, variant, threshold, worker, root, source,
or plugin overrides.  Every command is bound to the same explicit Manifest,
snapshot, Run-A protection authority and migration authority.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2.orchestrator import (
    RuntimeComparison,
    RuntimeV2Backend,
    RuntimeVerification,
    Stage2V2Orchestrator,
)
from era100x.research.stage_2.runtime_v2.checkpoint import RuntimeV2Checkpoint

COMMANDS = (
    "preflight",
    "build-foundation",
    "run-group1",
    "resume",
    "release",
    "verify",
    "compare",
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Stage 2 Group-1 Runtime V2")
    commands = root.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        command = commands.add_parser(name)
        command.add_argument("--run-id", required=True)
        command.add_argument("--manifest", required=True, type=Path)
        command.add_argument("--snapshot-id", required=True)
        command.add_argument("--run-a-protection", required=True, type=Path)
        command.add_argument("--migration-manifest", required=True, type=Path)
    return root


def main(
    argv: Sequence[str] | None = None,
    *,
    backend: RuntimeV2Backend | None = None,
) -> int:
    args = parser().parse_args(argv)
    if backend is None:
        # Production is a static repository registration.  Tests may still
        # inject an explicit fake backend without importing production source
        # authorities or touching the approved external volume.
        from era100x.research.stage_2.runtime_v2.production_backend import (
            ProductionRuntimeV2Backend,
        )

        backend = ProductionRuntimeV2Backend()
    orchestrator = Stage2V2Orchestrator(backend)
    result: RuntimeV2Checkpoint | RuntimeVerification | RuntimeComparison
    common = {
        "run_id": args.run_id,
        "manifest_path": args.manifest,
        "snapshot_id": args.snapshot_id,
        "protection_path": args.run_a_protection,
        "migration_path": args.migration_manifest,
    }
    if args.command == "preflight":
        result = orchestrator.preflight(**common)
    elif args.command == "build-foundation":
        result = orchestrator.build_foundation(**common)
    elif args.command == "run-group1":
        result = orchestrator.run_group1(**common)
    elif args.command == "resume":
        result = orchestrator.resume(**common)
    elif args.command == "release":
        result = orchestrator.release(**common)
    elif args.command == "verify":
        result = orchestrator.verify(**common)
    elif args.command == "compare":
        result = orchestrator.compare(**common)
    else:  # pragma: no cover - argparse rejects unknown commands.
        raise AssertionError(f"unreachable command: {args.command}")
    print(canonical_json(result.model_dump(mode="json")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
