#!/usr/bin/env python3
"""Validate the single Stage 2 policy and legacy read-only safety boundary."""

from __future__ import annotations

import argparse
from pathlib import Path

from era100x.foundation.governance import load_current_development_state
from era100x.research.stage_2.rerun.lightweight_governance import load_policy

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs/governance/stage2_active_policy_v2.json"


def validate_current_governance_state() -> list[str]:
    """Check machine evidence, not repeated prose markers."""

    errors: list[str] = []
    try:
        policy = load_policy(POLICY_PATH, repository_root=ROOT)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    if policy.payload["stage3_locked"] is not True:
        errors.append("Stage 2 policy must keep Stage 3 locked")
    if policy.payload["execution_limit"] != "S2P13-T16":
        errors.append("Stage 2 execution limit drift")
    try:
        legacy = load_current_development_state()
    except (OSError, ValueError) as exc:
        errors.append(f"legacy governance archive is invalid: {exc}")
    else:
        if legacy.stage3_locked is not True:
            errors.append("legacy governance archive does not keep Stage 3 locked")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true")
    parser.parse_args()
    errors = validate_current_governance_state()
    if errors:
        print("Governance policy validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    policy = load_policy(POLICY_PATH, repository_root=ROOT)
    print(
        "Governance policy PASS: "
        f"S2/{policy.payload['execution_limit']} policy_hash={policy.policy_hash}; "
        "Stage3 locked=True; prose markers=NOT_GATING"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
