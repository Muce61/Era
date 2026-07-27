"""Append-only T18 format smoke, formal producer and independent verifier."""

from __future__ import annotations

import fcntl
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .contracts import (
    BootstrapSummary,
    ClusterSufficientStatistic,
    FdrFamilySummary,
    MetricFamily,
    S2P15T18Authority,
)
from .engine import (
    aggregate_match_matrices,
    compute_all_summaries,
)
from .formatting import canonical_hash, canonical_json, read_json, sha256_file, write_exclusive
from .governance import (
    BootstrapPolicy,
    SourceBindings,
    audit_sources,
    freeze_authority,
    repository_clean,
    repository_commit,
    validate_approval,
)

EXPECTED_GROUPS = 456
EXPECTED_SUMMARIES = 54_720
EXPECTED_FDR_FAMILIES = 96
ProgressCallback = Callable[[dict[str, Any]], None]

CLUSTER_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("pre_registered_period", pa.string(), nullable=False),
        pa.field("evaluation_fold", pa.string(), nullable=False),
        pa.field("parameter_set_id", pa.string(), nullable=False),
        pa.field("time_combination_id", pa.string(), nullable=False),
        pa.field("week_start_ns", pa.int64(), nullable=False),
        pa.field("cluster_id", pa.string(), nullable=False),
        pa.field("real_count", pa.int64(), nullable=False),
        pa.field("placebo_count", pa.int64(), nullable=False),
        pa.field("paired_count", pa.int64(), nullable=False),
        pa.field("real_event_success", pa.list_(pa.int64()), nullable=False),
        pa.field("real_control_success", pa.list_(pa.int64()), nullable=False),
        pa.field("placebo_event_success", pa.list_(pa.int64()), nullable=False),
        pa.field("placebo_control_success", pa.list_(pa.int64()), nullable=False),
        pa.field("paired_real_event_success", pa.list_(pa.int64()), nullable=False),
        pa.field("paired_real_control_success", pa.list_(pa.int64()), nullable=False),
        pa.field("paired_placebo_event_success", pa.list_(pa.int64()), nullable=False),
        pa.field("paired_placebo_control_success", pa.list_(pa.int64()), nullable=False),
        pa.field("statistic_hash", pa.string(), nullable=False),
        pa.field("statistic_json", pa.string(), nullable=False),
    ]
)

SUMMARY_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("analysis_scope", pa.string(), nullable=False),
        pa.field("pre_registered_period", pa.string()),
        pa.field("evaluation_fold", pa.string()),
        pa.field("parameter_set_id", pa.string(), nullable=False),
        pa.field("time_combination_id", pa.string(), nullable=False),
        pa.field("combination_id", pa.string(), nullable=False),
        pa.field("metric_family", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("cluster_count", pa.int64(), nullable=False),
        pa.field("episode_count", pa.int64(), nullable=False),
        pa.field("meets_200_cluster_baseline", pa.bool_(), nullable=False),
        pa.field("estimate", pa.string()),
        pa.field("ci_lower", pa.string()),
        pa.field("ci_upper", pa.string()),
        pa.field("bootstrap_median", pa.string()),
        pa.field("bootstrap_standard_error", pa.string()),
        pa.field("raw_p_value", pa.string()),
        pa.field("adjusted_q_value", pa.string()),
        pa.field("fdr_significant", pa.bool_()),
        pa.field("fdr_role", pa.string(), nullable=False),
        pa.field("replicate_hash", pa.string()),
        pa.field("research_status", pa.string(), nullable=False),
        pa.field("summary_hash", pa.string(), nullable=False),
        pa.field("summary_json", pa.string(), nullable=False),
    ]
)

FDR_SCHEMA = pa.schema(
    [
        pa.field("family_id", pa.string(), nullable=False),
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("metric_family", pa.string(), nullable=False),
        pa.field("analysis_scope", pa.string(), nullable=False),
        pa.field("hypothesis_count", pa.int64(), nullable=False),
        pa.field("tested_hypothesis_count", pa.int64(), nullable=False),
        pa.field("significant_count", pa.int64(), nullable=False),
        pa.field("q_threshold", pa.string(), nullable=False),
        pa.field("family_hash", pa.string(), nullable=False),
        pa.field("family_json", pa.string(), nullable=False),
    ]
)


def _parquet_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in root.rglob("*.parquet")
            if path.is_file()
            and not path.is_symlink()
            and not path.name.startswith("._")
            and not any(part.startswith("._") for part in path.parts)
        )
    )


def _anchor_index(path: Path) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    parquet = pq.ParquetFile(path)
    columns = ("market_episode_id", "classification_row_hash", "anchor_ns", "episode_status")
    for batch in parquet.iter_batches(batch_size=65_536, columns=columns):
        ids = batch.column(0).to_pylist()
        hashes = batch.column(1).to_pylist()
        anchors = batch.column(2).to_pylist()
        statuses = batch.column(3).to_pylist()
        for episode_id, path_hash, anchor, status in zip(
            ids, hashes, anchors, statuses, strict=True
        ):
            if status != "ELIGIBLE":
                continue
            key = (str(episode_id), str(path_hash))
            if key in result:
                raise ValueError("duplicate T18 prepared-Episode identity")
            result[key] = int(anchor)
    return result


def _group_parts(path: Path, match_root: Path) -> tuple[str, str, str, str, str]:
    relative = path.relative_to(match_root)
    if len(relative.parts) != 4:
        raise ValueError("unexpected T17 match layout")
    instrument, period, fold = relative.parts[:3]
    parameter, timing = relative.stem.rsplit("__", 1)
    return instrument, period, fold, parameter, timing


def _matrix_json(path: Path) -> Iterable[str]:
    parquet = pq.ParquetFile(path)
    if parquet.schema_arrow.field("matrix_json").type != pa.string():
        raise ValueError("T17 matrix_json schema drift")
    for batch in parquet.iter_batches(batch_size=4_096, columns=["matrix_json"]):
        yield from (str(value) for value in batch.column(0).to_pylist())


def aggregate_sources(
    sources: SourceBindings,
    *,
    only_files: Sequence[Path] | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[ClusterSufficientStatistic, ...]:
    anchors = _anchor_index(sources.t16.prepared_episodes_path)
    files = tuple(only_files or sources.t17.match_files)
    output: list[ClusterSufficientStatistic] = []
    started = time.monotonic()
    for index, path in enumerate(files, start=1):
        instrument, period, fold, parameter, timing = _group_parts(path, sources.t17.match_root)
        output.extend(
            aggregate_match_matrices(
                matrix_json_values=_matrix_json(path),
                anchor_by_identity=anchors,
                instrument=instrument,
                period=period,
                fold=fold,
                parameter_set_id=parameter,
                time_combination_id=timing,
            )
        )
        if progress is not None:
            elapsed = max(time.monotonic() - started, 0.000001)
            progress(
                {
                    "phase": "CLUSTER_AGGREGATION",
                    "subphase": "T17_GROUPS",
                    "processed_units": index,
                    "total_units": len(files),
                    "percent": f"{index * 100 / len(files):.6f}",
                    "rows_per_second": f"{index / elapsed:.6f}",
                    "heartbeat_at": datetime.now(UTC).isoformat(),
                }
            )
    return tuple(output)


def _cluster_rows(items: Sequence[ClusterSufficientStatistic]) -> list[dict[str, Any]]:
    return [
        {
            **item.model_dump(mode="python"),
            "statistic_json": canonical_json(item.model_dump(mode="python")),
        }
        for item in items
    ]


def _summary_rows(items: Sequence[BootstrapSummary]) -> list[dict[str, Any]]:
    return [
        {
            **item.model_dump(mode="python"),
            "summary_json": canonical_json(item.model_dump(mode="python")),
        }
        for item in items
    ]


def _fdr_rows(items: Sequence[FdrFamilySummary]) -> list[dict[str, Any]]:
    return [
        {
            **item.model_dump(mode="python"),
            "family_json": canonical_json(item.model_dump(mode="python")),
        }
        for item in items
    ]


def _write_and_strict_read(
    path: Path,
    rows: list[dict[str, Any]],
    schema: pa.Schema,
    model: type[ClusterSufficientStatistic] | type[BootstrapSummary] | type[FdrFamilySummary],
    json_column: str,
) -> None:
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    if pq.read_schema(path) != schema:
        raise ValueError("T18 Parquet schema round-trip drift")
    values = pq.read_table(path, columns=[json_column]).column(0).to_pylist()
    parsed = [model.model_validate_json(str(value), strict=True) for value in values]
    if [canonical_json(item.model_dump(mode="python")) for item in parsed] != [
        str(value) for value in values
    ]:
        raise ValueError("T18 strict JSON round-trip drift")


def format_smoke(
    *,
    policy: BootstrapPolicy,
    sources: SourceBindings,
    repository_root: Path,
) -> dict[str, Any]:
    sample = next(
        path for path in sources.t17.match_files if path.name == "G1-PRIMARY-V1__T2.parquet"
    )
    started = time.monotonic()
    statistics = aggregate_sources(sources, only_files=(sample,))
    summaries, families = compute_all_summaries(statistics, iterations=5000)
    with tempfile.TemporaryDirectory(prefix="era-s2p15-t18-smoke-") as raw:
        root = Path(raw)
        cluster_path = root / "cluster-statistics.parquet"
        summary_path = root / "bootstrap-summaries.parquet"
        fdr_path = root / "fdr-families.parquet"
        _write_and_strict_read(
            cluster_path,
            _cluster_rows(statistics),
            CLUSTER_SCHEMA,
            ClusterSufficientStatistic,
            "statistic_json",
        )
        _write_and_strict_read(
            summary_path,
            _summary_rows(summaries),
            SUMMARY_SCHEMA,
            BootstrapSummary,
            "summary_json",
        )
        _write_and_strict_read(
            fdr_path,
            _fdr_rows(families),
            FDR_SCHEMA,
            FdrFamilySummary,
            "family_json",
        )
        output_hashes = {
            "cluster_statistics": sha256_file(cluster_path),
            "bootstrap_summaries": sha256_file(summary_path),
            "fdr_families": sha256_file(fdr_path),
        }
    payload: dict[str, object] = {
        "schema_name": "s2p15-t18-format-smoke",
        "schema_version": "1.0",
        "status": "PASS",
        "task_id": "S2P15-T18",
        "code_commit": repository_commit(repository_root),
        "policy_hash": policy.policy_hash,
        "source_t16_verify_hash": sources.t16.verify_hash,
        "source_t17_verify_hash": sources.t17.verify_hash,
        "sample_group": str(sample.relative_to(sources.t17.match_root)),
        "cluster_rows": len(statistics),
        "summary_rows": len(summaries),
        "fdr_family_rows": len(families),
        "output_hashes": output_hashes,
        "elapsed_seconds": f"{time.monotonic() - started:.6f}",
        "formal_objects_created": False,
    }
    payload["format_smoke_hash"] = canonical_hash(payload)
    receipt = policy.operations_root / "format-smokes" / f"{payload['format_smoke_hash']}.json"
    if receipt.exists():
        if read_json(receipt) != payload:
            raise ValueError("T18 format-smoke receipt collision")
    else:
        write_exclusive(receipt, payload)
    return cast(dict[str, Any], payload)


def _atomic_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    payload = {**payload, "checkpoint_hash": canonical_hash(payload)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _catalog(root: Path) -> dict[str, Any]:
    files = []
    for path in _parquet_files(root):
        files.append(
            {
                "relative_path": str(path.relative_to(root)),
                "row_count": pq.ParquetFile(path).metadata.num_rows,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload: dict[str, Any] = {
        "schema_name": "s2p15-t18-catalog",
        "schema_version": "1.0",
        "files": files,
    }
    payload["catalog_hash"] = canonical_hash(payload)
    return payload


def _read_cluster_statistics(path: Path) -> tuple[ClusterSufficientStatistic, ...]:
    if pq.read_schema(path) != CLUSTER_SCHEMA:
        raise ValueError("T18 cluster-statistics schema drift")
    return tuple(
        ClusterSufficientStatistic.model_validate_json(str(value), strict=True)
        for value in pq.read_table(path, columns=["statistic_json"]).column(0).to_pylist()
    )


def _read_summaries(path: Path) -> tuple[BootstrapSummary, ...]:
    if pq.read_schema(path) != SUMMARY_SCHEMA:
        raise ValueError("T18 bootstrap-summary schema drift")
    return tuple(
        BootstrapSummary.model_validate_json(str(value), strict=True)
        for value in pq.read_table(path, columns=["summary_json"]).column(0).to_pylist()
    )


def _read_families(path: Path) -> tuple[FdrFamilySummary, ...]:
    if pq.read_schema(path) != FDR_SCHEMA:
        raise ValueError("T18 FDR-family schema drift")
    return tuple(
        FdrFamilySummary.model_validate_json(str(value), strict=True)
        for value in pq.read_table(path, columns=["family_json"]).column(0).to_pylist()
    )


def verify_run(run_root: Path, *, recompute: bool = True) -> dict[str, Any]:
    contract = read_json(run_root / "run-contract.json")
    manifest = read_json(run_root / "published" / "manifest.json")
    catalog = read_json(run_root / "published" / "catalog.json")
    if manifest.get("manifest_hash") != canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    ) or catalog.get("catalog_hash") != canonical_hash(
        {key: value for key, value in catalog.items() if key != "catalog_hash"}
    ):
        raise ValueError("T18 published self Hash drift")
    published = run_root / "published"
    for item in cast(list[dict[str, Any]], catalog["files"]):
        path = published / str(item["relative_path"])
        if (
            sha256_file(path) != item["sha256"]
            or path.stat().st_size != item["byte_size"]
            or pq.ParquetFile(path).metadata.num_rows != item["row_count"]
        ):
            raise ValueError("T18 Catalog file drift")
    cluster_path = published / "cluster-statistics.parquet"
    summary_path = published / "bootstrap-summaries.parquet"
    family_path = published / "fdr-families.parquet"
    statistics = _read_cluster_statistics(cluster_path)
    summaries = _read_summaries(summary_path)
    families = _read_families(family_path)
    if len(summaries) != EXPECTED_SUMMARIES or len(families) != EXPECTED_FDR_FAMILIES:
        raise ValueError("T18 output count drift")
    if recompute:
        expected_summaries, expected_families = compute_all_summaries(statistics)
        if expected_summaries != summaries or expected_families != families:
            raise ValueError("T18 independent bootstrap recomputation drift")
    reconciliation = read_json(published / "reconciliation.json")
    if reconciliation.get("reconciliation_hash") != canonical_hash(
        {key: value for key, value in reconciliation.items() if key != "reconciliation_hash"}
    ) or manifest.get("reconciliation_hash") != reconciliation.get("reconciliation_hash"):
        raise ValueError("T18 reconciliation Hash drift")
    if (
        reconciliation.get("real_matched") != 413_827
        or reconciliation.get("placebo_matched") != 412_021
        or reconciliation.get("placebo_unmatched") != 1_806
        or reconciliation.get("summary_rows") != EXPECTED_SUMMARIES
        or reconciliation.get("status") != "PASS"
    ):
        raise ValueError("T18 reconciliation drift")
    payload: dict[str, Any] = {
        "schema_name": "s2p15-t18-verify-record",
        "schema_version": "1.0",
        "status": "PASS",
        "run_id": contract["run_id"],
        "authority_hash": contract["authority_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "cluster_rows": len(statistics),
        "summary_rows": len(summaries),
        "fdr_family_rows": len(families),
        "research_status": "STATISTICAL_EVIDENCE_ONLY_FINAL_GATE_PENDING",
        "stage3_locked": True,
    }
    payload["verify_hash"] = canonical_hash(payload)
    verify_path = run_root / "verify" / f"{payload['verify_hash']}.json"
    if not verify_path.exists():
        write_exclusive(verify_path, payload)
    return payload


def run_formal(
    *,
    policy: BootstrapPolicy,
    approval_path: Path,
    repository_root: Path,
    _resume_run_root: Path | None = None,
) -> dict[str, Any]:
    if not repository_clean(repository_root):
        raise ValueError("formal T18 Run requires a clean repository")
    sources = audit_sources(policy, repository_root=repository_root, full_hash_scan=True)
    approval = validate_approval(approval_path, policy=policy, repository_root=repository_root)
    smoke = read_json(
        policy.operations_root / "format-smokes" / f"{approval['format_smoke_hash']}.json"
    )
    if smoke.get("status") != "PASS":
        raise ValueError("formal T18 Run requires passing format smoke")
    lock_path = policy.operations_root / "run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another T18 Run holds the unique lock") from error
        existing_runs = tuple(
            path
            for path in (policy.evidence_root / "runs").glob("stage2-s2p15-t18-*")
            if path.is_dir() and not path.is_symlink()
        )
        if existing_runs and _resume_run_root is None:
            raise ValueError("T18 formal Run already exists; successor approval required")
        if _resume_run_root is None:
            authority = freeze_authority(
                policy=policy,
                approval=approval,
                sources=sources,
                repository_root=repository_root,
            )
            run_id = (
                f"stage2-s2p15-t18-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
                f"{authority.authority_hash[:12]}"
            )
            run_root = policy.evidence_root / "runs" / run_id
            run_root.mkdir(parents=True, exist_ok=False)
            contract = {
                "schema_name": "s2p15-t18-run-contract",
                "schema_version": "1.0",
                "run_id": run_id,
                "authority_hash": authority.authority_hash,
                "code_commit": repository_commit(repository_root),
                "policy_hash": policy.policy_hash,
                "source_t16_verify_hash": sources.t16.verify_hash,
                "source_t17_verify_hash": sources.t17.verify_hash,
                "status": "UNPUBLISHED",
            }
            contract["run_contract_hash"] = canonical_hash(contract)
            write_exclusive(run_root / "run-contract.json", contract)
        else:
            run_root = _resume_run_root
            if (
                len(existing_runs) != 1
                or existing_runs[0].resolve() != run_root.resolve()
                or run_root.is_symlink()
            ):
                raise ValueError("T18 resume Run identity drift")
            contract = read_json(run_root / "run-contract.json")
            if (
                contract.get("run_contract_hash")
                != canonical_hash(
                    {key: value for key, value in contract.items() if key != "run_contract_hash"}
                )
                or contract.get("code_commit") != repository_commit(repository_root)
                or contract.get("policy_hash") != policy.policy_hash
                or contract.get("source_t16_verify_hash") != sources.t16.verify_hash
                or contract.get("source_t17_verify_hash") != sources.t17.verify_hash
            ):
                raise ValueError("T18 resume contract drift")
            run_id = str(contract["run_id"])
            authority_path = (
                policy.evidence_root
                / "authorities"
                / f"authority-{contract['authority_hash']}.json"
            )
            authority = S2P15T18Authority.model_validate_json(
                authority_path.read_text(encoding="utf-8"),
                strict=True,
            )
            if (
                authority.approval_hash != approval.get("approval_hash")
                or authority.code_commit != repository_commit(repository_root)
                or authority.policy_hash != policy.policy_hash
            ):
                raise ValueError("T18 resume Authority/approval drift")
            if (run_root / "published").is_dir():
                return verify_run(run_root)
        checkpoint = run_root / "checkpoint.json"
        started = time.monotonic()

        def progress(payload: dict[str, Any]) -> None:
            _atomic_checkpoint(
                checkpoint,
                {
                    "schema_name": "s2p15-t18-checkpoint",
                    "schema_version": "1.0",
                    "run_id": run_id,
                    "status": "IN_PROGRESS",
                    "elapsed_seconds": f"{time.monotonic() - started:.6f}",
                    **payload,
                },
            )

        work = run_root / "work"
        work.mkdir(exist_ok=True)
        cluster_path = work / "cluster-statistics.parquet"
        if cluster_path.exists():
            statistics = _read_cluster_statistics(cluster_path)
        else:
            statistics = aggregate_sources(sources, progress=progress)
            _write_and_strict_read(
                cluster_path,
                _cluster_rows(statistics),
                CLUSTER_SCHEMA,
                ClusterSufficientStatistic,
                "statistic_json",
            )
        bootstrap_started: dict[str, float] = {}

        def bootstrap_progress(metric: MetricFamily, processed: int, total: int) -> None:
            phase = {
                "REAL_EVENT_DELTA": "REAL_BOOTSTRAP",
                "PLACEBO_DELTA": "PLACEBO_BOOTSTRAP",
                "PAIRED_REAL_MINUS_PLACEBO": "PAIRED_CONTRAST",
            }[metric]
            phase_started = bootstrap_started.setdefault(phase, time.monotonic())
            elapsed = max(time.monotonic() - phase_started, 0.000001)
            units_per_second = processed / elapsed
            progress(
                {
                    "phase": phase,
                    "subphase": "VECTORIZED_5000",
                    "processed_units": processed,
                    "total_units": total,
                    "percent": f"{processed * 100 / total:.6f}",
                    "units_per_second": f"{units_per_second:.6f}",
                    "eta_seconds": f"{max(0, total - processed) / units_per_second:.6f}",
                    "heartbeat_at": datetime.now(UTC).isoformat(),
                }
            )

        summaries, families = compute_all_summaries(statistics, progress=bootstrap_progress)
        progress(
            {
                "phase": "BH_FDR",
                "subphase": "BENJAMINI_HOCHBERG",
                "processed_units": len(families),
                "total_units": EXPECTED_FDR_FAMILIES,
                "percent": "100.000000",
                "heartbeat_at": datetime.now(UTC).isoformat(),
            }
        )
        summary_path = work / "bootstrap-summaries.parquet"
        family_path = work / "fdr-families.parquet"
        if summary_path.exists():
            if _read_summaries(summary_path) != summaries:
                raise ValueError("T18 resumed summary drift")
        else:
            _write_and_strict_read(
                summary_path,
                _summary_rows(summaries),
                SUMMARY_SCHEMA,
                BootstrapSummary,
                "summary_json",
            )
        if family_path.exists():
            if _read_families(family_path) != families:
                raise ValueError("T18 resumed FDR-family drift")
        else:
            _write_and_strict_read(
                family_path,
                _fdr_rows(families),
                FDR_SCHEMA,
                FdrFamilySummary,
                "family_json",
            )
        real_count = sum(item.real_count for item in statistics)
        placebo_count = sum(item.placebo_count for item in statistics)
        reconciliation: dict[str, Any] = {
            "schema_name": "s2p15-t18-reconciliation",
            "schema_version": "1.0",
            "real_matched": real_count,
            "placebo_matched": placebo_count,
            "placebo_unmatched": real_count - placebo_count,
            "cluster_rows": len(statistics),
            "summary_rows": len(summaries),
            "fdr_family_rows": len(families),
            "status": "PASS"
            if (
                real_count == 413_827
                and placebo_count == 412_021
                and len(summaries) == EXPECTED_SUMMARIES
                and len(families) == EXPECTED_FDR_FAMILIES
            )
            else "FAILED_UNPUBLISHED",
        }
        reconciliation["reconciliation_hash"] = canonical_hash(reconciliation)
        if reconciliation["status"] != "PASS":
            raise ValueError("T18 reconciliation failed")
        reconciliation_path = work / "reconciliation.json"
        if reconciliation_path.exists():
            if read_json(reconciliation_path) != reconciliation:
                raise ValueError("T18 resumed reconciliation drift")
        else:
            write_exclusive(reconciliation_path, reconciliation)
        progress(
            {
                "phase": "PUBLISH",
                "subphase": "APPEND_ONLY",
                "processed_units": 0,
                "total_units": 1,
                "percent": "0.000000",
                "heartbeat_at": datetime.now(UTC).isoformat(),
            }
        )
        publish_temp = run_root / "published.tmp"
        if publish_temp.exists():
            raise ValueError("T18 partial publish requires explicit integrity review")
        publish_temp.mkdir()
        shutil.copy2(cluster_path, publish_temp / cluster_path.name)
        shutil.copy2(summary_path, publish_temp / summary_path.name)
        shutil.copy2(family_path, publish_temp / family_path.name)
        shutil.copy2(work / "reconciliation.json", publish_temp / "reconciliation.json")
        catalog = _catalog(publish_temp)
        write_exclusive(publish_temp / "catalog.json", catalog)
        manifest: dict[str, Any] = {
            "schema_name": "s2p15-t18-manifest",
            "schema_version": "1.0",
            "run_id": run_id,
            "authority_hash": authority.authority_hash,
            "catalog_hash": catalog["catalog_hash"],
            "reconciliation_hash": reconciliation["reconciliation_hash"],
            "source_t16_verify_hash": sources.t16.verify_hash,
            "source_t17_verify_hash": sources.t17.verify_hash,
            "research_status": "STATISTICAL_EVIDENCE_ONLY_FINAL_GATE_PENDING",
            "stage3_locked": True,
        }
        manifest["manifest_hash"] = canonical_hash(manifest)
        write_exclusive(publish_temp / "manifest.json", manifest)
        os.replace(publish_temp, run_root / "published")
        progress(
            {
                "phase": "VERIFY",
                "subphase": "INDEPENDENT_RECOMPUTE",
                "processed_units": 0,
                "total_units": 1,
                "percent": "0.000000",
                "heartbeat_at": datetime.now(UTC).isoformat(),
            }
        )
        verify = verify_run(run_root)
        _atomic_checkpoint(
            checkpoint,
            {
                "schema_name": "s2p15-t18-checkpoint",
                "schema_version": "1.0",
                "run_id": run_id,
                "status": "PASS",
                "phase": "VERIFY",
                "subphase": "COMPLETE",
                "processed_units": 1,
                "total_units": 1,
                "percent": "100.000000",
                "elapsed_seconds": f"{time.monotonic() - started:.6f}",
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "verify_hash": verify["verify_hash"],
            },
        )
        return verify


def resume_formal(
    *,
    policy: BootstrapPolicy,
    approval_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    runs = tuple(
        path
        for path in (policy.evidence_root / "runs").glob("stage2-s2p15-t18-*")
        if path.is_dir() and not path.is_symlink()
    )
    if len(runs) != 1:
        raise ValueError("T18 resume requires exactly one Run")
    checkpoint = read_json(runs[0] / "checkpoint.json")
    if checkpoint.get("status") == "PASS":
        return verify_run(runs[0], recompute=False)
    if checkpoint.get("status") not in {"IN_PROGRESS", "RETRYABLE_INTERRUPTED"}:
        raise ValueError("T18 terminal prefix cannot resume")
    return run_formal(
        policy=policy,
        approval_path=approval_path,
        repository_root=repository_root,
        _resume_run_root=runs[0],
    )
