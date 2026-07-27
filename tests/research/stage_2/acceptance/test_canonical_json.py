from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    canonical_json_bytes,
    verify_canonical_json_file,
    write_canonical_json_exclusive,
)


def test_semantic_key_order_has_one_content_hash_but_array_order_matters() -> None:
    left = {"z": [1, 2], "a": {"b": "值"}}
    right = {"a": {"b": "值"}, "z": [1, 2]}
    assert canonical_content_hash(left) == canonical_content_hash(right)
    assert canonical_content_hash(left) != canonical_content_hash({"z": [2, 1], "a": {"b": "值"}})


def test_decimal_is_text_and_binary_float_is_rejected() -> None:
    assert canonical_json_bytes({"value": Decimal("1.25")}) == (b'{"value":"1.250000000000000000"}')
    with pytest.raises(ValueError, match="binary float"):
        canonical_json_bytes({"value": 1.25})


def test_terminal_lf_is_required_and_excluded_from_content_hash(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    expected = write_canonical_json_exclusive(path, {"a": 1})
    assert path.read_bytes() == b'{"a":1}\n'
    assert verify_canonical_json_file(path) == expected

    for name, value in (
        ("missing.json", b'{"a":1}'),
        ("double.json", b'{"a":1}\n\n'),
        ("crlf.json", b'{"a":1}\r\n'),
    ):
        target = tmp_path / name
        target.write_bytes(value)
        with pytest.raises(ValueError):
            verify_canonical_json_file(target)


def test_noncanonical_key_order_and_number_are_rejected(tmp_path: Path) -> None:
    unordered = tmp_path / "unordered.json"
    unordered.write_bytes(b'{"z":1,"a":2}\n')
    with pytest.raises(ValueError, match="keys"):
        verify_canonical_json_file(unordered)

    decimal = tmp_path / "decimal.json"
    decimal.write_bytes(b'{"value":1.25}\n')
    with pytest.raises(ValueError, match="integer"):
        verify_canonical_json_file(decimal)


def test_streaming_large_document_matches_reference_hash(tmp_path: Path) -> None:
    payload = {"rows": [{"id": index, "value": str(index)} for index in range(20_000)]}
    path = tmp_path / "large.json"
    expected = write_canonical_json_exclusive(path, payload)
    assert verify_canonical_json_file(path, expected_hash=expected) == expected
    assert json.loads(path.read_bytes()) == payload


def test_appledouble_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "._evidence.json"
    path.write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="unsafe"):
        verify_canonical_json_file(path)
