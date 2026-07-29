from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from era100x.research.stage_2.acceptance.canonical_json import (
    read_canonical_json,
    write_canonical_json_exclusive,
)
from era100x.research.stage_2.lifecycle import production
from era100x.research.stage_2.lifecycle.formal_chain import (
    TASK_ORDER,
    load_adapter_plan,
)
from era100x.research.stage_2.lifecycle.input_catalog import (
    REQUIRED_INPUT_BINDINGS,
    load_input_catalog,
    write_input_catalog,
)


def _input_catalog(tmp_path: Path) -> Path:
    sources = tmp_path / "sources"
    sources.mkdir()
    entries: dict[str, tuple[Path, str]] = {}
    for role in REQUIRED_INPUT_BINDINGS:
        path = sources / f"{role}.json"
        path.write_text(json.dumps({"role": role}) + "\n", encoding="utf-8")
        entries[role] = (
            path.resolve(),
            hashlib.sha256(role.encode()).hexdigest(),
        )
    return write_input_catalog(
        path=tmp_path / "input-catalog.json",
        entries=entries,
    )


def test_production_adapter_plan_binds_all_real_task_handlers(
    tmp_path: Path,
) -> None:
    script = tmp_path / "scripts/run_stage2_v18_task.py"
    module = tmp_path / "src/era100x/research/stage_2/lifecycle/production.py"
    formal = tmp_path / "src/era100x/research/stage_2/lifecycle/formal_chain.py"
    inputs = tmp_path / "src/era100x/research/stage_2/lifecycle/input_catalog.py"
    for path in (script, module, formal, inputs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.name}\n", encoding="utf-8")
    payload = production.production_adapter_plan_payload(
        repository_root=tmp_path,
        python_executable="/python",
    )
    plan_path = tmp_path / "adapter-plan.json"
    write_canonical_json_exclusive(plan_path, payload)

    plan = load_adapter_plan(plan_path, repository_root=tmp_path)
    assert tuple(plan.adapters) == TASK_ORDER
    assert tuple(production.HANDLERS) == TASK_ORDER
    assert all(
        adapter.argv[-1] == task_id
        for task_id, adapter in plan.adapters.items()
    )


def test_input_catalog_fails_closed_on_bound_file_drift(tmp_path: Path) -> None:
    path = _input_catalog(tmp_path)
    catalog = load_input_catalog(path)
    target = catalog.bindings["primary_config_hash"].path
    target.write_text('{"drift":true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="input binding drift"):
        load_input_catalog(path)


def test_task_entrypoint_seals_task_local_evidence_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_catalog = load_input_catalog(_input_catalog(tmp_path))
    run_root = tmp_path / "runs/stage2-s2p18-20260729T000000Z-aaaaaaaaaaaa"
    task_root = run_root / "staging/S2P18-T11"
    policy_path = tmp_path / "policy.json"
    adapter_path = tmp_path / "adapter.json"
    authority_path = tmp_path / "authority.json"
    write_canonical_json_exclusive(
        policy_path,
        {
            "preregistration_path": "prereg.json",
            "preregistration_hash": "b" * 64,
        },
    )
    adapter_path.write_text("{}\n", encoding="utf-8")
    authority = {
        "authority_hash": "a" * 64,
        "code_commit": "c" * 40,
        "adapter_plan_hash": "d" * 64,
        "policy_hash": "e" * 64,
        "input_catalog_path": str(input_catalog.path),
        "input_catalog_hash": input_catalog.catalog_hash,
    }
    write_canonical_json_exclusive(authority_path, authority)
    environment = {
        "ERA_S2P18_TASK_ID": "S2P18-T11",
        "ERA_S2P18_RUN_ROOT": str(run_root),
        "ERA_S2P18_TASK_ROOT": str(task_root),
        "ERA_S2P18_AUTHORITY_PATH": str(authority_path),
        "ERA_S2P18_POLICY_PATH": str(policy_path),
        "ERA_S2P18_ADAPTER_PLAN_PATH": str(adapter_path),
        "ERA_S2P18_REPOSITORY_ROOT": str(tmp_path),
        "ERA_S2P18_AUTHORITY_HASH": "a" * 64,
        "ERA_S2P18_ADAPTER_PLAN_HASH": "d" * 64,
        "ERA_S2P18_CODE_COMMIT": "c" * 40,
        "ERA_S2P18_UPSTREAM_RECEIPT_HASHES": "{}",
        "ERA_S2P18_PRODUCER_ATTEMPT": "1",
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setitem(
        production.HANDLERS,
        "S2P18-T11",
        lambda _context: {"row_count": 3, "result": "fixture"},
    )

    receipt_path = production.run_from_environment()
    receipt = read_canonical_json(receipt_path)
    assert receipt["task_id"] == "S2P18-T11"
    assert receipt["row_count"] == 3
    assert receipt["historical_execution_claim"] is False
    attempt = task_root / "attempts/attempt-0001"
    assert read_canonical_json(attempt / "task-verify.json")["status"] == "PASS"
    assert read_canonical_json(attempt / "manifest.json")["stage3_locked"] is True
