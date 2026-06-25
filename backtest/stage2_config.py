"""Frozen Stage 2 configuration loading and validation."""

import hashlib
import json
import subprocess
from pathlib import Path

from strategy.eth_trend_signals import EntryMode, StrategyConfig


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "configs"

FROZEN_CONFIGS = {
    "B1": CONFIG_DIR / "stage2_b1_frozen.json",
    "B2": CONFIG_DIR / "stage2_b2_frozen.json",
    "B3": CONFIG_DIR / "stage2_b3_frozen.json",
}


STRATEGY_CONFIG_FIELDS = {
    "entry_mode",
    "leverage",
    "ema_fast",
    "ema_slow",
    "donchian_entry",
    "donchian_exit",
    "atr_period",
    "atr_stop_mult",
    "fee_rate",
    "slippage_rate",
    "signal_timeframe",
    "position_sizing_mode",
    "risk_fraction",
}


def canonical_json_bytes(config: dict) -> bytes:
    return json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def config_hash(config: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(config)).hexdigest()


def file_sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def current_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def load_frozen_config(label: str) -> dict:
    if label not in FROZEN_CONFIGS:
        raise ValueError(f"Unknown frozen config label: {label}")
    path = FROZEN_CONFIGS[label]
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def strategy_config_from_frozen(frozen: dict) -> StrategyConfig:
    kwargs = {k: frozen[k] for k in STRATEGY_CONFIG_FIELDS if k in frozen}
    kwargs["entry_mode"] = EntryMode(kwargs["entry_mode"])
    return StrategyConfig(**kwargs)


def assert_no_overrides(frozen: dict, config: StrategyConfig) -> None:
    actual = config.__dict__.copy()
    actual["entry_mode"] = actual["entry_mode"].value
    mismatches = {}
    for field in STRATEGY_CONFIG_FIELDS:
        if field not in frozen:
            continue
        if actual.get(field) != frozen[field]:
            mismatches[field] = {"frozen": frozen[field], "actual": actual.get(field)}
    if mismatches:
        raise ValueError(f"StrategyConfig differs from frozen config: {mismatches}")


def frozen_config_hash_for_label(label: str) -> str:
    return config_hash(load_frozen_config(label))
