from __future__ import annotations

import pytest

from era100x.research.stage_2.runtime_v2.foundation_specs import (
    feature_foundation_dataset_specs,
)
from era100x.research.stage_2.runtime_v2.models import DatasetSpec


def test_foundation_specs_are_complete_stable_and_non_legacy() -> None:
    first = feature_foundation_dataset_specs()
    second = feature_foundation_dataset_specs()

    assert first == second
    assert {item.dataset_name for item in first} == {
        "contract_price_1s",
        "causal_price_bars",
        "trade_second_primitives",
        "trade_row_group_index",
    }
    assert tuple(item.spec_hash for item in first) == tuple(
        sorted(item.spec_hash for item in first)
    )
    assert all(item.legacy_hash_algorithm == "NOT_APPLICABLE" for item in first)
    assert all(item.computed_hash() == item.spec_hash for item in first)


def test_foundation_specs_reject_binary_floats() -> None:
    base = feature_foundation_dataset_specs()[0].model_dump(mode="python")
    base.pop("spec_hash")
    fields = list(base["fields"])
    fields[0] = {"name": "instrument", "data_type": "float64", "nullable": False}
    base["fields"] = tuple(fields)

    with pytest.raises(ValueError, match="binary floating-point"):
        DatasetSpec.seal(base)
