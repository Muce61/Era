from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from era100x.research.stage_2.acceptance.canonical_json import read_canonical_json
from era100x.research.stage_2.lifecycle import solo_inputs, solo_runtime
from era100x.research.stage_2.lifecycle.solo_governance import (
    TASK_DAG,
    TASK_ORDER,
    SoloRuntimePolicy,
)
from era100x.research.stage_2.lifecycle.solo_inputs import (
    REQUIRED_INPUT_BINDINGS,
    InputsLock,
    load_inputs_lock,
    write_inputs_lock,
)
from era100x.research.stage_2.lifecycle.solo_runtime import (
    RetryableTaskInterruption,
    TaskExecutionContext,
    execute_run,
    freeze_authority,
)

COMMIT = "a" * 40


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _source_audit() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_name": "stage2-lifecycle-source-audit",
        "schema_version": "1.0",
        "status": "PASS",
        "scope_start_date": "2020-01-01",
        "scope_end_date_exclusive": "2026-07-04",
        "contract_price_source_family": "BINANCE_USDM_AGGTRADES_DERIVED_1S_OHLC",
        "canonical_trade_source_family": "BINANCE_USDM_TRADES_ARCHIVES",
        "source_relationship": "DISTINCT_BINANCE_ARCHIVE_FAMILIES",
        "information_status": "SAME_SECOND_RANGE_BOUND_ADDITIONAL_ASSURANCE",
        "contract_price_root": "/fixture/contract",
        "canonical_trade_root": "/fixture/trades",
        "provenance_script_path": "/fixture/source.py",
        "provenance_script_sha256": "1" * 64,
        "source_checkpoint_path": "/fixture/checkpoint.json",
        "source_checkpoint_sha256": "2" * 64,
        "audits": [
            {
                "instrument": instrument,
                "trade_gap_count": 1,
                "trade_gap_second_count": 1,
                "contract_price_gap_seconds_covered": 1,
                "contract_price_zero_volume_gap_seconds": 0,
                "contract_price_duplicate_seconds": 0,
                "contract_price_extreme_beyond_visible_trades_count": 0,
            }
            for instrument in ("BTCUSDT", "ETHUSDT")
        ],
        "forward_filled_seconds_forbidden": True,
        "historical_execution_claim": False,
    }
    payload["audit_hash"] = solo_inputs.canonical_content_hash(payload)
    return payload


def _inputs_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> InputsLock:
    monkeypatch.setattr(solo_inputs, "EXPECTED_PARTITION_COUNT", 2)
    monkeypatch.setattr(
        solo_inputs,
        "EXPECTED_PARTITION_KEYS",
        frozenset(
            {
                ("BTCUSDT", "2020-01-01"),
                ("ETHUSDT", "2020-01-01"),
            }
        ),
    )
    sources = tmp_path / "sources"
    sources.mkdir()
    entries: dict[str, tuple[Path, str]] = {}
    for role in REQUIRED_INPUT_BINDINGS:
        path = sources / f"{role}.json"
        path.write_text(json.dumps({"role": role}) + "\n", encoding="utf-8")
        entries[role] = (path.resolve(), _hash(role))
    partitions: list[dict[str, Any]] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        path = sources / f"{instrument}_1s_20200101.parquet"
        path.write_bytes(instrument.encode())
        partitions.append(
            {
                "instrument": instrument,
                "date": "2020-01-01",
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
                "row_count": 1,
            }
        )
    path = write_inputs_lock(
        inputs_root=(tmp_path / "evidence/inputs").resolve(),
        entries=entries,
        source_audit=_source_audit(),
        contract_price_partitions=partitions,
    )
    return load_inputs_lock(path)


def _policy(tmp_path: Path) -> SoloRuntimePolicy:
    return SoloRuntimePolicy(
        path=tmp_path / "policy.json",
        payload={
            "preregistration_path": ("configs/research/stage_2/s2p19_t11_t20_solo_runtime_v1.json"),
            "task_dag": {task: list(dependencies) for task, dependencies in TASK_DAG.items()},
        },
        policy_hash="b" * 64,
        preregistration_hash="c" * 64,
        contract_bundle_hash="d" * 64,
        contract_hashes={},
    )


def _authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SoloRuntimePolicy, Path, Path]:
    monkeypatch.setattr(solo_runtime, "repository_clean", lambda _root: True)
    monkeypatch.setattr(solo_runtime, "repository_commit", lambda _root: COMMIT)
    inputs_lock = _inputs_lock(tmp_path, monkeypatch)
    policy = _policy(tmp_path)
    evidence_root = tmp_path / "evidence"
    authority = freeze_authority(
        policy=policy,
        inputs_lock=inputs_lock,
        repository_root=tmp_path,
        evidence_root=evidence_root,
        approved_by="Muce",
        approval_source="fixture approval",
        approved_commit=COMMIT,
        approved_inputs_lock_hash=inputs_lock.inputs_lock_hash,
        approved_at="2026-07-29T00:00:00+00:00",
    )
    return policy, authority, evidence_root


def _handlers(
    *,
    interrupt_once: str | None = None,
    fail: str | None = None,
) -> dict[str, Any]:
    def handler(ctx: TaskExecutionContext) -> dict[str, Any]:
        ctx.progress(
            {
                "status": "IN_PROGRESS",
                "phase": ctx.task_id,
                "subphase": "FIXTURE",
                "processed_units": 1,
                "total_units": 1,
                "throughput": "1",
                "eta_seconds": "0",
                "heartbeat_at": "2026-07-29T00:00:00+00:00",
                "verify_state": "PENDING",
            }
        )
        if ctx.task_id == fail:
            raise ValueError("fixture terminal failure")
        if ctx.task_id == interrupt_once and ctx.attempt == 1:
            raise RetryableTaskInterruption("fixture interruption")
        return {
            "row_count": 1,
            "metrics": {"fixture": 1},
            "research_status": (
                "STAGE2_NO_GO_CURRENT_EVIDENCE"
                if ctx.task_id == "S2P19-T20"
                else "FIXTURE_COMPLETE"
            ),
            **(
                {"research_decision": "STAGE2_NO_GO_CURRENT_EVIDENCE"}
                if ctx.task_id == "S2P19-T20"
                else {}
            ),
        }

    return {task: handler for task in TASK_ORDER}


def test_inputs_lock_rejects_symlink_and_hash_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = _inputs_lock(tmp_path, monkeypatch)
    linked = tmp_path / "linked.lock.json"
    linked.symlink_to(lock.path)
    with pytest.raises(ValueError, match="absolute regular non-symlink"):
        load_inputs_lock(linked.resolve().parent / linked.name)

    target = next(iter(lock.bindings.values())).path
    target.write_text("drift\n", encoding="utf-8")
    with pytest.raises(ValueError, match="input Hash drift"):
        load_inputs_lock(lock.path)


def test_fake_ten_task_chain_publishes_without_task_governance_bundles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy, authority, evidence_root = _authority(tmp_path, monkeypatch)
    published = execute_run(
        policy=policy,
        authority_path=authority,
        repository_root=tmp_path,
        evidence_root=evidence_root,
        handlers=_handlers(),
    )

    assert published.parent.name == "published"
    verify = read_canonical_json(published / "final/final-verify.json")
    assert verify["status"] == "PASS"
    assert verify["task_count"] == 10
    manifest = read_canonical_json(published / "final/final-manifest.json")
    assert len(manifest["task_results"]) == 10
    assert manifest["stage3_locked"] is True
    assert {
        "experiment_id",
        "primary_hypothesis",
        "frozen_data_ranges",
        "all_parameter_values_attempted",
        "code_commit",
        "inputs_lock_hash",
        "authority_hash",
        "all_attempts",
        "output_files",
        "result",
    }.issubset(manifest)
    assert not tuple(published.rglob("receipt.json"))
    assert not tuple(published.rglob("task-verify.json"))
    assert not tuple(published.rglob("catalog.json"))
    task_output = read_canonical_json(published / "tasks/S2P19-T11/attempt-0001/output.json")
    assert not Path(str(task_output["artifact_attempt_root"])).is_absolute()
    assert (published / str(task_output["artifact_attempt_root"])).is_dir()


def test_authority_is_idempotent_before_run_and_rejects_wrong_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(solo_runtime, "repository_clean", lambda _root: True)
    monkeypatch.setattr(solo_runtime, "repository_commit", lambda _root: COMMIT)
    inputs_lock = _inputs_lock(tmp_path, monkeypatch)
    policy = _policy(tmp_path)
    evidence_root = tmp_path / "evidence"
    kwargs = {
        "policy": policy,
        "inputs_lock": inputs_lock,
        "repository_root": tmp_path,
        "evidence_root": evidence_root,
        "approved_by": "Muce",
        "approval_source": "fixture approval",
        "approved_commit": COMMIT,
        "approved_inputs_lock_hash": inputs_lock.inputs_lock_hash,
        "approved_at": "2026-07-29T00:00:00+00:00",
    }
    monkeypatch.setattr(solo_runtime, "repository_clean", lambda _root: False)
    with pytest.raises(ValueError, match="clean repository"):
        freeze_authority(**kwargs)
    monkeypatch.setattr(solo_runtime, "repository_clean", lambda _root: True)
    first = freeze_authority(**kwargs)
    second = freeze_authority(**kwargs)
    assert first == second
    assert len(tuple((evidence_root / "authorities").glob("*.json"))) == 1

    with pytest.raises(ValueError, match="approved commit"):
        freeze_authority(**{**kwargs, "approved_commit": "f" * 40})
    with pytest.raises(ValueError, match="approved inputs lock"):
        freeze_authority(**{**kwargs, "approved_inputs_lock_hash": "0" * 64})
    execute_run(
        policy=policy,
        authority_path=first,
        repository_root=tmp_path,
        evidence_root=evidence_root,
        handlers=_handlers(),
    )
    with pytest.raises(ValueError, match="at most one Run"):
        freeze_authority(**kwargs)


def test_inputs_lock_requires_exact_partition_coverage_and_hash_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = _inputs_lock(tmp_path, monkeypatch)
    payload = read_canonical_json(lock.path)
    payload["contract_price_partitions"].pop()
    payload["inputs_lock_hash"] = solo_inputs.canonical_content_hash(
        {key: value for key, value in payload.items() if key != "inputs_lock_hash"}
    )
    invalid = lock.path.parent / f"inputs-{payload['inputs_lock_hash']}.lock.json"
    invalid.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="partition coverage drift"):
        load_inputs_lock(invalid)

    renamed = lock.path.parent / f"inputs-{'0' * 64}.lock.json"
    renamed.write_bytes(lock.path.read_bytes())
    with pytest.raises(ValueError, match="identity or self Hash drift"):
        load_inputs_lock(renamed)


def test_interrupted_task_resumes_in_new_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy, authority, evidence_root = _authority(tmp_path, monkeypatch)
    with pytest.raises(RetryableTaskInterruption):
        execute_run(
            policy=policy,
            authority_path=authority,
            repository_root=tmp_path,
            evidence_root=evidence_root,
            handlers=_handlers(interrupt_once="S2P19-T14"),
        )
    run_root = next((evidence_root / "runs").iterdir())
    published = execute_run(
        policy=policy,
        authority_path=authority,
        repository_root=tmp_path,
        evidence_root=evidence_root,
        handlers=_handlers(interrupt_once="S2P19-T14"),
        resume_run_root=run_root,
    )

    events = [
        json.loads(line)
        for line in (published / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    t14_attempts = [
        event["attempt"]
        for event in events
        if event["event_type"] == "TASK_STARTED" and event["task_id"] == "S2P19-T14"
    ]
    assert t14_attempts == [1, 2]
    assert (published / "tasks/S2P19-T14/attempt-0001").is_dir()
    assert (published / "tasks/S2P19-T14/attempt-0002").is_dir()


def test_terminal_failure_moves_run_to_failed_and_cannot_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy, authority, evidence_root = _authority(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="fixture terminal failure"):
        execute_run(
            policy=policy,
            authority_path=authority,
            repository_root=tmp_path,
            evidence_root=evidence_root,
            handlers=_handlers(fail="S2P19-T14"),
        )
    failed = next((evidence_root / "failed").iterdir())
    events = [
        json.loads(line)
        for line in (failed / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event_type"] == "RUN_FAILED"
    with pytest.raises(ValueError, match="active runs"):
        execute_run(
            policy=policy,
            authority_path=authority,
            repository_root=tmp_path,
            evidence_root=evidence_root,
            handlers=_handlers(),
            resume_run_root=failed,
        )


def test_output_hash_drift_on_resume_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy, authority, evidence_root = _authority(tmp_path, monkeypatch)
    with pytest.raises(RetryableTaskInterruption):
        execute_run(
            policy=policy,
            authority_path=authority,
            repository_root=tmp_path,
            evidence_root=evidence_root,
            handlers=_handlers(interrupt_once="S2P19-T13"),
        )
    run_root = next((evidence_root / "runs").iterdir())
    output = run_root / "tasks/S2P19-T11/attempt-0001/output.json"
    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="output Hash drift"):
        execute_run(
            policy=policy,
            authority_path=authority,
            repository_root=tmp_path,
            evidence_root=evidence_root,
            handlers=_handlers(interrupt_once="S2P19-T13"),
            resume_run_root=run_root,
        )
    assert next((evidence_root / "failed").iterdir()).is_dir()


def test_final_verify_failure_never_reaches_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy, authority, evidence_root = _authority(tmp_path, monkeypatch)
    monkeypatch.setattr(
        solo_runtime,
        "verify_candidate",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("fixture verify failure")),
    )
    with pytest.raises(ValueError, match="fixture verify failure"):
        execute_run(
            policy=policy,
            authority_path=authority,
            repository_root=tmp_path,
            evidence_root=evidence_root,
            handlers=_handlers(),
        )
    assert not (evidence_root / "published").exists()
    failed = next((evidence_root / "failed").iterdir())
    verify = read_canonical_json(failed / "final/final-verify.json")
    assert verify["status"] == "FAIL"


def test_fixed_real_handler_registry_has_exact_ten_tasks() -> None:
    from era100x.research.stage_2.lifecycle.solo_tasks import HANDLERS

    assert tuple(HANDLERS) == TASK_ORDER
    assert len(set(HANDLERS.values())) < len(HANDLERS)
