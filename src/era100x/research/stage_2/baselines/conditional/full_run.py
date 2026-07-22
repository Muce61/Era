"""Append-only governance and evidence gates for the S2-T15 v1.4 full run."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.runtime_v2.models import Receipt

from .receipt_supplement import latest_valid_receipt_distribution_supplement
from .binning_run import read_binning_set
from .v14_contracts import (
    COMBINATION_ORDER,
    EXPECTED_H2_OUTCOME_CELLS,
    EXPECTED_H2_PATHS,
    S2T15ContractAuthority,
    canonical_hash,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
AUTHORITY_ROOT = STAGE2_ROOT / "authorities" / "S2-T15" / "v1.4"
AUDIT_ROOT = AUTHORITY_ROOT / "audits"
BIN_ROOT = AUTHORITY_ROOT / "binning"
RUNS_ROOT = STAGE2_ROOT / "runs"

T10_RUN_ID = "stage2-g1-v2-b-20260720T111704Z-9c4b7c423a04"
T10_SNAPSHOT_ID = "df15b9cbb208a6f921b3a68bee24be44f77e83eb2c8ac1582ef942b108708d33"
T13_RUN_ID = "stage2-s2t13-first-passage-20260721T110224Z-d3f0c0331395"
T13_SNAPSHOT_ID = "3ea1f8e188c4cf605c05c49bc86118925784b27a3b7c0e9c1969edda7a295da0"
T14_RUN_ID = "stage2-s2t14-ambiguity-bounds-20260721T140507Z-8b4cf765602d"
T14_SNAPSHOT_ID = "d1c21c10ceb344814d321c1ca4b52f44977cdced55f63d79b54bff86e0e6cf2c"
T11_RUN_ID = "stage2-s2t11-paths-20260721T023117Z-029707f3c111"
T11_SNAPSHOT_ID = "d4d6a2f5c72a9fb8c964585a009d2c11048b1baa34432d3d16fb68ee9ff3979c"
T11_AUTHORITY_HASH = "029707f3c11104e8cf4919afd0cf25e608dfdc3b20cf6bd85f3f6e710f7eeef6"

T10_SNAPSHOT = RUNS_ROOT / T10_RUN_ID / "published" / "snapshots" / T10_SNAPSHOT_ID
T13_SNAPSHOT = RUNS_ROOT / T13_RUN_ID / "published" / "snapshots" / T13_SNAPSHOT_ID
T14_SNAPSHOT = RUNS_ROOT / T14_RUN_ID / "published" / "snapshots" / T14_SNAPSHOT_ID
T11_SNAPSHOT = RUNS_ROOT / T11_RUN_ID / "published" / "snapshots" / T11_SNAPSHOT_ID
T11_AUTHORITY = STAGE2_ROOT / "authorities" / "S2-T11" / f"{T11_AUTHORITY_HASH}.json"

GOVERNANCE_FILES = (
    REPOSITORY_ROOT / "docs/development/changes/CR-2026-026.md",
    REPOSITORY_ROOT / "docs/development/changes/CR-2026-027.md",
    REPOSITORY_ROOT / "docs/development/decisions/ADR-S2-009-conditional-baseline-v1.4.md",
    REPOSITORY_ROOT / "docs/development/tasks/stage_2/S2-T15-task.md",
    REPOSITORY_ROOT / "docs/development/tasks/stage_2/S2-T19-manifest.md",
)
REQUIRED_T10_DATASETS = {
    ("causal_price_bars", "2.0"),
    ("trade_second_primitives", "2.0"),
    ("contract_price_1s", "2.0"),
    ("canonical_key_levels", "group1-v1-price-v1"),
    ("market_episodes", "group1-v1-price-v1"),
    ("market_episodes", "group1-v1-flow-v1"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe, symlinked or missing evidence: {path}")


def _read_json(path: Path) -> dict[str, Any]:
    _safe_file(path)
    return cast(dict[str, Any], json.loads(path.read_bytes()))


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise ValueError(f"append-only evidence conflict: {path}") from None


def current_code_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True
    ).strip()


def repository_is_clean() -> bool:
    output = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=REPOSITORY_ROOT, text=True
    )
    return not output.strip()


def _governance_binding() -> dict[str, str]:
    for path in GOVERNANCE_FILES:
        _safe_file(path)
    cr = GOVERNANCE_FILES[0].read_text()
    receiver_cr = GOVERNANCE_FILES[1].read_text()
    adr = GOVERNANCE_FILES[2].read_text()
    task = GOVERNANCE_FILES[3].read_text()
    oq = (REPOSITORY_ROOT / "docs/development/OPEN_QUESTIONS.md").read_text()
    required = (
        ("CR approval", "status: APPROVED", cr),
        ("receiver CR approval", "status: APPROVED", receiver_cr),
        ("ADR approval", "APPROVED", adr),
        ("Task v1.4", "task_version: 1.4", task),
        ("OQ resolution", "OQ-S2-005", oq),
        ("OQ resolved state", "| RESOLVED | S2-T15 full conditional baseline", oq),
        ("receiver OQ resolved state", "| RESOLVED | S2-T15 upstream binding", oq),
    )
    for label, marker, content in required:
        if marker not in content:
            raise ValueError(f"S2-T15 governance gate missing: {label}")
    return {str(path.relative_to(REPOSITORY_ROOT)): sha256_file(path) for path in GOVERNANCE_FILES}


def audit_upstream(*, write_report: bool = True) -> dict[str, Any]:
    """Read and hash accepted T10/T13/T14 evidence without creating Authority/Run."""

    governance = _governance_binding()
    t10_manifest_path = T10_SNAPSHOT / "manifest.json"
    t10_catalog_path = T10_SNAPSHOT / "catalog.json"
    t13_manifest_path = T13_SNAPSHOT / "manifest.json"
    t13_catalog_path = T13_SNAPSHOT / "catalog.json"
    t14_manifest_path = T14_SNAPSHOT / "manifest.json"
    t14_catalog_path = T14_SNAPSHOT / "catalog.json"
    t11_manifest_path = T11_SNAPSHOT / "manifest.json"
    t11_catalog_path = T11_SNAPSHOT / "catalog.json"
    paths = (
        t10_manifest_path,
        t10_catalog_path,
        t13_manifest_path,
        t13_catalog_path,
        t14_manifest_path,
        t14_catalog_path,
        t11_manifest_path,
        t11_catalog_path,
        T11_AUTHORITY,
    )
    for path in paths:
        _safe_file(path)
    t10_manifest = _read_json(t10_manifest_path)
    t13_manifest = _read_json(t13_manifest_path)
    t13_catalog = _read_json(t13_catalog_path)
    t14_manifest = _read_json(t14_manifest_path)
    t14_catalog = _read_json(t14_catalog_path)
    t11_manifest = _read_json(t11_manifest_path)
    t11_catalog = _read_json(t11_catalog_path)
    t11_authority = _read_json(T11_AUTHORITY)
    if t13_manifest.get("snapshot_id") != T13_SNAPSHOT_ID:
        raise ValueError("T13 snapshot binding drift")
    if t14_manifest.get("snapshot_id") != T14_SNAPSHOT_ID:
        raise ValueError("T14 snapshot binding drift")
    if t14_manifest.get("source_s2t13_snapshot_id") != T13_SNAPSHOT_ID:
        raise ValueError("T14 no longer binds accepted T13")
    if (
        t11_manifest.get("manifest_hash") != T11_SNAPSHOT_ID
        or t11_catalog.get("catalog_hash") != t13_manifest.get("source_s2t11_catalog_hash")
        or t13_manifest.get("source_s2t11_manifest_hash") != T11_SNAPSHOT_ID
        or t11_authority.get("authority_hash") != T11_AUTHORITY_HASH
    ):
        raise ValueError("T11/Stage1 direct binding drift")
    if t14_catalog.get("combination_order") != list(COMBINATION_ORDER):
        raise ValueError("T14 30-cell combination order drift")
    if len(t14_catalog.get("parameter_set_timing_pairs", [])) != 19:
        raise ValueError("registered 19 parameter/timing pair universe drift")

    t10_specs = {
        (str(item.get("dataset_name")), str(item.get("dataset_version"))): item
        for item in cast(list[dict[str, Any]], t10_manifest.get("dataset_specs", []))
    }
    missing_specs = REQUIRED_T10_DATASETS.difference(t10_specs)
    if missing_specs:
        raise ValueError(f"T10 lacks required T15 datasets: {sorted(missing_specs)}")
    required_fields = {
        ("causal_price_bars", "2.0"): {
            "instrument",
            "interval_seconds",
            "event_ts_ns",
            "available_at_ns",
            "close",
            "source_file_sha256",
        },
        ("trade_second_primitives", "2.0"): {
            "instrument",
            "event_ts_ns",
            "second_end_ns",
            "available_at_ns",
            "trade_count",
            "source_logical_hash",
        },
        ("contract_price_1s", "2.0"): {
            "instrument",
            "event_ts_ns",
            "available_at_ns",
            "close",
            "source_file_sha256",
        },
        ("canonical_key_levels", "group1-v1-price-v1"): {
            "instrument",
            "available_at_ts",
            "key_level_id",
            "level_price",
            "priority",
            "expires_at_ns",
            "status",
            "event_parameter_set_id",
        },
        ("market_episodes", "group1-v1-price-v1"): {
            "instrument",
            "market_episode_id",
            "canonical_key_level_id",
            "parameter_set_id",
            "time_combination_id",
            "sweep_start_ns",
            "direction",
        },
        ("market_episodes", "group1-v1-flow-v1"): {
            "instrument",
            "market_episode_id",
            "canonical_key_level_id",
            "parameter_set_id",
            "time_combination_id",
            "sweep_start_ns",
            "direction",
        },
    }
    for key, expected in required_fields.items():
        actual = {str(field.get("name")) for field in t10_specs[key].get("fields", [])}
        if not expected.issubset(actual):
            raise ValueError(f"T10 {key} lacks required fields: {sorted(expected - actual)}")

    t13_h2_paths = 0
    t13_rows = 0
    t13_cells = 0
    t13_files: dict[str, dict[str, Any]] = {}
    registered_pairs: set[tuple[str, str]] = set()
    for instrument in ("BTCUSDT", "ETHUSDT"):
        path = T13_SNAPSHOT / instrument / "first_passage.parquet"
        _safe_file(path)
        metadata = pq.ParquetFile(path).metadata
        catalog_item = cast(dict[str, Any], t13_catalog["instruments"][instrument])
        digest = sha256_file(path)
        if digest != catalog_item["sha256"]:
            raise ValueError(f"T13 {instrument} Parquet hash drift")
        rows = metadata.num_rows
        if rows != int(catalog_item["first_passage"]["row_count"]):
            raise ValueError(f"T13 {instrument} row count drift")
        h2 = int(catalog_item["first_passage"]["evidence_level_counts"]["H2"])
        cells = h2 * 30
        t13_h2_paths += h2
        t13_rows += rows
        t13_cells += cells
        t13_files[instrument] = {"sha256": digest, "row_count": rows, "h2_paths": h2}
        pair_table = pq.read_table(
            path, columns=["parameter_set_id", "timing_id", "evidence_level"]
        )
        for row in pair_table.to_pylist():
            if row["evidence_level"] == "H2":
                registered_pairs.add((str(row["parameter_set_id"]), str(row["timing_id"])))
    if t13_h2_paths != EXPECTED_H2_PATHS or t13_cells != EXPECTED_H2_OUTCOME_CELLS:
        raise ValueError("sealed T13 H2 path/cell baseline drift")
    if len(registered_pairs) != 19:
        raise ValueError("sealed T13 no longer contains exactly 19 H2 parameter/timing pairs")

    t14_distributions = sum(
        int(item["distribution_count"])
        for item in cast(dict[str, dict[str, Any]], t14_catalog["instruments"]).values()
    )
    if t14_distributions != 2_280:
        raise ValueError("T14 aggregate distribution count drift")
    for instrument in ("BTCUSDT", "ETHUSDT"):
        path = T14_SNAPSHOT / instrument / "ambiguity_distributions.json"
        _safe_file(path)
        expected = t14_catalog["instruments"][instrument]["sha256"]
        if sha256_file(path) != expected:
            raise ValueError(f"T14 {instrument} aggregate hash drift")

    t10_checkpoint = _read_json(RUNS_ROOT / T10_RUN_ID / "checkpoint-v2.json")
    if t10_checkpoint.get("status") != "GROUP1_COMPLETE":
        raise ValueError("T10 fixed Run is no longer complete")
    t10_objects = T10_SNAPSHOT / "objects.parquet"
    t10_fragments = T10_SNAPSHOT / "fragments.parquet"
    t10_partitions = T10_SNAPSHOT / "logical_partitions.parquet"
    for path in (t10_objects, t10_fragments, t10_partitions):
        _safe_file(path)
    counts = {
        "objects": pq.ParquetFile(t10_objects).metadata.num_rows,
        "fragments": pq.ParquetFile(t10_fragments).metadata.num_rows,
        "logical_partitions": pq.ParquetFile(t10_partitions).metadata.num_rows,
    }
    if counts != {"objects": 208, "fragments": 77_265, "logical_partitions": 80_784}:
        raise ValueError("T10 fixed Run inventory drift")
    partition_table = pq.read_table(t10_partitions, columns=["semantic_order_key"])
    setup_context_counts: dict[str, int] = {}
    for value in partition_table["semantic_order_key"].to_pylist():
        parts = str(value).split("\x1f")
        if len(parts) != 9:
            raise ValueError("T10 logical partition semantic order key is malformed")
        setup_context = f"{parts[3]}@1.0|{parts[4]}@1.0"
        setup_context_counts[setup_context] = setup_context_counts.get(setup_context, 0) + 1
    expected_setup_contexts = {
        "KEY_LOW_SWEEP_RECLAIM_HOLD_V1@1.0|CAUSAL_EMA20_1H@1.0": 61_776,
        "FEATURE_FOUNDATION@1.0|FROZEN_STAGE1@1.0": 19_008,
    }
    if setup_context_counts != expected_setup_contexts:
        raise ValueError(f"T10 setup/context binding drift: {setup_context_counts}")
    receipt_table = pq.read_table(
        t10_partitions,
        columns=["partition_id", "semantic_order_key", "payload"],
    )
    required_dataset_keys = set(REQUIRED_T10_DATASETS)
    receipt_distribution_audit: dict[str, dict[str, Any]] = {}
    for partition_id, order_key, raw_payload in zip(
        receipt_table["partition_id"].to_pylist(),
        receipt_table["semantic_order_key"].to_pylist(),
        receipt_table["payload"].to_pylist(),
        strict=True,
    ):
        parts = str(order_key).split("\x1f")
        key = (parts[0], parts[1])
        if key not in required_dataset_keys:
            continue
        receipt = Receipt.model_validate_json(bytes(raw_payload))
        if receipt.partition.partition_id != str(partition_id):
            raise ValueError("T10 receipt payload partition binding drift")
        label = f"{key[0]}@{key[1]}"
        item = receipt_distribution_audit.setdefault(
            label,
            {"partition_count": 0, "missing_distribution_partition_count": 0, "examples": []},
        )
        item["partition_count"] += 1
        expected_names = {
            f"field.{name}" for name in cast(list[str], t10_specs[key]["distribution_fields"])
        }
        actual_names = {value.name for value in receipt.distributions}
        if not expected_names.issubset(actual_names):
            item["missing_distribution_partition_count"] += 1
            if len(item["examples"]) < 3:
                item["examples"].append(
                    {
                        "partition_id": str(partition_id),
                        "missing": sorted(expected_names - actual_names),
                    }
                )
    distribution_gap_count = sum(
        int(item["missing_distribution_partition_count"])
        for item in receipt_distribution_audit.values()
    )
    supplement = latest_valid_receipt_distribution_supplement()
    supplement_manifest = supplement[0] if supplement is not None else None
    supplement_path = supplement[1] if supplement is not None else None
    supplement_pass = distribution_gap_count == 0 or (
        supplement_manifest is not None
        and supplement_manifest.get("supplement_partition_count") == distribution_gap_count
        and supplement_manifest.get("dataset_partition_counts")
        == {
            "canonical_key_levels@group1-v1-price-v1": 4_752,
            "market_episodes@group1-v1-flow-v1": 4_752,
            "market_episodes@group1-v1-price-v1": 4_752,
        }
    )
    context_implementation = REPOSITORY_ROOT / "src/era100x/research/stage_2/gates/price/gate.py"
    _safe_file(context_implementation)

    payload: dict[str, Any] = {
        "schema_name": "stage2-s2t15-upstream-binding-report",
        "schema_version": "1.0",
        "task_version": "1.4",
        "status": "PASS" if supplement_pass else "BLOCKED",
        "reason_code": (
            "S2_T15_UPSTREAM_BINDING_PASS_WITH_CR_2026_027_SUPPLEMENT"
            if distribution_gap_count and supplement_pass
            else "S2_T15_UPSTREAM_T10_RECEIPT_DISTRIBUTIONS_MISSING"
            if distribution_gap_count
            else "S2_T15_UPSTREAM_BINDING_PASS_NATIVE"
        ),
        "created_at": datetime.now(tz=UTC).isoformat(),
        "authority_created": False,
        "run_id_created": False,
        "governance_hashes": governance,
        "t10": {
            "run_id": T10_RUN_ID,
            "snapshot_id": T10_SNAPSHOT_ID,
            "manifest_sha256": sha256_file(t10_manifest_path),
            "catalog_sha256": sha256_file(t10_catalog_path),
            **counts,
            "required_dataset_spec_hashes": {
                f"{name}@{version}": str(t10_specs[(name, version)]["spec_hash"])
                for name, version in sorted(REQUIRED_T10_DATASETS)
            },
            "receipt_distribution_audit": receipt_distribution_audit,
            "missing_distribution_partition_count": distribution_gap_count,
            "accepted_receiver_supplement_partition_count": (
                int(supplement_manifest["supplement_partition_count"])
                if supplement_manifest is not None and supplement_pass
                else 0
            ),
            "receiver_supplement_manifest_hash": (
                supplement_manifest.get("manifest_hash")
                if supplement_manifest is not None and supplement_pass
                else None
            ),
            "receiver_supplement_path": (
                str(supplement_path) if supplement_path is not None and supplement_pass else None
            ),
            "original_receipts_modified": False,
        },
        "t13": {
            "run_id": T13_RUN_ID,
            "snapshot_id": T13_SNAPSHOT_ID,
            "manifest_hash": t13_manifest["manifest_hash"],
            "catalog_hash": t13_catalog["catalog_hash"],
            "row_count": t13_rows,
            "h2_path_count": t13_h2_paths,
            "h2_outcome_cell_count": t13_cells,
            "files": t13_files,
            "registered_parameter_timing_pairs": [list(item) for item in sorted(registered_pairs)],
        },
        "t11": {
            "run_id": T11_RUN_ID,
            "snapshot_id": T11_SNAPSHOT_ID,
            "manifest_hash": t11_manifest["manifest_hash"],
            "catalog_hash": t11_catalog["catalog_hash"],
            "authority_hash": T11_AUTHORITY_HASH,
            "authority_file_sha256": sha256_file(T11_AUTHORITY),
            "binding_hash": canonical_hash(
                {
                    "manifest_hash": t11_manifest["manifest_hash"],
                    "catalog_hash": t11_catalog["catalog_hash"],
                    "authority_hash": T11_AUTHORITY_HASH,
                }
            ),
        },
        "stage1": {
            **cast(dict[str, Any], t11_authority["stage1"]),
            "binding_hash": canonical_hash(t11_authority["stage1"]),
        },
        "t14": {
            "run_id": T14_RUN_ID,
            "snapshot_id": T14_SNAPSHOT_ID,
            "manifest_hash": t14_manifest["manifest_hash"],
            "catalog_hash": t14_catalog["catalog_hash"],
            "binding_mode": "AGGREGATE_POLICY_ONLY_NO_EPISODE_JOIN",
            "distribution_count": t14_distributions,
        },
        "context_binding": {
            "setup_id": "KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
            "setup_version": "1.0",
            "context_model_id": "CAUSAL_EMA20_1H",
            "context_version": "1.0",
            "logical_partition_counts": setup_context_counts,
            "implementation_sha256": sha256_file(context_implementation),
            "formula": "LAST_FULLY_CLOSED_1H_CLOSE_VS_CAUSAL_EMA20",
            "additional_timeframe_filters": [],
            "status": "PASS",
        },
        "label_contract_hash": canonical_hash(
            {
                "t13_manifest_hash": t13_manifest["manifest_hash"],
                "t13_catalog_hash": t13_catalog["catalog_hash"],
                "t14_manifest_hash": t14_manifest["manifest_hash"],
                "t14_catalog_hash": t14_catalog["catalog_hash"],
                "t14_binding_mode": "AGGREGATE_POLICY_ONLY_NO_EPISODE_JOIN",
                "combination_order": list(COMBINATION_ORDER),
                "reference_price_source": "CONTRACT_PRICE_1S_CLOSE",
                "path_evidence_level": "H2",
                "zero_observations": "AMBIGUOUS",
                "ambiguous_primary_treatment": "FAILURE",
            }
        ),
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    payload["upstream_binding_hash"] = canonical_hash(
        {
            key: payload[key]
            for key in (
                "schema_name",
                "schema_version",
                "task_version",
                "status",
                "reason_code",
                "t10",
                "t13",
                "t14",
                "t11",
                "stage1",
                "context_binding",
                "label_contract_hash",
                "historical_evidence_only",
                "stage3_locked",
            )
        }
    )
    payload["audit_report_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "created_at"}
    )
    if write_report:
        _write_json_exclusive(AUDIT_ROOT / f"{payload['audit_report_hash']}.json", payload)
    return payload


def latest_audit() -> Path:
    candidates = tuple(path for path in AUDIT_ROOT.glob("*.json") if not path.name.startswith("._"))
    if not candidates:
        raise ValueError("no S2-T15 audit report exists")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def freeze_authority(*, audit_path: Path | None = None) -> tuple[S2T15ContractAuthority, Path]:
    if not repository_is_clean():
        raise ValueError("Authority requires a clean final-code commit")
    report = _read_json(audit_path or latest_audit())
    if report.get("status") != "PASS":
        raise ValueError(
            f"Authority blocked by upstream audit: {report.get('reason_code', 'UNKNOWN')}"
        )
    current = audit_upstream(write_report=False)
    if report.get("upstream_binding_hash") != current.get("upstream_binding_hash"):
        raise ValueError("upstream audit drift before Authority")
    if report.get("governance_hashes") != current.get("governance_hashes"):
        raise ValueError("governance changed after the selected upstream audit")
    governance = _governance_binding()
    authority = S2T15ContractAuthority.seal(
        {
            "code_commit": current_code_commit(),
            "upstream_binding_hash": report["upstream_binding_hash"],
            "source_s2t11_binding_hash": report["t11"]["binding_hash"],
            "stage1_binding_hash": report["stage1"]["binding_hash"],
            "context_binding_hash": sha256_file(
                REPOSITORY_ROOT / "src/era100x/research/stage_2/gates/price/gate.py"
            ),
            "label_contract_hash": report["label_contract_hash"],
            "preregistration_addendum_hash": governance[
                "docs/development/tasks/stage_2/S2-T19-manifest.md"
            ],
        }
    )
    path = AUTHORITY_ROOT / f"authority-{authority.authority_hash}.json"
    _write_json_exclusive(path, authority.model_dump(mode="json"))
    return authority, path


def preflight(*, authority_path: Path, binning_set_path: Path) -> dict[str, Any]:
    authority = S2T15ContractAuthority.model_validate_json(
        json.dumps(_read_json(authority_path), ensure_ascii=False, sort_keys=True)
    )
    if authority.authority_hash != authority.computed_hash():
        raise ValueError("Authority changed before preflight")
    if authority.code_commit != current_code_commit() or not repository_is_clean():
        raise ValueError("preflight code is not the clean Authority commit")
    binning = read_binning_set(binning_set_path, authority_hash=authority.authority_hash)
    if binning.get("code_commit") != authority.code_commit:
        raise ValueError("binning snapshot set code commit drift")
    if any(RUNS_ROOT.glob("stage2-s2t15-conditional-*")):
        raise ValueError("a T15 Run ID already exists; unique-run gate blocks creation")
    free_bytes = shutil.disk_usage(STAGE2_ROOT).free
    if free_bytes < 10 * 1024**3:
        raise ValueError("insufficient free space for S2-T15")
    return {
        "schema_name": "stage2-s2t15-preflight",
        "status": "PASS",
        "authority_hash": authority.authority_hash,
        "code_commit": authority.code_commit,
        "binning_set_hash": binning["binning_set_hash"],
        "free_bytes": free_bytes,
        "run_id_created": False,
        "stage3_locked": True,
    }
