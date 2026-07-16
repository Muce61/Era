"""Versioned stable identifiers for research facts."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import Enum
from typing import Any


def _text(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        raise TypeError("binary floats are forbidden in stable identifiers")
    return str(value)


def stable_id(schema: str, version: str, *parts: object) -> str:
    payload = "|".join((schema, version, *(_text(part) for part in parts)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def market_episode_identity(
    venue: str, instrument: str, canonical_key_level_id: str, sweep_start_ns: int
) -> str:
    """V1.3.4 FROZEN identity; strategy/config versions are intentionally absent."""

    payload = "|".join((venue, instrument, canonical_key_level_id, str(sweep_start_ns)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_decimal(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def canonical_identity_json(value: Any) -> str:
    """Canonical identity/payload JSON; free-form metadata must be removed by callers."""

    def convert(item: Any) -> Any:
        if isinstance(item, Decimal):
            return _canonical_decimal(item)
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, dict):
            return {str(key): convert(val) for key, val in sorted(item.items())}
        if isinstance(item, (list, tuple)):
            return [convert(val) for val in item]
        if isinstance(item, float):
            raise TypeError("binary floats are forbidden in candidate identity")
        return item

    return json.dumps(convert(value), ensure_ascii=False, separators=(",", ":"))


def versioned_payload_hash(schema: str, version: str, payload: Any) -> str:
    canonical = canonical_identity_json(payload)
    return hashlib.sha256(f"{schema}|{version}|{canonical}".encode()).hexdigest()


def canonical_candidate_identity(payload: dict[str, Any]) -> str:
    """CR-2026-004 identity; payload keys are emitted in an explicit fixed order."""

    return versioned_payload_hash("stage2-canonical-candidate", "v1", payload)


def canonical_candidate_payload_hash(payload: dict[str, Any]) -> str:
    return versioned_payload_hash("stage2-candidate-payload", "v1", payload)


def semantic_fact_payload_hash(payload: dict[str, Any]) -> str:
    semantic = {
        key: value for key, value in payload.items() if key not in {"code_version", "metadata"}
    }
    return versioned_payload_hash("stage2-event-fact-payload", "v1", semantic)
