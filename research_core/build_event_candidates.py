"""R1: Build unified event candidates from discovery OHLCV data."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import (
    DISCOVERY_DATA_PATH,
    RANDOM_SEED,
    RESEARCH_ROOT,
    append_run_log,
    current_git_commit,
    ensure_research_dirs,
    file_sha256,
    stable_hash,
    write_simple_yaml,
)
from research_core.event_table import FACTOR_COLUMNS, HORIZONS, build_event_candidates, load_ohlcv_1m


LABEL_PREFIXES = ("fwd_ret_", "fwd_mfe_", "fwd_mae_", "plus_1atr_first_", "minus_1atr_first_", "ambiguous_touch_")


def write_event_schema(columns: list[str]) -> None:
    required = [
        "event_id",
        "symbol",
        "signal_time",
        "execution_time",
        "execution_open",
        "close_15m",
        "high_15m",
        "low_15m",
        "volume_15m",
        "donchian55_upper",
        "donchian20_lower",
        "ema50",
        "ema200",
        "atr14",
    ]
    payload = {
        "schema_name": "research_core_event_candidates_v1",
        "required_fields": required,
        "factor_fields": FACTOR_COLUMNS,
        "label_prefixes": list(LABEL_PREFIXES),
        "all_fields": columns,
        "execution_rule": "15m_signal_confirmed_next_1m_open",
        "data_layer": "discovery",
    }
    write_simple_yaml(RESEARCH_ROOT / "schemas" / "event_schema.yaml", payload)


def write_factor_catalog() -> None:
    factors = []
    for name in FACTOR_COLUMNS:
        factors.append({
            "name": name,
            "role": "factor",
            "uses_future_data": False,
            "status": "active",
        })
    labels = []
    for h in HORIZONS:
        for prefix in LABEL_PREFIXES:
            labels.append({
                "name": f"{prefix}{h}",
                "role": "forward_label",
                "uses_future_data": True,
                "status": "label_only",
            })
    write_simple_yaml(
        RESEARCH_ROOT / "manifests" / "factor_catalog.yaml",
        {
            "catalog_name": "research_core_factor_catalog_v1",
            "factors": factors,
            "labels": labels,
        },
    )


def write_events(events: pd.DataFrame) -> str:
    parquet_path = RESEARCH_ROOT / "events" / "event_candidates.parquet"
    fallback_path = RESEARCH_ROOT / "events" / "event_candidates.pkl"
    try:
        events.to_parquet(parquet_path, index=False)
        return str(parquet_path)
    except Exception:
        events.to_pickle(fallback_path)
        return str(fallback_path)


def main() -> None:
    ensure_research_dirs()
    if not DISCOVERY_DATA_PATH.exists():
        raise FileNotFoundError(f"Missing discovery dataset: {DISCOVERY_DATA_PATH}")
    data_hash = file_sha256(DISCOVERY_DATA_PATH)
    data_1m = load_ohlcv_1m(DISCOVERY_DATA_PATH)
    events, df_15m = build_event_candidates(data_1m)
    event_path = write_events(events)
    events.head(200).to_csv(RESEARCH_ROOT / "events" / "event_candidates_sample.csv", index=False)
    write_event_schema(list(events.columns))
    write_factor_catalog()

    config_hash = stable_hash({"event_schema": list(events.columns), "factor_columns": FACTOR_COLUMNS, "horizons": HORIZONS})
    append_run_log({
        "run_id": "R1_EVENT_CANDIDATES",
        "stage": "R1",
        "script": "research_core/build_event_candidates.py",
        "config_hash": config_hash,
        "data_hash": data_hash,
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "discovery",
        "status": "success",
        "notes": f"Generated {len(events)} event candidates at {event_path}.",
    })

    label_cols = [c for c in events.columns if c.startswith(LABEL_PREFIXES)]
    report = [
        "# R1 Event Table Report",
        "",
        f"event_count: {len(events)}",
        f"strict_15m_bars: {len(df_15m)}",
        f"event_output: `{event_path}`",
        f"sample_output: `research_core/events/event_candidates_sample.csv`",
        "",
        "## Factor / Label Separation",
        "",
        f"factor_count: {len(FACTOR_COLUMNS)}",
        f"forward_label_count: {len(label_cols)}",
        "",
        "Forward labels are explicitly marked label-only and must not be used as factors.",
        "relative_strength_regime is `unavailable` because no BTC/multi-symbol relative-strength data is included in this migrated lightweight repository.",
    ]
    (RESEARCH_ROOT / "reports" / "R1_event_table_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

