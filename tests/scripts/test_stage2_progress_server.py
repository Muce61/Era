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
    _write(tmp_path / "reports/v2-publication-record.json")
    _write(tmp_path / "reports/v2-run-a-comparison.json")

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
    assert result["comparison_report_present"] is True
