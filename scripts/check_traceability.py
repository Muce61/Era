"""Strict integrity checks for the V1.3.5 planning traceability catalogue."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOGUE = ROOT / "docs/development/traceability/rules.yaml"
REQUIRED_FIELDS = {
    "rule_id",
    "rule_status",
    "source_section",
    "planned_stage",
    "planned_tasks",
    "implementation_paths",
    "test_paths",
    "validation_paths",
    "state",
}
ALLOWED_STATUSES = {"FROZEN", "BASELINE", "RESEARCH", "DEPRECATED", "BLOCKED_BY_FORWARD_VALIDATION"}


def _task_ids(root: Path) -> set[str]:
    ids: list[str] = []
    for path in (root / "docs/development/tasks").glob("stage_*/*.md"):
        content = path.read_text()
        match = re.search(r"^- task_id: (S\d+(?:P\d+)?-T\d+)$", content, re.MULTILINE)
        multi = re.search(r"^- task_ids: \[([^\]]+)\]$", content, re.MULTILINE)
        if match:
            ids.append(match.group(1))
        elif multi:
            task_ids = [item.strip() for item in multi.group(1).split(",")]
            if not task_ids or any(
                not re.fullmatch(r"S\d+(?:P\d+)?-T\d+", item)
                for item in task_ids
            ):
                raise ValueError(f"invalid task_ids metadata: {path.relative_to(root)}")
            ids.extend(task_ids)
        else:
            raise ValueError(f"missing task_id metadata: {path.relative_to(root)}")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate Task IDs")
    return set(ids)


def validate_catalogue(
    path: Path = DEFAULT_CATALOGUE, *, root: Path = ROOT, strict: bool = True
) -> list[str]:
    errors: list[str] = []
    raw: Any = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict) or raw.get("spec_version") != "V1.3.5":
        return ["catalogue must declare spec_version V1.3.5"]
    entries = raw.get("rules")
    if not isinstance(entries, list):
        return ["rules must be a list"]
    ids = [item.get("rule_id") for item in entries if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        errors.append("rule/invariant/contract/reason/gate IDs must be globally unique")
    formal = [
        item
        for item in entries
        if isinstance(item, dict)
        and not str(item.get("rule_id", "")).startswith(("INV-", "CONTRACT-", "REASON-", "GATE-"))
    ]
    invariants = [item for item in entries if str(item.get("rule_id", "")).startswith("INV-")]
    contracts = [item for item in entries if str(item.get("rule_id", "")).startswith("CONTRACT-")]
    reasons = [item for item in entries if str(item.get("rule_id", "")).startswith("REASON-")]
    gates = [item for item in entries if str(item.get("rule_id", "")).startswith("GATE-STAGE-")]
    expected = {
        "formal rules": (len(formal), 33),
        "invariants": (len(invariants), 41),
        "contracts": (len(contracts), 18),
        "reasons": (len(reasons), 52),
        "stage gates": (len(gates), 10),
    }
    for label, (actual, wanted) in expected.items():
        if actual != wanted:
            errors.append(f"expected {wanted} {label}, found {actual}")
    expected_invariants = {f"INV-{number:03d}" for number in range(1, 42)}
    if {item["rule_id"] for item in invariants} != expected_invariants:
        errors.append("INV-001 through INV-041 must be complete and unique")
    task_ids = _task_ids(root)
    stage_ids = {f"S{number}" for number in range(10)}
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            errors.append(f"entry {index} must be a mapping")
            continue
        missing = REQUIRED_FIELDS - item.keys()
        if missing:
            errors.append(f"{item.get('rule_id', index)} missing fields: {sorted(missing)}")
            continue
        if item["rule_status"] not in ALLOWED_STATUSES:
            errors.append(f"{item['rule_id']} has invalid rule_status")
        if item["planned_stage"] not in stage_ids:
            errors.append(f"{item['rule_id']} references unknown Stage")
        dangling = set(item["planned_tasks"]) - task_ids
        if dangling:
            errors.append(f"{item['rule_id']} has dangling Tasks: {sorted(dangling)}")
        for field in ("implementation_paths", "test_paths", "validation_paths"):
            if not item[field]:
                errors.append(f"{item['rule_id']} has empty {field}")
        if (
            strict
            and item["state"] != "PLANNED"
            and any(
                "PLANNED" in str(value)
                for field in ("implementation_paths", "test_paths", "validation_paths")
                for value in item[field]
            )
        ):
            errors.append(f"{item['rule_id']} claims {item['state']} while paths remain PLANNED")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--catalogue", type=Path, default=DEFAULT_CATALOGUE)
    args = parser.parse_args()
    errors = validate_catalogue(args.catalogue, strict=args.strict)
    if errors:
        print("Traceability validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Traceability coverage: 33 rules, 41 INV, 18 contracts, 52 reasons, 10 gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
