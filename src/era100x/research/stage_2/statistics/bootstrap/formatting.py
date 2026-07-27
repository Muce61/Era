"""One strict serialization boundary shared by T18 producer and verifier."""

from __future__ import annotations

import hashlib
import json
import math
import os
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, cast

QUANTUM = Decimal("0.000000000000000001")


def decimal_text(value: Decimal | float | int) -> str:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite statistic")
        decimal = Decimal(str(value))
    else:
        decimal = Decimal(value)
    return format(decimal.quantize(QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def _normalize(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("binary float is forbidden in canonical evidence")
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical evidence type: {type(value).__name__}")


def canonical_json(value: object) -> str:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.name.startswith("._")
        or any(part.startswith("._") for part in path.parts)
    ):
        raise ValueError(f"unsafe JSON evidence: {path}")
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("JSON evidence root must be an object")
    _normalize(payload)
    return cast(dict[str, Any], payload)


def write_exclusive(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (canonical_json(payload) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def sha256_file(path: Path) -> str:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.name.startswith("._")
        or any(part.startswith("._") for part in path.parts)
    ):
        raise ValueError(f"unsafe evidence file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
