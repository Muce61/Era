#!/usr/bin/env python3
"""Plan v1.10 personal formal runtime: status, prepare, run and resume."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from audit_stage2_lifecycle_source import (
    bound_trade_supplement,
    build_audit,
    collect_contract_price_partitions,
)
from era100x.research.stage_2.acceptance.canonical_json import read_canonical_json
from era100x.research.stage_2.lifecycle.solo_governance import load_policy
from era100x.research.stage_2.lifecycle.production_input_spec import (
    build_production_input_spec,
    load_production_trade_supplement,
    validate_production_inputs_lock,
)
from era100x.research.stage_2.lifecycle.solo_inputs import (
    load_inputs_lock,
    write_inputs_lock,
)
from era100x.research.stage_2.lifecycle.solo_runtime import (
    execute_run,
    freeze_authority,
    repository_clean,
    repository_commit,
    runtime_status,
)
from era100x.research.stage_2.lifecycle.solo_tasks import HANDLERS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "configs/governance/stage2_active_policy_v9.json"
DEFAULT_EVIDENCE_ROOT = Path("/Volumes/FuckingLife/era100x_stage2/formal/stage2-plan-v1.10")
START = date(2020, 1, 1)
END_EXCLUSIVE = date(2026, 7, 4)


def _supplement_binding(source_audit: dict[str, Any]) -> dict[str, str]:
    values = {
        "acceptance_path": str(source_audit.get("trade_supplement_acceptance_path", "")),
        "file_sha256": str(source_audit.get("trade_supplement_file_sha256", "")),
        "acceptance_hash": str(source_audit.get("trade_supplement_acceptance_hash", "")),
    }
    if not all(values.values()):
        raise ValueError("inputs lock Trade supplement binding is incomplete")
    return values


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "prepare", "run", "resume"))
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--inputs-lock", type=Path)
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--approved-by")
    parser.add_argument("--approval-source")
    parser.add_argument("--approved-commit")
    parser.add_argument("--approved-input-lock-hash")
    parser.add_argument("--approved-adoption-bundle-hash")
    return parser


def main() -> int:
    args = _parser().parse_args()
    policy = load_policy(args.policy.resolve(), repository_root=ROOT)
    evidence_root = args.evidence_root.resolve()
    if args.command == "status":
        payload: dict[str, Any] = runtime_status(evidence_root)
        payload.update(
            {
                "commit": repository_commit(ROOT),
                "repository_clean": repository_clean(ROOT),
                "policy_hash": policy.policy_hash,
                "preregistration_hash": policy.preregistration_hash,
                "contract_bundle_hash": policy.contract_bundle_hash,
            }
        )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "prepare":
        if not repository_clean(ROOT):
            raise ValueError("prepare requires a clean implementation commit")
        production_supplement = load_production_trade_supplement(ROOT)
        audit = build_audit(
            start=START,
            end_exclusive=END_EXCLUSIVE,
            trade_supplement_acceptance_path=production_supplement.acceptance_path,
            trade_supplement_file_sha256=production_supplement.file_sha256,
            trade_supplement_acceptance_hash=production_supplement.acceptance_hash,
        )
        if audit.status != "PASS":
            raise ValueError("prepare source audit did not PASS")
        partitions = collect_contract_price_partitions(audit=audit)
        production_spec = build_production_input_spec(
            repository_root=ROOT,
            contract_price_partitions=partitions,
        )
        lock_path = write_inputs_lock(
            inputs_root=evidence_root / "inputs",
            entries=production_spec.entries,
            source_audit=audit.model_dump(mode="json"),
            contract_price_partitions=partitions,
            production_binding_rules_hash=production_spec.rules_hash,
            adopted_task_bindings=production_spec.adoption_bundle.lock_payload(),
            adoption_bundle_hash=production_spec.adoption_bundle.bundle_hash,
        )
        lock = load_inputs_lock(lock_path)
        validate_production_inputs_lock(inputs_lock=lock, repository_root=ROOT)
        print(
            json.dumps(
                {
                    "approval_required": True,
                    "commit": repository_commit(ROOT),
                    "policy_hash": policy.policy_hash,
                    "preregistration_hash": policy.preregistration_hash,
                    "contract_bundle_hash": policy.contract_bundle_hash,
                    "inputs_lock_path": str(lock.path),
                    "inputs_lock_hash": lock.inputs_lock_hash,
                    "adoption_bundle_hash": lock.adoption_bundle_hash,
                    "formal_run_executed": False,
                    "stage3_locked": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "run":
        required = (
            args.inputs_lock,
            args.approved_by,
            args.approval_source,
            args.approved_commit,
            args.approved_input_lock_hash,
            args.approved_adoption_bundle_hash,
        )
        if not all(required):
            raise ValueError(
                "run requires inputs lock, approver, approval source, exact commit "
                "and exact inputs-lock/adoption-bundle Hashes"
            )
        inputs_lock = load_inputs_lock(args.inputs_lock.resolve())
        validate_production_inputs_lock(inputs_lock=inputs_lock, repository_root=ROOT)
        authority_path = freeze_authority(
            policy=policy,
            inputs_lock=inputs_lock,
            repository_root=ROOT,
            evidence_root=evidence_root,
            approved_by=str(args.approved_by),
            approval_source=str(args.approval_source),
            approved_commit=str(args.approved_commit),
            approved_inputs_lock_hash=str(args.approved_input_lock_hash),
            approved_adoption_bundle_hash=str(args.approved_adoption_bundle_hash),
        )
        run_supplement = _supplement_binding(inputs_lock.source_audit)
        with bound_trade_supplement(
            acceptance_path=Path(run_supplement["acceptance_path"]),
            acceptance_file_sha256=run_supplement["file_sha256"],
            acceptance_hash=run_supplement["acceptance_hash"],
        ):
            published = execute_run(
                policy=policy,
                authority_path=authority_path,
                repository_root=ROOT,
                evidence_root=evidence_root,
                handlers=HANDLERS,
            )
        print(published)
        return 0
    if args.authority is None or args.run_root is None:
        raise ValueError("resume requires --authority and --run-root")
    authority = read_canonical_json(args.authority.resolve())
    inputs_lock = load_inputs_lock(Path(str(authority["inputs_lock_path"])))
    validate_production_inputs_lock(inputs_lock=inputs_lock, repository_root=ROOT)
    resume_supplement = _supplement_binding(inputs_lock.source_audit)
    with bound_trade_supplement(
        acceptance_path=Path(resume_supplement["acceptance_path"]),
        acceptance_file_sha256=resume_supplement["file_sha256"],
        acceptance_hash=resume_supplement["acceptance_hash"],
    ):
        published = execute_run(
            policy=policy,
            authority_path=args.authority.resolve(),
            repository_root=ROOT,
            evidence_root=evidence_root,
            handlers=HANDLERS,
            resume_run_root=args.run_root.resolve(),
        )
    print(published)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
