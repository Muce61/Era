#!/usr/bin/env python3
"""Validate and seal the approved CR-2026-011 real-data memory profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2.models import (
    MAX_PROCESS_CURRENT_RSS_BYTES,
    MAX_PROCESS_RSS_DELTA_BYTES,
)

STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
RUNS_ROOT = STAGE2_ROOT / "runs"
ARROW_LIMIT_BYTES = 1_073_741_824
CASES = (
    "BTCUSDT-2020-01-01",
    "BTCUSDT-2026-02-05",
    "BTCUSDT-2026-07-01",
    "ETHUSDT-2026-02-05",
    "ETHUSDT-2026-07-01",
)
REPLAY_CASES = (
    "BTCUSDT-2020-01-01",
    "BTCUSDT-2026-07-01",
    "ETHUSDT-2026-02-05",
)
LEGACY_FAILURE_TRADE_HASH = "bc07b6eac3e5b16d441d663640621164eec1872997ffa07e9fa6e3e34dcc32da"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--diagnostic-run-id", required=True)
    result.add_argument("--legacy-red-profile", type=Path, required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = _diagnostic_root(args.diagnostic_run_id)
    report_root = root / "reports"
    profiles = {case: _read_profile(report_root / f"{case}.json") for case in CASES}
    replays = {case: _read_profile(report_root / f"{case}-replay2.json") for case in REPLAY_CASES}
    legacy = _read_json(args.legacy_red_profile)
    if legacy.get("implementation") != "pre-cr011-full-day-polars-scan":
        raise ValueError("legacy red profile implementation marker changed")
    if legacy.get("trade_semantic_hash") != LEGACY_FAILURE_TRADE_HASH:
        raise ValueError("legacy failure-day semantic hash changed")
    if profiles["BTCUSDT-2020-01-01"]["result"]["trade_second_semantic_sha256"] != (
        LEGACY_FAILURE_TRADE_HASH
    ):
        raise ValueError("row-group correction changed the original failure-day semantics")
    for case, replay in replays.items():
        original = profiles[case]
        for field in (
            "price_arrow_bytes",
            "bars_arrow_bytes",
            "trade_second_arrow_bytes",
            "trade_second_rows",
            "price_semantic_sha256",
            "bars_semantic_sha256",
            "trade_second_semantic_sha256",
        ):
            if original["result"][field] != replay["result"][field]:
                raise ValueError(f"memory-profile deterministic field differs: {case}/{field}")
    maximums = {
        "current_rss_bytes": max(
            item["result"]["max_current_rss_bytes"] for item in profiles.values()
        ),
        "current_rss_delta_bytes": max(
            item["result"]["max_current_rss_delta_bytes"] for item in profiles.values()
        ),
        "peak_rss_bytes": max(item["result"]["max_peak_rss_bytes"] for item in profiles.values()),
        "peak_rss_delta_bytes": max(
            item["result"]["max_peak_rss_delta_bytes"] for item in profiles.values()
        ),
        "arrow_table_bytes": max(
            item["result"]["max_arrow_table_bytes"] for item in profiles.values()
        ),
    }
    if maximums["current_rss_bytes"] >= MAX_PROCESS_CURRENT_RSS_BYTES:
        raise ValueError("profile exceeded the proposed current-RSS gate")
    if maximums["peak_rss_delta_bytes"] >= MAX_PROCESS_RSS_DELTA_BYTES:
        raise ValueError("profile exceeded the proposed baseline-relative RSS gate")
    if maximums["arrow_table_bytes"] >= ARROW_LIMIT_BYTES:
        raise ValueError("profile exceeded the independent Arrow inflight gate")
    payload: dict[str, Any] = {
        "schema_name": "stage2-v2-memory-profile-evidence",
        "evidence_version": "1.0",
        "status": "PASS",
        "change_request": "CR-2026-011",
        "diagnostic_run_id": args.diagnostic_run_id,
        "read_only": True,
        "cases": {
            case: {
                "profile_sha256": _sha256(report_root / f"{case}.json"),
                "source_trade_rows": profiles[case]["source"]["trade_rows"],
                "result": profiles[case]["result"],
            }
            for case in CASES
        },
        "replay_cases": {
            case: {
                "profile_sha256": _sha256(report_root / f"{case}-replay2.json"),
                "semantic_match": True,
            }
            for case in REPLAY_CASES
        },
        "legacy_red_profile_sha256": _sha256(args.legacy_red_profile),
        "legacy_failure_trade_semantic_sha256": LEGACY_FAILURE_TRADE_HASH,
        "maximums": maximums,
        "gates": {
            "arrow_inflight_bytes": ARROW_LIMIT_BYTES,
            "process_current_rss_bytes": MAX_PROCESS_CURRENT_RSS_BYTES,
            "process_peak_rss_delta_bytes": MAX_PROCESS_RSS_DELTA_BYTES,
        },
        "deterministic_replay": "PASS",
        "semantic_regression": "PASS",
    }
    encoded = (canonical_json(payload) + "\n").encode()
    digest = hashlib.sha256(encoded).hexdigest()
    path = report_root / f"memory-profile-evidence-{digest}.json"
    _write_once(path, encoded)
    print(canonical_json({"path": str(path), "evidence_sha256": digest, "maximums": maximums}))
    return 0


def _diagnostic_root(run_id: str) -> Path:
    if not run_id.startswith("stage2-g1-v2-memory-diagnostic-cr-2026-011-"):
        raise ValueError("invalid CR-2026-011 diagnostic run_id")
    if "/" in run_id or ".." in run_id or not Path("/Volumes/FuckingLife").is_mount():
        raise ValueError("unsafe CR-2026-011 diagnostic authority")
    root = (RUNS_ROOT / run_id).resolve()
    if not root.is_dir() or root.is_symlink() or not root.is_relative_to(RUNS_ROOT.resolve()):
        raise FileNotFoundError(root)
    return root


def _read_profile(path: Path) -> dict[str, Any]:
    profile = _read_json(path)
    if (
        profile.get("schema_name") != "stage2-v2-foundation-memory-profile"
        or profile.get("change_request") != "CR-2026-011"
        or profile.get("read_only") is not True
    ):
        raise ValueError(f"invalid CR-2026-011 profile: {path}")
    return profile


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _write_once(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise FileExistsError(f"append-only memory evidence differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
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


if __name__ == "__main__":
    raise SystemExit(main())
