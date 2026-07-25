from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

import pytest

from era100x.research.stage_2.rerun.strict_json import (
    strict_json_bytes,
    strict_json_value,
)


class Status(StrEnum):
    PASS = "PASS"


@dataclass(frozen=True)
class Result:
    value: Decimal
    status: Status


def test_strict_json_is_deterministic_and_preserves_decimal_text() -> None:
    encoded = strict_json_bytes({"result": Result(Decimal("1.2300"), Status.PASS)})

    assert encoded == b'{"result":{"status":"PASS","value":"1.2300"}}\n'
    assert json.loads(encoded) == {"result": {"status": "PASS", "value": "1.2300"}}


def test_strict_json_rejects_binary_float_and_non_finite_decimal() -> None:
    with pytest.raises(TypeError, match="binary floats"):
        strict_json_value({"value": 1.23})
    with pytest.raises(ValueError, match="non-finite"):
        strict_json_value(Decimal("NaN"))


def test_strict_json_rejects_key_collisions_after_string_normalization() -> None:
    with pytest.raises(ValueError, match="key collision"):
        strict_json_value({1: "integer", "1": "string"})
