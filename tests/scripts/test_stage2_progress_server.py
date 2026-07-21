from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).parents[2] / "scripts/run_stage2_progress_server.py"
SPEC = importlib.util.spec_from_file_location("stage2_progress_server", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_execution_observability = MODULE._execution_observability
_acceptance_projection = MODULE._acceptance_projection
_stage2_task_projection = MODULE._stage2_task_projection
_stage2_path_metrics_projection = MODULE._stage2_path_metrics_projection
_stage2_first_passage_projection = MODULE._stage2_first_passage_projection
_json_hash = MODULE._json_hash

T12_RUN_ID = "stage2-s2t12-metrics-20260721T040435Z-abcdef123456"
T13_RUN_ID = "stage2-s2t13-first-passage-20260721T104500Z-abcdef123456"


def _write(path: Path, content: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _sealed(payload: dict, field: str) -> dict:
    result = dict(payload)
    result[field] = _json_hash(payload)
    return result


def _t12_authority() -> dict:
    return _sealed(
        {
            "task_id": "S2-T12",
            "task_version": "1.3",
            "code_commit": "abcdef0",
            "historical_evidence_only": True,
        },
        "authority_hash",
    )


def _write_t12_active(root: Path, run_id: str = T12_RUN_ID) -> tuple[Path, dict]:
    run_root = root / "runs" / run_id
    authority = _t12_authority()
    _write(run_root / "manifests/preflight-authority.json", json.dumps(authority))
    execution = _sealed(
        {
            **authority,
            "run_id": run_id,
            "started_at_utc": "2026-07-21T04:04:35Z",
        },
        "execution_manifest_hash",
    )
    _write(
        run_root / "manifests" / f"execution-{execution['execution_manifest_hash']}.json",
        json.dumps(execution),
    )
    _write(
        root / "authorities/S2-T12" / f"{authority['authority_hash']}.json",
        json.dumps(authority),
    )
    return run_root, authority


def _instrument_catalog(instrument: str, episodes: int, payload: bytes) -> dict:
    return {
        "instrument": instrument,
        "episode_count": episodes,
        "byte_size": len(payload),
        "sha256": ("1" if instrument == "BTCUSDT" else "2") * 64,
        "path_metrics": {
            "row_count": episodes * 2,
            "evidence_level_counts": {"H1": episodes, "H2": episodes},
            "metric_status_counts": {"COMPUTED": episodes * 2 - 1, "NO_OBSERVATIONS": 1},
        },
    }


def _write_t12_pass(
    root: Path,
    repository_root: Path,
    run_id: str = T12_RUN_ID,
    *,
    human_accepted: bool = False,
) -> None:
    run_root, authority = _write_t12_active(root, run_id)
    snapshot_id = "3" * 64
    snapshot = run_root / "published/snapshots" / snapshot_id
    payloads = {"BTCUSDT": b"btc", "ETHUSDT": b"eth-data"}
    entries = {
        instrument: _instrument_catalog(instrument, episodes, payloads[instrument])
        for instrument, episodes in (("BTCUSDT", 10), ("ETHUSDT", 12))
    }
    for instrument, payload in payloads.items():
        path = snapshot / instrument / "path_metrics.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    catalog = _sealed(
        {
            "schema_name": "stage2-s2t12-path-metrics-catalog",
            "schema_version": "1.0",
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "instruments": entries,
        },
        "catalog_hash",
    )
    execution_path = next((run_root / "manifests").glob("execution-*.json"))
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    manifest = _sealed(
        {
            "schema_name": "stage2-s2t12-path-metrics-manifest",
            "schema_version": "1.0",
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "execution_manifest_hash": execution["execution_manifest_hash"],
            "historical_evidence_only": True,
        },
        "manifest_hash",
    )
    completion = {
        "status": "PASS",
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    _write(snapshot / "catalog.json", json.dumps(catalog))
    _write(snapshot / "manifest.json", json.dumps(manifest))
    _write(run_root / "reports/completion.json", json.dumps(completion))
    summary_instruments = {
        instrument: {
            "episode_count": entry["episode_count"],
            "h1_rows": entry["path_metrics"]["evidence_level_counts"]["H1"],
            "h2_rows": entry["path_metrics"]["evidence_level_counts"]["H2"],
            "row_count": entry["path_metrics"]["row_count"],
            "output_sha256": entry["sha256"],
        }
        for instrument, entry in entries.items()
    }
    summary = {
        "schema_name": "s2-t12-path-metrics-repository-summary",
        "task_id": "S2-T12",
        "task_version": "1.3",
        "run_id": run_id,
        "authority_hash": authority["authority_hash"],
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "total_metric_rows": 44,
        "instruments": summary_instruments,
        "verify_status": "PASS",
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    if human_accepted:
        summary.update(
            {
                "status": "PASSED_HUMAN_ACCEPTED",
                "human_accepted": True,
                "accepted_by": "Muce",
                "accepted_at": "2026-07-21T06:39:21Z",
            }
        )
    _write(
        repository_root / MODULE.S2T12_SUMMARY_RELATIVE_PATH,
        json.dumps(summary),
    )
    _write(
        repository_root / MODULE.S2T12_VALIDATION_RELATIVE_PATH,
        (f"S2-T12 {'PASSED / HUMAN ACCEPTED' if human_accepted else 'VALIDATED'}\nRun {run_id}\n"),
    )


def _t13_authority() -> dict:
    return _sealed(
        {
            "task_id": "S2-T13",
            "task_version": "1.3",
            "code_commit": "abcdef0",
            "combination_order": [f"combination-{index}" for index in range(30)],
            "historical_evidence_only": True,
        },
        "authority_hash",
    )


def _write_t13_active(root: Path, run_id: str = T13_RUN_ID) -> tuple[Path, dict]:
    run_root = root / "runs" / run_id
    authority = _t13_authority()
    _write(run_root / "manifests/preflight-authority.json", json.dumps(authority))
    execution = _sealed(
        {
            **authority,
            "run_id": run_id,
            "started_at_utc": "2026-07-21T10:45:00Z",
        },
        "execution_manifest_hash",
    )
    _write(
        run_root / "manifests" / f"execution-{execution['execution_manifest_hash']}.json",
        json.dumps(execution),
    )
    _write(
        root / "authorities/S2-T13" / f"{authority['authority_hash']}.json",
        json.dumps(authority),
    )
    return run_root, authority


def _t13_instrument(instrument: str, episodes: int, payload: bytes) -> dict:
    rows = episodes * 2
    classifications = rows * 30
    return {
        "instrument": instrument,
        "episode_count": episodes,
        "byte_size": len(payload),
        "sha256": ("4" if instrument == "BTCUSDT" else "5") * 64,
        "first_passage": {
            "row_count": rows,
            "classification_count": classifications,
            "evidence_level_counts": {"H1": episodes, "H2": episodes},
            "label_counts": {"EXPIRED": classifications},
            "timing_id_counts": {"T1": 2, "T2": rows - 6, "T3": 2, "T4": 2},
        },
    }


def _write_t13_pass(
    root: Path,
    repository_root: Path,
    run_id: str = T13_RUN_ID,
) -> None:
    run_root, authority = _write_t13_active(root, run_id)
    snapshot_id = "6" * 64
    snapshot = run_root / "published/snapshots" / snapshot_id
    payloads = {"BTCUSDT": b"btc-labels", "ETHUSDT": b"eth-labels"}
    entries = {
        instrument: _t13_instrument(instrument, episodes, payloads[instrument])
        for instrument, episodes in (("BTCUSDT", 10), ("ETHUSDT", 12))
    }
    for instrument, payload in payloads.items():
        path = snapshot / instrument / "first_passage.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    catalog = _sealed(
        {
            "schema_name": "stage2-s2t13-first-passage-catalog",
            "schema_version": "1.0",
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "combination_order": authority["combination_order"],
            "instruments": entries,
        },
        "catalog_hash",
    )
    execution_path = next((run_root / "manifests").glob("execution-*.json"))
    execution = json.loads(execution_path.read_text())
    manifest = _sealed(
        {
            "schema_name": "stage2-s2t13-first-passage-manifest",
            "schema_version": "1.0",
            "task_id": "S2-T13",
            "task_version": "1.3",
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "execution_manifest_hash": execution["execution_manifest_hash"],
            "authority_hash": authority["authority_hash"],
            "historical_evidence_only": True,
            "stage3_locked": True,
        },
        "manifest_hash",
    )
    total_rows = sum(entry["first_passage"]["row_count"] for entry in entries.values())
    total_classifications = sum(
        entry["first_passage"]["classification_count"] for entry in entries.values()
    )
    completion = {
        "status": "PASS",
        "task_id": "S2-T13",
        "task_version": "1.3",
        "run_id": run_id,
        "authority_hash": authority["authority_hash"],
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "total_path_rows": total_rows,
        "total_classification_count": total_classifications,
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    _write(snapshot / "catalog.json", json.dumps(catalog))
    _write(snapshot / "manifest.json", json.dumps(manifest))
    _write(run_root / "reports/completion.json", json.dumps(completion))
    summary = {
        "schema_name": "s2-t13-first-passage-repository-summary",
        "task_id": "S2-T13",
        "task_version": "1.3",
        "run_id": run_id,
        "authority_hash": authority["authority_hash"],
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "total_path_rows": total_rows,
        "total_classification_count": total_classifications,
        "instruments": {
            instrument: {
                "episode_count": entry["episode_count"],
                "path_rows": entry["first_passage"]["row_count"],
                "classification_count": entry["first_passage"]["classification_count"],
                "output_sha256": entry["sha256"],
            }
            for instrument, entry in entries.items()
        },
        "verify_status": "PASS",
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    _write(repository_root / MODULE.S2T13_SUMMARY_RELATIVE_PATH, json.dumps(summary))
    _write(
        repository_root / MODULE.S2T13_VALIDATION_RELATIVE_PATH,
        f"S2-T13 VALIDATED\nRun {run_id}\n",
    )


def test_execution_observability_projects_append_only_evidence(tmp_path: Path) -> None:
    adoption = {
        "adopted_file_count": 8708,
        "adopted_byte_count": 57388412230,
        "foundation_checkpoint_count": 796,
        "group1_month_count": 158,
        "group1_dataset_count": 2054,
    }
    _write(
        tmp_path / "manifests/group1-monthly-adoption-test.json",
        json.dumps(adoption),
    )
    _write(tmp_path / "staging/receipts/foundation/BTCUSDT.json")
    _write(tmp_path / "staging/group1/packed-seals/a.json")
    _write(tmp_path / "staging/group1/packed-seals/._a.json")
    _write(tmp_path / "staging/group1/partials/a.arrow")
    _write(tmp_path / "staging/evidence/group1-components/a.json")
    _write(
        tmp_path / "checkpoint-v2.json",
        json.dumps(
            {
                "completed_tasks": [
                    {"task_id": "FOUNDATION:BTCUSDT", "resource_anomaly_count": 0},
                    {"task_id": "GROUP1:BTCUSDT:V1_PRICE", "resource_anomaly_count": 7},
                ]
            }
        ),
    )
    _write(
        tmp_path / "reports/v2-publication-record.json",
        json.dumps({"publication_state": "PUBLISHED"}),
    )
    _write(
        tmp_path / "reports/v2-run-a-comparison.json",
        json.dumps(
            {
                "report": {
                    "status": "PASS",
                    "matched_partition_count": 61776,
                    "daily_row_hash_match_count": 61776,
                    "differences": [],
                    "missing_in_v2": [],
                    "extra_in_v2": [],
                    "global_distributions_equal": True,
                }
            }
        ),
    )
    _write(
        tmp_path / "reports/compare-only-authority-cr-2026-019.json",
        json.dumps({"status": "AUTHORIZED_COMPARE_ONLY", "allowed_commands": ["compare"]}),
    )

    result = _execution_observability(tmp_path)

    assert result["successor_created"] is True
    assert result["adoption"] == adoption
    assert result["packed_seal_count"] == 1
    assert result["partial_file_count"] == 1
    assert result["group1_component_count"] == 1
    assert result["group1_component_total"] == 4
    assert result["group1_components"]["group1_btc_price"] is False
    assert result["task_receipts"]["foundation_btc"] is True
    assert result["task_receipts"]["foundation_eth"] is False
    assert result["resource_anomalies"] == {
        "FOUNDATION:BTCUSDT": 0,
        "GROUP1:BTCUSDT:V1_PRICE": 7,
    }
    assert result["resource_anomaly_count"] == 7
    assert result["publication_record_present"] is True
    assert result["publication_state"] == "PUBLISHED"
    assert result["comparison_report_present"] is True
    assert result["compare_only_status"] == "AUTHORIZED_COMPARE_ONLY"
    assert result["compare_only_allowed_commands"] == ["compare"]
    assert result["comparison_status"] == "PASS"
    assert result["matched_partition_count"] == 61776
    assert result["daily_row_hash_match_count"] == 61776
    assert result["difference_count"] == 0
    assert result["missing_partition_count"] == 0
    assert result["extra_partition_count"] == 0
    assert result["global_distributions_equal"] is True


def test_execution_observability_projects_cr018_release_only_evidence(tmp_path: Path) -> None:
    _write(
        tmp_path / "reports/release-only-authority-cr-2026-018.json",
        json.dumps(
            {
                "status": "AUTHORIZED_RELEASE_ONLY",
                "allowed_commands": ["release", "verify", "compare"],
                "object_count": 208,
                "seal_count": 208,
                "partition_count": 80784,
                "superseded_run_id": "stage2-g1-v2-b-superseded",
            }
        ),
    )
    _write(
        tmp_path / "reports/release-only-preflight-cr-2026-018.json",
        json.dumps({"status": "PASS"}),
    )

    result = _execution_observability(tmp_path)

    assert result["successor_created"] is False
    assert result["release_only"] is True
    assert result["release_only_status"] == "AUTHORIZED_RELEASE_ONLY"
    assert result["release_only_preflight_status"] == "PASS"
    assert result["release_only_allowed_commands"] == ["release", "verify", "compare"]
    assert result["sealed_object_count"] == 208
    assert result["sealed_seal_count"] == 208
    assert result["sealed_partition_count"] == 80784
    assert result["superseded_run_id"] == "stage2-g1-v2-b-superseded"


def test_acceptance_is_derived_from_live_release_verify_and_exact_compare_evidence() -> None:
    status = {
        "overall_logical_partitions_done": 80784,
        "pipeline_subflows": [
            {"name": "RELEASE", "status": "PASS"},
            {"name": "VERIFY", "status": "PASS"},
            {"name": "RUN_A_RUN_B_COMPARE", "status": "PASS"},
        ],
    }
    observability = {
        "task_receipts": {name: True for name in MODULE.RUNTIME_TASK_RECEIPTS},
        "publication_state": "PUBLISHED_WITH_RESOURCE_ANOMALIES",
        "quality_status": "PASS",
        "comparison_report_present": True,
        "matched_partition_count": 61776,
        "daily_row_hash_match_count": 61776,
        "missing_partition_count": 0,
        "extra_partition_count": 0,
        "difference_count": 0,
        "global_distributions_equal": True,
    }

    result = _acceptance_projection(status, observability)

    assert result["s2_t10_status"] == "PASS"
    assert result["group1_status"] == "PASS"
    assert result["stage3_status"] == "LOCKED"
    assert all(result["checks"].values())

    observability["difference_count"] = 1
    assert _acceptance_projection(status, observability)["s2_t10_status"] == "FAILED"


def _path_receipt_payload(
    status: str,
    sequence: int = 0,
    previous: str | None = None,
    reason_code: str | None = None,
):
    from era100x.research.stage_2.paths.extraction import PathExtractionReceipt

    passed = status == "PASS"
    return PathExtractionReceipt.seal(
        {
            "code_commit": "abcdef0",
            "sequence": sequence,
            "previous_receipt_hash": previous,
            "status": status,
            "reason_code": reason_code or f"S2_T11_{status}",
            "btc_episodes_done": 10 if passed else 4,
            "btc_episodes_total": 10,
            "eth_episodes_done": 8 if passed else 1,
            "eth_episodes_total": 8,
            "input_hashes": {"BTCUSDT": "1" * 64, "ETHUSDT": "2" * 64},
            "output_hashes": {"BTCUSDT": "3" * 64, "ETHUSDT": "4" * 64} if passed else {},
            "acceptance_checks": {"utc": True, "shuffle": True},
            "full_output_complete": passed,
            "validation_status": "PASS" if passed else "NOT_RUN",
            "validation_path": "docs/development/validations/stage_2/S2-T11.md",
            "validation_hash": "5" * 64 if passed else None,
            "created_at": "2026-07-21T00:00:00Z",
        }
    )


def _write_path_receipt(root: Path, receipt) -> None:
    path = root / "task-evidence/S2-T11" / f"{receipt.sequence:06d}-{receipt.receipt_hash}.json"
    _write(path, json.dumps(receipt.model_dump(mode="json")))


def test_s2_t11_missing_receipt_is_never_pass(tmp_path: Path) -> None:
    result = _stage2_task_projection(tmp_path)

    assert result["status"] == "NOT_STARTED"
    assert result["receipt_count"] == 0


def test_s2_t11_in_progress_and_failed_receipts_expose_counts_and_reason(tmp_path: Path) -> None:
    active = _path_receipt_payload("IN_PROGRESS")
    _write_path_receipt(tmp_path, active)
    result = _stage2_task_projection(tmp_path)
    assert result["status"] == "IN_PROGRESS"
    assert result["btc_done"] == 4
    assert result["eth_done"] == 1

    failed_root = tmp_path / "failed"
    failed = _path_receipt_payload("FAILED")
    _write_path_receipt(failed_root, failed)
    failed_result = _stage2_task_projection(failed_root)
    assert failed_result["status"] == "FAILED"
    assert failed_result["reason_code"] == "S2_T11_FAILED"


def test_s2_t11_pass_requires_full_separate_hashed_evidence(tmp_path: Path) -> None:
    passed = _path_receipt_payload("PASS")
    _write_path_receipt(tmp_path, passed)
    result = _stage2_task_projection(tmp_path)

    assert result["status"] == "PASS"
    assert result["full_output_complete"] is True
    assert result["validation_status"] == "PASS"
    assert all(result["checks"].values())
    assert result["task_version"] == "1.3"
    assert result["human_accepted"] is False


def test_s2_t11_human_acceptance_is_derived_from_append_only_receipt(tmp_path: Path) -> None:
    passed = _path_receipt_payload(
        "PASS",
        reason_code="S2_T11_HUMAN_ACCEPTED_20260721T024707Z",
    )
    _write_path_receipt(tmp_path, passed)

    result = _stage2_task_projection(tmp_path)

    assert result["status"] == "PASS"
    assert result["human_accepted"] is True


def test_ui_derives_s2_t11_version_and_complete_task_count() -> None:
    page = MODULE_PATH.with_name("stage2_progress_ui.html").read_text(encoding="utf-8")

    assert 'task.task_version || "UNKNOWN"' in page
    assert "/ 14 PASSED" in page
    assert "S2-T11 v1.2" not in page
    assert "S2-T13<b>CHECKING</b>" in page
    assert "S2-T13<b>PASSED</b>" not in page


def test_s2_t11_malformed_symlink_and_conflicting_chain_fail_closed(tmp_path: Path) -> None:
    directory = tmp_path / "task-evidence/S2-T11"
    _write(directory / "broken.json", "not-json")
    assert _stage2_task_projection(tmp_path)["status"] == "EVIDENCE_INVALID"

    symlink_root = tmp_path / "symlink"
    target = tmp_path / "target"
    target.mkdir()
    link = symlink_root / "task-evidence/S2-T11"
    link.parent.mkdir(parents=True)
    link.symlink_to(target, target_is_directory=True)
    assert _stage2_task_projection(symlink_root)["status"] == "EVIDENCE_INVALID"

    conflict_root = tmp_path / "conflict"
    first = _path_receipt_payload("IN_PROGRESS")
    _write_path_receipt(conflict_root, first)
    second = _path_receipt_payload("FAILED", sequence=1, previous="9" * 64)
    _write_path_receipt(conflict_root, second)
    assert _stage2_task_projection(conflict_root)["status"] == "EVIDENCE_INVALID"


def test_s2_t12_missing_and_active_runs_never_pass(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    missing = _stage2_path_metrics_projection(tmp_path, repository_root)
    assert missing["status"] == "NOT_STARTED"
    assert missing["reason_code"] == "S2_T12_RUN_MISSING"

    _write_t12_active(tmp_path)
    active = _stage2_path_metrics_projection(tmp_path, repository_root)
    assert active["status"] == "IN_PROGRESS"
    assert active["run_id"] == T12_RUN_ID
    assert active["checks"]["published_completion_present"] is False


def test_s2_t12_failed_unpublished_run_exposes_reason(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / T12_RUN_ID
    failure = {
        "task_id": "S2-T12",
        "task_version": "1.3",
        "run_id": T12_RUN_ID,
        "status": "FAILED_UNPUBLISHED",
        "failure_class": "VALIDATION_ERROR",
        "reason": "test failure",
        "resume_allowed": False,
    }
    _write(run_root / "reports/failure.json", json.dumps(failure))

    result = _stage2_path_metrics_projection(tmp_path, tmp_path / "repository")

    assert result["status"] == "FAILED"
    assert result["reason_code"] == "S2_T12_FAILED_UNPUBLISHED"
    assert result["reason"] == "test failure"
    assert result["resume_allowed"] is False


def test_s2_t12_pass_requires_bound_authority_catalog_summary_and_validation(
    tmp_path: Path,
) -> None:
    stage2_root = tmp_path / "stage2"
    repository_root = tmp_path / "repository"
    _write_t12_pass(stage2_root, repository_root)

    result = _stage2_path_metrics_projection(stage2_root, repository_root)

    assert result["status"] == "PASS"
    assert result["reason_code"] == "S2_T12_FULL_OUTPUT_VERIFIED_VALIDATION_PASS"
    assert result["total_metric_rows"] == 44
    assert result["instruments"]["BTCUSDT"]["h1_rows"] == 10
    assert result["instruments"]["BTCUSDT"]["h2_rows"] == 10
    assert result["instruments"]["ETHUSDT"]["h1_rows"] == 12
    assert result["instruments"]["ETHUSDT"]["h2_rows"] == 12
    assert result["verify_status"] == "PASS"
    assert result["validation_status"] == "PASS"
    assert result["historical_evidence_only"] is True
    assert result["stage3_locked"] is True
    assert result["human_accepted"] is False
    assert len(result["checks"]) == 16
    assert all(result["checks"].values())


def test_s2_t12_tampered_repository_summary_fails_closed(tmp_path: Path) -> None:
    stage2_root = tmp_path / "stage2"
    repository_root = tmp_path / "repository"
    _write_t12_pass(stage2_root, repository_root)
    summary_path = repository_root / MODULE.S2T12_SUMMARY_RELATIVE_PATH
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["total_metric_rows"] += 1
    _write(summary_path, json.dumps(summary))

    result = _stage2_path_metrics_projection(stage2_root, repository_root)

    assert result["status"] == "EVIDENCE_INVALID"
    assert result["checks"]["repository_summary_matches"] is False


def test_s2_t12_human_acceptance_requires_complete_repository_metadata(tmp_path: Path) -> None:
    stage2_root = tmp_path / "stage2"
    repository_root = tmp_path / "repository"
    _write_t12_pass(stage2_root, repository_root, human_accepted=True)

    accepted = _stage2_path_metrics_projection(stage2_root, repository_root)
    assert accepted["status"] == "PASS"
    assert accepted["human_accepted"] is True

    summary_path = repository_root / MODULE.S2T12_SUMMARY_RELATIVE_PATH
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.pop("accepted_at")
    _write(summary_path, json.dumps(summary))
    incomplete = _stage2_path_metrics_projection(stage2_root, repository_root)
    assert incomplete["status"] == "PASS"
    assert incomplete["human_accepted"] is False


def test_s2_t12_newest_terminal_run_wins_without_fallback(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    _write_t12_pass(tmp_path, repository_root)
    newer_run_id = "stage2-s2t12-metrics-20260721T040436Z-fedcba654321"
    failure = {
        "task_id": "S2-T12",
        "task_version": "1.3",
        "run_id": newer_run_id,
        "status": "FAILED_UNPUBLISHED",
        "failure_class": "VALIDATION_ERROR",
        "reason": "newer run failed",
        "resume_allowed": False,
    }
    _write(
        tmp_path / "runs" / newer_run_id / "reports/failure.json",
        json.dumps(failure),
    )

    result = _stage2_path_metrics_projection(tmp_path, repository_root)

    assert result["status"] == "FAILED"
    assert result["run_id"] == newer_run_id
    assert result["reason"] == "newer run failed"


def test_s2_t12_symlink_run_and_terminal_evidence_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    linked_run = tmp_path / "runs" / T12_RUN_ID
    linked_run.parent.mkdir(parents=True)
    linked_run.symlink_to(target, target_is_directory=True)
    result = _stage2_path_metrics_projection(tmp_path, tmp_path / "repository")
    assert result["status"] == "EVIDENCE_INVALID"

    terminal_root = tmp_path / "terminal"
    run_root, _ = _write_t12_active(terminal_root)
    completion_target = tmp_path / "completion.json"
    _write(completion_target, json.dumps({"status": "PASS"}))
    completion_path = run_root / "reports/completion.json"
    completion_path.parent.mkdir(parents=True)
    completion_path.symlink_to(completion_target)
    terminal_result = _stage2_path_metrics_projection(
        terminal_root,
        tmp_path / "repository",
    )
    assert terminal_result["status"] == "EVIDENCE_INVALID"


def test_s2_t13_missing_and_active_runs_never_pass(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    missing = _stage2_first_passage_projection(tmp_path, repository_root)
    assert missing["status"] == "NOT_STARTED"
    assert missing["reason_code"] == "S2_T13_RUN_MISSING"

    _write_t13_active(tmp_path)
    active = _stage2_first_passage_projection(tmp_path, repository_root)
    assert active["status"] == "IN_PROGRESS"
    assert active["run_id"] == T13_RUN_ID
    assert active["checks"]["published_completion_present"] is False


def test_s2_t13_pass_requires_authority_matrix_verify_and_validation(tmp_path: Path) -> None:
    stage2_root = tmp_path / "stage2"
    repository_root = tmp_path / "repository"
    _write_t13_pass(stage2_root, repository_root)

    result = _stage2_first_passage_projection(stage2_root, repository_root)

    assert result["status"] == "PASS"
    assert result["reason_code"] == "S2_T13_FULL_OUTPUT_VERIFIED_VALIDATION_PASS"
    assert result["total_path_rows"] == 44
    assert result["total_classification_count"] == 1320
    assert result["instruments"]["BTCUSDT"]["h1_rows"] == 10
    assert result["instruments"]["ETHUSDT"]["h2_rows"] == 12
    assert result["verify_status"] == "PASS"
    assert result["validation_status"] == "PASS"
    assert result["historical_evidence_only"] is True
    assert result["stage3_locked"] is True
    assert result["human_accepted"] is False
    assert all(result["checks"].values())


def test_s2_t13_newest_failure_wins_without_fallback(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    _write_t13_pass(tmp_path, repository_root)
    newer = "stage2-s2t13-first-passage-20260721T104501Z-fedcba654321"
    failure = {
        "task_id": "S2-T13",
        "task_version": "1.3",
        "run_id": newer,
        "status": "FAILED_UNPUBLISHED",
        "failure_class": "VALIDATION_ERROR",
        "reason": "newer run failed",
        "resume_allowed": False,
    }
    _write(tmp_path / "runs" / newer / "reports/failure.json", json.dumps(failure))

    result = _stage2_first_passage_projection(tmp_path, repository_root)

    assert result["status"] == "FAILED"
    assert result["run_id"] == newer
    assert result["reason"] == "newer run failed"


def test_s2_t13_tampered_summary_and_symlink_fail_closed(tmp_path: Path) -> None:
    stage2_root = tmp_path / "stage2"
    repository_root = tmp_path / "repository"
    _write_t13_pass(stage2_root, repository_root)
    summary_path = repository_root / MODULE.S2T13_SUMMARY_RELATIVE_PATH
    summary = json.loads(summary_path.read_text())
    summary["total_classification_count"] += 1
    _write(summary_path, json.dumps(summary))
    result = _stage2_first_passage_projection(stage2_root, repository_root)
    assert result["status"] == "EVIDENCE_INVALID"
    assert result["checks"]["repository_summary_matches"] is False

    linked_root = tmp_path / "linked"
    target = tmp_path / "outside-t13"
    target.mkdir()
    run_link = linked_root / "runs" / T13_RUN_ID
    run_link.parent.mkdir(parents=True)
    run_link.symlink_to(target, target_is_directory=True)
    linked = _stage2_first_passage_projection(linked_root, repository_root)
    assert linked["status"] == "EVIDENCE_INVALID"
