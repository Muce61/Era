"""Append-only execution and verification for one successor producer."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, cast
import hashlib

from era100x.foundation.governance import require_operation_allowed

from .orchestrator import canonical_hash, repository_clean
from .producer_contracts import ProducerContext
from .production_adapters import RECEIPT_SCHEMA
from .scoped_producers import (
    produce_scoped_ambiguity,
    produce_scoped_first_passage,
    produce_scoped_metrics,
    produce_scoped_paths,
)
from .strict_json import strict_json_bytes, strict_json_value


def _write_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(strict_json_bytes(value))


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe or missing producer JSON: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("producer JSON root must be an object")
    return cast(dict[str, Any], value)


def _seal(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = canonical_hash(value)
    return result


def _artifact_data_root(context: ProducerContext) -> Path:
    return (
        context.receipt_path.parent
        / "artifacts"
        / (f"{context.execution_mode.lower()}-{context.scope.execution_scope_hash[:12]}")
    )


def _bound_data_root(source_root: Path) -> Path:
    output = _read(source_root / "output.json")
    data_root = Path(str(output.get("artifact_data_root", "")))
    if (
        not data_root.is_absolute()
        or data_root.is_symlink()
        or not data_root.is_dir()
        or not data_root.resolve().is_relative_to(source_root.resolve())
    ):
        raise ValueError("upstream producer data-root binding is unsafe")
    return data_root


ProgressCallback = Callable[[dict[str, Any]], None]


class _FormalProgressReporter:
    """Persist truthful task progress and append one durable record per completed day/unit."""

    def __init__(self, context: ProducerContext, *, attempt: int) -> None:
        self.context = context
        self.attempt = attempt
        self.started_at = datetime.now(UTC).isoformat()
        self.completed_at: str | None = None
        self.log_path = context.checkpoint_path.with_name("daily-progress.jsonl")
        self.sequence = 0
        self.last_checkpoint_write = 0.0
        self.last_update: dict[str, Any] = {}
        self.open_day: tuple[str, str] | None = None
        self.open_day_update: dict[str, Any] | None = None

    def _checkpoint(self, update: dict[str, Any], *, status: str) -> None:
        completed = max(0, int(update.get("completed_units", 0)))
        total = max(0, int(update.get("total_units", 0)))
        percent = (
            (Decimal(completed) * Decimal(100) / Decimal(total)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
            if total
            else Decimal("0.00")
        )
        payload = _seal(
            {
                "schema_name": "stage2-plan-v13-producer-checkpoint-v2",
                "status": status,
                "reason_code": (
                    "PRODUCER_PROGRESS" if status == "IN_PROGRESS" else f"PRODUCER_{status}"
                ),
                "task_id": self.context.task_id,
                "execution_mode": self.context.execution_mode,
                "attempt": self.attempt,
                "code_commit": self.context.code_commit,
                "adapter_plan_hash": self.context.adapter_plan_hash,
                "execution_scope_hash": self.context.scope.execution_scope_hash,
                "completed_units": completed,
                "total_units": total,
                "progress_percent": format(percent, "f"),
                "row_count": int(update.get("row_count", completed)),
                "current_instrument": update.get("current_instrument"),
                "current_date": update.get("current_date"),
                "phase": update.get("phase"),
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "progress_log_path": str(self.log_path),
                "progress_sequence": self.sequence,
                **(
                    {"failure_reason": update["failure_reason"]}
                    if update.get("failure_reason")
                    else {}
                ),
                **({"receipt_hash": update["receipt_hash"]} if update.get("receipt_hash") else {}),
            },
            "checkpoint_hash",
        )
        temporary = self.context.checkpoint_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.context.checkpoint_path)
        self.last_checkpoint_write = time.monotonic()

    def _append(self, update: dict[str, Any], *, event_type: str) -> None:
        self.sequence += 1
        event = _seal(
            {
                "schema_name": "stage2-plan-v13-progress-event-v1",
                "sequence": self.sequence,
                "event_type": event_type,
                "task_id": self.context.task_id,
                "execution_mode": self.context.execution_mode,
                "attempt": self.attempt,
                "code_commit": self.context.code_commit,
                "adapter_plan_hash": self.context.adapter_plan_hash,
                "execution_scope_hash": self.context.scope.execution_scope_hash,
                "recorded_at": datetime.now(UTC).isoformat(),
                **update,
            },
            "event_hash",
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def start(self) -> None:
        update = {
            "completed_units": 0,
            "total_units": 0,
            "row_count": 0,
            "phase": "STARTING",
        }
        self._append(update, event_type="TASK_STARTED")
        self._checkpoint(update, status="IN_PROGRESS")

    def update(self, update: dict[str, Any]) -> None:
        normalized = dict(update)
        current_date = normalized.get("current_date")
        instrument = str(normalized.get("current_instrument") or "")
        day_changed = False
        if current_date:
            day_key = (instrument, str(current_date))
            if self.open_day is not None and day_key != self.open_day:
                assert self.open_day_update is not None
                self._append(self.open_day_update, event_type="UTC_DAY_COMPLETED")
                day_changed = True
            self.open_day = day_key
            self.open_day_update = normalized
        else:
            self._append(normalized, event_type="UNIT_COMPLETED")
        self.last_update = normalized
        if day_changed or time.monotonic() - self.last_checkpoint_write >= 2:
            self._checkpoint(normalized, status="IN_PROGRESS")

    def finish(self, *, row_count: int, receipt_hash: str | None = None) -> None:
        self.completed_at = datetime.now(UTC).isoformat()
        if self.open_day_update is not None:
            self._append(self.open_day_update, event_type="UTC_DAY_COMPLETED")
            self.open_day_update = None
        update = {
            **self.last_update,
            "completed_units": int(self.last_update.get("total_units", 1)),
            "total_units": int(self.last_update.get("total_units", 1)),
            "row_count": row_count,
            "phase": "COMPLETE",
        }
        if receipt_hash is not None:
            update["receipt_hash"] = receipt_hash
        self._append(update, event_type="TASK_COMPLETED")
        self._checkpoint(update, status="PASS")

    def fail(self, reason: str) -> None:
        self.completed_at = datetime.now(UTC).isoformat()
        update = {**self.last_update, "failure_reason": reason, "phase": "FAILED"}
        self._append(update, event_type="TASK_FAILED")
        self._checkpoint(update, status="FAILED")


def _producer_payload(
    context: ProducerContext,
    data_root: Path,
    *,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    start = date.fromisoformat(context.scope.start_date)
    end = date.fromisoformat(context.scope.end_date_exclusive)
    if context.task_id == "S2P13-T11":
        from .seven_day_rehearsal import produce_scoped_lifecycle

        return produce_scoped_lifecycle(
            start_date=start,
            end_date_exclusive=end,
            progress_callback=progress_callback,
        )
    if context.task_id == "S2P13-T12":
        return produce_scoped_paths(
            output_root=data_root,
            start_date=start,
            end_date_exclusive=end,
            progress_callback=progress_callback,
        )
    if context.task_id in {"S2P13-T13", "S2P13-T14"}:
        source = context.upstream["S2P13-T12"]
        source_root = _bound_data_root(source.artifact_root)
        if context.task_id == "S2P13-T13":
            return produce_scoped_metrics(
                output_root=data_root,
                source_paths_root=source_root,
                source_snapshot_id=source.snapshot_id,
                source_manifest_hash=source.manifest_hash,
                source_catalog_hash=source.catalog_hash,
                progress_callback=progress_callback,
            )
        return produce_scoped_first_passage(
            output_root=data_root,
            source_paths_root=source_root,
            source_snapshot_id=source.snapshot_id,
            source_manifest_hash=source.manifest_hash,
            source_catalog_hash=source.catalog_hash,
            progress_callback=progress_callback,
        )
    if context.task_id == "S2P13-T15":
        source = context.upstream["S2P13-T14"]
        source_first_passage_root = _bound_data_root(source.artifact_root)
        result = produce_scoped_ambiguity(
            output_root=data_root,
            source_first_passage_root=source_first_passage_root,
            progress_callback=progress_callback,
        )
        result["source_first_passage_root"] = str(source_first_passage_root)
        return result
    if context.task_id == "S2P13-T16":
        if context.execution_mode == "FORMAL":
            return _produce_formal_t16(context, data_root, progress_callback=progress_callback)
        from .seven_day_rehearsal import produce_scoped_conditional_baseline

        t15_output = _read(context.upstream["S2P13-T15"].artifact_root / "output.json")
        source_root = Path(str(t15_output.get("source_first_passage_root", "")))
        if not source_root.is_absolute() or source_root.is_symlink() or not source_root.is_dir():
            raise ValueError("T16 cannot resolve the current T14 First Passage binding")
        return produce_scoped_conditional_baseline(source_first_passage_root=source_root)
    raise ValueError(f"unsupported successor producer: {context.task_id}")


def _produce_formal_t16(
    context: ProducerContext,
    data_root: Path,
    *,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Freeze dynamic successor Authority/TRAIN bins, then run the real T16 engine."""

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

    from .lightweight_governance import (
        _read_json as read_governance_json,
        _self_hash_valid,
        load_policy,
    )
    from .seven_day_rehearsal import LABEL_CONTRACT_HASH

    chain_path = Path(os.environ.get("ERA_S2P13_CHAIN_AUTHORITY_PATH", ""))
    policy_path = Path(os.environ.get("ERA_S2P13_POLICY_PATH", ""))
    if not chain_path.is_absolute() or not policy_path.is_absolute():
        raise ValueError("formal T16 requires ChainAuthority and Policy bindings")
    chain = read_governance_json(chain_path)
    if (
        not _self_hash_valid(chain, "authority_hash")
        or chain.get("schema_name") != "stage2-chain-authority-v2"
        or chain.get("code_commit") != context.code_commit
    ):
        raise ValueError("formal T16 ChainAuthority drift")
    policy = load_policy(policy_path, repository_root=context.repository_root)
    if chain.get("policy_hash") != policy.policy_hash:
        raise ValueError("formal T16 Policy drift")
    source_t15 = _read(context.upstream["S2P13-T15"].artifact_root / "output.json")
    first_passage_root = Path(str(source_t15.get("source_first_passage_root", "")))
    if (
        not first_passage_root.is_absolute()
        or first_passage_root.is_symlink()
        or not first_passage_root.is_dir()
    ):
        raise ValueError("formal T16 cannot resolve the current T14 row evidence")
    gate_path = context.repository_root / "src/era100x/research/stage_2/gates/price/gate.py"
    context_hash = hashlib.sha256(gate_path.read_bytes()).hexdigest()
    authority = S2P13T16ContractAuthority.seal(
        {
            "code_commit": context.code_commit,
            "chain_authority_hash": chain["authority_hash"],
            "policy_hash": policy.policy_hash,
            "source_t10_binding_hash": T10_SNAPSHOT_ID,
            "source_s2p13_t11_binding_hash": context.upstream["S2P13-T11"].producer_receipt_hash,
            "source_s2p13_t13_binding_hash": context.upstream["S2P13-T13"].producer_receipt_hash,
            "source_s2p13_t15_binding_hash": context.upstream["S2P13-T15"].producer_receipt_hash,
            "context_binding_hash": context_hash,
            "label_contract_hash": LABEL_CONTRACT_HASH,
            "preregistration_hash": context.preregistration_hash,
        }
    )
    authority_path = data_root / f"authority-{authority.authority_hash}.json"
    _write_exclusive(authority_path, authority.model_dump(mode="json"))
    if progress_callback is not None:
        progress_callback(
            {"completed_units": 1, "total_units": 4, "phase": "AUTHORITY", "row_count": 0}
        )
    bins, bins_path = freeze_binning_snapshots(
        authority_path=authority_path,
        bin_root=data_root / "train-bins",
        t10_snapshot=T10_SNAPSHOT,
        t10_snapshot_id=T10_SNAPSHOT_ID,
        current_commit=context.code_commit,
        repository_clean=repository_clean(context.repository_root),
        lightweight_policy_authorized=True,
    )
    if progress_callback is not None:
        progress_callback(
            {"completed_units": 2, "total_units": 4, "phase": "TRAIN_BINS", "row_count": 0}
        )
    runs_root = data_root / "runs"
    runs_root.mkdir()
    manifest, published = run_full_execution(
        authority_path=authority_path,
        binning_set_path=bins_path,
        runs_root=runs_root,
        t10_snapshot=T10_SNAPSHOT,
        t10_snapshot_id=T10_SNAPSHOT_ID,
        t13_snapshot=first_passage_root,
        current_commit=context.code_commit,
        repository_clean=repository_clean(context.repository_root),
        lightweight_policy_authorized=True,
    )
    if progress_callback is not None:
        progress_callback(
            {
                "completed_units": 3,
                "total_units": 4,
                "phase": "CONDITIONAL_BASELINE",
                "row_count": int(manifest.get("source_h2_path_count", 0)),
            }
        )
    verify, _ = verify_published_run(run_root=published.parents[2])
    if verify.get("status") != "PASS":
        raise ValueError("formal T16 independent Verify did not PASS")
    if progress_callback is not None:
        progress_callback(
            {
                "completed_units": 4,
                "total_units": 4,
                "phase": "VERIFY",
                "row_count": int(verify["source_h2_path_count"]),
            }
        )
    return {
        "task_id": "S2P13-T16",
        "authority_hash": authority.authority_hash,
        "binning_set_hash": bins["binning_set_hash"],
        "bin_source_roles": ["TRAIN"],
        "outcome_fields_read_before_matching": [],
        "published_snapshot": str(published),
        "manifest_hash": manifest["manifest_hash"],
        "verify_hash": verify["verify_hash"],
        "row_count": int(verify["source_h2_path_count"]),
        "historical_evidence_only": True,
        "research_result": "DESCRIPTIVE_ONLY_PRIMARY_PENDING_T18",
        "stage3_locked": True,
    }


def _require_formal_gate(context: ProducerContext, *, resume: bool) -> None:
    policy_value = os.environ.get("ERA_S2P13_POLICY_PATH")
    chain_value = os.environ.get("ERA_S2P13_CHAIN_AUTHORITY_PATH")
    if not policy_value and not chain_value:
        require_operation_allowed("RESUME" if resume else "RUN")
        return
    if not policy_value or not chain_value:
        raise ValueError("lightweight formal gate is only partially bound")
    from .lightweight_governance import (
        _read_json as read_governance_json,
        _self_hash_valid,
        load_policy,
    )

    policy = load_policy(Path(policy_value), repository_root=context.repository_root)
    chain = read_governance_json(Path(chain_value))
    supplement_path = os.environ.get("ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_PATH", "")
    supplement_hash = os.environ.get("ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_HASH", "")
    if (
        not _self_hash_valid(chain, "authority_hash")
        or chain.get("schema_name") != "stage2-chain-authority-v2"
        or chain.get("code_commit") != context.code_commit
        or chain.get("policy_hash") != policy.policy_hash
        or chain.get("stage3_locked") is not True
        or chain.get("trade_supplement_acceptance_path") != str(policy.trade_supplement_path)
        or chain.get("trade_supplement_file_hash") != policy.trade_supplement_file_hash
        or chain.get("trade_supplement_acceptance_hash") != policy.trade_supplement_acceptance_hash
        or supplement_path != str(policy.trade_supplement_path)
        or supplement_hash != policy.trade_supplement_file_hash
        or not repository_clean(context.repository_root)
    ):
        raise ValueError("lightweight formal gate binding drift")


def _publish_producer_attempt(
    context: ProducerContext,
    *,
    artifact_root: Path,
    data_root: Path,
    reporter: _FormalProgressReporter,
) -> dict[str, Any]:
    raw_payload = _producer_payload(context, data_root, progress_callback=reporter.update)
    raw_payload["artifact_data_root"] = str(data_root)
    normalized = strict_json_value(raw_payload)
    if not isinstance(normalized, dict):
        raise TypeError("producer payload must normalize to a JSON object")
    payload = cast(dict[str, Any], normalized)
    output_path = artifact_root / "output.json"
    _write_exclusive(output_path, payload)
    output_hash = canonical_hash(payload)
    row_count = int(payload.get("row_count", -1))
    if row_count < 0:
        raise ValueError("producer did not reconcile a primary row count")
    chain_id = f"stage2-s2p13-successor-{context.adapter_plan_hash[:12]}"
    run_id = (
        f"stage2-{context.task_id.lower()}-{context.adapter_plan_hash[:12]}"
        if context.execution_mode == "FORMAL"
        else None
    )
    evidence_id = run_id or f"rehearsal-{context.code_commit[:12]}-{context.task_id.lower()}"
    manifest = _seal(
        {
            "schema_name": "stage2-plan-v13-producer-manifest-v2",
            "stage_plan_version": "1.3",
            "task_id": context.task_id,
            "execution_mode": context.execution_mode,
            "chain_id": chain_id,
            "run_id": run_id,
            "evidence_id": evidence_id,
            "code_commit": context.code_commit,
            "adapter_plan_hash": context.adapter_plan_hash,
            "execution_scope": context.scope.payload(),
            "upstream_handoffs": {name: item.payload() for name, item in context.upstream.items()},
            "preregistration_hash": context.preregistration_hash,
            "output_hash": output_hash,
            "row_count": row_count,
        },
        "manifest_hash",
    )
    manifest_path = artifact_root / "manifest.json"
    _write_exclusive(manifest_path, manifest)
    catalog = _seal(
        {
            "schema_name": "stage2-plan-v13-producer-catalog-v2",
            "task_id": context.task_id,
            "manifest_hash": manifest["manifest_hash"],
            "files": [
                {
                    "relative_path": "output.json",
                    "content_hash": output_hash,
                }
            ],
        },
        "catalog_hash",
    )
    catalog_path = artifact_root / "catalog.json"
    _write_exclusive(catalog_path, catalog)
    receipt = _seal(
        {
            "schema_name": RECEIPT_SCHEMA,
            "status": "PASS",
            "stage_plan_version": "1.3",
            "execution_mode": context.execution_mode,
            "task_id": context.task_id,
            "code_commit": context.code_commit,
            "chain_id": chain_id,
            "run_id": run_id,
            "evidence_id": evidence_id,
            "artifact_root": str(artifact_root),
            "snapshot_id": str(manifest["manifest_hash"]),
            "manifest_path": str(manifest_path),
            "manifest_hash": str(manifest["manifest_hash"]),
            "catalog_path": str(catalog_path),
            "catalog_hash": str(catalog["catalog_hash"]),
            "adapter_plan_hash": context.adapter_plan_hash,
            "upstream_handoffs": {name: item.payload() for name, item in context.upstream.items()},
            "execution_scope": context.scope.payload(),
            "output_hash": output_hash,
            "row_count": row_count,
            "consumer_readback": "PASS",
            "reconciliation": "PASS",
            "verify_status": "PASS",
        },
        "receipt_hash",
    )
    _write_exclusive(context.receipt_path, receipt)
    reporter.finish(row_count=row_count, receipt_hash=str(receipt["receipt_hash"]))
    return verify_producer(context)


def execute_producer(context: ProducerContext, *, resume: bool = False) -> dict[str, Any]:
    """Execute once and publish a strict v2 receipt."""

    context.input_preflight()
    if context.execution_mode == "FORMAL":
        _require_formal_gate(context, resume=resume)
    if context.receipt_path.exists():
        return verify_producer(context)
    artifact_root = _artifact_data_root(context)
    if artifact_root.is_symlink():
        raise ValueError("producer artifact root is a symlink")
    artifact_root.mkdir(parents=True, exist_ok=True)
    checkpoint = _read(context.checkpoint_path) if context.checkpoint_path.exists() else {}
    attempt = int(checkpoint.get("attempt", 0)) + 1
    data_root = artifact_root / f"attempt-{attempt}" / "data"
    if data_root.parent.exists():
        raise ValueError("producer attempt identity already exists")
    data_root.parent.mkdir(parents=True)
    reporter = _FormalProgressReporter(context, attempt=attempt)
    reporter.start()
    try:
        return _publish_producer_attempt(
            context,
            artifact_root=artifact_root,
            data_root=data_root,
            reporter=reporter,
        )
    except BaseException as exc:
        reporter.fail(f"{type(exc).__name__}: {exc}")
        raise


def verify_producer(context: ProducerContext) -> dict[str, Any]:
    """Strictly verify the task receipt and its exact output."""

    receipt = _read(context.receipt_path)
    claimed = receipt.pop("receipt_hash", None)
    if claimed != canonical_hash(receipt):
        raise ValueError("producer receipt hash mismatch")
    receipt["receipt_hash"] = claimed
    if (
        receipt.get("schema_name") != RECEIPT_SCHEMA
        or receipt.get("status") != "PASS"
        or receipt.get("task_id") != context.task_id
        or receipt.get("execution_mode") != context.execution_mode
        or receipt.get("code_commit") != context.code_commit
        or receipt.get("adapter_plan_hash") != context.adapter_plan_hash
        or receipt.get("execution_scope") != context.scope.payload()
        or receipt.get("upstream_handoffs")
        != {name: item.payload() for name, item in context.upstream.items()}
    ):
        raise ValueError("producer receipt binding mismatch")
    artifact_root = Path(str(receipt["artifact_root"]))
    output = _read(artifact_root / "output.json")
    if canonical_hash(output) != receipt.get("output_hash") or int(
        output.get("row_count", -1)
    ) != int(receipt.get("row_count", -2)):
        raise ValueError("producer output read-back or reconciliation mismatch")
    return receipt
