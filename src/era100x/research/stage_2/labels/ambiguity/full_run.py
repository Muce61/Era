"""Append-only full runner for approved S2-T14 v1.3 ambiguity distributions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.labels.first_passage.full_run import (
    COMBINATION_ORDER,
    COMBINATIONS_PER_PATH,
    RUNS_ROOT,
    current_code_commit,
)
from era100x.research.stage_2.labels.first_passage.models import (
    REGISTERED_STOP_BPS,
    REGISTERED_TARGET_BPS,
)
from era100x.research.stage_2.metrics.path.full_run import _write_json_exclusive
from era100x.research.stage_2.paths.extraction.full_run import sha256_file
from era100x.research.stage_2.paths.extraction.models import _canonical_json

REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
STAGE2_ROOT = RUNS_ROOT.parent
AUTHORITY_ROOT = STAGE2_ROOT / "authorities" / "S2-T14"
TASK_VERSION = "1.3"
RUN_PREFIX = "stage2-s2t14-ambiguity-bounds-"
SAFE_RUN_ID = re.compile(r"^stage2-s2t14-ambiguity-bounds-\d{8}T\d{6}Z-[0-9a-f]{12}$")
CLI = "uv run python scripts/run_stage2_ambiguity_bounds.py {preflight,run,resume,verify}"

SOURCE_RUN_ID = "stage2-s2t13-first-passage-20260721T110224Z-d3f0c0331395"
SOURCE_AUTHORITY_HASH = "ab76072c501742199cf5952fda85be25d704fc7020430be192ad40ea514cbbbe"
SOURCE_SNAPSHOT_ID = "3ea1f8e188c4cf605c05c49bc86118925784b27a3b7c0e9c1969edda7a295da0"
SOURCE_MANIFEST_HASH = "24c404179037ab7db08afd96b94fd284e7896db18801011e4267081680e0aaed"
SOURCE_CATALOG_HASH = "8511c27310e40fd103f9eeccde2067ed5c1279765377c8b35652dd9072c8889e"
SOURCE_CODE_COMMIT = "fdb4555232d0e456453a95197b5f6b23a01aa5b9"
SOURCE_TOTAL_PATH_ROWS = 1_065_416
SOURCE_TOTAL_CLASSIFICATIONS = 31_962_480
SOURCE_RUN_ROOT = RUNS_ROOT / SOURCE_RUN_ID
SOURCE_SNAPSHOT_ROOT = SOURCE_RUN_ROOT / "published" / "snapshots" / SOURCE_SNAPSHOT_ID
SOURCE_REPOSITORY_SUMMARY = (
    REPOSITORY_ROOT / "artifacts/manifests/stage_2/s2_t13_first_passage_summary.json"
)
SOURCE_HANDOFF_RECEIPT: Path | None = None
REPOSITORY_SUMMARY = (
    REPOSITORY_ROOT / "artifacts/manifests/stage_2/s2_t14_ambiguity_bounds_summary.json"
)
INSTRUMENTS = ("BTCUSDT", "ETHUSDT")
LABELS = ("TARGET_FIRST", "STOP_FIRST", "EXPIRED", "AMBIGUOUS")


def _json_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _self_hash_matches(payload: dict[str, Any], field: str) -> bool:
    expected = payload.pop(field, None)
    actual = _json_hash(payload)
    payload[field] = expected
    return bool(expected == actual)


def _read_json(path: Path, *, description: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
        raise ValueError(f"unsafe or missing {description}")
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {description}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid {description}")
    return cast(dict[str, Any], payload)


def _source_path(instrument: str) -> Path:
    return SOURCE_SNAPSHOT_ROOT / instrument / "first_passage.parquet"


def _source_contract() -> dict[str, Any]:
    if SOURCE_RUN_ROOT.is_symlink() or SOURCE_SNAPSHOT_ROOT.is_symlink():
        raise ValueError("unsafe S2-T13 source root")
    completion = _read_json(
        SOURCE_RUN_ROOT / "reports/completion.json", description="S2-T13 completion"
    )
    manifest = _read_json(SOURCE_SNAPSHOT_ROOT / "manifest.json", description="S2-T13 manifest")
    catalog = _read_json(SOURCE_SNAPSHOT_ROOT / "catalog.json", description="S2-T13 catalog")
    if not _self_hash_matches(manifest, "manifest_hash"):
        raise ValueError("S2-T13 manifest self-hash mismatch")
    if not _self_hash_matches(catalog, "catalog_hash"):
        raise ValueError("S2-T13 catalog self-hash mismatch")
    automated_handoff: dict[str, Any] | None = None
    if SOURCE_HANDOFF_RECEIPT is None:
        summary = _read_json(SOURCE_REPOSITORY_SUMMARY, description="S2-T13 repository summary")
    else:
        automated_handoff = _read_json(
            SOURCE_HANDOFF_RECEIPT, description="S2-T13 automated rerun handoff"
        )
        if not _self_hash_matches(automated_handoff, "handoff_hash"):
            raise ValueError("S2-T13 automated handoff self-hash mismatch")
        if (
            automated_handoff.get("schema_name") != "stage2-s2t11-t15-rerun-handoff-v1"
            or automated_handoff.get("task_id") != "S2-T13"
            or automated_handoff.get("status") != "VERIFY_PASS"
            or automated_handoff.get("historical_evidence_only") is not True
            or automated_handoff.get("stage3_locked") is not True
        ):
            raise ValueError("invalid S2-T13 automated handoff contract")
        summary = {
            **automated_handoff,
            "task_id": "S2-T13",
            "task_version": "1.3",
            "status": "VERIFIED_AUTOMATED_CHAIN_HANDOFF",
            "verify_status": "PASS",
            "instruments": {
                instrument: {
                    "output_sha256": catalog.get("instruments", {})
                    .get(instrument, {})
                    .get("sha256")
                }
                for instrument in INSTRUMENTS
            },
        }
    expected = {
        "run_id": SOURCE_RUN_ID,
        "authority_hash": SOURCE_AUTHORITY_HASH,
        "snapshot_id": SOURCE_SNAPSHOT_ID,
        "manifest_hash": SOURCE_MANIFEST_HASH,
        "catalog_hash": SOURCE_CATALOG_HASH,
        "total_path_rows": SOURCE_TOTAL_PATH_ROWS,
        "total_classification_count": SOURCE_TOTAL_CLASSIFICATIONS,
    }
    for name, value in expected.items():
        if summary.get(name) != value or completion.get(name) != value:
            raise ValueError(f"accepted S2-T13 {name} binding changed")
    accepted_source = (
        summary.get("status") == "PASSED_HUMAN_ACCEPTED"
        and summary.get("human_accepted") is True
        or automated_handoff is not None
        and summary.get("status") == "VERIFIED_AUTOMATED_CHAIN_HANDOFF"
    )
    if (
        summary.get("task_id") != "S2-T13"
        or summary.get("task_version") != "1.3"
        or not accepted_source
        or summary.get("verify_status") != "PASS"
        or summary.get("code_commit") != SOURCE_CODE_COMMIT
        or manifest.get("code_commit") != SOURCE_CODE_COMMIT
        or manifest.get("authority_hash") != SOURCE_AUTHORITY_HASH
        or manifest.get("snapshot_id") != SOURCE_SNAPSHOT_ID
        or manifest.get("run_id") != SOURCE_RUN_ID
        or catalog.get("run_id") != SOURCE_RUN_ID
        or catalog.get("snapshot_id") != SOURCE_SNAPSHOT_ID
        or catalog.get("combination_order") != list(COMBINATION_ORDER)
    ):
        raise ValueError("accepted S2-T13 terminal contract changed")
    bound: dict[str, Any] = {
        "source_s2t13_run_id": SOURCE_RUN_ID,
        "source_s2t13_authority_hash": SOURCE_AUTHORITY_HASH,
        "source_s2t13_snapshot_id": SOURCE_SNAPSHOT_ID,
        "source_s2t13_manifest_hash": SOURCE_MANIFEST_HASH,
        "source_s2t13_catalog_hash": SOURCE_CATALOG_HASH,
        "source_s2t13_code_commit": SOURCE_CODE_COMMIT,
        "source_s2t13_total_path_rows": SOURCE_TOTAL_PATH_ROWS,
        "source_s2t13_total_classifications": SOURCE_TOTAL_CLASSIFICATIONS,
        "combination_order": list(COMBINATION_ORDER),
        "source_instruments": {},
    }
    total_rows = 0
    total_classifications = 0
    parameter_timing_pairs: set[tuple[str, str]] = set()
    evidence_levels: set[str] = set()
    for instrument in INSTRUMENTS:
        path = _source_path(instrument)
        if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
            raise ValueError(f"unsafe or missing S2-T13 source: {instrument}")
        source_summary = catalog.get("instruments", {}).get(instrument, {})
        repository_instrument = summary.get("instruments", {}).get(instrument, {})
        metadata = pq.read_metadata(path)
        digest = sha256_file(path)
        rows = int(source_summary.get("first_passage", {}).get("row_count", -1))
        classifications = int(
            source_summary.get("first_passage", {}).get("classification_count", -1)
        )
        if (
            metadata.num_rows != rows
            or digest != source_summary.get("sha256")
            or digest != repository_instrument.get("output_sha256")
            or path.stat().st_size != int(source_summary.get("byte_size", -1))
            or classifications != rows * COMBINATIONS_PER_PATH
        ):
            raise ValueError(f"S2-T13 source file binding changed: {instrument}")
        bound["source_instruments"][instrument] = {
            "path_rows": rows,
            "classification_count": classifications,
            "byte_size": path.stat().st_size,
            "sha256": digest,
            "label_counts": source_summary["first_passage"]["label_counts"],
            "label_reason_counts": source_summary["first_passage"]["label_reason_counts"],
        }
        total_rows += rows
        total_classifications += classifications
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(
            batch_size=20_000,
            columns=["parameter_set_id", "timing_id", "evidence_level"],
        ):
            for row in batch.to_pylist():
                parameter_timing_pairs.add((str(row["parameter_set_id"]), str(row["timing_id"])))
                evidence_levels.add(str(row["evidence_level"]))
    if (
        total_rows != SOURCE_TOTAL_PATH_ROWS
        or total_classifications != SOURCE_TOTAL_CLASSIFICATIONS
    ):
        raise ValueError("S2-T13 aggregate source counts changed")
    parameter_set_ids = sorted({item[0] for item in parameter_timing_pairs})
    if (
        len(parameter_set_ids) != 19
        or len(parameter_timing_pairs) != 19
        or evidence_levels != {"H1", "H2"}
    ):
        raise ValueError("S2-T13 parameter/evidence domain changed")
    bound.update(
        {
            "parameter_set_ids": parameter_set_ids,
            "parameter_set_timing_pairs": [
                {"parameter_set_id": parameter, "timing_id": timing}
                for parameter, timing in sorted(parameter_timing_pairs)
            ],
            "timing_ids": sorted({item[1] for item in parameter_timing_pairs}),
            "evidence_levels": sorted(evidence_levels),
            "expected_distribution_count_per_instrument": 1_140,
        }
    )
    return bound


def create_preflight_manifest(*, code_commit: str) -> tuple[dict[str, Any], Path]:
    if code_commit != current_code_commit():
        raise ValueError("preflight code commit is not current HEAD")
    source = _source_contract()
    payload: dict[str, Any] = {
        "schema_name": "stage2-s2t14-preflight-authority",
        "schema_version": "1.0",
        "task_id": "S2-T14",
        "task_version": TASK_VERSION,
        "manual_version": "V1.3.4",
        "change_request": "CR-2026-024",
        "code_commit": code_commit,
        "full_run_cli": CLI,
        "output_root": str(STAGE2_ROOT),
        "output_mode": "COMPACT_DISTRIBUTIONS_ONLY",
        "primary_ambiguous_policy": "FAILURE",
        "conditional_ambiguous_policy": "EXCLUDE",
        "theoretical_upper_ambiguous_policy": "SUCCESS",
        "expected_path_rows": SOURCE_TOTAL_PATH_ROWS,
        "expected_classification_count": SOURCE_TOTAL_CLASSIFICATIONS,
        "expected_distribution_count": 2_280,
        "historical_evidence_only": True,
        "stage3_locked": True,
        "prohibited_outputs": [
            "PNL",
            "RETURN",
            "REAL_RETURN",
            "ROUND_SUCCESS",
            "LIVE_EXECUTION",
            "CONDITIONAL_BASELINE",
            "PLACEBO",
            "CLUSTER",
            "BOOTSTRAP",
        ],
        **source,
    }
    payload["authority_hash"] = _json_hash(payload)
    path = AUTHORITY_ROOT / f"{payload['authority_hash']}.json"
    _write_json_exclusive(path, payload)
    return payload, path


def latest_preflight_manifest() -> Path:
    candidates = tuple(
        path for path in AUTHORITY_ROOT.glob("*.json") if not path.name.startswith("._")
    )
    if not candidates:
        raise ValueError("no S2-T14 preflight Authority exists")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def read_preflight_manifest(path: Path) -> dict[str, Any]:
    payload = _read_json(path, description="S2-T14 preflight Authority")
    if not _self_hash_matches(payload, "authority_hash"):
        raise ValueError("S2-T14 preflight Authority hash mismatch")
    if (
        payload.get("task_version") != TASK_VERSION
        or payload.get("change_request") != "CR-2026-024"
    ):
        raise ValueError("S2-T14 preflight Authority contract mismatch")
    source = _source_contract()
    for key, value in source.items():
        if payload.get(key) != value:
            raise ValueError("S2-T14 frozen S2-T13 source binding changed")
    return payload


def _rate(numerator: int, denominator: int) -> str | None:
    return None if denominator == 0 else format(Decimal(numerator) / Decimal(denominator), "f")


def _aggregate_source(instrument: str) -> tuple[dict[str, Any], dict[str, Any]]:
    source = _source_contract()["source_instruments"][instrument]
    counters: dict[tuple[str, str, str, str, str], Counter[str]] = defaultdict(Counter)
    reasons: dict[tuple[str, str, str, str, str], Counter[str]] = defaultdict(Counter)
    path_rows = 0
    classifications = 0
    parquet = pq.ParquetFile(_source_path(instrument))
    for batch in parquet.iter_batches(batch_size=2_000):
        for row in batch.to_pylist():
            claimed_hash = row.pop("classification_row_hash")
            if claimed_hash != _json_hash(row):
                raise ValueError("S2-T13 classification row hash mismatch")
            if (
                row["instrument"] != instrument
                or row["historical_evidence_only"] is not True
                or row["combination_order"] != list(COMBINATION_ORDER)
                or row["target_domain_bps"] != list(REGISTERED_TARGET_BPS)
                or row["stop_domain_bps"] != list(REGISTERED_STOP_BPS)
                or row["classification_count"] != COMBINATIONS_PER_PATH
                or len(row["labels"]) != COMBINATIONS_PER_PATH
                or len(row["label_reasons"]) != COMBINATIONS_PER_PATH
            ):
                raise ValueError("S2-T13 classification matrix contract changed")
            evidence = str(row["evidence_level"])
            timing = str(row["timing_id"])
            parameter = str(row["parameter_set_id"])
            combinations = (
                (target_bps, stop_bps)
                for target_bps in REGISTERED_TARGET_BPS
                for stop_bps in REGISTERED_STOP_BPS
            )
            for index, (target, stop) in enumerate(combinations):
                key = (evidence, parameter, timing, format(target, "f"), format(stop, "f"))
                label = str(row["labels"][index])
                reason = str(row["label_reasons"][index])
                if label not in LABELS:
                    raise ValueError("S2-T13 contains an unknown label")
                if evidence == "H2" and reason == "H1_SAME_EVENT_TARGET_AND_STOP":
                    raise ValueError("H2 cannot contain H1 same-event ambiguity")
                counters[key][label] += 1
                reasons[key][reason] += 1
                classifications += 1
            path_rows += 1
    distributions: list[dict[str, Any]] = []
    labels_total: Counter[str] = Counter()
    reasons_total: Counter[str] = Counter()
    for key in sorted(counters):
        evidence, parameter, timing, group_target, group_stop = key
        counts = counters[key]
        reason_counts = reasons[key]
        total = sum(counts.values())
        target_count = counts["TARGET_FIRST"]
        ambiguous_count = counts["AMBIGUOUS"]
        conditional_denominator = total - ambiguous_count
        distributions.append(
            {
                "instrument": instrument,
                "evidence_level": evidence,
                "parameter_set_id": parameter,
                "timing_id": timing,
                "target_bps": group_target,
                "stop_bps": group_stop,
                "total_count": total,
                "label_counts": {label: counts[label] for label in LABELS},
                "label_reason_counts": dict(sorted(reason_counts.items())),
                "primary_target_first_numerator": target_count,
                "primary_target_first_denominator": total,
                "primary_target_first_rate": _rate(target_count, total),
                "conditional_target_first_numerator": target_count,
                "conditional_target_first_denominator": conditional_denominator,
                "conditional_target_first_rate": _rate(target_count, conditional_denominator),
                "theoretical_lower_target_first_numerator": target_count,
                "theoretical_lower_target_first_denominator": total,
                "theoretical_lower_target_first_rate": _rate(target_count, total),
                "theoretical_upper_target_first_numerator": target_count + ambiguous_count,
                "theoretical_upper_target_first_denominator": total,
                "theoretical_upper_target_first_rate": _rate(target_count + ambiguous_count, total),
                "h1_same_event_adverse_count": reason_counts["H1_SAME_EVENT_TARGET_AND_STOP"],
                "h1_same_event_optimistic_count": reason_counts["H1_SAME_EVENT_TARGET_AND_STOP"],
                "raw_ambiguous_preserved": True,
            }
        )
        labels_total.update(counts)
        reasons_total.update(reason_counts)
    if (
        path_rows != int(source["path_rows"])
        or classifications != int(source["classification_count"])
        or dict(sorted(labels_total.items())) != source["label_counts"]
        or dict(sorted(reasons_total.items())) != source["label_reason_counts"]
    ):
        raise ValueError(f"S2-T14 did not account for S2-T13 exactly once: {instrument}")
    output: dict[str, Any] = {
        "schema_name": "stage2-s2t14-ambiguity-distributions",
        "schema_version": "1.0",
        "task_id": "S2-T14",
        "task_version": TASK_VERSION,
        "instrument": instrument,
        "source_run_id": SOURCE_RUN_ID,
        "source_snapshot_id": SOURCE_SNAPSHOT_ID,
        "source_output_sha256": source["sha256"],
        "path_rows": path_rows,
        "classification_count": classifications,
        "distribution_count": len(distributions),
        "label_counts": dict(sorted(labels_total.items())),
        "label_reason_counts": dict(sorted(reasons_total.items())),
        "historical_evidence_only": True,
        "primary_ambiguous_policy": "FAILURE",
        "conditional_ambiguous_policy": "EXCLUDE",
        "theoretical_upper_ambiguous_policy": "SUCCESS",
        "distributions": distributions,
    }
    output["output_hash"] = _json_hash(output)
    summary = {
        "instrument": instrument,
        "episode_count": path_rows // 2,
        "path_rows": path_rows,
        "classification_count": classifications,
        "distribution_count": len(distributions),
        "label_counts": output["label_counts"],
        "label_reason_counts": output["label_reason_counts"],
        "ambiguous_count": labels_total["AMBIGUOUS"],
        "primary_target_first_count": labels_total["TARGET_FIRST"],
        "conditional_denominator": classifications - labels_total["AMBIGUOUS"],
        "theoretical_upper_target_first_count": labels_total["TARGET_FIRST"]
        + labels_total["AMBIGUOUS"],
        "output_hash": output["output_hash"],
    }
    return output, summary


def _write_distribution(
    path: Path, output: dict[str, Any], summary: dict[str, Any]
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=False)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    os.replace(temporary, path)
    result = {**summary, "byte_size": path.stat().st_size, "sha256": sha256_file(path)}
    _write_json_exclusive(path.with_suffix(".summary.json"), result)
    return result


def _new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{RUN_PREFIX}{stamp}-{uuid.uuid4().hex[:12]}"


def _initialize_run(run_root: Path) -> None:
    if run_root.exists():
        raise ValueError(f"S2-T14 run already exists: {run_root.name}")
    for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
        (run_root / name).mkdir(parents=True, exist_ok=False)


def execute_run(*, preflight_path: Path, run_id: str | None = None) -> Path:
    authority = read_preflight_manifest(preflight_path)
    if authority.get("code_commit") != current_code_commit():
        raise ValueError("S2-T14 Authority code commit is not current HEAD")
    selected = run_id or _new_run_id()
    if SAFE_RUN_ID.fullmatch(selected) is None:
        raise ValueError("unsafe S2-T14 Run ID")
    run_root = RUNS_ROOT / selected
    _initialize_run(run_root)
    _write_json_exclusive(run_root / "manifests/preflight-authority.json", authority)
    execution = {
        **authority,
        "run_id": selected,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "execution_manifest_hash": "",
    }
    execution["execution_manifest_hash"] = _json_hash(
        {key: value for key, value in execution.items() if key != "execution_manifest_hash"}
    )
    _write_json_exclusive(
        run_root / "manifests" / f"execution-{execution['execution_manifest_hash']}.json",
        execution,
    )
    try:
        return resume_run(run_root)
    except BaseException as exc:
        _write_json_exclusive(
            run_root / "reports/failure.json",
            {
                "task_id": "S2-T14",
                "task_version": TASK_VERSION,
                "run_id": selected,
                "status": "FAILED_UNPUBLISHED",
                "failure_class": type(exc).__name__,
                "reason": str(exc),
                "resume_allowed": False,
                "published": False,
                "created_at_utc": datetime.now(UTC).isoformat(),
            },
        )
        raise


def resume_run(run_root: Path) -> Path:
    if run_root.is_symlink() or not run_root.is_dir():
        raise ValueError("S2-T14 run root is unsafe or missing")
    if (run_root / "reports/failure.json").exists():
        raise ValueError("failed S2-T14 Run is immutable and cannot resume")
    manifests = sorted((run_root / "manifests").glob("execution-*.json"))
    if len(manifests) != 1 or manifests[0].is_symlink():
        raise ValueError("S2-T14 Run requires exactly one execution Manifest")
    execution = _read_json(manifests[0], description="S2-T14 execution Manifest")
    if not _self_hash_matches(execution, "execution_manifest_hash"):
        raise ValueError("S2-T14 execution Manifest hash mismatch")
    authority = read_preflight_manifest(run_root / "manifests/preflight-authority.json")
    if execution.get("authority_hash") != authority["authority_hash"]:
        raise ValueError("S2-T14 execution/Authority mismatch")
    summaries: dict[str, Any] = {}
    for instrument in INSTRUMENTS:
        output_path = run_root / "staging" / instrument / "ambiguity_distributions.json"
        summary_path = output_path.with_suffix(".summary.json")
        if output_path.is_file() and summary_path.is_file():
            summary = _read_json(summary_path, description=f"S2-T14 {instrument} summary")
            if summary.get("sha256") != sha256_file(output_path):
                raise ValueError("existing S2-T14 staging output hash mismatch")
        else:
            if output_path.exists() or summary_path.exists():
                raise ValueError("partial S2-T14 staging output cannot be overwritten")
            output, compact = _aggregate_source(instrument)
            summary = _write_distribution(output_path, output, compact)
        summaries[instrument] = summary
        report = run_root / "reports" / f"{instrument.lower()}-completion.json"
        if not report.exists():
            _write_json_exclusive(report, summary)
    catalog_base = {
        "schema_name": "stage2-s2t14-ambiguity-bounds-catalog",
        "schema_version": "1.0",
        "run_id": run_root.name,
        "source_s2t13_run_id": SOURCE_RUN_ID,
        "source_s2t13_snapshot_id": SOURCE_SNAPSHOT_ID,
        **{
            key: authority[key]
            for key in (
                "combination_order",
                "parameter_set_ids",
                "parameter_set_timing_pairs",
                "timing_ids",
                "evidence_levels",
                "expected_distribution_count_per_instrument",
            )
        },
        "instruments": summaries,
    }
    snapshot_id = _json_hash(catalog_base)
    catalog = {**catalog_base, "snapshot_id": snapshot_id}
    catalog["catalog_hash"] = _json_hash(catalog)
    manifest = {
        "schema_name": "stage2-s2t14-ambiguity-bounds-manifest",
        "schema_version": "1.0",
        "task_id": "S2-T14",
        "task_version": TASK_VERSION,
        "run_id": run_root.name,
        "snapshot_id": snapshot_id,
        "execution_manifest_hash": execution["execution_manifest_hash"],
        "authority_hash": authority["authority_hash"],
        "source_s2t13_run_id": SOURCE_RUN_ID,
        "source_s2t13_authority_hash": SOURCE_AUTHORITY_HASH,
        "source_s2t13_snapshot_id": SOURCE_SNAPSHOT_ID,
        "source_s2t13_manifest_hash": SOURCE_MANIFEST_HASH,
        "source_s2t13_catalog_hash": SOURCE_CATALOG_HASH,
        "source_s2t13_code_commit": SOURCE_CODE_COMMIT,
        "code_commit": execution["code_commit"],
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    manifest["manifest_hash"] = _json_hash(manifest)
    snapshot_staging = run_root / "staging/snapshot"
    snapshot_staging.mkdir(exist_ok=False)
    for instrument in INSTRUMENTS:
        os.replace(run_root / "staging" / instrument, snapshot_staging / instrument)
    _write_json_exclusive(snapshot_staging / "catalog.json", catalog)
    _write_json_exclusive(snapshot_staging / "manifest.json", manifest)
    published = run_root / "published/snapshots" / snapshot_id
    published.parent.mkdir(parents=True, exist_ok=True)
    if published.exists():
        raise ValueError("S2-T14 immutable snapshot already exists")
    os.replace(snapshot_staging, published)
    completion = {
        "status": "PASS",
        "task_id": "S2-T14",
        "task_version": TASK_VERSION,
        "run_id": run_root.name,
        "authority_hash": authority["authority_hash"],
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "instruments": summaries,
        "total_path_rows": sum(item["path_rows"] for item in summaries.values()),
        "total_classification_count": sum(
            item["classification_count"] for item in summaries.values()
        ),
        "total_distribution_count": sum(item["distribution_count"] for item in summaries.values()),
        "total_ambiguous_count": sum(item["ambiguous_count"] for item in summaries.values()),
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    _write_json_exclusive(run_root / "reports/completion.json", completion)
    return run_root


def find_resumable_run() -> Path:
    candidates = sorted(
        path
        for path in RUNS_ROOT.glob(f"{RUN_PREFIX}*")
        if path.is_dir()
        and not path.is_symlink()
        and not (path / "reports/completion.json").exists()
        and not (path / "reports/failure.json").exists()
    )
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one resumable S2-T14 Run, found {len(candidates)}")
    return candidates[0]


def _verify_output(path: Path, instrument: str, expected: dict[str, Any]) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
        raise ValueError("unsafe or missing S2-T14 output")
    if path.stat().st_size != int(expected["byte_size"]) or sha256_file(path) != expected["sha256"]:
        raise ValueError("S2-T14 output size/hash mismatch")
    published = _read_json(path, description=f"S2-T14 {instrument} distribution")
    claimed_hash = published.pop("output_hash", None)
    if claimed_hash != _json_hash(published):
        raise ValueError("S2-T14 output self-hash mismatch")
    published["output_hash"] = claimed_hash
    recomputed, summary = _aggregate_source(instrument)
    if published != recomputed:
        raise ValueError("S2-T14 distribution recomputation mismatch")
    for key, value in summary.items():
        if expected.get(key) != value:
            raise ValueError("S2-T14 catalog summary mismatch")
    return summary


def verify_run(run_root: Path) -> dict[str, Any]:
    if run_root.is_symlink() or not run_root.is_dir():
        return {"status": "FAIL", "reason": "unsafe or missing S2-T14 Run"}
    try:
        completion = _read_json(
            run_root / "reports/completion.json", description="S2-T14 completion"
        )
        snapshot = run_root / "published/snapshots" / str(completion["snapshot_id"])
        manifest = _read_json(snapshot / "manifest.json", description="S2-T14 manifest")
        catalog = _read_json(snapshot / "catalog.json", description="S2-T14 catalog")
        if not _self_hash_matches(manifest, "manifest_hash"):
            raise ValueError("S2-T14 manifest hash mismatch")
        if not _self_hash_matches(catalog, "catalog_hash"):
            raise ValueError("S2-T14 catalog hash mismatch")
        authority = read_preflight_manifest(run_root / "manifests/preflight-authority.json")
        execution_paths = sorted((run_root / "manifests").glob("execution-*.json"))
        if len(execution_paths) != 1:
            raise ValueError("S2-T14 execution Manifest count mismatch")
        execution = _read_json(execution_paths[0], description="S2-T14 execution Manifest")
        if not _self_hash_matches(execution, "execution_manifest_hash"):
            raise ValueError("S2-T14 execution Manifest hash mismatch")
        if (
            manifest.get("run_id") != run_root.name
            or catalog.get("run_id") != run_root.name
            or completion.get("run_id") != run_root.name
            or manifest.get("snapshot_id") != completion.get("snapshot_id")
            or catalog.get("snapshot_id") != completion.get("snapshot_id")
            or manifest.get("authority_hash") != authority.get("authority_hash")
            or manifest.get("execution_manifest_hash") != execution.get("execution_manifest_hash")
            or manifest.get("source_s2t13_run_id") != SOURCE_RUN_ID
            or manifest.get("source_s2t13_snapshot_id") != SOURCE_SNAPSHOT_ID
        ):
            raise ValueError("S2-T14 terminal lineage mismatch")
        verified = {
            instrument: _verify_output(
                snapshot / instrument / "ambiguity_distributions.json",
                instrument,
                catalog["instruments"][instrument],
            )
            for instrument in INSTRUMENTS
        }
        total_paths = sum(item["path_rows"] for item in verified.values())
        total_classifications = sum(item["classification_count"] for item in verified.values())
        total_distributions = sum(item["distribution_count"] for item in verified.values())
        total_ambiguous = sum(item["ambiguous_count"] for item in verified.values())
        if (
            total_paths != completion.get("total_path_rows")
            or total_classifications != completion.get("total_classification_count")
            or total_distributions != completion.get("total_distribution_count")
            or total_paths != SOURCE_TOTAL_PATH_ROWS
            or total_classifications != SOURCE_TOTAL_CLASSIFICATIONS
            or total_distributions != 2_280
        ):
            raise ValueError("S2-T14 completion counts mismatch")
    except (OSError, ValueError, KeyError, json.JSONDecodeError, pa.ArrowException) as exc:
        return {"status": "FAIL", "run_id": run_root.name, "reason": str(exc)}
    return {
        "status": "PASS",
        "run_id": run_root.name,
        "authority_hash": completion["authority_hash"],
        "snapshot_id": completion["snapshot_id"],
        "manifest_hash": completion["manifest_hash"],
        "catalog_hash": completion["catalog_hash"],
        "instruments": verified,
        "total_path_rows": total_paths,
        "total_classification_count": total_classifications,
        "total_distribution_count": total_distributions,
        "total_ambiguous_count": total_ambiguous,
        "historical_evidence_only": True,
        "stage3_locked": True,
    }


__all__ = [
    "AUTHORITY_ROOT",
    "REPOSITORY_SUMMARY",
    "RUNS_ROOT",
    "create_preflight_manifest",
    "current_code_commit",
    "execute_run",
    "find_resumable_run",
    "latest_preflight_manifest",
    "read_preflight_manifest",
    "resume_run",
    "verify_run",
]
