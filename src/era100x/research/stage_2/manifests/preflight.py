"""Read-only Stage 1 verification and Stage 2 external-root preflight."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

from .configuration import config_hash, parameter_sets, timing_configurations
from .models import (
    OutputPolicy,
    ResearchPeriod,
    Stage1Baseline,
    Stage2PreregistrationManifest,
    canonical_json,
)
from .repository import AppendOnlyManifestRepository

STAGE1_RUN_ID = "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
EXPECTED_CANONICAL_MANIFEST_HASH = (
    "436ffbe36e310dd015a962a29593360729d06db25ff96eddf12644c62d76e94f"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_stage1_manifest(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    claimed = payload.pop("manifest_sha256")
    computed = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if claimed != computed or computed != EXPECTED_CANONICAL_MANIFEST_HASH:
        raise ValueError("Stage 1 canonical manifest hash changed")
    if payload["run_id"] != STAGE1_RUN_ID:
        raise ValueError("Stage 1 data run changed")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def contract_price_inventory(root: Path) -> tuple[str, int]:
    records: list[dict[str, object]] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        directory = root / f"{instrument}_1s_agg"
        csv_files = sorted(directory.glob(f"{instrument}_1s_*.csv"))
        parquet_files = sorted(directory.glob(f"{instrument}_1s_*.parquet"))
        if len(csv_files) != 2016 or len(parquet_files) != 371:
            raise ValueError(
                f"{instrument} Contract Price physical inventory changed: "
                f"csv={len(csv_files)}, parquet={len(parquet_files)}"
            )
        files = csv_files + parquet_files
        by_date: dict[str, set[str]] = {}
        for path in files:
            match = re.search(r"(\d{8})(?=\.(?:csv|parquet)$)", path.name)
            if match is None:
                raise ValueError(f"unrecognized Contract Price filename: {path.name}")
            day = match.group(1)
            by_date.setdefault(day, set()).add(path.suffix)
            records.append(
                {
                    "instrument": instrument,
                    "date": day,
                    "relative_path": str(path.relative_to(root)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "canonical_for_date": path.suffix == ".csv"
                    or ".csv" not in by_date.get(day, set()),
                }
            )
        if len(by_date) != 2376:
            raise ValueError(f"{instrument} Contract Price date coverage changed: {len(by_date)}")
        if sum(formats == {".csv", ".parquet"} for formats in by_date.values()) != 11:
            raise ValueError(f"{instrument} Contract Price overlap policy changed")
    return hashlib.sha256(canonical_json(records).encode()).hexdigest(), len(records)


def initialize_external_root(root: Path, run_id: str) -> tuple[Path, int]:
    if str(root) != "/Volumes/FuckingLife/era100x_stage2":
        raise ValueError("unapproved Stage 2 root")
    run_root = root / "runs" / run_id
    if run_root.exists():
        raise FileExistsError("run root already exists")
    for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
        (run_root / name).mkdir(parents=True, exist_ok=False)
    probe = run_root / "tmp" / ".write-probe"
    probe.write_bytes(b"stage2-write-probe\n")
    with probe.open("rb") as stream:
        os.fsync(stream.fileno())
    probe.unlink()
    return run_root, shutil.disk_usage(root).free


def estimate_peak_bytes(
    *,
    days: int = 2376,
    min_episode_gap_seconds: int = 60,
    parameter_sets: int = 20,
    variants: int = 2,
    instruments: int = 2,
    complete_publications: int = 2,
    staging_copies: int = 1,
    schema_max_record_bytes: int = 2048,
) -> int:
    episodes_per_day = 86_400 // min_episode_gap_seconds
    copies = complete_publications + staging_copies
    return (
        days
        * episodes_per_day
        * parameter_sets
        * variants
        * instruments
        * copies
        * schema_max_record_bytes
    )


def create_preregistration(
    *,
    governance_commit: str,
    stage1_run_root: Path,
    contract_price_root: Path,
    stage2_root: Path,
) -> tuple[Stage2PreregistrationManifest, Path]:
    """Perform the real S2-T19 baseline/root gate and publish one immutable manifest."""

    stage1_payload, physical_manifest_hash = verify_stage1_manifest(
        stage1_run_root / "manifest.json"
    )
    symbols = stage1_payload["symbols"]
    inventory_hash, inventory_count = contract_price_inventory(contract_price_root)
    prereg_run_id = "stage2-g1-preregistration-v1.0"
    run_root, free_bytes = initialize_external_root(stage2_root, prereg_run_id)
    peak = estimate_peak_bytes()
    required = peak * 120 // 100
    if free_bytes < required:
        raise OSError(f"Stage 2 space gate failed: {free_bytes} < {required}")
    baseline = Stage1Baseline(
        baseline_version="v1.0",
        tag="stage-1-v1.0-passed",
        commit="b7d4ff3d18dcfc515feb8892659cb0b186cd68f8",
        data_run_id=STAGE1_RUN_ID,
        canonical_manifest_sha256=EXPECTED_CANONICAL_MANIFEST_HASH,
        physical_manifest_sha256=physical_manifest_hash,
        btc_catalog_sha256=sha256_file(stage1_run_root / "BTCUSDT.catalog.json"),
        eth_catalog_sha256=sha256_file(stage1_run_root / "ETHUSDT.catalog.json"),
        btc_trades_logical_hash=symbols["BTCUSDT"]["logical_data_hash"],
        eth_trades_logical_hash=symbols["ETHUSDT"]["logical_data_hash"],
        contract_price_inventory_hash=inventory_hash,
        contract_price_file_count=inventory_count,
    )
    payload: dict[str, Any] = {
        "schema_name": "stage2-group1-preregistration",
        "manifest_version": "1.0",
        "research_run_family": "stage2-group1-event-construction",
        "stage_plan_version": "1.2",
        "task_version": "1.3",
        "manual_version": "V1.3.4",
        "governance_commit": governance_commit,
        "stage1": baseline,
        "instruments": ("BTCUSDT", "ETHUSDT"),
        "primary_instrument": "BTCUSDT",
        "secondary_instrument": "ETHUSDT",
        "direction": "LONG",
        "evidence_level": "H2_HISTORICAL_CONDITIONAL_EVENT_EVIDENCE",
        "primary_hypothesis": (
            "strict TARGET_FIRST probability exceeds same-instrument conditional random baseline"
        ),
        "primary_label": "TARGET_FIRST_STRICT",
        "ambiguous_primary_treatment": "FAILURE",
        "time_semantics": "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN",
        "timing_configurations": timing_configurations(),
        "periods": (
            ResearchPeriod(
                period_id="P1", start_ns=1577836800000000000, end_ns=1640995200000000000
            ),
            ResearchPeriod(
                period_id="P2", start_ns=1640995200000000000, end_ns=1704067200000000000
            ),
            ResearchPeriod(
                period_id="P3", start_ns=1704067200000000000, end_ns=1783123200000000000
            ),
        ),
        "parameter_sets": parameter_sets(),
        "target_domain_bps": tuple(map(Decimal, ("20", "30", "40", "50", "70", "100"))),
        "stop_domain_bps": tuple(map(Decimal, ("15", "20", "25", "30", "35"))),
        "matching_fields_never_relaxed": (
            "instrument",
            "direction",
            "high_timeframe_trend_state",
            "pre_registered_period",
            "research_split_or_fold",
        ),
        "matching_relaxation_order": ("L0", "L1", "L2", "L3", "L4", "L5"),
        "controls_per_episode": 5,
        "matching_seed": 20260716,
        "bootstrap_seed": 20260716,
        "cluster_definition": "instrument_x_utc_calendar_week",
        "bootstrap_iterations": 5000,
        "ci_definition": "two_sided_95_percentile_bootstrap",
        "primary_failure_lines": tuple(f"F{i}" for i in range(1, 11)),
        "eth_secondary_classes": (
            "REPLICATED",
            "BTC_ONLY",
            "NOT_REPLICATED",
            "PRIMARY_FAILED",
        ),
        "purge_embargo_rule": "period_and_split_safe; purge >= max lookback + max episode/horizon",
        "small_sample_windows": (
            "P1_FIRST_FULL_UTC_WEEK_PLUS_PREVIOUS_DAY_WARMUP",
            "P2_FIRST_FULL_UTC_WEEK_PLUS_PREVIOUS_DAY_WARMUP",
            "P3_FIRST_FULL_UTC_WEEK_PLUS_PREVIOUS_DAY_WARMUP",
        ),
        "full_input_period": "[2020-01-01T00:00:00Z,2026-07-04T00:00:00Z)",
        "allowed_outputs": (
            "canonical_key_levels",
            "raw_key_levels",
            "arbitration",
            "sweeps",
            "reclaims",
            "holds",
            "price_triggers",
            "flow_features",
            "market_episodes",
            "candidate_inclusion",
            "catalog",
            "manifest",
            "quality_report",
            "count_summary",
        ),
        "prohibited_metrics": (
            "MFE",
            "MAE",
            "TIME_TO_ACTIVATION",
            "TARGET_FIRST",
            "STOP_FIRST",
            "AMBIGUOUS_LABEL",
            "BOOTSTRAP",
            "CI",
            "PNL",
            "RETURN",
        ),
        "prohibited_capabilities": (
            "BID",
            "ASK",
            "SPREAD",
            "TS_RECV",
            "L2",
            "QUEUE_POSITION",
            "PARTIAL_FILL",
            "ACTUAL_SLIPPAGE",
            "PRIVATE_ORDER_FLOW",
            "TRADING_CONNECTION",
        ),
        "full_run_cli": (
            "uv run python scripts/run_stage2_group1_candidates.py {preflight,run,resume,verify}"
        ),
        "output_policy": OutputPolicy(
            root=str(stage2_root),
            layout=("staging", "published", "manifests", "reports", "logs", "tmp"),
            append_only_directories=("published", "manifests", "reports"),
            required_free_space_multiplier=Decimal("1.20"),
            estimated_peak_bytes=peak,
            required_free_bytes=required,
            available_free_bytes=free_bytes,
        ),
        "invalidation_conditions": (
            "Stage 1 baseline, manifest, catalog, logical hash or Contract Price inventory changes",
            "ADR-S2-004 or ADR-S2-005 definition changes",
            "config, code, split, purge or embargo changes",
            "append-only or CLI contract changes",
        ),
        "config_hash": config_hash(),
    }
    manifest = Stage2PreregistrationManifest.seal(payload)
    path = AppendOnlyManifestRepository(run_root / "manifests").publish(manifest)
    return manifest, path
