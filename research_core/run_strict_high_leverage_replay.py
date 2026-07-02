"""Run strict 1m replay for high-leverage gate candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from research_core.common import (
    RANDOM_SEED,
    RESEARCH_ROOT,
    append_run_log,
    current_git_commit,
    ensure_research_dirs,
    file_sha256,
    stable_hash,
)
from research_core.cross_asset_validation_analysis import default_symbol_paths, merge_symbol_1m
from research_core.event_table import add_base_indicators, strict_resample_15m
from research_core.high_leverage_gate_analysis import (
    H3_GATES,
    build_fixed_gate_thresholds,
    gate_mask_fixed,
    high_risk_mask_fixed,
    unique_event_labels,
)
from research_core.high_leverage_h4_validation_analysis import H4_GATES, H4_PROTOTYPES
from research_core.strict_high_leverage_replay import (
    STRICT_LEVERAGE_MODES,
    compare_proxy_to_strict,
    strict_replay_events,
    strict_summary,
)


CORE_SYMBOLS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
RUN_CORE_LAYER = False
STRICT_GATES = ["G1_SINGLE_BEST_PATH_SAFETY"]


def parse_signal_time(event_id: str) -> pd.Timestamp:
    return pd.to_datetime(str(event_id).split("_", 1)[1], utc=True)


def prepare_core_events(labels: pd.DataFrame) -> pd.DataFrame:
    events = labels.copy()
    events["signal_time"] = events["event_id"].map(parse_signal_time)
    events["execution_time"] = pd.to_datetime(events["entry_time"], utc=True)
    events["atr14"] = events["atr"]
    events["data_layer"] = "h3_core_strict_replay"
    return events


def symbol_data(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    paths = default_symbol_paths(symbol)
    data_1m = merge_symbol_1m(paths)
    data_15m = add_base_indicators(strict_resample_15m(data_1m))
    return data_1m, data_15m, [p for p in paths if p.exists()]


def run_layer(
    data_layer: str,
    events: pd.DataFrame,
    symbols: list[str],
    gates: list[str],
    gate_factors: pd.DataFrame,
    gate_thresholds: pd.DataFrame,
    out: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    data_hashes = []
    for symbol in symbols:
        data_1m, data_15m, paths = symbol_data(symbol)
        data_hashes.extend(file_sha256(p) for p in paths)
        for prototype in H4_PROTOTYPES:
            event_part = events[(events["symbol"] == symbol) & (events["prototype"] == prototype)].copy()
            if event_part.empty:
                continue
            event_part = event_part.sort_values("execution_time").reset_index(drop=True)
            high_risk = high_risk_mask_fixed(event_part, gate_factors, gate_thresholds, prototype)
            event_part = event_part.assign(gate_high_risk=high_risk)
            for gate in gates:
                if gate == "G2_CONSENSUS_TWO_FACTORS" and prototype != "P6_MOMENTUM_OR_BREAKOUT_TOP20":
                    continue
                mask, gate_status = gate_mask_fixed(event_part, gate_factors, gate_thresholds, prototype, gate)
                if gate == "G4_RISK_MONITOR_DOWNSHIFT":
                    accepted = event_part.copy()
                else:
                    accepted = event_part.loc[mask].copy()
                for leverage_mode in STRICT_LEVERAGE_MODES:
                    trades, equity, audit = strict_replay_events(
                        accepted,
                        data_1m,
                        data_15m,
                        symbol,
                        prototype,
                        gate,
                        leverage_mode,
                    )
                    summary = strict_summary(trades, equity)
                    summary_rows.append({
                        "data_layer": data_layer,
                        "symbol": symbol,
                        "prototype": prototype,
                        "gate": gate,
                        "leverage_mode": leverage_mode,
                        "gate_status": gate_status,
                        "candidate_event_count": int(len(event_part)),
                        "accepted_event_count": int(len(accepted)),
                        **summary,
                    })
                    stem = f"{data_layer}_{symbol}_{prototype}_{gate}_{leverage_mode}"
                    trades.assign(data_layer=data_layer).to_csv(out / "strict_trades" / f"{stem}_trades.csv", index=False)
                    equity.assign(data_layer=data_layer, symbol=symbol, prototype=prototype, gate=gate, leverage_mode=leverage_mode).to_csv(
                        out / "strict_equity_curves" / f"{stem}_equity.csv",
                        index=False,
                    )
                    audit.assign(data_layer=data_layer).to_csv(out / "strict_audit" / f"{stem}_audit.csv", index=False)
    return pd.DataFrame(summary_rows), pd.DataFrame({"data_hash": sorted(set(data_hashes))})


def main() -> None:
    ensure_research_dirs()
    out = RESEARCH_ROOT / "strict_high_leverage_replay"
    for path in [out, out / "strict_trades", out / "strict_equity_curves", out / "strict_audit"]:
        path.mkdir(parents=True, exist_ok=True)
        for old in path.glob("*.csv"):
            old.unlink()

    gate_factors = pd.read_csv(RESEARCH_ROOT / "high_leverage_gate" / "h3_gate_factors.csv")
    discovery_gate_events = unique_event_labels(pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety" / "path_safety_labels.csv"))
    gate_thresholds = build_fixed_gate_thresholds(discovery_gate_events, gate_factors)
    gate_thresholds.to_csv(out / "strict_gate_fixed_thresholds.csv", index=False)

    if RUN_CORE_LAYER:
        core_events = prepare_core_events(discovery_gate_events)
        core_summary, core_hashes = run_layer(
            "h3_core_strict_replay",
            core_events,
            CORE_SYMBOLS,
            STRICT_GATES,
            gate_factors,
            gate_thresholds,
            out,
        )
    else:
        core_summary = pd.DataFrame()
        core_hashes = pd.DataFrame()

    holdout_summary = pd.DataFrame()
    holdout_hashes = pd.DataFrame()
    h4_events_path = RESEARCH_ROOT / "high_leverage_h4_validation" / "h4_validation_events.parquet"
    if h4_events_path.exists():
        holdout_events = pd.read_parquet(h4_events_path)
        holdout_symbols = sorted(holdout_events["symbol"].dropna().unique().tolist())
        holdout_summary, holdout_hashes = run_layer(
            "h4_holdout_strict_replay",
            holdout_events,
            holdout_symbols,
            H4_GATES,
            gate_factors,
            gate_thresholds,
            out,
        )

    summary = pd.concat([core_summary, holdout_summary], ignore_index=True) if not holdout_summary.empty else core_summary
    summary.to_csv(out / "strict_replay_summary.csv", index=False)

    proxy_frames = []
    h3_proxy = RESEARCH_ROOT / "high_leverage_gate" / "gate_leverage_summary.csv"
    h4_proxy = RESEARCH_ROOT / "high_leverage_h4_validation" / "h4_leverage_summary.csv"
    if h3_proxy.exists():
        proxy_frames.append(pd.read_csv(h3_proxy).assign(data_layer="h3_core_strict_replay"))
    if h4_proxy.exists():
        proxy_frames.append(pd.read_csv(h4_proxy).assign(data_layer="h4_holdout_strict_replay"))
    comparison = pd.DataFrame()
    if proxy_frames:
        proxy = pd.concat(proxy_frames, ignore_index=True)
        comparison = compare_proxy_to_strict(proxy, summary)
    comparison.to_csv(out / "strict_vs_proxy_comparison.csv", index=False)

    hash_frame = pd.concat([core_hashes, holdout_hashes], ignore_index=True) if not holdout_hashes.empty else core_hashes
    hash_frame.to_csv(out / "strict_data_hashes.csv", index=False)

    report = [
        "# Strict High Leverage Replay Report",
        "",
        "data_layer: strict_high_leverage_replay",
        "oos_status: not_oos",
        "simulation_approval: not_allowed",
        "",
        "This run replays accepted P4/P6 high-leverage gate events from raw 1m bars.",
        "It checks liquidation, ATR stop, Donchian20 exit, and end-of-backtest exits directly from bar data.",
        "Scope is intentionally limited to H4 holdout H4 gates and fixed_20x/adaptive_3x_8x for tractable strict audit coverage.",
        "",
        "## Summary",
        "",
        summary.sort_values(["data_layer", "symbol", "prototype", "gate", "leverage_mode"]).to_markdown(index=False) if not summary.empty else "No strict replay rows.",
        "",
        "## Proxy vs Strict",
        "",
        comparison.head(120).to_markdown(index=False) if not comparison.empty else "No proxy comparison available.",
        "",
        "## Guardrails",
        "",
        "- no alpha rule changed",
        "- fixed H3/discovery gate thresholds used",
        "- strict replay is not OOS",
        "- no deployable strategy rule generated",
    ]
    (RESEARCH_ROOT / "reports" / "strict_high_leverage_replay_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    append_run_log({
        "run_id": "STRICT_HIGH_LEVERAGE_REPLAY",
        "stage": "STRICT_REPLAY",
        "script": "research_core/run_strict_high_leverage_replay.py",
        "config_hash": stable_hash({
            "leverage_modes": STRICT_LEVERAGE_MODES,
            "core_gates": STRICT_GATES,
            "holdout_gates": H4_GATES,
            "run_core_layer": RUN_CORE_LAYER,
            "threshold_source": "h3_discovery_core_symbols",
            "exit_rules": "1m liquidation, ATR stop, Donchian20 exit",
        }),
        "data_hash": stable_hash({
            "gate_factors": file_sha256(RESEARCH_ROOT / "high_leverage_gate" / "h3_gate_factors.csv"),
            "data_hashes": hash_frame["data_hash"].tolist() if not hash_frame.empty else [],
        }),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "strict_high_leverage_replay",
        "status": "success",
        "notes": "strict 1m high leverage replay; fixed H3/discovery gate thresholds; not OOS; no deployable strategy rule generated.",
    })


if __name__ == "__main__":
    main()
