from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = Path("/Users/muce/1m_data/long_history_1m/merged")
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "outputs"

SYMBOLS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
PRIMARY_SYMBOLS = ["ETHUSDT", "BTCUSDT"]
FORWARD_HORIZONS_MINUTES = [15, 30, 60, 120, 240, 480]

DISCOVERY_END = "2023-12-31 23:59:00+00:00"
VALIDATION_START = "2024-01-01 00:00:00+00:00"
VALIDATION_END = "2024-12-31 23:59:00+00:00"
OOS_START = "2025-01-01 00:00:00+00:00"

TREND_BASELINE_RULES = {
    "signal_timeframe": "15min",
    "execution_timeframe": "1min",
    "direction": "long_only",
    "donchian_entry": 55,
    "ema_fast": 50,
    "ema_slow": 200,
    "donchian_exit": 20,
    "atr_period": 14,
    "atr_stop_mult": 3.0,
}


@dataclass(frozen=True)
class RegimeResearchConfig:
    data_dir: Path = DEFAULT_DATA_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR
    symbols: list[str] = field(default_factory=lambda: list(SYMBOLS))
    horizons_minutes: list[int] = field(default_factory=lambda: list(FORWARD_HORIZONS_MINUTES))
    signal_timeframe: str = "15min"
    atr_period: int = 14
    discovery_end: str = DISCOVERY_END
    validation_start: str = VALIDATION_START
    validation_end: str = VALIDATION_END
    oos_start: str = OOS_START

    @property
    def discovery_end_ts(self):
        import pandas as pd

        return pd.Timestamp(self.discovery_end)

