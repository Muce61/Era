from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from era100x.research.stage_2.rerun.producer_contracts import (
    ExecutionScope,
    ProducerContext,
)
from era100x.research.stage_2.rerun.producer_execution import (
    _require_formal_gate,
    execute_producer,
    verify_producer,
)
from era100x.research.stage_2.lifecycle import (
    FundingTrack,
    LifecyclePairResult,
    LifecyclePolicyResult,
    OptionalExitModelStatus,
    SourceCoverage,
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
        repository_root=tmp_path,
    )


def test_execute_serializes_reads_back_and_reuses_verified_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(
        "era100x.research.stage_2.rerun.producer_execution._producer_payload",
        lambda _context, _data_root, **_kwargs: {
            "task_id": "S2P13-T11",
            "row_count": 3,
        },
    )
    receipt = execute_producer(context)
    assert receipt["execution_mode"] == "REHEARSAL"
    assert receipt["run_id"] is None
    assert receipt["row_count"] == 3
    checkpoint = json.loads(context.checkpoint_path.read_text())
    assert checkpoint["status"] == "PASS"
    assert checkpoint["schema_name"] == "stage2-plan-v13-producer-checkpoint-v2"
    assert checkpoint["progress_percent"] == "100.00"
    assert checkpoint["started_at"]
    assert checkpoint["completed_at"]
    events = [
        json.loads(line)
        for line in context.checkpoint_path.with_name("daily-progress.jsonl")
        .read_text()
        .splitlines()
    ]
    assert [event["event_type"] for event in events] == [
        "TASK_STARTED",
        "TASK_COMPLETED",
    ]
    assert execute_producer(context) == receipt


def test_verify_rejects_output_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(
        "era100x.research.stage_2.rerun.producer_execution._producer_payload",
        lambda _context, _data_root, **_kwargs: {
            "task_id": "S2P13-T11",
            "row_count": 3,
        },
    )
    receipt = execute_producer(context)
    output = Path(str(receipt["artifact_root"])) / "output.json"
    output.write_text('{"row_count":4}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="read-back"):
        verify_producer(context)


def test_execute_serializes_real_lifecycle_decimal_enum_and_dataclass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    policy = LifecyclePolicyResult(
        policy_id="CONTINUE_TO_THEORETICAL_FULLY_FLAT",
        terminal_state="RIGHT_CENSORED",
        exit_reason=None,
        censor_reason=None,
        decision_ts_ns=None,
        scenario_net_pnl=Decimal("0.400000000000000000"),
        terminal_ticket_equity=Decimal("10.400000000000000000"),
        ticket_doubled=False,
        reserve_breached=False,
        remaining_proxy_quantity=Decimal("0"),
    )
    pair = LifecyclePairResult(
        market_episode_id="episode-1",
        instrument="BTCUSDT",
        eligible_at_primary_landmark=True,
        activated_before_landmark=False,
        landmark_net_exitable_pnl=Decimal("0.400000000000000000"),
        immediate_exit=replace(policy, policy_id="IMMEDIATE_EXIT_AT_8M"),
        continue_holding=policy,
        source_coverage=SourceCoverage.COMPLETE,
        funding_track=FundingTrack.PRIMARY_HISTORICAL_ACTUAL,
        price_proxy_source="CONTRACT_PRICE_1S",
        protection_exit_model=OptionalExitModelStatus.NOT_MODELLED_STAGE2,
        structure_exit_model=OptionalExitModelStatus.NOT_MODELLED_STAGE2,
        historical_mark_price_claim=False,
        output_hash="d" * 64,
    )
    monkeypatch.setattr(
        "era100x.research.stage_2.rerun.producer_execution._producer_payload",
        lambda _context, _data_root, **_kwargs: {
            "task_id": "S2P13-T11",
            "entry_reference_price": Decimal("42000.100000000000000000"),
            "funding_tracks": [pair],
            "row_count": 1,
        },
    )

    receipt = execute_producer(context)
    output = json.loads((Path(str(receipt["artifact_root"])) / "output.json").read_text())

    assert output["entry_reference_price"] == "42000.100000000000000000"
    assert output["funding_tracks"][0]["landmark_net_exitable_pnl"] == "0.400000000000000000"
    assert output["funding_tracks"][0]["source_coverage"] == "COMPLETE"
    assert output["funding_tracks"][0]["continue_holding"]["scenario_net_pnl"] == (
        "0.400000000000000000"
    )
    assert receipt["verify_status"] == "PASS"


@pytest.mark.parametrize(
    ("task_id", "task_payload"),
    [
        (
            "S2P13-T12",
            {
                "reports": [{"instrument": "BTCUSDT", "episode_count": 12}],
                "file_count": 5,
            },
        ),
        (
            "S2P13-T13",
            {
                "reports": [{"instrument": "BTCUSDT", "episode_count": 12}],
                "file_count": 2,
            },
        ),
        (
            "S2P13-T14",
            {
                "reports": [{"instrument": "BTCUSDT", "episode_count": 12}],
                "file_count": 2,
            },
        ),
        (
            "S2P13-T15",
            {
                "reports": [{"instrument": "BTCUSDT", "path_rows": 12}],
                "classification_count": 360,
            },
        ),
        (
            "S2P13-T16",
            {
                "authority_hash": "a" * 64,
                "binning_set_hash": "b" * 64,
                "bin_source_roles": ["TRAIN"],
            },
        ),
    ],
)
def test_t12_to_t16_producer_envelopes_strictly_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task_id: str,
    task_payload: dict[str, object],
) -> None:
    context = replace(_context(tmp_path), task_id=task_id)
    task_payload = {**task_payload, "task_id": task_id, "row_count": 12}
    monkeypatch.setattr(
        "era100x.research.stage_2.rerun.producer_execution._producer_payload",
        lambda _context, _data_root, **_kwargs: task_payload,
    )

    receipt = execute_producer(context)

    assert receipt["task_id"] == task_id
    assert verify_producer(context) == receipt


def test_progress_checkpoint_and_log_record_completed_utc_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)

    def payload(_context: object, _data_root: Path, **kwargs: object) -> dict[str, object]:
        callback = kwargs["progress_callback"]
        assert callable(callback)
        callback(
            {
                "completed_units": 1,
                "total_units": 3,
                "row_count": 4,
                "current_instrument": "BTCUSDT",
                "current_date": "2020-01-01",
            }
        )
        callback(
            {
                "completed_units": 2,
                "total_units": 3,
                "row_count": 8,
                "current_instrument": "BTCUSDT",
                "current_date": "2020-01-02",
            }
        )
        callback(
            {
                "completed_units": 3,
                "total_units": 3,
                "row_count": 12,
                "current_instrument": "BTCUSDT",
                "current_date": "2020-01-02",
            }
        )
        return {"task_id": "S2P13-T11", "row_count": 12}

    monkeypatch.setattr(
        "era100x.research.stage_2.rerun.producer_execution._producer_payload", payload
    )
    execute_producer(context)
    events = [
        json.loads(line)
        for line in context.checkpoint_path.with_name("daily-progress.jsonl")
        .read_text()
        .splitlines()
    ]
    daily = [event for event in events if event["event_type"] == "UTC_DAY_COMPLETED"]
    assert [(event["current_date"], event["completed_units"]) for event in daily] == [
        ("2020-01-01", 1),
        ("2020-01-02", 3),
    ]
    assert json.loads(context.checkpoint_path.read_text())["row_count"] == 12


def test_failed_producer_leaves_failed_progress_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)

    def fail(_context: object, _data_root: Path, **_kwargs: object) -> dict[str, object]:
        raise ValueError("source hash drift")

    monkeypatch.setattr("era100x.research.stage_2.rerun.producer_execution._producer_payload", fail)
    with pytest.raises(ValueError, match="source hash drift"):
        execute_producer(context)
    checkpoint = json.loads(context.checkpoint_path.read_text())
    assert checkpoint["status"] == "FAILED"
    assert checkpoint["failure_reason"] == "ValueError: source hash drift"
    assert checkpoint["started_at"]
    assert checkpoint["completed_at"]


def test_final_serialization_failure_updates_task_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(
        "era100x.research.stage_2.rerun.producer_execution._producer_payload",
        lambda _context, _data_root, **_kwargs: {
            "task_id": "S2P13-T11",
            "forbidden_binary_float": 0.4,
            "row_count": 1,
        },
    )

    with pytest.raises(TypeError, match="binary floats"):
        execute_producer(context)

    checkpoint = json.loads(context.checkpoint_path.read_text())
    assert checkpoint["status"] == "FAILED"
    assert checkpoint["failure_reason"] == ("TypeError: binary floats are forbidden in strict JSON")


def test_lightweight_formal_gate_rejects_partial_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = replace(_context(tmp_path), execution_mode="FORMAL")
    monkeypatch.setenv("ERA_S2P13_POLICY_PATH", str(tmp_path / "policy.json"))
    monkeypatch.delenv("ERA_S2P13_CHAIN_AUTHORITY_PATH", raising=False)
    with pytest.raises(ValueError, match="partially bound"):
        _require_formal_gate(context, resume=False)
