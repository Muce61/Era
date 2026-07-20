from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
SOURCE_ROOTS = (ROOT / "src", ROOT / "scripts")
DEPRECATED_TERMINAL_RESOURCE_TOKENS = (
    "catalog object/seal summaries must each remain <= 200",
    "MAX_CATALOG_OBJECTS",
    "MAX_GROUP1_PACKED_OBJECTS",
    "max_group1_packed_objects",
    "require_catalog_object_budget",
    "group1_object_budget",
)


def test_no_stage_reintroduces_deprecated_terminal_resource_gates() -> None:
    hits: list[str] = []
    for source_root in SOURCE_ROOTS:
        for path in sorted(source_root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for token in DEPRECATED_TERMINAL_RESOURCE_TOKENS:
                if token in source:
                    hits.append(f"{path.relative_to(ROOT)}: {token}")

    assert hits == []
