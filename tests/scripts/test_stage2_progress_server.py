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


def _write(path: Path, content: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
