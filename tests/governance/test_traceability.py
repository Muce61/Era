from copy import deepcopy
from pathlib import Path

import yaml

from scripts.check_traceability import DEFAULT_CATALOGUE, validate_catalogue


def _catalogue(tmp_path: Path, mutate: object | None = None) -> Path:
    data = yaml.safe_load(DEFAULT_CATALOGUE.read_text())
    if callable(mutate):
        mutate(data)
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def test_t_inv_id_001_complete_catalogue_passes() -> None:
    assert validate_catalogue() == []


def test_t_inv_id_002_duplicate_id_fails(tmp_path: Path) -> None:
    def mutate(data: dict[str, object]) -> None:
        rules = data["rules"]
        assert isinstance(rules, list)
        rules.append(deepcopy(rules[0]))

    errors = validate_catalogue(_catalogue(tmp_path, mutate))
    assert any("globally unique" in error for error in errors)


def test_t_inv_id_003_missing_invariant_fails(tmp_path: Path) -> None:
    def mutate(data: dict[str, object]) -> None:
        rules = data["rules"]
        assert isinstance(rules, list)
        data["rules"] = [item for item in rules if item["rule_id"] != "INV-041"]

    errors = validate_catalogue(_catalogue(tmp_path, mutate))
    assert any("INV-001 through INV-041" in error for error in errors)


def test_t_inv_id_004_planned_paths_cannot_claim_passed(tmp_path: Path) -> None:
    def mutate(data: dict[str, object]) -> None:
        rules = data["rules"]
        assert isinstance(rules, list)
        rules[0]["state"] = "PASSED"

    errors = validate_catalogue(_catalogue(tmp_path, mutate), strict=True)
    assert any("paths remain PLANNED" in error for error in errors)


def test_dangling_task_reference_fails(tmp_path: Path) -> None:
    def mutate(data: dict[str, object]) -> None:
        rules = data["rules"]
        assert isinstance(rules, list)
        rules[0]["planned_tasks"].append("S0-T99")

    errors = validate_catalogue(_catalogue(tmp_path, mutate))
    assert any("dangling Tasks" in error for error in errors)
