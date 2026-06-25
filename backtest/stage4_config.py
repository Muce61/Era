"""Frozen Stage 4 C1 configuration loading."""

import json
from pathlib import Path

from backtest.stage2_config import (
    assert_no_overrides,
    config_hash,
    load_frozen_config as load_stage2_frozen,
    strategy_config_from_frozen,
)
from strategy.eth_trend_signals import StrategyConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "configs"

STAGE4_FROZEN_CONFIGS = {
    "C1": CONFIG_DIR / "stage4_c1_frozen.json",
}

STAGE4_COMPARISON_LABELS = ["B0", "B1", "B2", "B3", "C1"]


def load_stage4_frozen_config(label: str) -> dict:
    if label == "C1":
        with open(STAGE4_FROZEN_CONFIGS["C1"], "r", encoding="utf-8") as f:
            return json.load(f)
    if label == "B0":
        frozen = dict(load_stage2_frozen("B1"))
        frozen["entry_mode"] = "no_candle"
        return frozen
    label_map = {"B1": "B1", "B2": "B2", "B3": "B3"}
    if label not in label_map:
        raise ValueError(f"Unknown stage4 label: {label}")
    return load_stage2_frozen(label_map[label])


def run_config_from_label(label: str) -> StrategyConfig:
    frozen = load_stage4_frozen_config(label)
    config = strategy_config_from_frozen(frozen)
    assert_no_overrides(frozen, config)
    return config


def frozen_config_hash(label: str) -> str:
    return config_hash(load_stage4_frozen_config(label))
