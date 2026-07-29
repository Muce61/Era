"""Fixed Plan v1.9 handler registry over the unchanged Stage 2 engines."""

from __future__ import annotations

import json
import shutil
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

from .source_audit import LifecycleSourceAudit
from .solo_runtime import TaskExecutionContext

FULL_START: Final = date(2020, 1, 1)
FULL_END_EXCLUSIVE: Final = date(2026, 7, 4)
Progress = Callable[[dict[str, Any]], None]
TaskContext = TaskExecutionContext


def _read(path: Path) -> dict[str, Any]:
    value = read_canonical_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"producer JSON root must be an object: {path}")
    return value


def validate_full_period_contract_price_inputs(
    ctx: TaskContext,
) -> LifecycleSourceAudit:
    """Verify the complete source audit and every bound OHLC partition."""

    audit = LifecycleSourceAudit.model_validate(ctx.inputs_lock.source_audit)
    if (
        audit.status != "PASS"
        or audit.scope_start_date != FULL_START.isoformat()
        or audit.scope_end_date_exclusive != FULL_END_EXCLUSIVE.isoformat()
    ):
        raise ValueError("T11 full-period Contract Price source audit drift")
    for item in ctx.inputs_lock.partitions:
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
    return audit


def _task_t11(ctx: TaskContext) -> dict[str, Any]:
    from era100x.research.stage_2.rerun.seven_day_rehearsal import (
        produce_scoped_lifecycle_v18,
    )

    source_audit = validate_full_period_contract_price_inputs(ctx)
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
        source_audit=source_audit,
        source_audit_hash=source_audit.audit_hash,
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
            "source_t11_output_tree_hash": ctx.upstream_hashes["S2P19-T11"],
        }
    )
    return payload


def _task_t13_or_t14(ctx: TaskContext) -> dict[str, Any]:
    from era100x.research.stage_2.rerun.scoped_producers import (
        produce_scoped_first_passage,
        produce_scoped_metrics,
    )

    source = ctx.upstream_output("S2P19-T12")
    source_root = ctx.resolve_run_path(source["artifact_data_root"])
    attempt_root = ctx.resolve_run_path(source["artifact_attempt_root"])
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
        if ctx.task_id == "S2P19-T13"
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

    source = ctx.upstream_output("S2P19-T14")
    source_root = ctx.resolve_run_path(source["artifact_data_root"])
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
    """Run the unchanged T16 mathematical engine under the v1.9 Authority."""

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

    t15 = ctx.upstream_output("S2P19-T15")
    first_passage_root = ctx.resolve_run_path(t15["source_first_passage_root"])
    authority = S2P13T16ContractAuthority.seal(
        {
            "code_commit": ctx.code_commit,
            "chain_authority_hash": ctx.authority_hash,
            "policy_hash": str(ctx.authority["policy_hash"]),
            "source_t10_binding_hash": T10_SNAPSHOT_ID,
            "source_s2p13_t11_binding_hash": ctx.upstream_hashes["S2P19-T11"],
            "source_s2p13_t13_binding_hash": ctx.upstream_hashes["S2P19-T13"],
            "source_s2p13_t15_binding_hash": ctx.upstream_hashes["S2P19-T15"],
            "context_binding_hash": sha256_file(
                ctx.repository_root / "src/era100x/research/stage_2/gates/price/gate.py"
            ),
            "label_contract_hash": LABEL_CONTRACT_HASH,
            "preregistration_hash": str(
                _read(ctx.repository_root / str(ctx.authority["preregistration_path"]))[
                    "preregistration_hash"
                ]
            ),
        }
    )
    authority_path = ctx.data_root / f"engine-authority-{authority.authority_hash}.json"
    write_canonical_json_exclusive(authority_path, authority.model_dump(mode="json"))
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

    output = ctx.upstream_output("S2P19-T16")
    snapshot = ctx.resolve_run_path(output["published_snapshot"])
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
    output_root = ctx.upstream_root("S2P19-T16")
    output_hash = ctx.upstream_hashes["S2P19-T16"]
    return T16Binding(
        receipt_path=output_root / "output.json",
        receipt_hash=output_hash,
        artifact_manifest_hash=output_hash,
        artifact_catalog_hash=output_hash,
        authority_hash=str(output["authority_hash"]),
        binning_hash=str(output["binning_set_hash"]),
        snapshot_id=snapshot.name,
        verify_hash=str(output["verify_hash"]),
        snapshot_root=snapshot,
        binning_root=ctx.resolve_run_path(output["binning_root"]),
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

    output = ctx.upstream_output("S2P19-T17")
    match_root = ctx.resolve_run_path(output["match_root"])
    match_files = tuple(sorted(match_root.rglob("*.parquet")))
    reconciliation = _read(match_root.parent / "reconciliation.json")
    attempt_root = ctx.upstream_root("S2P19-T17")
    output_hash = ctx.upstream_hashes["S2P19-T17"]
    return T17Binding(
        run_root=attempt_root,
        snapshot_root=attempt_root,
        snapshot_id=output_hash,
        verify_hash=output_hash,
        manifest_hash=output_hash,
        catalog_hash=output_hash,
        prepared_source_verify_hash=t16.verify_hash,
        match_root=match_root,
        match_files=match_files,
        summary_path=ctx.resolve_run_path(output["summary_path"]),
        counts={
            "source_eligible": int(reconciliation["source_eligible"]),
            "source_matched_slots": int(reconciliation["source_matched_slots"]),
            "source_unmatched_not_sampled": int(reconciliation["source_unmatched_not_sampled"]),
            "placebo_matched": int(reconciliation["placebo_matched"]),
            "placebo_unmatched": int(reconciliation["placebo_unmatched"]),
            "groups": len(match_files),
            "summaries": pq.ParquetFile(
                ctx.resolve_run_path(output["summary_path"])
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
    t18_output = ctx.upstream_output("S2P19-T18")
    t18_hash = ctx.upstream_hashes["S2P19-T18"]
    t11_output = ctx.upstream_output("S2P19-T11")
    t11_source = ctx.resolve_run_path(t11_output["artifact_output_path"])
    primary_compat = ctx.data_root / "compat/lifecycle-primary.json"
    episode_count = _compat_lifecycle(
        t11_source,
        primary_compat,
        track="contract_price_ohlc_primary",
    )
    return SourceBindings(
        t11=T11Binding(
            receipt_hash=ctx.upstream_hashes["S2P19-T11"],
            manifest_hash=ctx.upstream_hashes["S2P19-T11"],
            catalog_hash=ctx.upstream_hashes["S2P19-T11"],
            output_hash=sha256_file(primary_compat),
            output_path=primary_compat,
            row_count=episode_count,
        ),
        upstreams=T18Upstreams(t16=t16, t17=t17),
        t18=T18Binding(
            verify_hash=t18_hash,
            manifest_hash=t18_hash,
            catalog_hash=t18_hash,
            summary_path=ctx.resolve_run_path(t18_output["summary_path"]),
            cluster_path=ctx.resolve_run_path(t18_output["cluster_path"]),
            summary_rows=int(t18_output["row_count"]),
        ),
    )


def _task_t19(ctx: TaskContext) -> dict[str, Any]:
    from era100x.research.stage_2.acceptance.evidence_gate.engine import project_lifecycle
    from era100x.research.stage_2.acceptance.evidence_gate.runner import _project_and_write

    sources = _evidence_sources(ctx)
    projection = _project_and_write(sources, ctx.data_root / "evidence", progress=ctx.progress)
    t11 = ctx.upstream_output("S2P19-T11")
    comparator = ctx.data_root / "compat/lifecycle-comparator.json"
    count = _compat_lifecycle(
        ctx.resolve_run_path(t11["artifact_output_path"]),
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
        "schema_name": "s2p19-lifecycle-track-comparison-v1",
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
    path = ctx.repository_root / "configs/research/stage_2/s2p18_t11_t16_performance_v1.json"
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
        or int(payload.get("observed_max_rss_bytes", 0)) > int(payload.get("max_rss_bytes_gate", 0))
    ):
        raise ValueError("Plan v1.8 performance evidence drift")
    return payload


def _task_t20(ctx: TaskContext) -> dict[str, Any]:
    """Build the successor acceptance package without freezing a research PASS."""

    t19 = ctx.upstream_output("S2P19-T19")
    source = ctx.resolve_run_path(t19["evidence_root"])
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
        "schema_name": "s2p19-t20-final-decision-v1",
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
    write_canonical_json_exclusive(destination / "stage2-successor-final-decision.json", decision)
    report = [
        "# S2P19-T20 Successor Final Acceptance",
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
    "S2P19-T11": _task_t11,
    "S2P19-T12": _task_t12,
    "S2P19-T13": _task_t13_or_t14,
    "S2P19-T14": _task_t13_or_t14,
    "S2P19-T15": _task_t15,
    "S2P19-T16": _task_t16,
    "S2P19-T17": _task_t17,
    "S2P19-T18": _task_t18,
    "S2P19-T19": _task_t19,
    "S2P19-T20": _task_t20,
}
