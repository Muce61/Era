"""One strict JSON boundary shared by rehearsal and formal successor producers."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, cast


def strict_json_value(value: Any) -> Any:
    """Return a deterministic JSON value without binary floating-point values."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal is forbidden in strict JSON")
        return format(value, "f")
    if isinstance(value, float):
        raise TypeError("binary floats are forbidden in strict JSON")
    if isinstance(value, Enum):
        return strict_json_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return strict_json_value(asdict(cast(Any, value)))
    if hasattr(value, "model_dump"):
        return strict_json_value(value.model_dump(mode="python"))
    if isinstance(value, dict):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if text_key in converted:
                raise ValueError(f"strict JSON key collision: {text_key}")
            converted[text_key] = strict_json_value(item)
        return converted
    if isinstance(value, (tuple, list)):
        return [strict_json_value(item) for item in value]
    raise TypeError(f"unsupported strict JSON value: {type(value).__name__}")


def strict_json_bytes(value: object) -> bytes:
    """Encode one canonical JSON document with a trailing newline."""

    return (
        json.dumps(
            strict_json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
