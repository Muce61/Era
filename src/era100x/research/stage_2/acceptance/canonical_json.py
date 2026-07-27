"""Canonical JSON content hashing for append-only Stage 2 evidence.

The logical content hash excludes the one required terminal LF.  Producer and
verifier share this module so a physical-file hash can never be confused with
the canonical JSON content hash again.
"""

from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, BinaryIO, cast

import ijson  # type: ignore[import-untyped]

CANONICAL_JSON_CONTENT_SCHEMA = "CANONICAL_JSON_CONTENT_V1"
DECIMAL_QUANTUM = Decimal("0.000000000000000001")


def decimal_text(value: Decimal | int) -> str:
    decimal = Decimal(value)
    return format(decimal.quantize(DECIMAL_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def _normalize(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("binary float is forbidden in canonical JSON evidence")
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical JSON evidence type: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_json(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def canonical_content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _safe_file(path: Path) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.name.startswith("._")
        or any(part.startswith("._") for part in path.parts)
    ):
        raise ValueError(f"unsafe canonical JSON evidence: {path}")


class _ContentReader:
    """Read all but the required terminal LF while hashing physical content."""

    def __init__(self, handle: BinaryIO, size: int) -> None:
        self._handle = handle
        self._remaining = size - 1
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        if self._remaining == 0:
            return b""
        requested = self._remaining if size is None or size < 0 else min(size, self._remaining)
        block = self._handle.read(requested)
        if not block:
            raise ValueError("canonical JSON evidence truncated during read")
        self._remaining -= len(block)
        self.digest.update(block)
        return block


class _CanonicalEventEncoder:
    """Incrementally canonicalize an ijson event stream without materializing it."""

    def __init__(self) -> None:
        self.digest = hashlib.sha256()
        self._stack: list[dict[str, object]] = []
        self._root_seen = False

    def _write(self, value: bytes) -> None:
        self.digest.update(value)

    def _value_prefix(self) -> None:
        if not self._stack:
            if self._root_seen:
                raise ValueError("canonical JSON must contain exactly one root value")
            self._root_seen = True
            return
        context = self._stack[-1]
        if context["kind"] == "array":
            if context["first"] is False:
                self._write(b",")
            context["first"] = False
            return
        if context["expecting_value"] is not True:
            raise ValueError("canonical JSON object value lacks a key")
        context["expecting_value"] = False

    def consume(self, event: str, value: object) -> None:
        if event == "map_key":
            if not self._stack or self._stack[-1]["kind"] != "map":
                raise ValueError("map key outside object")
            context = self._stack[-1]
            if context["expecting_value"] is True:
                raise ValueError("object key has no value")
            key = str(value)
            previous = cast(str | None, context["previous_key"])
            if previous is not None and key <= previous:
                raise ValueError("canonical JSON object keys are not strictly sorted")
            if context["first"] is False:
                self._write(b",")
            context["first"] = False
            context["previous_key"] = key
            context["expecting_value"] = True
            self._write(json.dumps(key, ensure_ascii=False).encode("utf-8") + b":")
            return
        if event in {"start_map", "start_array"}:
            self._value_prefix()
            kind = "map" if event == "start_map" else "array"
            self._write(b"{" if kind == "map" else b"[")
            self._stack.append(
                {
                    "kind": kind,
                    "first": True,
                    "previous_key": None,
                    "expecting_value": False,
                }
            )
            return
        if event in {"end_map", "end_array"}:
            if not self._stack:
                raise ValueError("canonical JSON has an unmatched closing token")
            context = self._stack.pop()
            expected = "map" if event == "end_map" else "array"
            if context["kind"] != expected or context["expecting_value"] is True:
                raise ValueError("canonical JSON container structure is invalid")
            self._write(b"}" if expected == "map" else b"]")
            return
        self._value_prefix()
        if event == "string":
            self._write(json.dumps(str(value), ensure_ascii=False).encode("utf-8"))
        elif event == "number":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("canonical JSON numeric evidence must be an integer")
            self._write(str(value).encode("ascii"))
        elif event == "boolean":
            self._write(b"true" if value is True else b"false")
        elif event == "null":
            self._write(b"null")
        else:
            raise ValueError(f"unsupported JSON parser event: {event}")

    def finish(self) -> str:
        if self._stack or not self._root_seen:
            raise ValueError("canonical JSON document is incomplete")
        return self.digest.hexdigest()


def verify_canonical_json_file(path: Path, *, expected_hash: str | None = None) -> str:
    """Stream-parse, canonicalize and hash a strict JSON document.

    The file must be byte-for-byte canonical and end in exactly one LF.  The LF
    is not part of the returned content hash.
    """

    _safe_file(path)
    size = path.stat().st_size
    if size < 2:
        raise ValueError("canonical JSON file is empty")
    with path.open("rb") as handle:
        handle.seek(-1, os.SEEK_END)
        if handle.read(1) != b"\n":
            raise ValueError("canonical JSON file must end with exactly one LF")
        handle.seek(-2, os.SEEK_END)
        if handle.read(1) in {b"\n", b"\r"}:
            raise ValueError("canonical JSON file has a non-canonical terminal sequence")
        handle.seek(0)
        reader = _ContentReader(handle, size)
        encoder = _CanonicalEventEncoder()
        for event, value in ijson.basic_parse(reader, use_float=False):
            encoder.consume(str(event), value)
        canonical_hash = encoder.finish()
        raw_hash = reader.digest.hexdigest()
    if raw_hash != canonical_hash:
        raise ValueError("JSON bytes are not the canonical representation of their content")
    if expected_hash is not None and canonical_hash != expected_hash:
        raise ValueError("canonical JSON content Hash mismatch")
    return canonical_hash


def read_canonical_json(path: Path) -> dict[str, Any]:
    verify_canonical_json_file(path)
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("canonical JSON evidence root must be an object")
    return cast(dict[str, Any], payload)


def write_canonical_json_exclusive(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_json_bytes(value)
    with path.open("xb") as handle:
        handle.write(content)
        handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    content_hash = hashlib.sha256(content).hexdigest()
    verify_canonical_json_file(path, expected_hash=content_hash)
    return content_hash


def sha256_file(path: Path) -> str:
    _safe_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = [
    "CANONICAL_JSON_CONTENT_SCHEMA",
    "canonical_content_hash",
    "canonical_json",
    "canonical_json_bytes",
    "decimal_text",
    "read_canonical_json",
    "sha256_file",
    "verify_canonical_json_file",
    "write_canonical_json_exclusive",
]
