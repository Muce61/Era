"""Versioned stable identifiers for research facts."""

from __future__ import annotations

import hashlib
from decimal import Decimal


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
