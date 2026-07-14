"""Resumable Stage 1 full-data build CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from era100x.data.full_build import FullBuild  # noqa: E402
from era100x.data.full_build.builder import checkpoint_status  # noqa: E402


def canonical_config(path: Path) -> tuple[dict[str, object], str]:
    config: dict[str, object] = yaml.safe_load(path.read_text())
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(encoded).hexdigest()


def git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "resume"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--config", type=Path, required=True)
        sub.add_argument("--run-id")
    status = subparsers.add_parser("status")
    status.add_argument("--work-root", type=Path, required=True)
    status.add_argument("--run-id", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--work-root", type=Path, required=True)
    verify.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if args.command in {"status", "verify"}:
        checkpoint = checkpoint_status(args.work_root, args.run_id)
        if args.command == "verify" and checkpoint["status"] != "COMPLETE":
            raise ValueError("run is not complete")
        print(json.dumps(checkpoint, sort_keys=True, indent=2))
        return 0
    config, config_hash = canonical_config(args.config)
    work_root = Path(str(config["work_root"]))
    commit = git_commit()
    run_id = args.run_id
    if args.command == "start":
        if run_id is None:
            timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
            run_id = f"stage1-v1.0-{timestamp}-{commit}-{config_hash[:8]}"
    elif run_id is None:
        raise ValueError("resume requires --run-id")
    assert run_id is not None
    print(f"run_id={run_id}", flush=True)
    builder = FullBuild(work_root, run_id, commit, config_hash)
    checkpoint = builder.run()
    print(json.dumps(checkpoint, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
