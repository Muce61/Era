"""Real Plan v1.8 producer adapters over the frozen Stage 2 research engines.

The module gives every successor Task a new S2P18 identity while treating the
older task-specific implementations as mathematical engines only.  No legacy
receipt, Authority, Run ID or fixed result count is adopted.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Final, cast

import ijson  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    read_canonical_json,
    sha256_file,
    write_canonical_json_exclusive,
)

from .formal_chain import TASK_ORDER, producer_receipt
from .governance import load_source_audit
from .input_catalog import InputCatalog, load_input_catalog

FULL_START: Final = date(2020, 1, 1)
FULL_END_EXCLUSIVE: Final = date(2026, 7, 4)
Progress = Callable[[dict[str, Any]], None]


def _read(path: Path) -> dict[str, Any]:
    value = read_canonical_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"producer JSON root must be an object: {path}")
    return value


def _atomic_latest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _tree_hash(root: Path) -> str:
    entries = [
        {
            "relative_path": str(path.relative_to(root)),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and not path.name.startswith("._")
        and "scratch" not in path.relative_to(root).parts
    ]
    return canonical_content_hash(entries)


class TaskContext:
    """Validated outer-chain context visible to one production engine adapter."""

    def __init__(self) -> None:
        self.task_id = os.environ["ERA_S2P18_TASK_ID"]
        if self.task_id not in TASK_ORDER:
            raise ValueError("unknown Plan v1.8 Task identity")
        self.run_root = Path(os.environ["ERA_S2P18_RUN_ROOT"])
        self.task_root = Path(os.environ["ERA_S2P18_TASK_ROOT"])
        self.authority_path = Path(os.environ["ERA_S2P18_AUTHORITY_PATH"])
        self.policy_path = Path(os.environ["ERA_S2P18_POLICY_PATH"])
        self.adapter_plan_path = Path(os.environ["ERA_S2P18_ADAPTER_PLAN_PATH"])
        self.repository_root = Path(os.environ["ERA_S2P18_REPOSITORY_ROOT"])
        self.authority_hash = os.environ["ERA_S2P18_AUTHORITY_HASH"]
        self.adapter_plan_hash = os.environ["ERA_S2P18_ADAPTER_PLAN_HASH"]
        self.code_commit = os.environ["ERA_S2P18_CODE_COMMIT"]
        self.attempt = int(os.environ["ERA_S2P18_PRODUCER_ATTEMPT"])
        self.upstream_hashes = cast(
            dict[str, str],
            json.loads(os.environ["ERA_S2P18_UPSTREAM_RECEIPT_HASHES"]),
        )
        authority = _read(self.authority_path)
        if (
            authority.get("authority_hash") != self.authority_hash
            or authority.get("code_commit") != self.code_commit
            or authority.get("adapter_plan_hash") != self.adapter_plan_hash
        ):
            raise ValueError("producer outer Authority binding drift")
        self.policy = _read(self.policy_path)
        self.authority = authority
        self.input_catalog = load_input_catalog(
            Path(str(authority["input_catalog_path"]))
        )
        if authority.get("input_catalog_hash") != self.input_catalog.catalog_hash:
            raise ValueError("producer input Catalog binding drift")
        self.attempt_root = self.task_root / "attempts" / f"attempt-{self.attempt:04d}"
        self.data_root = self.attempt_root / "data"
        self.checkpoints = self.attempt_root / "checkpoints"

    def upstream_root(self, task_id: str) -> Path:
        if task_id not in self.upstream_hashes:
            raise ValueError(f"producer missing upstream binding: {task_id}")
        root = self.run_root / "staging" / task_id
        receipt = _read(self.run_root / "receipts" / f"{task_id}.json")
        if receipt.get("task_receipt_hash") != self.upstream_hashes[task_id]:
            raise ValueError(f"producer upstream receipt drift: {task_id}")
        return root

    def upstream_output(self, task_id: str) -> dict[str, Any]:
        receipt = _read(self.run_root / "receipts" / f"{task_id}.json")
        outputs = cast(list[dict[str, Any]], receipt["output_files"])
        candidates = [
            self.upstream_root(task_id) / str(item["relative_path"])
            for item in outputs
            if str(item["relative_path"]).endswith("/output.json")
        ]
        if len(candidates) != 1:
            raise ValueError(f"producer expected one upstream output: {task_id}")
        return _read(candidates[0])

    def progress(self, payload: dict[str, Any]) -> None:
        ordinal = len(tuple(self.checkpoints.glob("*.json"))) + 1
        body: dict[str, Any] = {
            "schema_name": "s2p18-producer-checkpoint-v1",
            "schema_version": "1.0",
            "task_id": self.task_id,
            "attempt": self.attempt,
            "ordinal": ordinal,
            "authority_hash": self.authority_hash,
            "adapter_plan_hash": self.adapter_plan_hash,
            "code_commit": self.code_commit,
            **payload,
        }
        body["checkpoint_hash"] = canonical_content_hash(body)
        write_canonical_json_exclusive(
            self.checkpoints / f"{ordinal:06d}.json", body
        )
        _atomic_latest(self.task_root / "checkpoint-latest.json", body)


def _bundle(ctx: TaskContext, payload: dict[str, Any]) -> Path:
    """Seal one task-local Catalog, Manifest and Verify before outer receipt."""

    from era100x.research.stage_2.rerun.strict_json import strict_json_value

    payload = {
        **payload,
        "task_id": ctx.task_id,
        "stage_plan_version": "1.8",
        "engine_reuse_role": "MATHEMATICAL_ENGINE_ONLY",
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    normalized = strict_json_value(payload)
    if not isinstance(normalized, dict):
        raise TypeError("successor producer payload must normalize to an object")
    payload = cast(dict[str, Any], normalized)
    output = ctx.attempt_root / "output.json"
    write_canonical_json_exclusive(output, payload)
    files = [
        path
        for path in sorted(ctx.attempt_root.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and not path.name.startswith("._")
        and path.name
        not in {"catalog.json", "manifest.json", "task-verify.json"}
        and "scratch" not in path.relative_to(ctx.attempt_root).parts
    ]
    catalog: dict[str, object] = {
        "schema_name": "s2p18-task-catalog-v1",
        "schema_version": "1.0",
        "task_id": ctx.task_id,
        "files": [
            {
                "relative_path": str(path.relative_to(ctx.attempt_root)),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                **(
                    {"row_count": pq.ParquetFile(path).metadata.num_rows}
                    if path.suffix == ".parquet"
                    else {}
                ),
            }
            for path in files
        ],
    }
    catalog["catalog_hash"] = canonical_content_hash(catalog)
    catalog_path = ctx.attempt_root / "catalog.json"
    write_canonical_json_exclusive(catalog_path, catalog)
    manifest: dict[str, object] = {
        "schema_name": "s2p18-task-manifest-v1",
        "schema_version": "1.0",
        "task_id": ctx.task_id,
        "run_id": ctx.run_root.name,
        "authority_hash": ctx.authority_hash,
        "adapter_plan_hash": ctx.adapter_plan_hash,
        "code_commit": ctx.code_commit,
        "input_catalog_hash": ctx.input_catalog.catalog_hash,
        "upstream_receipt_hashes": dict(sorted(ctx.upstream_hashes.items())),
        "catalog_hash": catalog["catalog_hash"],
        "output_hash": canonical_content_hash(payload),
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    manifest["manifest_hash"] = canonical_content_hash(manifest)
    manifest_path = ctx.attempt_root / "manifest.json"
    write_canonical_json_exclusive(manifest_path, manifest)
    verify: dict[str, object] = {
        "schema_name": "s2p18-task-verify-v1",
        "schema_version": "1.0",
        "task_id": ctx.task_id,
        "run_id": ctx.run_root.name,
        "authority_hash": ctx.authority_hash,
        "catalog_hash": catalog["catalog_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "tree_hash": _tree_hash(ctx.attempt_root),
        "status": "PASS",
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    verify["verify_hash"] = canonical_content_hash(verify)
    verify_path = ctx.attempt_root / "task-verify.json"
    write_canonical_json_exclusive(verify_path, verify)
    complete_files = [
        path
        for path in sorted(ctx.attempt_root.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and "scratch" not in path.relative_to(ctx.attempt_root).parts
    ]
    return producer_receipt(
        task_id=ctx.task_id,
        run_root=ctx.run_root,
        output_files=complete_files,
        row_count=int(payload.get("row_count", 0)),
        result_status="PASS",
        authority_hash=ctx.authority_hash,
        adapter_plan_hash=ctx.adapter_plan_hash,
        code_commit=ctx.code_commit,
        upstream_receipt_hashes=ctx.upstream_hashes,
    )


def validate_full_period_contract_price_catalog(
    input_catalog: InputCatalog,
) -> tuple[Path, str]:
    """Verify the complete source audit and every bound OHLC partition."""

    binding = input_catalog.bindings["contract_price_catalog_hash"]
    catalog = _read(binding.path)
    audit_path = Path(str(catalog.get("source_audit_path", "")))
    audit_hash = str(catalog.get("source_audit_hash", ""))
    partitions = catalog.get("partitions")
    if (
        catalog.get("schema_name") != "s2p18-contract-price-source-catalog-v1"
        or catalog.get("scope_start_date") != FULL_START.isoformat()
        or catalog.get("scope_end_date_exclusive") != FULL_END_EXCLUSIVE.isoformat()
        or catalog.get("catalog_hash") != binding.binding_hash
        or canonical_content_hash(
            {key: value for key, value in catalog.items() if key != "catalog_hash"}
        )
        != binding.binding_hash
        or not audit_path.is_absolute()
        or not audit_path.is_file()
        or audit_path.is_symlink()
        or catalog.get("source_audit_sha256") != sha256_file(audit_path)
        or len(audit_hash) != 64
        or not isinstance(partitions, list)
        or catalog.get("partition_count") != len(partitions)
    ):
        raise ValueError("T11 requires the full-period Contract Price source Catalog")
    audit = load_source_audit(audit_path, expected_hash=audit_hash)
    if (
        audit.scope_start_date != FULL_START.isoformat()
        or audit.scope_end_date_exclusive != FULL_END_EXCLUSIVE.isoformat()
    ):
        raise ValueError("T11 full-period Contract Price source audit drift")
    for item in partitions:
        if not isinstance(item, dict):
            raise ValueError("T11 Contract Price partition Catalog entry drift")
        path = Path(str(item.get("path", "")))
        if (
            not path.is_absolute()
            or not path.is_file()
            or path.is_symlink()
            or item.get("sha256") != sha256_file(path)
            or item.get("size_bytes") != path.stat().st_size
        ):
            raise ValueError("T11 Contract Price partition Hash drift")
    return audit_path, audit_hash


def _task_t11(ctx: TaskContext) -> dict[str, Any]:
    from era100x.research.stage_2.rerun.seven_day_rehearsal import (
        produce_scoped_lifecycle_v18,
    )

    source_audit_path, source_audit_hash = (
        validate_full_period_contract_price_catalog(ctx.input_catalog)
    )
    ctx.progress(
        {
            "status": "IN_PROGRESS",
            "phase": "LIFECYCLE",
            "processed_units": 0,
            "total_units": 1,
            "verify_state": "PENDING",
        }
    )
    return produce_scoped_lifecycle_v18(
        start_date=FULL_START,
        end_date_exclusive=FULL_END_EXCLUSIVE,
        source_audit_path=source_audit_path,
        source_audit_hash=source_audit_hash,
        progress_callback=ctx.progress,
    )


def _task_t12(ctx: TaskContext) -> dict[str, Any]:
    from era100x.research.stage_2.rerun.scoped_producers import produce_scoped_paths

    payload = produce_scoped_paths(
        output_root=ctx.data_root,
        start_date=FULL_START,
        end_date_exclusive=FULL_END_EXCLUSIVE,
        progress_callback=ctx.progress,
    )
    payload.update(
        {
            "h2_estimand": "CANONICAL_TRADES_UNCHANGED",
            "lifecycle_ohlc_consumed_as_h2_label": False,
            "source_t11_receipt_hash": ctx.upstream_hashes["S2P18-T11"],
        }
    )
    return payload


def _task_t13_or_t14(ctx: TaskContext) -> dict[str, Any]:
    from era100x.research.stage_2.rerun.scoped_producers import (
        produce_scoped_first_passage,
        produce_scoped_metrics,
    )

    source = ctx.upstream_output("S2P18-T12")
    source_root = Path(str(source["artifact_data_root"]))
    attempt_root = Path(str(source["artifact_attempt_root"]))
    manifest = _read(attempt_root / "manifest.json")
    catalog = _read(attempt_root / "catalog.json")
    payload = (
        produce_scoped_metrics(
            output_root=ctx.data_root,
            source_paths_root=source_root,
            source_snapshot_id=str(manifest["manifest_hash"]),
            source_manifest_hash=str(manifest["manifest_hash"]),
            source_catalog_hash=str(catalog["catalog_hash"]),
            progress_callback=ctx.progress,
        )
        if ctx.task_id == "S2P18-T13"
        else produce_scoped_first_passage(
            output_root=ctx.data_root,
            source_paths_root=source_root,
            source_snapshot_id=str(manifest["manifest_hash"]),
            source_manifest_hash=str(manifest["manifest_hash"]),
            source_catalog_hash=str(catalog["catalog_hash"]),
            progress_callback=ctx.progress,
        )
    )
    payload.update(
        {
            "h2_estimand": "CANONICAL_TRADES_UNCHANGED",
            "lifecycle_tracks_joined_for_reporting_only": True,
        }
    )
    return payload


def _task_t15(ctx: TaskContext) -> dict[str, Any]:
    from era100x.research.stage_2.rerun.scoped_producers import produce_scoped_ambiguity

    source = ctx.upstream_output("S2P18-T14")
    source_root = Path(str(source["artifact_data_root"]))
    payload = produce_scoped_ambiguity(
        output_root=ctx.data_root,
        source_first_passage_root=source_root,
        progress_callback=ctx.progress,
    )
    payload["source_first_passage_root"] = str(source_root)
    payload["h2_estimand"] = "CANONICAL_TRADES_UNCHANGED"
    return payload


def _unique(root: Path, pattern: str) -> Path:
    matches = tuple(
        path
        for path in root.rglob(pattern)
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )
    if len(matches) != 1:
        raise ValueError(f"expected one {pattern}, found {len(matches)}")
    return matches[0]


def _task_t16(ctx: TaskContext) -> dict[str, Any]:
    """Run the unchanged T16 mathematical engine under the outer v1.8 Authority."""

    from era100x.research.stage_2.baselines.conditional.binning_run import (
        freeze_binning_snapshots,
    )
    from era100x.research.stage_2.baselines.conditional.execution_run import (
        run_full_execution,
        verify_published_run,
    )
    from era100x.research.stage_2.baselines.conditional.full_run import (
        T10_SNAPSHOT,
        T10_SNAPSHOT_ID,
    )
    from era100x.research.stage_2.baselines.conditional.v14_contracts import (
        S2P13T16ContractAuthority,
    )
    from era100x.research.stage_2.rerun.orchestrator import repository_clean
    from era100x.research.stage_2.rerun.seven_day_rehearsal import LABEL_CONTRACT_HASH

    t15 = ctx.upstream_output("S2P18-T15")
    first_passage_root = Path(str(t15["source_first_passage_root"]))
    authority = S2P13T16ContractAuthority.seal(
        {
            "code_commit": ctx.code_commit,
            "chain_authority_hash": ctx.authority_hash,
            "policy_hash": str(ctx.authority["policy_hash"]),
            "source_t10_binding_hash": T10_SNAPSHOT_ID,
            "source_s2p13_t11_binding_hash": ctx.upstream_hashes["S2P18-T11"],
            "source_s2p13_t13_binding_hash": ctx.upstream_hashes["S2P18-T13"],
            "source_s2p13_t15_binding_hash": ctx.upstream_hashes["S2P18-T15"],
            "context_binding_hash": sha256_file(
                ctx.repository_root / "src/era100x/research/stage_2/gates/price/gate.py"
            ),
            "label_contract_hash": LABEL_CONTRACT_HASH,
            "preregistration_hash": str(
                _read(
                    ctx.repository_root / str(ctx.policy["preregistration_path"])
                )["preregistration_hash"]
            ),
        }
    )
    authority_path = ctx.data_root / f"engine-authority-{authority.authority_hash}.json"
    write_canonical_json_exclusive(
        authority_path, authority.model_dump(mode="json")
    )
    bins, bins_path = freeze_binning_snapshots(
        authority_path=authority_path,
        bin_root=ctx.data_root / "train-bins",
        t10_snapshot=T10_SNAPSHOT,
        t10_snapshot_id=T10_SNAPSHOT_ID,
        current_commit=ctx.code_commit,
        repository_clean=repository_clean(ctx.repository_root),
        lightweight_policy_authorized=True,
        progress_callback=ctx.progress,
    )
    runs_root = ctx.data_root / "runs"
    runs_root.mkdir()
    manifest, published = run_full_execution(
        authority_path=authority_path,
        binning_set_path=bins_path,
        runs_root=runs_root,
        t10_snapshot=T10_SNAPSHOT,
        t10_snapshot_id=T10_SNAPSHOT_ID,
        t13_snapshot=first_passage_root,
        current_commit=ctx.code_commit,
        repository_clean=repository_clean(ctx.repository_root),
        lightweight_policy_authorized=True,
        progress_callback=ctx.progress,
    )
    verify, _ = verify_published_run(run_root=published.parents[2])
    if verify.get("status") != "PASS":
        raise ValueError("successor T16 engine Verify did not PASS")
    return {
        "authority_hash": authority.authority_hash,
        "binning_set_hash": bins["binning_set_hash"],
        "binning_root": str(bins_path.parent),
        "published_snapshot": str(published),
        "manifest_hash": manifest["manifest_hash"],
        "verify_hash": verify["verify_hash"],
        "row_count": int(verify["source_h2_path_count"]),
        "h2_estimand": "CANONICAL_TRADES_UNCHANGED",
        "semantic_equivalence_required": True,
        "historical_evidence_only": True,
        "research_result": "DESCRIPTIVE_ONLY_PRIMARY_PENDING_T18",
    }


def _t16_binding(ctx: TaskContext) -> Any:
    from era100x.research.stage_2.baselines.placebo.governance import T16Binding

    output = ctx.upstream_output("S2P18-T16")
    snapshot = Path(str(output["published_snapshot"]))
    verify_path = _unique(snapshot.parents[2] / "verify", "*.json")
    verify = _read(verify_path)
    match_path = snapshot / "results/conditional_match_matrices.parquet"
    outcome_path = snapshot / "results/control_outcome_matrices.parquet"
    summary_path = snapshot / "results/descriptive_summaries.parquet"
    selections = snapshot / "selections"
    counts = {
        "eligible": pq.ParquetFile(match_path).metadata.num_rows,
        "matched": int(verify["matched_episode_count"]),
        "unmatched": int(verify["unmatched_episode_count"]),
        "controls": pq.ParquetFile(outcome_path).metadata.num_rows,
        "summaries": pq.ParquetFile(summary_path).metadata.num_rows,
        "groups": len(tuple(selections.rglob("*.parquet"))),
    }
    attempt_root = Path(str(output["artifact_attempt_root"]))
    manifest = _read(attempt_root / "manifest.json")
    catalog = _read(attempt_root / "catalog.json")
    return T16Binding(
        receipt_path=ctx.run_root / "receipts/S2P18-T16.json",
        receipt_hash=ctx.upstream_hashes["S2P18-T16"],
        artifact_manifest_hash=str(manifest["manifest_hash"]),
        artifact_catalog_hash=str(catalog["catalog_hash"]),
        authority_hash=str(output["authority_hash"]),
        binning_hash=str(output["binning_set_hash"]),
        snapshot_id=snapshot.name,
        verify_hash=str(output["verify_hash"]),
        snapshot_root=snapshot,
        binning_root=Path(str(output["binning_root"])),
        prepared_episodes_path=snapshot / "episodes/prepared-episodes.parquet",
        selections_root=selections,
        outcome_path=outcome_path,
        match_path=match_path,
        summary_path=summary_path,
        counts=counts,
    )


def _task_t17(ctx: TaskContext) -> dict[str, Any]:
    from era100x.research.stage_2.baselines.placebo.runner import (
        _promote_result_metadata,
        attach_outcomes_and_summarize,
        produce_blind_selections,
    )

    binding = _t16_binding(ctx)
    blind = ctx.data_root / "blind-selections"
    results = ctx.data_root / "results"
    produce_blind_selections(binding=binding, output_root=blind, progress=ctx.progress)
    scratch = ctx.attempt_root / "scratch"
    scratch.mkdir(parents=True)
    reconciliation = attach_outcomes_and_summarize(
        binding=binding,
        blind_root=blind,
        output_root=results / "matches",
        local_database_path=scratch / "outcomes.sqlite",
        progress=ctx.progress,
    )
    _promote_result_metadata(results)
    shutil.rmtree(scratch)
    return {
        "reconciliation_hash": reconciliation["reconciliation_hash"],
        "source_t16_verify_hash": binding.verify_hash,
        "match_root": str(results / "matches"),
        "summary_path": str(results / "descriptive_summaries.parquet"),
        "row_count": int(reconciliation["source_matched_slots"]),
        "research_status": "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING",
    }


def _t17_binding(ctx: TaskContext, t16: Any) -> Any:
    from era100x.research.stage_2.statistics.bootstrap.governance import T17Binding

    output = ctx.upstream_output("S2P18-T17")
    match_root = Path(str(output["match_root"]))
    match_files = tuple(sorted(match_root.rglob("*.parquet")))
    reconciliation = _read(match_root.parent / "reconciliation.json")
    attempt_root = Path(str(output["artifact_attempt_root"]))
    manifest = _read(attempt_root / "manifest.json")
    catalog = _read(attempt_root / "catalog.json")
    return T17Binding(
        run_root=attempt_root,
        snapshot_root=attempt_root,
        snapshot_id=str(manifest["manifest_hash"]),
        verify_hash=str(_read(attempt_root / "task-verify.json")["verify_hash"]),
        manifest_hash=str(manifest["manifest_hash"]),
        catalog_hash=str(catalog["catalog_hash"]),
        prepared_source_verify_hash=t16.verify_hash,
        match_root=match_root,
        match_files=match_files,
        summary_path=Path(str(output["summary_path"])),
        counts={
            "source_eligible": int(reconciliation["source_eligible"]),
            "source_matched_slots": int(reconciliation["source_matched_slots"]),
            "source_unmatched_not_sampled": int(
                reconciliation["source_unmatched_not_sampled"]
            ),
            "placebo_matched": int(reconciliation["placebo_matched"]),
            "placebo_unmatched": int(reconciliation["placebo_unmatched"]),
            "groups": len(match_files),
            "summaries": pq.ParquetFile(
                Path(str(output["summary_path"]))
            ).metadata.num_rows,
        },
    )


def _task_t18(ctx: TaskContext) -> dict[str, Any]:
    from era100x.research.stage_2.statistics.bootstrap.engine import (
        compute_all_summaries,
    )
    from era100x.research.stage_2.statistics.bootstrap.governance import SourceBindings
    from era100x.research.stage_2.statistics.bootstrap.contracts import (
        BootstrapSummary,
        ClusterSufficientStatistic,
        FdrFamilySummary,
    )
    from era100x.research.stage_2.statistics.bootstrap.runner import (
        CLUSTER_SCHEMA,
        FDR_SCHEMA,
        SUMMARY_SCHEMA,
        _cluster_rows,
        _fdr_rows,
        _summary_rows,
        _write_and_strict_read,
        aggregate_sources,
    )

    t16 = _t16_binding(ctx)
    t17 = _t17_binding(ctx, t16)
    sources = SourceBindings(t16=t16, t17=t17)
    statistics = aggregate_sources(sources, progress=ctx.progress)
    summaries, families = compute_all_summaries(statistics, iterations=5000)
    ctx.data_root.mkdir(parents=True, exist_ok=False)
    cluster_path = ctx.data_root / "cluster-statistics.parquet"
    summary_path = ctx.data_root / "bootstrap-summaries.parquet"
    fdr_path = ctx.data_root / "fdr-families.parquet"
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
    return {
        "cluster_path": str(cluster_path),
        "summary_path": str(summary_path),
        "fdr_path": str(fdr_path),
        "cluster_rows": len(statistics),
        "row_count": len(summaries),
        "fdr_family_rows": len(families),
        "bootstrap_iterations": 5000,
        "research_status": "STATISTICAL_EVIDENCE_ONLY_FINAL_GATE_PENDING",
    }


def _compat_lifecycle(
    source: Path,
    target: Path,
    *,
    track: str,
) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with source.open("rb") as handle, target.open("x", encoding="utf-8") as output:
        output.write('{"lifecycle":[')
        for row in ijson.items(handle, "lifecycle.item", use_float=False):
            if count:
                output.write(",")
            converted = {
                **cast(dict[str, Any], row),
                "funding_tracks": row[track],
            }
            output.write(
                json.dumps(
                    converted,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            count += 1
        output.write("]}\n")
    return count


def _evidence_sources(ctx: TaskContext) -> Any:
    from era100x.research.stage_2.acceptance.evidence_gate.governance import (
        SourceBindings,
        T11Binding,
        T18Binding,
    )
    from era100x.research.stage_2.statistics.bootstrap.governance import (
        SourceBindings as T18Upstreams,
    )

    t16 = _t16_binding(ctx)
    t17 = _t17_binding(ctx, t16)
    t18_output = ctx.upstream_output("S2P18-T18")
    t18_attempt = Path(str(t18_output["artifact_attempt_root"]))
    t18_manifest = _read(t18_attempt / "manifest.json")
    t18_catalog = _read(t18_attempt / "catalog.json")
    t11_output = ctx.upstream_output("S2P18-T11")
    t11_source = Path(str(t11_output["artifact_output_path"]))
    primary_compat = ctx.data_root / "compat/lifecycle-primary.json"
    episode_count = _compat_lifecycle(
        t11_source,
        primary_compat,
        track="contract_price_ohlc_primary",
    )
    return SourceBindings(
        t11=T11Binding(
            receipt_hash=ctx.upstream_hashes["S2P18-T11"],
            manifest_hash=str(
                _read(Path(str(t11_output["artifact_attempt_root"])) / "manifest.json")[
                    "manifest_hash"
                ]
            ),
            catalog_hash=str(
                _read(Path(str(t11_output["artifact_attempt_root"])) / "catalog.json")[
                    "catalog_hash"
                ]
            ),
            output_hash=sha256_file(primary_compat),
            output_path=primary_compat,
            row_count=episode_count,
        ),
        upstreams=T18Upstreams(t16=t16, t17=t17),
        t18=T18Binding(
            verify_hash=str(_read(t18_attempt / "task-verify.json")["verify_hash"]),
            manifest_hash=str(t18_manifest["manifest_hash"]),
            catalog_hash=str(t18_catalog["catalog_hash"]),
            summary_path=Path(str(t18_output["summary_path"])),
            cluster_path=Path(str(t18_output["cluster_path"])),
            summary_rows=int(t18_output["row_count"]),
        ),
    )


def _task_t19(ctx: TaskContext) -> dict[str, Any]:
    from era100x.research.stage_2.acceptance.evidence_gate.engine import project_lifecycle
    from era100x.research.stage_2.acceptance.evidence_gate.runner import _project_and_write

    sources = _evidence_sources(ctx)
    projection = _project_and_write(sources, ctx.data_root / "evidence", progress=ctx.progress)
    t11 = ctx.upstream_output("S2P18-T11")
    comparator = ctx.data_root / "compat/lifecycle-comparator.json"
    count = _compat_lifecycle(
        Path(str(t11["artifact_output_path"])),
        comparator,
        track="pure_trades_comparator",
    )
    _, _, comparator_cards = project_lifecycle(
        comparator,
        source_hash=sha256_file(comparator),
        expected_episode_count=count,
    )
    cards_path = ctx.data_root / "evidence/evidence-cards.json"
    cards = _read(cards_path)
    primary_cards = cast(dict[str, Any], cards["lifecycle"])
    comparison: dict[str, object] = {
        "schema_name": "s2p18-lifecycle-track-comparison-v1",
        "schema_version": "1.0",
        "pure_trades_comparator": comparator_cards,
        "contract_price_ohlc_primary": primary_cards,
        "h2_primary_affected": False,
        "historical_execution_claim": False,
    }
    comparison["comparison_hash"] = canonical_content_hash(comparison)
    comparison_path = ctx.data_root / "evidence/lifecycle-track-comparison.json"
    write_canonical_json_exclusive(comparison_path, comparison)
    cards["lifecycle_tracks"] = comparison
    cards["historical_h2_primary"] = "PRIMARY_FAILED"
    cards["successor_h2_primary"] = cards["btc_primary"]
    cards["stage3_locked"] = True
    cards_path.unlink()
    write_canonical_json_exclusive(cards_path, cards)
    return {
        **projection,
        "evidence_root": str(ctx.data_root / "evidence"),
        "lifecycle_comparison_hash": comparison["comparison_hash"],
        "historical_h2_primary": "PRIMARY_FAILED",
        "successor_h2_primary": cards["btc_primary"],
        "row_count": int(projection["gate_rows"]),
        "stage3_locked": True,
    }


def _performance_evidence(ctx: TaskContext) -> dict[str, Any]:
    path = (
        ctx.repository_root
        / "configs/research/stage_2/s2p18_t11_t16_performance_v1.json"
    )
    payload = _read(path)
    claimed = payload.get("performance_hash")
    benchmarks = payload.get("benchmarks")
    if (
        payload.get("status") != "PASS"
        or payload.get("formal_run_executed") is not False
        or not isinstance(claimed, str)
        or claimed
        != canonical_content_hash(
            {key: value for key, value in payload.items() if key != "performance_hash"}
        )
        or not isinstance(benchmarks, list)
        or {item.get("task_id") for item in benchmarks if isinstance(item, dict)}
        != {"S2P18-T11", "S2P18-T16"}
        or any(
            not isinstance(item, dict)
            or item.get("semantic_equality") is not True
            or float(str(item.get("speedup", "0"))) < 2
            for item in benchmarks
        )
        or int(payload.get("observed_max_rss_bytes", 0))
        > int(payload.get("max_rss_bytes_gate", 0))
    ):
        raise ValueError("Plan v1.8 performance evidence drift")
    return payload


def _task_t20(ctx: TaskContext) -> dict[str, Any]:
    """Build the successor acceptance package without freezing a research PASS."""

    t19 = ctx.upstream_output("S2P18-T19")
    source = Path(str(t19["evidence_root"]))
    destination = ctx.data_root / "final"
    shutil.copytree(source, destination)
    cards = _read(destination / "evidence-cards.json")
    comparison = _read(destination / "lifecycle-track-comparison.json")
    performance = _performance_evidence(ctx)
    successor_h2 = str(cards["btc_primary"])
    research_decision = (
        "STAGE2_NO_GO_CURRENT_EVIDENCE"
        if successor_h2 == "PRIMARY_FAILED"
        else "STAGE2_REVIEW_REQUIRED_NO_STAGE3_AUTHORITY"
    )
    t11_speedup = min(
        float(str(item["speedup"]))
        for item in performance["benchmarks"]
        if item["task_id"] == "S2P18-T11"
    )
    t16_speedup = min(
        float(str(item["speedup"]))
        for item in performance["benchmarks"]
        if item["task_id"] == "S2P18-T16"
    )
    decision: dict[str, object] = {
        "schema_name": "s2p18-t20-final-decision-v1",
        "schema_version": "1.0",
        "engineering_status": "PASS",
        "historical_h2_primary": "PRIMARY_FAILED",
        "successor_h2_primary": successor_h2,
        "eth_classification": cards["eth_classification"],
        "lifecycle_tracks": comparison,
        "t11_t16_performance": performance,
        "research_decision": research_decision,
        "h2_result_overwritten": False,
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    decision["decision_hash"] = canonical_content_hash(decision)
    write_canonical_json_exclusive(
        destination / "stage2-successor-final-decision.json", decision
    )
    report = [
        "# S2P18-T20 Successor Final Acceptance",
        "",
        "- Engineering evidence chain: `PASS`",
        "- Historical H2 Primary: `PRIMARY_FAILED`",
        f"- Successor H2 Primary: `{successor_h2}`",
        f"- Research decision: `{research_decision}`",
        f"- T11 minimum speedup: `{t11_speedup:.6f}×`",
        f"- T16 minimum speedup: `{t16_speedup:.6f}×`",
        f"- Observed peak RSS: `{performance['observed_max_rss_bytes']}` bytes",
        "- Stage 3: `LOCKED`",
        "",
        "Lifecycle repair is reported separately from H2 and cannot overwrite "
        "the historical result.",
    ]
    (destination / "stage2-successor-final-report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    return {
        "final_root": str(destination),
        "decision_hash": decision["decision_hash"],
        "historical_h2_primary": "PRIMARY_FAILED",
        "successor_h2_primary": successor_h2,
        "research_decision": research_decision,
        "row_count": int(t19["row_count"]),
        "stage3_locked": True,
    }


HANDLERS: Final[dict[str, Callable[[TaskContext], dict[str, Any]]]] = {
    "S2P18-T11": _task_t11,
    "S2P18-T12": _task_t12,
    "S2P18-T13": _task_t13_or_t14,
    "S2P18-T14": _task_t13_or_t14,
    "S2P18-T15": _task_t15,
    "S2P18-T16": _task_t16,
    "S2P18-T17": _task_t17,
    "S2P18-T18": _task_t18,
    "S2P18-T19": _task_t19,
    "S2P18-T20": _task_t20,
}


def run_from_environment() -> Path:
    """Execute one real successor Task and seal its task-local evidence."""

    ctx = TaskContext()
    existing = ctx.run_root / "receipts" / f"{ctx.task_id}.json"
    if existing.is_file():
        return existing
    ctx.attempt_root.mkdir(parents=True, exist_ok=False)
    ctx.progress(
        {
            "status": "IN_PROGRESS",
            "phase": "START",
            "processed_units": 0,
            "total_units": 1,
            "verify_state": "PENDING",
        }
    )
    payload = HANDLERS[ctx.task_id](ctx)
    payload.update(
        {
            "artifact_attempt_root": str(ctx.attempt_root),
            "artifact_data_root": str(ctx.data_root),
            "artifact_output_path": str(ctx.attempt_root / "output.json"),
        }
    )
    bundle_path = _bundle(ctx, payload)
    return bundle_path


def production_adapter_plan_payload(
    *,
    repository_root: Path,
    python_executable: str = sys.executable,
) -> dict[str, object]:
    """Build the commit-local ten-Task adapter plan; caller writes it append-only."""

    script = repository_root / "scripts/run_stage2_v18_task.py"
    module = repository_root / "src/era100x/research/stage_2/lifecycle/production.py"
    formal = repository_root / "src/era100x/research/stage_2/lifecycle/formal_chain.py"
    inputs = repository_root / "src/era100x/research/stage_2/lifecycle/input_catalog.py"
    executables = (script, module, formal, inputs)
    hashes = [sha256_file(path) for path in executables]
    payload: dict[str, object] = {
        "schema_name": "s2p18-task-adapter-plan-v1",
        "schema_version": "1.0",
        "stage_plan_version": "1.8",
        "task_order": list(TASK_ORDER),
        "adapters": [
            {
                "task_id": task_id,
                "argv": [python_executable, str(script), task_id],
                "executable_paths": [
                    str(path.relative_to(repository_root)) for path in executables
                ],
                "executable_hashes": hashes,
                "timeout_seconds": 7 * 24 * 60 * 60,
            }
            for task_id in TASK_ORDER
        ],
    }
    payload["adapter_plan_hash"] = canonical_content_hash(payload)
    return payload
