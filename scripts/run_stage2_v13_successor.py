#!/usr/bin/env python3
"""Inspect or execute the approved Plan v1.3 successor production chain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from era100x.foundation.governance import load_current_development_state
from era100x.research.stage_2.rerun.orchestrator import (
    TASKS,
    SuccessorSupervisor,
    approval_readiness,
    current_commit,
)
from era100x.research.stage_2.rerun.production_adapters import (
    ProductionAdapterPlan,
    build_production_adapters,
    load_adapter_plan,
)


def _read_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe or missing formal evidence: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("formal evidence root must be an object")
    return value


def _require_plan_binding(*, approval_path: Path, plan: ProductionAdapterPlan) -> None:
    approval = _read_json(approval_path)
    if approval.get("adapter_plan_hash") != plan.plan_hash or approval.get(
        "adapter_plan_path"
    ) != str(plan.path):
        raise ValueError("formal approval does not bind the exact production adapter plan")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "preflight", "run", "resume"))
    parser.add_argument("--rehearsal", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--adapter-plan", type=Path)
    parser.add_argument("--operations-root", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    state = load_current_development_state()
    if args.mode == "inspect":
        result = approval_readiness(
            state=state,
            rehearsal_path=args.rehearsal,
            repository_root=args.repository_root,
        )
        if args.adapter_plan is not None:
            try:
                plan = load_adapter_plan(
                    args.adapter_plan,
                    code_commit=current_commit(args.repository_root),
                )
                result["adapter_plan_status"] = "VALID"
                result["adapter_plan_hash"] = plan.plan_hash
            except (OSError, ValueError) as exc:
                result["adapter_plan_status"] = "INVALID"
                result["adapter_plan_reason"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "READY" else 2
    if args.approval is None or args.adapter_plan is None or args.operations_root is None:
        raise SystemExit(f"{args.mode} requires --approval, --adapter-plan and --operations-root")
    plan = load_adapter_plan(
        args.adapter_plan,
        code_commit=current_commit(args.repository_root),
    )
    _require_plan_binding(approval_path=args.approval, plan=plan)
    adapters = build_production_adapters(
        plan,
        supervisor_root=args.operations_root,
        repository_root=args.repository_root,
    )
    supervisor = SuccessorSupervisor(
        root=args.operations_root,
        approval_path=args.approval,
        repository_root=args.repository_root,
        adapters=adapters,
    )
    if args.mode == "preflight":
        for task_id in TASKS:
            adapters[task_id].static_preflight()
        result = {
            "status": "PASS",
            "mode": "preflight",
            "adapter_plan_hash": plan.plan_hash,
            "formal_run_created": False,
        }
    else:
        result = {"mode": args.mode, **supervisor.run_or_resume()}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
