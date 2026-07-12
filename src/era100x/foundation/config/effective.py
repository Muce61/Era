from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Mode = Literal["research", "backtest", "shadow", "testnet", "live", "compound"]
FROZEN_KEYS = {"venue", "direction", "margin_mode", "position_mode", "max_leverage"}


class EffectiveConfigSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manual_version: Literal["V1.3.4"] = "V1.3.4"
    mode: Mode
    values: dict[str, Any]
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def _canonical_hash(values: dict[str, Any]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def resolve_effective_config(
    *,
    mode: Mode,
    exchange_constraints: dict[str, Any],
    approved_risk: dict[str, Any],
    strategy_defaults: dict[str, Any],
    research_overrides: dict[str, Any] | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> EffectiveConfigSnapshot:
    if mode in {"live", "compound"} and cli_overrides:
        raise ValueError("CLI overrides are forbidden in live/compound modes")
    layers = [exchange_constraints, approved_risk, strategy_defaults]
    if mode in {"research", "backtest"}:
        layers.append(research_overrides or {})
    layers.append(cli_overrides or {})
    values: dict[str, Any] = {}
    frozen: dict[str, Any] = {}
    for index, layer in enumerate(layers):
        for key, value in layer.items():
            if key in FROZEN_KEYS and key in frozen and frozen[key] != value:
                raise ValueError(f"FROZEN configuration override rejected: {key}")
            values[key] = value
            if index == 0 and key in FROZEN_KEYS:
                frozen[key] = value
    digest = _canonical_hash({"manual_version": "V1.3.4", "mode": mode, "values": values})
    return EffectiveConfigSnapshot(mode=mode, values=values, config_hash=digest)
