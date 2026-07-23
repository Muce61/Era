from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.rerun.producer_contracts import (
    ExecutionScope,
    ProducerContext,
)
from era100x.research.stage_2.rerun.producer_execution import (
    execute_producer,
    verify_producer,
)


def _context(tmp_path: Path) -> ProducerContext:
    task_root = tmp_path / "S2P13-T11"
    task_root.mkdir()
    preregistration = tmp_path / "preregistration.md"
    preregistration.write_text("frozen", encoding="utf-8")
    return ProducerContext(
        task_id="S2P13-T11",
        execution_mode="REHEARSAL",
        code_commit="a" * 40,
        adapter_plan_hash="b" * 64,
        receipt_path=task_root / "receipt.json",
        checkpoint_path=task_root / "checkpoint.json",
        scope=ExecutionScope.seal(
            mode="SEVEN_DAY",
            start_date="2020-01-01",
            end_date_exclusive="2020-01-08",
        ),
        upstream={},
        preregistration_path=preregistration,
        preregistration_hash="c" * 64,
    )


def test_execute_serializes_reads_back_and_reuses_verified_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(
        "era100x.research.stage_2.rerun.producer_execution._producer_payload",
        lambda _context, _data_root: {"task_id": "S2P13-T11", "row_count": 3},
    )
    receipt = execute_producer(context)
    assert receipt["execution_mode"] == "REHEARSAL"
    assert receipt["run_id"] is None
    assert receipt["row_count"] == 3
    assert json.loads(context.checkpoint_path.read_text())["status"] == "PASS"
    assert execute_producer(context) == receipt


def test_verify_rejects_output_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(
        "era100x.research.stage_2.rerun.producer_execution._producer_payload",
        lambda _context, _data_root: {"task_id": "S2P13-T11", "row_count": 3},
    )
    receipt = execute_producer(context)
    output = Path(str(receipt["artifact_root"])) / "output.json"
    output.write_text('{"row_count":4}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="read-back"):
        verify_producer(context)
