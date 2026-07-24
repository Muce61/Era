from __future__ import annotations

import importlib.util
import hashlib
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
_stage2_ambiguity_bounds_projection = MODULE._stage2_ambiguity_bounds_projection
_stage2_conditional_baseline_projection = MODULE._stage2_conditional_baseline_projection
_stage2_v13_projection = MODULE._stage2_v13_projection
_json_hash = MODULE._json_hash

T12_RUN_ID = "stage2-s2t12-metrics-20260721T040435Z-abcdef123456"
T13_RUN_ID = "stage2-s2t13-first-passage-20260721T104500Z-abcdef123456"
T14_RUN_ID = "stage2-s2t14-ambiguity-bounds-20260721T140500Z-abcdef123456"


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
    human_accepted: bool = False,
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
    if human_accepted:
        summary.update(
            {
                "status": "PASSED_HUMAN_ACCEPTED",
                "human_accepted": True,
                "accepted_by": "Muce",
                "accepted_at": "2026-07-21T12:52:58Z",
            }
        )
    _write(repository_root / MODULE.S2T13_SUMMARY_RELATIVE_PATH, json.dumps(summary))
    _write(
        repository_root / MODULE.S2T13_VALIDATION_RELATIVE_PATH,
        f"S2-T13 VALIDATED\nRun {run_id}\n",
    )


def _t14_authority() -> dict:
    parameter_set_ids = [f"parameter-{index:02d}" for index in range(19)]
    return _sealed(
        {
            "task_id": "S2-T14",
            "task_version": "1.3",
            "code_commit": "abcdef0",
            "source_s2t13_run_id": T13_RUN_ID,
            "source_s2t13_snapshot_id": "6" * 64,
            "source_s2t13_authority_hash": "a" * 64,
            "source_s2t13_manifest_hash": "7" * 64,
            "source_s2t13_catalog_hash": "8" * 64,
            "source_s2t13_code_commit": "65a5473",
            "combination_order": [f"combination-{index}" for index in range(30)],
            "parameter_set_ids": parameter_set_ids,
            "parameter_set_timing_pairs": [
                {"parameter_set_id": value, "timing_id": f"T{index % 4 + 1}"}
                for index, value in enumerate(parameter_set_ids)
            ],
            "timing_ids": ["T1", "T2", "T3", "T4"],
            "evidence_levels": ["H1", "H2"],
            "expected_distribution_count_per_instrument": 1_140,
            "historical_evidence_only": True,
            "stage3_locked": True,
        },
        "authority_hash",
    )


def _write_t14_active(root: Path, run_id: str = T14_RUN_ID) -> tuple[Path, dict]:
    run_root = root / "runs" / run_id
    authority = _t14_authority()
    _write(run_root / "manifests/preflight-authority.json", json.dumps(authority))
    execution = _sealed(
        {
            **authority,
            "run_id": run_id,
            "started_at_utc": "2026-07-21T14:05:00Z",
        },
        "execution_manifest_hash",
    )
    _write(
        run_root / "manifests" / f"execution-{execution['execution_manifest_hash']}.json",
        json.dumps(execution),
    )
    _write(
        root / "authorities/S2-T14" / f"{authority['authority_hash']}.json",
        json.dumps(authority),
    )
    return run_root, authority


def _t14_instrument(instrument: str, episodes: int, payload: bytes) -> dict:
    path_rows = episodes * 2
    classifications = path_rows * 30
    ambiguous = classifications // 10
    target_first = classifications // 5
    stop_first = classifications // 4
    expired = classifications - ambiguous - target_first - stop_first
    return {
        "instrument": instrument,
        "episode_count": episodes,
        "path_rows": path_rows,
        "classification_count": classifications,
        "distribution_count": 1_140,
        "label_counts": {
            "TARGET_FIRST": target_first,
            "STOP_FIRST": stop_first,
            "EXPIRED": expired,
            "AMBIGUOUS": ambiguous,
        },
        "label_reason_counts": {
            "TARGET_OBSERVED_FIRST": target_first,
            "STOP_OBSERVED_FIRST": stop_first,
            "HORIZON_EXPIRED_WITHOUT_TOUCH": expired,
            "H1_SAME_EVENT_TARGET_AND_STOP": ambiguous,
        },
        "primary_target_first_count": target_first,
        "conditional_denominator": classifications - ambiguous,
        "theoretical_upper_target_first_count": target_first + ambiguous,
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _write_t14_pass(
    root: Path,
    repository_root: Path,
    run_id: str = T14_RUN_ID,
    *,
    human_accepted: bool = False,
) -> None:
    run_root, authority = _write_t14_active(root, run_id)
    snapshot_id = "9" * 64
    snapshot = run_root / "published/snapshots" / snapshot_id
    payloads = {
        "BTCUSDT": b'{"instrument":"BTCUSDT","distributions":[]}',
        "ETHUSDT": b'{"instrument":"ETHUSDT","distributions":[]}',
    }
    entries = {
        instrument: _t14_instrument(instrument, episodes, payloads[instrument])
        for instrument, episodes in (("BTCUSDT", 10), ("ETHUSDT", 12))
    }
    for instrument, payload in payloads.items():
        path = snapshot / instrument / "ambiguity_distributions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    catalog = _sealed(
        {
            "schema_name": "stage2-s2t14-ambiguity-bounds-catalog",
            "schema_version": "1.0",
            "run_id": run_id,
            "snapshot_id": snapshot_id,
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
            "instruments": entries,
        },
        "catalog_hash",
    )
    execution_path = next((run_root / "manifests").glob("execution-*.json"))
    execution = json.loads(execution_path.read_text())
    manifest = _sealed(
        {
            "schema_name": "stage2-s2t14-ambiguity-bounds-manifest",
            "schema_version": "1.0",
            "task_id": "S2-T14",
            "task_version": "1.3",
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "execution_manifest_hash": execution["execution_manifest_hash"],
            "authority_hash": authority["authority_hash"],
            "source_s2t13_run_id": authority["source_s2t13_run_id"],
            "source_s2t13_snapshot_id": authority["source_s2t13_snapshot_id"],
            "source_s2t13_authority_hash": authority["source_s2t13_authority_hash"],
            "source_s2t13_manifest_hash": authority["source_s2t13_manifest_hash"],
            "source_s2t13_catalog_hash": authority["source_s2t13_catalog_hash"],
            "source_s2t13_code_commit": authority["source_s2t13_code_commit"],
            "historical_evidence_only": True,
            "stage3_locked": True,
        },
        "manifest_hash",
    )
    total_rows = sum(entry["path_rows"] for entry in entries.values())
    total_classifications = sum(entry["classification_count"] for entry in entries.values())
    total_distributions = sum(entry["distribution_count"] for entry in entries.values())
    total_ambiguous = sum(entry["label_counts"]["AMBIGUOUS"] for entry in entries.values())
    completion = {
        "status": "PASS",
        "task_id": "S2-T14",
        "task_version": "1.3",
        "run_id": run_id,
        "authority_hash": authority["authority_hash"],
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "total_path_rows": total_rows,
        "total_classification_count": total_classifications,
        "total_distribution_count": total_distributions,
        "total_ambiguous_count": total_ambiguous,
        "historical_evidence_only": True,
        "stage3_locked": True,
    }
    _write(snapshot / "catalog.json", json.dumps(catalog))
    _write(snapshot / "manifest.json", json.dumps(manifest))
    _write(run_root / "reports/completion.json", json.dumps(completion))
    summary = {
        "schema_name": "s2-t14-ambiguity-bounds-repository-summary",
        "task_id": "S2-T14",
        "task_version": "1.3",
        "run_id": run_id,
        "authority_hash": authority["authority_hash"],
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "source_s2t13_run_id": authority["source_s2t13_run_id"],
        "total_path_rows": total_rows,
        "total_classification_count": total_classifications,
        "total_distribution_count": total_distributions,
        "total_ambiguous_count": total_ambiguous,
        "instruments": {
            instrument: {
                "episode_count": entry["episode_count"],
                "path_rows": entry["path_rows"],
                "classification_count": entry["classification_count"],
                "distribution_count": entry["distribution_count"],
                "ambiguous_count": entry["label_counts"]["AMBIGUOUS"],
                "output_sha256": entry["sha256"],
            }
            for instrument, entry in entries.items()
        },
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
                "accepted_at": "2026-07-21T15:00:00Z",
            }
        )
    _write(repository_root / MODULE.S2T14_SUMMARY_RELATIVE_PATH, json.dumps(summary))
    _write(
        repository_root / MODULE.S2T14_VALIDATION_RELATIVE_PATH,
        f"S2-T14 VALIDATED\nRun {run_id}\n",
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


def test_ui_derives_current_task_version_count_and_acceptance_without_hardcoded_pass() -> None:
    page = MODULE_PATH.with_name("stage2_progress_ui.html").read_text(encoding="utf-8")

    assert 'task.task_version || "UNKNOWN"' in page
    assert "/ 16 PASSED" in page
    assert "S2-T11 v1.2" not in page
    assert "S2-T15<b>CHECKING</b>" in page
    assert "S2-T15<b>PASSED</b>" not in page
    assert 'tasks["S2-T14"]' in page
    assert 'tasks["S2-T15"]' in page
    assert "VALIDATED · AWAITING HUMAN" in page
    assert "PASSED · HUMAN ACCEPTED" in page
    assert "等待 OQ-S2-006 的人工输入绑定决定" in page
    assert "missing receipt distributions" in page
    assert 'fetch("/api/v13/status"' in page
    assert "refreshV13();" in page
    assert "setInterval(refreshV13, 5000)" in page
    assert "legacyRefreshInFlight" in page
    assert "task.progress_percent" in page
    assert "task.current_instrument" in page
    assert "task.current_date" in page
    assert "rehearsal_progress_percent" in page
    assert "rehearsal_heartbeat_at" in page
    assert "formal_rehearsal_gate_mode" in page
    assert "background_runtime_waiver_reason" in page
    assert 'state === "running" ? 35' not in page


def test_s2_t15_audit_projects_not_started_without_authority_or_run(tmp_path: Path) -> None:
    audit = {
        "status": "PASS",
        "authority_created": False,
        "run_id_created": False,
        "upstream_binding_hash": "a" * 64,
        "t13": {"h2_path_count": 532708, "h2_outcome_cell_count": 15981240},
        "t14": {"binding_mode": "AGGREGATE_POLICY_ONLY_NO_EPISODE_JOIN"},
    }
    _write(
        tmp_path / "authorities/S2-T15/v1.4/audits" / f"{'a' * 64}.json",
        json.dumps(audit),
    )

    result = _stage2_conditional_baseline_projection(tmp_path)

    assert result["status"] == "NOT_STARTED"
    assert result["audit_status"] == "PASS"
    assert result["authority_count"] == 0
    assert result["run_count"] == 0


def test_s2_t15_verify_alone_cannot_project_pass(tmp_path: Path) -> None:
    authority_hash = "b" * 64
    _write(
        tmp_path / "authorities/S2-T15/v1.4" / f"authority-{authority_hash}.json",
        "{}",
    )
    run_id = "stage2-s2t15-conditional-20260722T000000Z-000000000000"
    _write(
        tmp_path / "runs" / run_id / "reports/verify.json",
        json.dumps(
            {
                "status": "PASS",
                "reconciliation_status": "PASS",
                "historical_evidence_only": True,
                "stage3_locked": True,
                "run_id": run_id,
                "authority_hash": authority_hash,
            }
        ),
    )

    result = _stage2_conditional_baseline_projection(tmp_path)

    assert result["status"] == "IN_PROGRESS"
    assert result["verify_status"] == "PASS"
    assert result["validation_status"] != "PASS"


def test_s2_t15_blocked_audit_projects_blocked(tmp_path: Path) -> None:
    audit = {
        "status": "BLOCKED",
        "reason_code": "S2_T15_UPSTREAM_T10_RECEIPT_DISTRIBUTIONS_MISSING",
        "authority_created": False,
        "run_id_created": False,
        "t13": {"h2_path_count": 532708, "h2_outcome_cell_count": 15981240},
        "t14": {"binding_mode": "AGGREGATE_POLICY_ONLY_NO_EPISODE_JOIN"},
    }
    _write(
        tmp_path / "authorities/S2-T15/v1.4/audits" / f"{'c' * 64}.json",
        json.dumps(audit),
    )

    result = _stage2_conditional_baseline_projection(tmp_path)

    assert result["status"] == "BLOCKED"
    assert result["audit_status"] == "BLOCKED"
    assert result["reason_code"] == "S2_T15_UPSTREAM_T10_RECEIPT_DISTRIBUTIONS_MISSING"


def test_s2_t15_failed_checkpoint_overrides_stale_run_in_progress(tmp_path: Path) -> None:
    run_id = "stage2-s2t15-conditional-20260722T000000Z-000000000000"
    _write(
        tmp_path / "runs" / run_id / "checkpoint.json",
        json.dumps(
            {
                "run_id": run_id,
                "status": "FAILED_UNPUBLISHED",
                "phase": "FAILED",
                "published": False,
                "stage3_locked": True,
            }
        ),
    )

    result = _stage2_conditional_baseline_projection(tmp_path)

    assert result["status"] == "FAILED"
    assert result["reason_code"] == "S2_T15_FAILED_UNPUBLISHED"


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


def test_s2_t13_human_acceptance_is_derived_from_repository_summary(tmp_path: Path) -> None:
    stage2_root = tmp_path / "stage2"
    repository_root = tmp_path / "repository"
    _write_t13_pass(stage2_root, repository_root, human_accepted=True)

    result = _stage2_first_passage_projection(stage2_root, repository_root)

    assert result["status"] == "PASS"
    assert result["human_accepted"] is True
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


def test_s2_t14_missing_and_active_runs_never_pass(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    missing = _stage2_ambiguity_bounds_projection(tmp_path, repository_root)
    assert missing["status"] == "NOT_STARTED"
    assert missing["reason_code"] == "S2_T14_RUN_MISSING"

    run_root, _ = _write_t14_active(tmp_path)
    _write(
        run_root / "reports/btcusdt-completion.json",
        json.dumps(
            {
                "instrument": "BTCUSDT",
                "episode_count": 10,
                "path_rows": 20,
                "classification_count": 600,
                "distribution_count": 1_140,
                "ambiguous_count": 60,
            }
        ),
    )
    active = _stage2_ambiguity_bounds_projection(tmp_path, repository_root)
    assert active["status"] == "IN_PROGRESS"
    assert active["run_id"] == T14_RUN_ID
    assert active["instruments"]["BTCUSDT"]["distribution_count"] == 1_140
    assert active["checks"]["published_completion_present"] is False


def test_s2_t14_pass_requires_bound_source_distributions_verify_and_validation(
    tmp_path: Path,
) -> None:
    stage2_root = tmp_path / "stage2"
    repository_root = tmp_path / "repository"
    _write_t14_pass(stage2_root, repository_root)

    result = _stage2_ambiguity_bounds_projection(stage2_root, repository_root)

    assert result["status"] == "PASS"
    assert result["reason_code"] == "S2_T14_FULL_OUTPUT_VERIFIED_VALIDATION_PASS"
    assert result["total_path_rows"] == 44
    assert result["total_classification_count"] == 1_320
    assert result["total_distribution_count"] == 2_280
    assert result["total_ambiguous_count"] == 132
    assert result["instruments"]["BTCUSDT"]["distribution_count"] == 1_140
    assert result["instruments"]["ETHUSDT"]["classification_count"] == 720
    assert result["source_s2t13_run_id"] == T13_RUN_ID
    assert result["verify_status"] == "PASS"
    assert result["validation_status"] == "PASS"
    assert result["historical_evidence_only"] is True
    assert result["stage3_locked"] is True
    assert result["human_accepted"] is False
    assert all(result["checks"].values())


def test_s2_t14_human_acceptance_is_derived_from_repository_summary(tmp_path: Path) -> None:
    stage2_root = tmp_path / "stage2"
    repository_root = tmp_path / "repository"
    _write_t14_pass(stage2_root, repository_root, human_accepted=True)

    result = _stage2_ambiguity_bounds_projection(stage2_root, repository_root)

    assert result["status"] == "PASS"
    assert result["human_accepted"] is True
    assert all(result["checks"].values())


def test_s2_t14_newest_failure_wins_without_fallback(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    _write_t14_pass(tmp_path, repository_root)
    newer = "stage2-s2t14-ambiguity-bounds-20260721T140501Z-fedcba654321"
    failure = {
        "task_id": "S2-T14",
        "task_version": "1.3",
        "run_id": newer,
        "status": "FAILED_UNPUBLISHED",
        "failure_class": "VALIDATION_ERROR",
        "reason": "newer run failed",
        "resume_allowed": False,
    }
    _write(tmp_path / "runs" / newer / "reports/failure.json", json.dumps(failure))

    result = _stage2_ambiguity_bounds_projection(tmp_path, repository_root)

    assert result["status"] == "FAILED"
    assert result["run_id"] == newer
    assert result["reason"] == "newer run failed"

    malformed_root = tmp_path / "malformed"
    malformed = dict(failure)
    malformed.pop("resume_allowed")
    _write(malformed_root / "runs" / newer / "reports/failure.json", json.dumps(malformed))
    invalid = _stage2_ambiguity_bounds_projection(malformed_root, repository_root)
    assert invalid["status"] == "EVIDENCE_INVALID"
    assert invalid["reason_code"] == "S2_T14_EVIDENCE_INVALID"


def test_s2_t14_tampered_summary_output_and_symlink_fail_closed(tmp_path: Path) -> None:
    stage2_root = tmp_path / "stage2"
    repository_root = tmp_path / "repository"
    _write_t14_pass(stage2_root, repository_root)
    summary_path = repository_root / MODULE.S2T14_SUMMARY_RELATIVE_PATH
    summary = json.loads(summary_path.read_text())
    summary["total_ambiguous_count"] += 1
    _write(summary_path, json.dumps(summary))
    result = _stage2_ambiguity_bounds_projection(stage2_root, repository_root)
    assert result["status"] == "EVIDENCE_INVALID"
    assert result["checks"]["repository_summary_matches"] is False

    clean_root = tmp_path / "clean"
    clean_repository = tmp_path / "clean-repository"
    _write_t14_pass(clean_root, clean_repository)
    output = (
        clean_root
        / "runs"
        / T14_RUN_ID
        / "published/snapshots"
        / ("9" * 64)
        / "BTCUSDT/ambiguity_distributions.json"
    )
    original = output.read_bytes()
    output.write_bytes(b"X" + original[1:])
    tampered = _stage2_ambiguity_bounds_projection(clean_root, clean_repository)
    assert tampered["status"] == "EVIDENCE_INVALID"
    assert tampered["checks"]["btcusdt_complete"] is False

    linked_root = tmp_path / "linked"
    target = tmp_path / "outside-t14"
    target.mkdir()
    run_link = linked_root / "runs" / T14_RUN_ID
    run_link.parent.mkdir(parents=True)
    run_link.symlink_to(target, target_is_directory=True)
    linked = _stage2_ambiguity_bounds_projection(linked_root, repository_root)
    assert linked["status"] == "EVIDENCE_INVALID"


def test_stage2_v13_projection_is_evidence_driven_and_stage3_locked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository_root)
    monkeypatch.setattr(MODULE, "CANONICAL_REPOSITORY_ROOT", repository_root)
    monkeypatch.setattr(MODULE, "_repository_commit", lambda: "abc123")
    monkeypatch.setattr(
        MODULE,
        "_funding_evidence_projection",
        lambda root: {
            "status": "PASS",
            "scope": "SEVEN_DAY_REHEARSAL",
            "total_row_count": 42,
            "difference_count": 0,
            "verify_status": "PASS",
            "full_history_accepted": False,
        },
    )
    monkeypatch.setattr(
        MODULE,
        "load_current_development_state",
        lambda: type(
            "State",
            (),
            {
                "task_status": "IMPLEMENTATION_IN_PROGRESS",
                "current_task": "S2P13-T11",
                "blocking_questions": ("OQ-S2-009",),
                "srp_execution_status": "FRAMEWORK_IMPLEMENTED_FORMAL_OUTPUT_FORBIDDEN",
                "formal_successor_result_exists": False,
                "stage3_locked": True,
                "approved_execution_limit": "S2P13-T16",
            },
        )(),
    )

    result = _stage2_v13_projection(tmp_path / "stage2")

    assert result["status"] == "IN_PROGRESS"
    assert result["repo_root"] == str(repository_root)
    assert result["repo_commit"] == "abc123"
    assert result["tasks"]["S2P13-T11"]["status"] == "IN_PROGRESS"
    assert result["tasks"]["S2P13-T12"]["status"] == "BLOCKED"
    assert result["blocking_questions"] == ["OQ-S2-009"]
    assert result["pending_execution_gates"] == ["FINAL_CODE_7_DAY_REHEARSAL"]
    assert result["execution_gates"]["FINAL_CODE_7_DAY_REHEARSAL"] == "PENDING"
    assert result["stage3_locked"] is True
    assert result["formal_successor_result_exists"] is False
    assert result["price_proxy_source"] == "CONTRACT_PRICE_1S"
    assert result["historical_mark_price_claim"] is False
    assert result["lifecycle_target_contract"] == "DYNAMIC_NET_TICKET_DOUBLE_APPROX_136BP"
    assert result["auxiliary_first_passage_target_bps"] == 20
    assert result["funding_tracks"] == [
        "PRIMARY_HISTORICAL_ACTUAL",
        "STRESS_ADVERSE_1_5X",
        "STRESS_ADVERSE_2X",
        "STRESS_NO_FUNDING_CREDIT",
    ]
    assert result["liquidation_contract"] == "CONTRACT_PRICE_NET_MARGIN_DEPLETION_MINUS_8U"
    assert result["remaining_input_blockers"] == ["HISTORICAL_FUNDING"]
    assert result["funding_evidence"]["status"] == "PASS"
    assert result["funding_evidence"]["scope"] == "SEVEN_DAY_REHEARSAL"

    monkeypatch.setattr(
        MODULE,
        "_funding_evidence_projection",
        lambda root: {
            "status": "PASS",
            "scope": "SEVEN_DAY_REHEARSAL",
            "acceptance_status": "PASS",
            "historical_funding_bound": True,
            "full_history_accepted": True,
        },
    )
    accepted = _stage2_v13_projection(tmp_path / "stage2")
    assert accepted["remaining_input_blockers"] == []

    live_progress = _sealed(
        {
            "schema_name": "stage2-plan-v13-rehearsal-progress-v1",
            "schema_version": "1.0",
            "status": "IN_PROGRESS",
            "code_commit": "abc123",
            "purpose": "FINAL_CODE_RELEASE_GATE",
            "output_root": str(tmp_path / "stage2/rehearsals/final-code/abc123"),
            "start_date": "2020-01-01",
            "end_date_exclusive": "2020-01-08",
            "current_task": "S2P13-T11",
            "completed_task_count": 0,
            "task_count": len(MODULE.V13_TASKS),
            "overall_progress_percent": "4.17",
            "tasks": {
                task: {
                    "status": "IN_PROGRESS" if task == "S2P13-T11" else "NOT_STARTED",
                    "reason_code": ("RUNNING" if task == "S2P13-T11" else "WAITING_FOR_REHEARSAL"),
                    "completed_units": 3 if task == "S2P13-T11" else 0,
                    "total_units": 12 if task == "S2P13-T11" else 0,
                    "progress_percent": "25.00" if task == "S2P13-T11" else "0.00",
                    "row_count": 12 if task == "S2P13-T11" else 0,
                    "verify_status": "NOT_STARTED",
                    "current_instrument": "ETHUSDT" if task == "S2P13-T11" else None,
                    "current_date": "2020-01-03" if task == "S2P13-T11" else None,
                }
                for task in MODULE.V13_TASKS
            },
            "heartbeat_at": "2999-01-01T00:00:00+00:00",
            "stage3_locked": True,
        },
        "checkpoint_hash",
    )
    _write(
        tmp_path
        / "stage2/operations/stage2-plan-v1.3-successor"
        / "seven-day-rehearsal-progress.abc123.json",
        json.dumps(live_progress),
    )
    live = _stage2_v13_projection(tmp_path / "stage2")
    assert live["status"] == "IN_PROGRESS"
    assert live["rehearsal_status"] == "IN_PROGRESS"
    assert live["rehearsal_progress_percent"] == "4.17"
    assert live["current_task"] == "S2P13-T11"
    assert live["tasks"]["S2P13-T11"]["progress_percent"] == "25.00"
    assert live["tasks"]["S2P13-T11"]["current_instrument"] == "ETHUSDT"
    assert live["tasks"]["S2P13-T11"]["current_date"] == "2020-01-03"

    policy_operations = tmp_path / "stage2/formal-operations"
    policy_evidence = tmp_path / "stage2/formal-evidence"
    approval_hash = "d" * 64
    _write(policy_operations / "approvals/approval-formal.json", "{}")
    monkeypatch.setattr(
        MODULE,
        "load_policy",
        lambda *_args, **_kwargs: type(
            "Policy",
            (),
            {
                "policy_hash": "e" * 64,
                "trade_supplement_acceptance_hash": "f" * 64,
                "operations_root": policy_operations,
                "evidence_root": policy_evidence,
            },
        )(),
    )
    monkeypatch.setattr(
        MODULE,
        "validate_approval",
        lambda *_args, **_kwargs: {
            "approval_hash": approval_hash,
            "status": "APPROVED",
            "code_commit": "abc123",
        },
    )
    chain_root = policy_evidence / "chains" / approval_hash
    _write(
        chain_root / "operations/checkpoint.json",
        json.dumps(
            {
                "status": "IN_PROGRESS",
                "current_task": "S2P13-T11",
                "tasks": {
                    task: {
                        "status": "IN_PROGRESS" if task == "S2P13-T11" else "NOT_STARTED",
                        "handoff": None,
                    }
                    for task in MODULE.V13_TASKS
                },
            }
        ),
    )
    formal_task_checkpoint = _sealed(
        {
            "schema_name": "stage2-plan-v13-producer-checkpoint-v2",
            "status": "IN_PROGRESS",
            "reason_code": "PRODUCER_PROGRESS",
            "task_id": "S2P13-T11",
            "execution_mode": "FORMAL",
            "attempt": 1,
            "code_commit": "abc123",
            "adapter_plan_hash": "1" * 64,
            "execution_scope_hash": "2" * 64,
            "completed_units": 20,
            "total_units": 80,
            "progress_percent": "25.00",
            "row_count": 80,
            "current_instrument": "BTCUSDT",
            "current_date": "2020-01-05",
            "phase": "LIFECYCLE",
            "heartbeat_at": "2999-01-02T00:00:00+00:00",
            "progress_log_path": str(chain_root / "tasks/S2P13-T11/daily-progress.jsonl"),
            "progress_sequence": 5,
        },
        "checkpoint_hash",
    )
    _write(
        chain_root / "tasks/S2P13-T11/checkpoint.json",
        json.dumps(formal_task_checkpoint),
    )
    formal = _stage2_v13_projection(tmp_path / "stage2")
    assert formal["formal_chain_status"] == "IN_PROGRESS"
    assert formal["formal_progress_percent"] == 4.17
    assert formal["formal_heartbeat_at"] == "2999-01-02T00:00:00+00:00"
    assert formal["tasks"]["S2P13-T11"]["progress_percent"] == "25.00"
    assert formal["tasks"]["S2P13-T11"]["phase"] == "LIFECYCLE"
    (policy_operations / "approvals/approval-formal.json").unlink()

    rehearsal_report_path = (
        tmp_path / "stage2/rehearsals/final-code/seven-day-rehearsal-report.json"
    )
    rehearsal_report = _sealed(
        {
            "status": "PASS",
            "code_commit": "abc123",
            "lifecycle": [
                {
                    "funding_tracks": [
                        {
                            "continue_holding": {
                                "terminal_state": "RIGHT_CENSORED",
                                "exit_reason": None,
                            }
                        }
                    ]
                }
            ],
            "conditional_baseline_probe": [{"instrument": "BTCUSDT", "match_level": "L3"}],
            "handoffs": [
                {
                    "task_id": task,
                    "row_count": index,
                    "output_hash": str(index) * 64,
                    "verify_status": "PASS",
                }
                for index, task in enumerate(MODULE.V13_TASKS, start=1)
            ],
        },
        "report_hash",
    )
    _write(rehearsal_report_path, json.dumps(rehearsal_report))
    receipt = _sealed(
        {
            "schema_name": "stage2-plan-v13-seven-day-rehearsal-v1",
            "status": "PASS",
            "tasks": list(MODULE.V13_TASKS),
            "code_commit": "abc123",
            "day_count": 7,
            "report_path": str(rehearsal_report_path),
            "report_hash": rehearsal_report["report_hash"],
            "producer_serialization": "PASS",
            "strict_consumer_readback": "PASS",
            "reconciliation": "PASS",
            "verify": "PASS",
            "ui_projection": "PASS",
        },
        "receipt_hash",
    )
    _write(
        tmp_path
        / "stage2/operations/stage2-plan-v1.3-successor"
        / "seven-day-rehearsal-receipt.abc123.json",
        json.dumps(receipt),
    )
    rehearsed = _stage2_v13_projection(tmp_path / "stage2")
    assert rehearsed["rehearsal_status"] == "PASS"
    assert rehearsed["execution_gates"]["FINAL_CODE_7_DAY_REHEARSAL"] == "PASS"
    assert rehearsed["pending_execution_gates"] == []
    assert rehearsed["status"] == "REHEARSAL_PASS_AWAITING_FORMAL_APPROVAL"
    assert rehearsed["rehearsal_report_valid"] is True
    assert rehearsed["right_censored_count"] == 1
    assert rehearsed["rehearsal_t16_match_levels"] == {"BTCUSDT": "L3"}
    assert rehearsed["price_proxy_source"] == "CONTRACT_PRICE_1S"
    assert rehearsed["tasks"]["S2P13-T14"]["row_count"] == 4
    assert rehearsed["tasks"]["S2P13-T14"]["verify_status"] == "PASS"
    assert all(
        task["reason_code"] == "SEVEN_DAY_REHEARSAL_PASS_NOT_FORMAL"
        for task in rehearsed["tasks"].values()
    )

    receipt["code_commit"] = "wrong"
    receipt["receipt_hash"] = _json_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    _write(
        tmp_path
        / "stage2/operations/stage2-plan-v1.3-successor"
        / "seven-day-rehearsal-receipt.abc123.json",
        json.dumps(receipt),
    )
    (
        tmp_path
        / "stage2/operations/stage2-plan-v1.3-successor"
        / "seven-day-rehearsal-progress.abc123.json"
    ).unlink()
    drifted = _stage2_v13_projection(tmp_path / "stage2")
    assert drifted["rehearsal_status"] == "NOT_STARTED"
    assert drifted["execution_gates"]["FINAL_CODE_7_DAY_REHEARSAL"] == "PENDING"


def test_stage2_v13_projection_rejects_stale_server(
    tmp_path: Path,
    monkeypatch,
) -> None:
    served_root = tmp_path / "old-worktree"
    canonical_root = tmp_path / "canonical"
    served_root.mkdir()
    canonical_root.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", served_root)
    monkeypatch.setattr(MODULE, "CANONICAL_REPOSITORY_ROOT", canonical_root)
    monkeypatch.setattr(MODULE, "_repository_commit", lambda: "stale123")

    result = _stage2_v13_projection(tmp_path / "stage2")

    assert result["status"] == "STALE_SERVER"
    assert result["reason_code"] == "S2_V13_STALE_SERVER"
    assert result["server_stale"] is True
