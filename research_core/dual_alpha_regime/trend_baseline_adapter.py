from __future__ import annotations

from pathlib import Path

import pandas as pd


FROZEN_TREND_FIELDS = {
    "donchian_entry": 55,
    "donchian_exit": 20,
    "ema_fast": 50,
    "ema_slow": 200,
    "atr_period": 14,
    "atr_stop_mult": 3.0,
}


def write_trend_baseline_freeze(output_dir: Path) -> pd.DataFrame:
    """Write the frozen trend baseline mapping without changing strategy code."""

    rows = [{"field": k, "frozen_value": v, "status": "frozen_no_parameter_search"} for k, v in FROZEN_TREND_FIELDS.items()]
    rows.append({"field": "implementation_note", "frozen_value": "adapter_only", "status": "no_engine_mutation"})
    df = pd.DataFrame(rows)
    df.to_csv(output_dir / "trend_strategy_summary.csv", index=False)
    return df

