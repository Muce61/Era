from __future__ import annotations

import json
from decimal import Decimal
from enum import Enum

import pytest

from era100x.research.stage_2.pipelines.candidates.io import canonical_json_row_v1_bytes


class Example(Enum):
    VALUE = "value"


@pytest.mark.parametrize(
    "record",
    (
        {"z": None, "a": True, "n": 17, "s": "plain"},
        {"unicode": "比特币", "controls": 'line\nquote"slash\\'},
        {"nested": {"b": 2, "a": [3, None, False]}, "tuple": ("x", "y")},
        {"decimal": Decimal("1.2300"), "enum": Example.VALUE},
    ),
)
def test_canonical_json_row_v1_encoder_is_byte_exact(record: dict[str, object]) -> None:
    expected = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    assert canonical_json_row_v1_bytes(record) == expected


def test_canonical_json_row_v1_rejects_binary_float() -> None:
    with pytest.raises(TypeError, match="forbids float"):
        canonical_json_row_v1_bytes({"forbidden": 1.5})
