"""Append-only full execution, publication and verification for S2-T15 v1.4."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .binning_run import prepare_feature_block, read_binning_set
from .episode_producer import prepare_episode_evidence
from .h2_control_reader import H2ControlReader
from .outcome_blind_producer import BinningIndex, SameFamilyIntervals, match_group
from .outcome_run import produce_post_selection_evidence
from .reconciliation import ControlReconciliation, EpisodeReconciliation
from .successor_policy import (
    require_final_successor_creation_state,
    require_final_successor_resume_state,
)
from .t10_access import FixedT10Reader, read_json_file
from .v14_contracts import (
    ConditionalBaselineMatchMatrix,
    COMBINATION_ORDER,
    ControlOutcomeMatrix,
    EXPECTED_H2_OUTCOME_CELLS,
    EXPECTED_H2_PATHS,
    REGISTERED_PARAMETER_TIMING_PAIRS,
    S2T15ContractAuthority,
    canonical_hash,
)

RUN_PATTERN = re.compile(r"^stage2-s2t15-conditional-\d{8}T\d{6}Z-[0-9a-f]{12}$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def _new_run_id(authority_hash: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    value = f"stage2-s2t15-conditional-{timestamp}-{authority_hash[:12]}"
    if not RUN_PATTERN.fullmatch(value):
        raise AssertionError("internally generated unsafe T15 Run ID")
    return value


def _selection_relative(
    instrument: str, period: str, fold: str, parameter: str, timing: str
) -> Path:
    return Path(instrument) / period / fold / f"{parameter}__{timing}.parquet"


def _report_relative(path: Path) -> Path:
    return path.with_suffix(".report.json")


def _copy_tree_files(source: Path, destination: Path) -> None:
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise ValueError("symlinked run evidence cannot be published")
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with path.open("rb") as reader, target.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=8 * 1024 * 1024)


def _publication_entries(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in {"catalog.json", "manifest.json"}:
            continue
        item: dict[str, Any] = {
            "relative_path": str(path.relative_to(root)),
            "byte_size": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        if path.suffix == ".parquet":
            item["row_count"] = pq.ParquetFile(path).metadata.num_rows
        result.append(item)
    return result


def _aggregate_reconciliation(
    *,
    episode_report: dict[str, Any],
    selection_reports: list[dict[str, Any]],
    post_report: dict[str, Any],
) -> tuple[EpisodeReconciliation, ControlReconciliation]:
    matched = sum(int(report["matched_episode_count"]) for report in selection_reports)
    unmatched = sum(int(report["unmatched_episode_count"]) for report in selection_reports)
    episode = EpisodeReconciliation(
        source_h2_path_count=int(episode_report["source_h2_path_count"]),
        train_only_not_evaluated_count=int(episode_report["train_only_not_evaluated_count"]),
        excluded_episode_count=int(episode_report["excluded_episode_count"]),
        eligible_episode_count=int(episode_report["eligible_episode_count"]),
        matched_episode_count=matched,
        unmatched_episode_count=unmatched,
        source_h2_outcome_cell_count=EXPECTED_H2_OUTCOME_CELLS,
        event_outcome_cell_count=int(episode_report["eligible_episode_count"]) * 30,
    )
    episode.require_frozen_source_baseline()
    unique_grid_reports: dict[tuple[str, str, str], dict[str, int]] = {}
    candidate_counts = {
        "candidate_opportunity_count": 0,
        "key_level_unavailable": 0,
        "registered_same_family_event": 0,
        "outcome_source_unavailable": 0,
        "eligible_control_count": 0,
        "unique_control_candidate_count": 0,
    }
    for report in selection_reports:
        key = (str(report["instrument"]), str(report["period"]), str(report["fold"]))
        accounting = cast(dict[str, int], report["control_accounting"])
        existing = unique_grid_reports.setdefault(key, accounting)
        for field in (
            "grid_anchor_count",
            "incomplete_information_span",
            "price_feature_unavailable",
            "activity_feature_unavailable",
            "context_unavailable",
            "market_state_eligible_anchor_count",
        ):
            if int(existing.get(field, 0)) != int(accounting.get(field, 0)):
                raise ValueError("parameter groups disagree on base control-grid accounting")
        for field in candidate_counts:
            candidate_counts[field] += int(accounting.get(field, 0))
    grid = {
        field: 0
        for field in (
            "grid_anchor_count",
            "incomplete_information_span",
            "price_feature_unavailable",
            "activity_feature_unavailable",
            "context_unavailable",
            "market_state_eligible_anchor_count",
        )
    }
    for accounting in unique_grid_reports.values():
        for field in grid:
            grid[field] += int(accounting.get(field, 0))
    control = ControlReconciliation(
        grid_anchor_count=grid["grid_anchor_count"],
        outside_period_or_split=0,
        incomplete_information_span=grid["incomplete_information_span"],
        price_feature_unavailable=grid["price_feature_unavailable"],
        activity_feature_unavailable=grid["activity_feature_unavailable"],
        context_unavailable=grid["context_unavailable"],
        market_state_eligible_anchor_count=grid["market_state_eligible_anchor_count"],
        candidate_opportunity_count=candidate_counts["candidate_opportunity_count"],
        key_level_unavailable=candidate_counts["key_level_unavailable"],
        registered_same_family_event=candidate_counts["registered_same_family_event"],
        outcome_source_unavailable=0,
        eligible_control_count=candidate_counts["eligible_control_count"],
        unique_control_candidate_count=candidate_counts["unique_control_candidate_count"],
        matched_episode_count=matched,
        control_assignment_count=int(post_report["control_assignment_count"]),
        orphan_assignment_count=0,
        duplicate_assignment_within_episode=0,
        control_outcome_matrix_count=int(post_report["control_outcome_matrix_count"]),
        control_outcome_cell_count=int(post_report["control_outcome_cell_count"]),
    )
    return episode, control


def run_full_execution(
    *,
    authority_path: Path,
    binning_set_path: Path,
    runs_root: Path,
    t10_snapshot: Path,
    t10_snapshot_id: str,
    t13_snapshot: Path,
    current_commit: str,
    repository_clean: bool,
    resume_run_id: str | None = None,
) -> tuple[dict[str, Any], Path]:
    authority = S2T15ContractAuthority.model_validate_json(
        json.dumps(read_json_file(authority_path), ensure_ascii=False, sort_keys=True)
    )
    bins = read_binning_set(binning_set_path, authority_hash=authority.authority_hash)
    if authority.code_commit != current_commit or not repository_clean:
        raise ValueError("T15 run requires the clean Authority commit")
    if bins.get("code_commit") != current_commit:
        raise ValueError("T15 binning set was not frozen by the Authority commit")
    if resume_run_id is None:
        predecessor = require_final_successor_creation_state(runs_root)
        run_id = _new_run_id(authority.authority_hash)
        run_root = runs_root / run_id
        run_root.mkdir(parents=False, exist_ok=False)
        checkpoint_path = run_root / "checkpoint.json"
        checkpoint: dict[str, Any] = {
            "schema_name": "stage2-s2t15-checkpoint",
            "schema_version": "1.0",
            "run_id": run_id,
            "status": "IN_PROGRESS",
            "phase": "INITIALIZED",
            "completed_group_count": 0,
            "expected_group_count": 456,
            "authority_hash": authority.authority_hash,
            "binning_set_hash": bins["binning_set_hash"],
            "supersedes_failed_run_id": predecessor.name,
            "historical_evidence_only": True,
            "stage3_locked": True,
        }
        _write_checkpoint(checkpoint_path, checkpoint)
        _write_json_exclusive(
            run_root / "manifests" / "authority.json", authority.model_dump(mode="json")
        )
        _write_json_exclusive(run_root / "manifests" / "binning-set.json", bins)
    else:
        if not RUN_PATTERN.fullmatch(resume_run_id):
            raise ValueError("unsafe T15 resume Run ID")
        run_id = resume_run_id
        run_root = runs_root / run_id
        predecessor = require_final_successor_resume_state(runs_root, run_id)
        checkpoint_path = run_root / "checkpoint.json"
        checkpoint = read_json_file(checkpoint_path)
        if (
            checkpoint.get("run_id") != run_id
            or checkpoint.get("authority_hash") != authority.authority_hash
            or checkpoint.get("binning_set_hash") != bins["binning_set_hash"]
            or checkpoint.get("status")
            not in {"IN_PROGRESS", "COMPLETE_PENDING_VERIFY", "VERIFIED_PASS"}
        ):
            raise ValueError("T15 resume checkpoint binding or status drift")
        stored_authority = S2T15ContractAuthority.model_validate_json(
            json.dumps(
                read_json_file(run_root / "manifests" / "authority.json"),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        stored_bins = read_json_file(run_root / "manifests" / "binning-set.json")
        if stored_authority != authority or stored_bins != bins:
            raise ValueError("T15 resume Authority or binning evidence drift")
    execution_manifest: dict[str, Any] = {
        "schema_name": "stage2-s2t15-execution-manifest",
        "schema_version": "1.0",
        "run_id": run_id,
        "authority_hash": authority.authority_hash,
        "binning_set_hash": bins["binning_set_hash"],
        "code_commit": current_commit,
        "supersedes_failed_run_id": predecessor.name,
        "expected_h2_path_count": EXPECTED_H2_PATHS,
        "expected_h2_outcome_cell_count": EXPECTED_H2_OUTCOME_CELLS,
        "expected_group_count": 456,
        "registered_parameter_timing_pairs": [
            list(value) for value in REGISTERED_PARAMETER_TIMING_PAIRS
        ],
        "output_layout": [
            "prepared-episodes",
            "outcome-blind-selections",
            "control-outcome-matrices",
            "conditional-match-matrices",
            "descriptive-summaries",
            "reconciliation",
        ],
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    execution_manifest["execution_manifest_hash"] = canonical_hash(execution_manifest)
    execution_manifest_path = run_root / "manifests" / "execution-manifest.json"
    if resume_run_id is None:
        _write_json_exclusive(execution_manifest_path, execution_manifest)
    elif read_json_file(execution_manifest_path) != execution_manifest:
        raise ValueError("T15 resume execution Manifest drift")
    if checkpoint.get("status") in {"COMPLETE_PENDING_VERIFY", "VERIFIED_PASS"}:
        snapshot_id = str(checkpoint.get("snapshot_id", ""))
        published = run_root / "published" / "snapshots" / snapshot_id
        published_manifest = read_json_file(published / "manifest.json")
        if published_manifest.get("snapshot_id") != snapshot_id:
            raise ValueError("T15 resumed publication identity drift")
        return published_manifest, published

    reader = FixedT10Reader(t10_snapshot, expected_snapshot_id=t10_snapshot_id)
    parameter_ids = tuple(value[0] for value in REGISTERED_PARAMETER_TIMING_PAIRS)
    evaluation_feature_root = run_root / "work" / "evaluation-features"
    checkpoint["phase"] = "PREPARING_HOLDOUT_FEATURES"
    _write_checkpoint(checkpoint_path, checkpoint)
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for period in ("P1", "P2", "P3"):
            prepare_feature_block(
                reader=reader,
                root=evaluation_feature_root,
                authority_hash=authority.authority_hash,
                instrument=instrument,
                period=period,
                block_index=4,
                parameter_set_ids=parameter_ids,
            )

    checkpoint["phase"] = "PREPARING_EPISODES"
    _write_checkpoint(checkpoint_path, checkpoint)
    episode_root = run_root / "work" / "episodes"
    episode_report, episode_path = prepare_episode_evidence(
        reader=reader, t13_snapshot=t13_snapshot, output_root=episode_root
    )
    episode_table = pq.read_table(episode_path)
    same_family = SameFamilyIntervals(episode_table)
    bin_index = BinningIndex(binning_set_path, authority_hash=authority.authority_hash)
    selections_root = run_root / "work" / "selections"
    selection_reports: list[dict[str, Any]] = []
    checkpoint["phase"] = "OUTCOME_BLIND_MATCHING"
    _write_checkpoint(checkpoint_path, checkpoint)
    bin_root = binning_set_path.parent
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for period in ("P1", "P2", "P3"):
            for fold_index in range(4):
                fold = f"F{fold_index}"
                block_index = fold_index + 1
                feature_root = bin_root if block_index < 4 else evaluation_feature_root
                feature_path = (
                    feature_root / "prepared" / instrument / period / f"B{block_index}.parquet"
                )
                base_mask = pc.and_(
                    pc.equal(episode_table["episode_status"], "ELIGIBLE"),
                    pc.and_(
                        pc.equal(episode_table["instrument"], instrument),
                        pc.and_(
                            pc.equal(episode_table["pre_registered_period"], period),
                            pc.equal(episode_table["evaluation_fold"], fold),
                        ),
                    ),
                )
                base = episode_table.filter(base_mask)
                for parameter, timing in REGISTERED_PARAMETER_TIMING_PAIRS:
                    group = base.filter(pc.equal(base["parameter_set_id"], parameter))
                    if group.num_rows and not all(
                        value == timing for value in group["time_combination_id"].to_pylist()
                    ):
                        raise ValueError("Episode parameter/timing isolation drift")
                    relative = _selection_relative(instrument, period, fold, parameter, timing)
                    output = selections_root / relative
                    report_path = selections_root / _report_relative(relative)
                    if output.exists() or report_path.exists():
                        if output.is_symlink() or report_path.is_symlink():
                            raise ValueError("symlinked selection evidence cannot be resumed")
                        if not output.is_file() or not report_path.is_file():
                            raise ValueError("partial selection group cannot be resumed")
                        report = read_json_file(report_path)
                        report_core = {
                            key: value for key, value in report.items() if key != "report_hash"
                        }
                        if (
                            canonical_hash(report_core) != report.get("report_hash")
                            or report.get("selection_parquet_sha256") != _sha256_file(output)
                            or report.get("status") != "PASS"
                            or (
                                report.get("instrument"),
                                report.get("period"),
                                report.get("fold"),
                                report.get("parameter_set_id"),
                                report.get("time_combination_id"),
                            )
                            != (instrument, period, fold, parameter, timing)
                            or report.get("outcome_fields_read_before_matching") != []
                        ):
                            raise ValueError("selection group failed resume validation")
                    else:
                        report = match_group(
                            authority=authority,
                            bins=bin_index,
                            same_family=same_family,
                            episode_rows=cast(list[dict[str, Any]], group.to_pylist()),
                            feature_block_path=feature_path,
                            instrument=instrument,
                            period=period,
                            fold=fold,
                            parameter_set_id=parameter,
                            time_combination_id=timing,
                            output_path=output,
                            t10_snapshot_hash=t10_snapshot_id,
                        )
                        _write_json_exclusive(report_path, report)
                    selection_reports.append(report)
                    checkpoint["completed_group_count"] = len(selection_reports)
                    _write_checkpoint(checkpoint_path, checkpoint)
    if len(selection_reports) != 456:
        raise ValueError("outcome-blind matching group universe is incomplete")

    checkpoint["phase"] = "POST_SELECTION_H2_OUTCOMES"
    _write_checkpoint(checkpoint_path, checkpoint)
    attempt = run_root / "work" / f"post-selection-{uuid.uuid4().hex}"
    h2_reader = H2ControlReader(t10_snapshot=t10_snapshot, t10_snapshot_id=t10_snapshot_id)
    post_report = produce_post_selection_evidence(
        selection_root=selections_root,
        output_root=attempt,
        h2_reader=h2_reader,
    )
    episode_reconciliation, control_reconciliation = _aggregate_reconciliation(
        episode_report=episode_report,
        selection_reports=selection_reports,
        post_report=post_report,
    )
    reconciliation: dict[str, Any] = {
        "schema_name": "stage2-s2t15-reconciliation",
        "schema_version": "1.0",
        "status": "PASS",
        "episode": episode_reconciliation.model_dump(mode="json"),
        "control": control_reconciliation.model_dump(mode="json"),
        "historical_evidence_only": True,
    }
    reconciliation["reconciliation_hash"] = canonical_hash(reconciliation)

    checkpoint["phase"] = "PUBLISHING"
    _write_checkpoint(checkpoint_path, checkpoint)
    staging = run_root / "staging" / uuid.uuid4().hex
    _copy_tree_files(episode_root, staging / "episodes")
    _copy_tree_files(selections_root, staging / "selections")
    for name in (
        "control_outcome_matrices.parquet",
        "conditional_match_matrices.parquet",
        "descriptive_summaries.parquet",
    ):
        source = attempt / name
        target = staging / "results" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as input_handle, target.open("xb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle, length=8 * 1024 * 1024)
    _copy_tree_files(evaluation_feature_root, staging / "evaluation-features")
    _write_json_exclusive(staging / "reports" / "post-selection.json", post_report)
    _write_json_exclusive(staging / "reports" / "reconciliation.json", reconciliation)
    entries = _publication_entries(staging)
    catalog: dict[str, Any] = {
        "schema_name": "stage2-s2t15-catalog",
        "schema_version": "1.0",
        "run_id": run_id,
        "authority_hash": authority.authority_hash,
        "binning_set_hash": bins["binning_set_hash"],
        "files": entries,
        "historical_evidence_only": True,
    }
    catalog["catalog_hash"] = canonical_hash(catalog)
    snapshot_id = str(catalog["catalog_hash"])
    manifest: dict[str, Any] = {
        "schema_name": "stage2-s2t15-manifest",
        "schema_version": "1.0",
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "authority_hash": authority.authority_hash,
        "binning_set_hash": bins["binning_set_hash"],
        "execution_manifest_hash": execution_manifest["execution_manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "reconciliation_hash": reconciliation["reconciliation_hash"],
        "research_result": "DESCRIPTIVE_ONLY_PRIMARY_PENDING_T18",
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    catalog["snapshot_id"] = snapshot_id
    catalog["manifest_hash"] = manifest["manifest_hash"]
    _write_json_exclusive(staging / "catalog.json", catalog)
    _write_json_exclusive(staging / "manifest.json", manifest)
    published = run_root / "published" / "snapshots" / snapshot_id
    published.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, published)
    checkpoint.update(
        {
            "status": "COMPLETE_PENDING_VERIFY",
            "phase": "PUBLISHED",
            "snapshot_id": snapshot_id,
            "manifest_hash": manifest["manifest_hash"],
        }
    )
    _write_checkpoint(checkpoint_path, checkpoint)
    return manifest, published


def verify_published_run(*, run_root: Path) -> tuple[dict[str, Any], Path]:
    """Rescan all published T15 evidence and independently recompute summaries."""

    if run_root.is_symlink() or not run_root.is_dir() or not RUN_PATTERN.fullmatch(run_root.name):
        raise ValueError("unsafe T15 Run root")
    checkpoint_path = run_root / "checkpoint.json"
    checkpoint = read_json_file(checkpoint_path)
    snapshot_id = str(checkpoint.get("snapshot_id", ""))
    snapshot = run_root / "published" / "snapshots" / snapshot_id
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError("missing published T15 snapshot")
    catalog = read_json_file(snapshot / "catalog.json")
    manifest = read_json_file(snapshot / "manifest.json")
    catalog_core = {
        key: value
        for key, value in catalog.items()
        if key not in {"catalog_hash", "snapshot_id", "manifest_hash"}
    }
    if canonical_hash(catalog_core) != catalog.get("catalog_hash"):
        raise ValueError("T15 Catalog hash mismatch")
    if snapshot_id != catalog.get("catalog_hash") or snapshot_id != manifest.get("snapshot_id"):
        raise ValueError("T15 snapshot identity mismatch")
    if canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    ) != manifest.get("manifest_hash"):
        raise ValueError("T15 Manifest hash mismatch")
    actual_entries = _publication_entries(snapshot)
    if actual_entries != catalog.get("files"):
        raise ValueError("T15 Catalog file inventory drift")

    episode_path = snapshot / "episodes" / "prepared-episodes.parquet"
    episode_table = pq.read_table(
        episode_path,
        columns=["classification_row_hash", "episode_status"],
    )
    if episode_table.num_rows != EXPECTED_H2_PATHS:
        raise ValueError("published Episode source count drift")
    eligible_hashes = {
        str(row_hash)
        for row_hash, status in zip(
            episode_table["classification_row_hash"].to_pylist(),
            episode_table["episode_status"].to_pylist(),
            strict=True,
        )
        if status == "ELIGIBLE"
    }

    outcome_path = snapshot / "results" / "control_outcome_matrices.parquet"
    outcome_masks: dict[str, int] = {}
    matrix_ids: set[str] = set()
    for batch in pq.ParquetFile(outcome_path).iter_batches(
        batch_size=2_000,
        columns=["control_candidate_id", "control_outcome_matrix_id", "matrix_json"],
    ):
        for row in pa.Table.from_batches([batch]).to_pylist():
            control_matrix = ControlOutcomeMatrix.model_validate_json(row["matrix_json"])
            if (
                control_matrix.control_candidate_id != row["control_candidate_id"]
                or control_matrix.control_outcome_matrix_id != row["control_outcome_matrix_id"]
                or control_matrix.control_outcome_matrix_id in matrix_ids
            ):
                raise ValueError("control outcome identity or uniqueness drift")
            matrix_ids.add(control_matrix.control_outcome_matrix_id)
            outcome_masks[control_matrix.control_outcome_matrix_id] = sum(
                cell.strict_target_first << index
                for index, cell in enumerate(control_matrix.outcomes)
            )

    match_path = snapshot / "results" / "conditional_match_matrices.parquet"
    observed_episode_hashes: set[str] = set()
    group_totals: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    matched_total = 0
    assignment_total = 0
    for batch in pq.ParquetFile(match_path).iter_batches(batch_size=2_000):
        for row in pa.Table.from_batches([batch]).to_pylist():
            match_matrix = ConditionalBaselineMatchMatrix.model_validate_json(row["matrix_json"])
            if match_matrix.output_hash != row["output_hash"]:
                raise ValueError("conditional match matrix output hash drift")
            if match_matrix.source_h2_path_hash in observed_episode_hashes:
                raise ValueError("eligible Episode was matched more than once")
            observed_episode_hashes.add(match_matrix.source_h2_path_hash)
            if not set(match_matrix.control_outcome_matrix_ids).issubset(matrix_ids):
                raise ValueError("match references an unknown control outcome matrix")
            key = (
                str(row["instrument"]),
                str(row["pre_registered_period"]),
                str(row["evaluation_fold"]),
                str(row["parameter_set_id"]),
                str(row["time_combination_id"]),
            )
            totals = group_totals.setdefault(
                key,
                {
                    "eligible": 0,
                    "matched": 0,
                    "event": [0] * 30,
                    "baseline": [Decimal(0)] * 30,
                },
            )
            totals["eligible"] += 1
            if match_matrix.status == "MATCHED":
                totals["matched"] += 1
                matched_total += 1
                assignment_total += 5
                for index, event in enumerate(match_matrix.event_outcomes):
                    totals["event"][index] += event.strict_target_first
                    totals["baseline"][index] += Decimal(
                        sum(
                            (outcome_masks[matrix_id] >> index) & 1
                            for matrix_id in match_matrix.control_outcome_matrix_ids
                        )
                    ) / Decimal(5)
    if observed_episode_hashes != eligible_hashes:
        raise ValueError("published eligible Episode universe is not matched exactly once")

    summaries_path = snapshot / "results" / "descriptive_summaries.parquet"
    summary_rows = cast(list[dict[str, Any]], pq.read_table(summaries_path).to_pylist())
    expected_summary_count = len(group_totals) * 30
    if len(summary_rows) != expected_summary_count:
        raise ValueError("descriptive summary group/cell universe drift")
    for row in summary_rows:
        key = (
            str(row["instrument"]),
            str(row["pre_registered_period"]),
            str(row["evaluation_fold"]),
            str(row["parameter_set_id"]),
            str(row["time_combination_id"]),
        )
        totals = group_totals[key]
        index = COMBINATION_ORDER.index(str(row["combination_id"]))
        matched = int(totals["matched"])
        if matched:
            event_rate = Decimal(totals["event"][index]) / Decimal(matched)
            baseline_rate = Decimal(totals["baseline"][index]) / Decimal(matched)
            expected: tuple[str | None, str | None, str | None] = (
                format(event_rate, "f"),
                format(baseline_rate, "f"),
                format(event_rate - baseline_rate, "f"),
            )
        else:
            expected = (None, None, None)
        actual = (
            row["event_target_first_rate"],
            row["baseline_target_first_rate"],
            row["delta_target_first"],
        )
        if actual != expected:
            raise ValueError("descriptive summary recomputation mismatch")
        if (
            int(row["eligible_episode_count"]) != int(totals["eligible"])
            or int(row["matched_episode_count"]) != matched
        ):
            raise ValueError("descriptive summary count mismatch")

    reconciliation_path = snapshot / "reports" / "reconciliation.json"
    reconciliation = read_json_file(reconciliation_path)
    claimed_reconciliation = reconciliation.get("reconciliation_hash")
    if (
        canonical_hash(
            {key: value for key, value in reconciliation.items() if key != "reconciliation_hash"}
        )
        != claimed_reconciliation
    ):
        raise ValueError("reconciliation report hash mismatch")
    episode_reconciliation = EpisodeReconciliation.model_validate(reconciliation["episode"])
    episode_reconciliation.require_frozen_source_baseline()
    control_reconciliation = ControlReconciliation.model_validate(reconciliation["control"])
    if (
        episode_reconciliation.eligible_episode_count != len(eligible_hashes)
        or episode_reconciliation.matched_episode_count != matched_total
        or control_reconciliation.control_assignment_count != assignment_total
        or control_reconciliation.control_outcome_matrix_count != len(matrix_ids)
    ):
        raise ValueError("reconciliation disagrees with rescanned published evidence")
    verify: dict[str, Any] = {
        "schema_name": "stage2-s2t15-verify-record",
        "schema_version": "1.0",
        "status": "PASS",
        "run_id": run_root.name,
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "reconciliation_hash": claimed_reconciliation,
        "source_h2_path_count": EXPECTED_H2_PATHS,
        "source_h2_outcome_cell_count": EXPECTED_H2_OUTCOME_CELLS,
        "eligible_episode_count": len(eligible_hashes),
        "matched_episode_count": matched_total,
        "unmatched_episode_count": len(eligible_hashes) - matched_total,
        "control_assignment_count": assignment_total,
        "unique_control_outcome_matrix_count": len(matrix_ids),
        "summary_row_count": len(summary_rows),
        "research_result": "DESCRIPTIVE_ONLY_PRIMARY_PENDING_T18",
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    verify["verify_hash"] = canonical_hash(verify)
    verify_path = run_root / "verify" / f"{verify['verify_hash']}.json"
    _write_json_exclusive(verify_path, verify)
    checkpoint.update(
        {
            "status": "VERIFIED_PASS",
            "phase": "COMPLETE",
            "verify_hash": verify["verify_hash"],
        }
    )
    _write_checkpoint(checkpoint_path, checkpoint)
    return verify, verify_path
